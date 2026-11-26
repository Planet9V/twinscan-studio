"""WonderEcho Pro Neural TTS (Edge + Offline Piper + eSpeak), Anti-Clipping EQ, ALSA Audio, 5-Byte Serial Protocol & Intent Router.

Implements:
- Studio-quality Neural TTS cascade (``edge_tts`` -> offline ``piper_tts`` -> ``espeak-ng``) with
  ``ffmpeg`` anti-clipping EQ tuned for the 2 W WonderEcho Pro speaker.
- Exact 5-byte WonderEcho Pro serial frame parser (``AA 55 <type> <cmd> FB``).
- Remote ALSA Card 2 mixer inspection & volume/mute control over SSH.
- Push-to-Talk microphone capture (``arecord -D plughw:2,0``) & natural-language voice intent execution.
- ``WonderEchoWakeManager`` background wake-word listener for ``/dev/wonderecho``.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import os
import re
import struct
import subprocess
import sys
import uuid
import wave
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

import httpx

from src.robot.ssh_manager import run_remote_python

VALID_VOICE_ENGINES = frozenset({"auto", "edge_tts", "piper_tts", "espeak"})

EDGE_TTS_VOICES: List[Dict[str, str]] = [
    {
        "id": "en-US-AndrewMultilingualNeural",
        "label": "Andrew · US Warm Male",
        "engine": "edge_tts",
        "accent": "US",
        "gender": "Male",
        "description": "Warm, natural studio voice (recommended default)",
    },
    {
        "id": "en-US-AriaNeural",
        "label": "Aria · US Expressive Female",
        "engine": "edge_tts",
        "accent": "US",
        "gender": "Female",
        "description": "Expressive conversational assistant",
    },
    {
        "id": "en-US-AvaMultilingualNeural",
        "label": "Ava · US Friendly Female",
        "engine": "edge_tts",
        "accent": "US",
        "gender": "Female",
        "description": "Friendly multilingual neural voice",
    },
    {
        "id": "en-US-GuyNeural",
        "label": "Guy · US Clear Male",
        "engine": "edge_tts",
        "accent": "US",
        "gender": "Male",
        "description": "Crisp broadcast-style male voice",
    },
    {
        "id": "en-US-JennyNeural",
        "label": "Jenny · US Conversational Female",
        "engine": "edge_tts",
        "accent": "US",
        "gender": "Female",
        "description": "Clear, upbeat customer-assistant voice",
    },
    {
        "id": "en-GB-SoniaNeural",
        "label": "Sonia · UK Studio Female",
        "engine": "edge_tts",
        "accent": "UK",
        "gender": "Female",
        "description": "Polished British neural voice",
    },
    {
        "id": "en-GB-RyanNeural",
        "label": "Ryan · UK Crisp Male",
        "engine": "edge_tts",
        "accent": "UK",
        "gender": "Male",
        "description": "Articulate British male neural voice",
    },
]

PIPER_TTS_VOICES: List[Dict[str, str]] = [
    {
        "id": "en_US-lessac-medium",
        "label": "Lessac · Offline US Natural",
        "engine": "piper_tts",
        "accent": "US",
        "gender": "Female",
        "description": "Fast 100% offline neural VITS voice (recommended offline)",
        "hf_path": "en/en_US/lessac/medium",
    },
    {
        "id": "en_US-ryan-medium",
        "label": "Ryan · Offline US Male",
        "engine": "piper_tts",
        "accent": "US",
        "gender": "Male",
        "description": "Warm offline US male neural voice",
        "hf_path": "en/en_US/ryan/medium",
    },
    {
        "id": "en_US-amy-medium",
        "label": "Amy · Offline US Warm Female",
        "engine": "piper_tts",
        "accent": "US",
        "gender": "Female",
        "description": "Balanced offline US female neural voice",
        "hf_path": "en/en_US/amy/medium",
    },
    {
        "id": "en_GB-alba-medium",
        "label": "Alba · Offline UK Female",
        "engine": "piper_tts",
        "accent": "UK",
        "gender": "Female",
        "description": "Crisp offline Scottish/UK neural voice",
        "hf_path": "en/en_GB/alba/medium",
    },
]

ESPEAK_VOICES: List[Dict[str, str]] = [
    {
        "id": "en-us",
        "label": "US English · Legacy eSpeak",
        "engine": "espeak",
        "accent": "US",
        "gender": "Neutral",
        "description": "Zero-dependency robotic formant fallback",
    },
    {
        "id": "en-gb",
        "label": "UK English · Legacy eSpeak",
        "engine": "espeak",
        "accent": "UK",
        "gender": "Neutral",
        "description": "British legacy formant fallback",
    },
    {
        "id": "en-us+f3",
        "label": "US Female · Legacy eSpeak",
        "engine": "espeak",
        "accent": "US",
        "gender": "Female",
        "description": "Higher-pitched legacy formant fallback",
    },
]

DEFAULT_EDGE_VOICE = EDGE_TTS_VOICES[0]["id"]
DEFAULT_PIPER_VOICE = PIPER_TTS_VOICES[0]["id"]
DEFAULT_ESPEAK_VOICE = ESPEAK_VOICES[0]["id"]

PIPER_HF_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
WONDERECHO_EQ_FILTER = "highpass=f=180,acompressor=threshold=-18dB:ratio=3:attack=5:release=60,alimiter=limit=0.88"

_PIPER_VOICE_CACHE: Dict[str, Any] = {}

WONDERECHO_OFFLINE_COMMANDS: Dict[int, Dict[str, str]] = {
    0x09: {"label": "Go Forward", "intent": "move_forward"},
    0x0A: {"label": "Go Backward", "intent": "move_backward"},
    0x0B: {"label": "Turn Left / Stop", "intent": "stop"},
    0x76: {"label": "Wake Acknowledge", "intent": "wake"},
    0x8A: {"label": "Stand Up", "intent": "stand"},
    0x8B: {"label": "Sit Down", "intent": "sit"},
    0x8C: {"label": "Lie Down", "intent": "lie_down"},
    0x8D: {"label": "Shake Hands / Wave", "intent": "wave"},
}


def parse_wonderecho_frame(data: bytes) -> Optional[Dict[str, Any]]:
    """Parse a 5-byte WonderEcho Pro UART frame (``AA 55 <type> <cmd> FB``).

    Args:
        data: Raw serial byte buffer (at least 5 bytes).

    Returns:
        Structured event dictionary ``{event, frame_type, cmd_code, label, intent}``
        when a valid frame is present, else ``None``.
    """
    if not data or len(data) < 5:
        return None
    for idx in range(len(data) - 4):
        if data[idx] == 0xAA and data[idx + 1] == 0x55 and data[idx + 4] == 0xFB:
            ftype = data[idx + 2]
            cmd = data[idx + 3]
            if ftype == 0x03 and cmd == 0x00:
                return {
                    "event": "wake",
                    "frame_type": ftype,
                    "cmd_code": cmd,
                    "label": "Hello Hiwonder (Wake)",
                    "intent": "wake",
                }
            if ftype == 0x02 and cmd == 0x00:
                return {
                    "event": "sleep",
                    "frame_type": ftype,
                    "cmd_code": cmd,
                    "label": "Sleep",
                    "intent": "sleep",
                }
            if ftype == 0x00:
                meta = WONDERECHO_OFFLINE_COMMANDS.get(
                    cmd, {"label": f"Offline Command 0x{cmd:02X}", "intent": "unknown"}
                )
                return {
                    "event": "offline_command",
                    "frame_type": ftype,
                    "cmd_code": cmd,
                    "label": meta["label"],
                    "intent": meta["intent"],
                }
            return {
                "event": "unknown",
                "frame_type": ftype,
                "cmd_code": cmd,
                "label": f"Frame 0x{ftype:02X} 0x{cmd:02X}",
                "intent": "unknown",
            }
    return None


def parse_amixer_controls(text: str) -> Dict[str, Any]:
    """Parse ``amixer -c <card> contents`` / ``scontents`` output for speaker and mic levels.

    Args:
        text: Raw stdout from ``amixer``.

    Returns:
        Dictionary with ``speaker_volume_pct``, ``speaker_muted``, ``mic_gain_pct``, ``mic_muted``.
    """
    speaker_vol = 80
    speaker_muted = False
    mic_vol = 75
    mic_muted = False

    current = ""
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("Simple mixer control"):
            low = s.lower()
            if any(k in low for k in ("speaker", "pcm", "master", "playback", "headphone")):
                current = "speaker"
            elif any(k in low for k in ("mic", "capture", "adc")):
                current = "mic"
            else:
                current = ""
            continue
        s_low = s.lower()
        if current == "speaker":
            if "capture" in s_low and "playback" not in s_low:
                continue
            seg = s
            if "playback" in s_low:
                seg = s[s_low.index("playback") :]
                if "capture" in seg.lower():
                    seg = seg[: seg.lower().index("capture")]
            seg_low = seg.lower()
            m_pct = re.search(r"\[(\d{1,3})%\]", seg)
            if m_pct:
                speaker_vol = max(0, min(100, int(m_pct.group(1))))
            if "[off]" in seg_low:
                speaker_muted = True
            elif "[on]" in seg_low:
                speaker_muted = False
        elif current == "mic":
            # UAC USB audio (WonderEcho Card 2) prints BOTH Playback sidetone [off] and Capture [on]
            # on the same line: "Mono: Playback 322 [65%] [20.12dB] [off] Capture 322 [65%] [20.12dB] [on]".
            # Always isolate the Capture segment so sidetone Playback [off] never marks Mic as muted.
            if "playback" in s_low and "capture" not in s_low:
                continue
            seg = s[s_low.index("capture") :] if "capture" in s_low else s
            seg_low = seg.lower()
            m_pct = re.search(r"\[(\d{1,3})%\]", seg)
            if m_pct:
                mic_vol = max(0, min(100, int(m_pct.group(1))))
            if "[off]" in seg_low:
                mic_muted = True
            elif "[on]" in seg_low:
                mic_muted = False

    return {
        "speaker_volume_pct": speaker_vol,
        "speaker_muted": speaker_muted,
        "mic_gain_pct": mic_vol,
        "mic_muted": mic_muted,
    }


def _generate_pcm_wav(tones: List[Tuple[float, float, float]], sample_rate: int = 16000) -> bytes:
    """Synthesize a clean 16-bit mono PCM WAV buffer from ``(freq_hz, duration_s, gain)`` segments."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for freq, dur_s, gain in tones:
            n_samples = max(1, int(sample_rate * dur_s))
            fade = max(1, int(sample_rate * 0.015))
            for i in range(n_samples):
                env = 1.0
                if i < fade:
                    env = i / fade
                elif i > n_samples - fade:
                    env = max(0.0, (n_samples - i) / fade)
                sample = math.sin(2.0 * math.pi * freq * (i / sample_rate)) * gain * env
                val = int(max(-32767, min(32767, sample * 32767)))
                frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def synthesize_chime_wav(chime: str = "dong") -> bytes:
    """Synthesize an unmistakable 16 kHz mono WAV chime for the WonderEcho Pro speaker.

    Args:
        chime: One of ``"dong"``, ``"wakeup"``, ``"success"``, or ``"alert"``.

    Returns:
        Raw WAV bytes ready for ``aplay -D plughw:2,0``.
    """
    key = str(chime or "dong").strip().lower()
    patterns: Dict[str, List[Tuple[float, float, float]]] = {
        "dong": [(587.33, 0.14, 0.55), (440.0, 0.24, 0.5)],
        "wakeup": [(523.25, 0.09, 0.5), (659.25, 0.09, 0.55), (783.99, 0.16, 0.6)],
        "success": [(523.25, 0.10, 0.5), (659.25, 0.10, 0.5), (1046.5, 0.20, 0.55)],
        "alert": [(880.0, 0.12, 0.65), (0.0, 0.05, 0.0), (880.0, 0.12, 0.65), (0.0, 0.05, 0.0), (660.0, 0.18, 0.6)],
    }
    return _generate_pcm_wav(patterns.get(key, patterns["dong"]))


def synthesize_tts_wav(
    text: str,
    voice: str = "en-us",
    speed: int = 155,
) -> Tuple[bytes, str]:
    """Synthesize spoken WAV audio using ``espeak-ng`` (with pure-Python WAV fallback).

    Args:
        text: Spoken message (truncated safely to 300 printable ASCII characters).
        voice: ``espeak-ng`` voice code (e.g. ``"en-us"``, ``"en-gb"``, ``"en-us+f3"``).
        speed: Words-per-minute speed clamped to ``[90, 260]``.

    Returns:
        Tuple ``(wav_bytes, engine_name)``.
    """
    clean_text = "".join(ch for ch in str(text or "") if 32 <= ord(ch) <= 126).strip()[:300]
    if not clean_text:
        raise ValueError("Spoken text must not be empty")
    safe_voice = voice if re.match(r"^[a-zA-Z0-9_+\-]{2,20}$", str(voice or "")) else "en-us"
    safe_speed = max(90, min(260, int(speed)))

    try:
        proc = subprocess.run(
            ["espeak-ng", "-v", safe_voice, "-s", str(safe_speed), "--stdout", clean_text],
            capture_output=True,
            timeout=10.0,
        )
        if proc.returncode == 0 and len(proc.stdout) > 44 and proc.stdout[:4] == b"RIFF":
            return proc.stdout, "espeak-ng"
    except FileNotFoundError:
        sys.stderr.write("[voice.tts] espeak-ng not found locally; falling back to synthesized WAV tone.\n")
    except Exception as exc:
        sys.stderr.write(f"[voice.tts] espeak-ng failed: {exc}\n")

    return synthesize_chime_wav("wakeup"), "fallback-tone"


def _piper_models_dir(models_dir: Optional[str | Path] = None) -> Path:
    """Resolve persistent Piper ONNX voice cache directory."""
    root = Path(models_dir or os.environ.get("TWINSCAN_MODELS_DIR", "./data/models"))
    return root / "piper"


def list_available_voices(models_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    """Return curated Neural + Offline + Legacy voice catalog and cached Piper voice IDs.

    Args:
        models_dir: Optional override for ``TWINSCAN_MODELS_DIR``.

    Returns:
        Dictionary matching ``VoiceCatalogResponse`` with ``default_engine``, ``engines``,
        ``voices``, and ``cached_piper_voices``.
    """
    piper_dir = _piper_models_dir(models_dir)
    cached_piper: List[str] = []
    voices: List[Dict[str, Any]] = []

    for v in EDGE_TTS_VOICES:
        voices.append({**v, "cached": False})

    for v in PIPER_TTS_VOICES:
        vid = v["id"]
        is_cached = (piper_dir / f"{vid}.onnx").is_file() and (piper_dir / f"{vid}.onnx.json").is_file()
        if is_cached:
            cached_piper.append(vid)
        entry = {k: val for k, val in v.items() if k != "hf_path"}
        entry["cached"] = is_cached
        voices.append(entry)

    for v in ESPEAK_VOICES:
        voices.append({**v, "cached": True})

    return {
        "default_engine": "piper_tts",
        "engines": [
            {
                "id": "piper_tts",
                "label": "Piper Neural (100% Offline · Default)",
                "description": "Fast local VITS neural ONNX speech cached in /app/data/models/piper.",
                "offline": True,
            },
            {
                "id": "edge_tts",
                "label": "Edge Neural (Studio Online)",
                "description": "Natural human-grade Microsoft Neural voices via WebSocket.",
                "offline": False,
            },
            {
                "id": "auto",
                "label": "Auto (Studio -> Offline Neural)",
                "description": "Tries Edge Neural first, falls back to local Piper Neural, then eSpeak.",
                "offline": False,
            },
            {
                "id": "espeak",
                "label": "eSpeak (Legacy)",
                "description": "Zero-dependency local formant synthesizer.",
                "offline": True,
            },
        ],
        "voices": voices,
        "cached_piper_voices": cached_piper,
    }


def condition_audio_for_wonderecho(
    audio_bytes: bytes,
    input_format: str = "wav",
    anti_clip: bool = True,
) -> bytes:
    """Transcode and apply WonderEcho 2 W anti-clipping EQ (180 Hz high-pass, compressor, limiter) via ``ffmpeg``.

    Args:
        audio_bytes: Raw encoded input audio (MP3 or WAV).
        input_format: ``ffmpeg`` input format name (e.g. ``"mp3"`` or ``"wav"``).
        anti_clip: When ``True``, applies ``highpass=f=180``, compressor, and peak limiter.

    Returns:
        16 kHz mono 16-bit PCM WAV bytes ready for ``aplay -D plughw:2,0``.
    """
    fmt = str(input_format or "wav").strip().lower()
    if fmt not in ("wav", "mp3", "ogg", "flac"):
        fmt = "wav"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", fmt, "-i", "pipe:0"]
    if anti_clip:
        cmd.extend(["-af", WONDERECHO_EQ_FILTER])
    cmd.extend(["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"])

    try:
        proc = subprocess.run(cmd, input=audio_bytes, capture_output=True, timeout=20.0)
        if proc.returncode == 0 and len(proc.stdout) > 44 and proc.stdout[:4] == b"RIFF":
            return proc.stdout
        err = proc.stderr.decode(errors="ignore").strip()
        sys.stderr.write(f"[voice.eq] ffmpeg conditioning failed (rc={proc.returncode}): {err}\n")
    except FileNotFoundError:
        sys.stderr.write("[voice.eq] ffmpeg not installed locally; bypassing EQ conditioning.\n")
    except Exception as exc:
        sys.stderr.write(f"[voice.eq] ffmpeg error: {exc}\n")

    if fmt == "wav" and len(audio_bytes) > 44 and audio_bytes[:4] == b"RIFF":
        return audio_bytes
    raise RuntimeError(f"ffmpeg is required to decode {fmt} audio for WonderEcho playback")


async def synthesize_edge_tts_mp3(
    text: str,
    voice: str = DEFAULT_EDGE_VOICE,
    speed: int = 155,
) -> bytes:
    """Synthesize studio-quality Neural speech MP3 bytes using Microsoft ``edge-tts`` (3x retry + stderr).

    Args:
        text: Spoken message (sanitized and capped to 400 characters).
        voice: Edge Neural voice identifier (defaults to ``en-US-AndrewMultilingualNeural``).
        speed: Target speaking speed in WPM (155 = normal ``+0%``).

    Returns:
        Raw MP3 audio bytes.
    """
    clean_text = "".join(ch for ch in str(text or "") if 32 <= ord(ch) <= 126).strip()[:400]
    if not clean_text:
        raise ValueError("Spoken text must not be empty")

    valid_ids = {v["id"] for v in EDGE_TTS_VOICES}
    safe_voice = voice if voice in valid_ids else DEFAULT_EDGE_VOICE
    rate_pct = max(-40, min(50, int(round(((float(speed) - 155.0) / 155.0) * 60.0))))
    rate_str = f"{rate_pct:+d}%"

    import edge_tts

    last_exc: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            comm = edge_tts.Communicate(text=clean_text, voice=safe_voice, rate=rate_str)
            chunks: List[bytes] = []
            async for chunk in comm.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
            mp3_bytes = b"".join(chunks)
            if len(mp3_bytes) > 512:
                return mp3_bytes
            raise RuntimeError("edge-tts returned empty audio stream")
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(f"[voice.edge_tts] Attempt {attempt}/3 failed ({safe_voice}): {exc}\n")
            if attempt < 3:
                await asyncio.sleep(0.35 * attempt)
    raise RuntimeError(f"edge-tts failed after 3 attempts: {last_exc}")


async def ensure_piper_voice_model(
    voice_id: str = DEFAULT_PIPER_VOICE,
    models_dir: Optional[str | Path] = None,
) -> Tuple[Path, Path]:
    """Ensure a Piper ONNX voice model and config JSON are cached locally (3x retry + stderr).

    Args:
        voice_id: Curated Piper voice ID (e.g. ``"en_US-lessac-medium"``).
        models_dir: Optional override for ``TWINSCAN_MODELS_DIR``.

    Returns:
        Tuple ``(onnx_path, config_json_path)``.
    """
    meta = next((v for v in PIPER_TTS_VOICES if v["id"] == voice_id), PIPER_TTS_VOICES[0])
    vid = meta["id"]
    hf_path = meta["hf_path"]
    piper_dir = _piper_models_dir(models_dir)
    piper_dir.mkdir(parents=True, exist_ok=True)

    onnx_path = piper_dir / f"{vid}.onnx"
    json_path = piper_dir / f"{vid}.onnx.json"

    async def _download_file(url: str, dest: Path, min_size: int) -> None:
        if dest.is_file() and dest.stat().st_size >= min_size:
            return
        last_err: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    if len(resp.content) < min_size:
                        raise RuntimeError(f"Downloaded file too small ({len(resp.content)} B)")
                    tmp = dest.with_suffix(dest.suffix + ".tmp")
                    tmp.write_bytes(resp.content)
                    tmp.replace(dest)
                    return
            except Exception as exc:
                last_err = exc
                sys.stderr.write(f"[voice.piper] Download {dest.name} failed (attempt {attempt}/3): {exc}\n")
                if attempt < 3:
                    await asyncio.sleep(0.5 * attempt)
        raise RuntimeError(f"Failed downloading Piper voice {dest.name}: {last_err}")

    base = f"{PIPER_HF_BASE_URL}/{hf_path}/{vid}"
    await _download_file(f"{base}.onnx.json", json_path, min_size=100)
    await _download_file(f"{base}.onnx", onnx_path, min_size=100_000)
    return onnx_path, json_path


def _load_piper_voice_cached(onnx_path: Path, json_path: Path) -> Any:
    """Load and cache a ``piper.PiperVoice`` instance in memory."""
    key = str(onnx_path.resolve())
    cached = _PIPER_VOICE_CACHE.get(key)
    if cached is not None:
        return cached
    import piper

    voice = piper.PiperVoice.load(onnx_path, config_path=json_path, use_cuda=False)
    _PIPER_VOICE_CACHE[key] = voice
    return voice


async def synthesize_piper_tts_wav(
    text: str,
    voice_id: str = DEFAULT_PIPER_VOICE,
    speed: int = 155,
    models_dir: Optional[str | Path] = None,
) -> bytes:
    """Synthesize 100% offline local Neural speech WAV bytes using ``piper-tts``.

    Args:
        text: Spoken message (sanitized and capped to 400 characters).
        voice_id: Curated Piper voice ID (defaults to ``en_US-lessac-medium``).
        speed: Target speaking speed in WPM (mapped to Piper ``length_scale``).
        models_dir: Optional override for ``TWINSCAN_MODELS_DIR``.

    Returns:
        Raw WAV bytes synthesized by Piper ONNX.
    """
    clean_text = "".join(ch for ch in str(text or "") if 32 <= ord(ch) <= 126).strip()[:400]
    if not clean_text:
        raise ValueError("Spoken text must not be empty")

    onnx_path, json_path = await ensure_piper_voice_model(voice_id=voice_id, models_dir=models_dir)
    length_scale = max(0.6, min(1.6, 155.0 / max(80.0, float(speed))))

    def _run_synth() -> bytes:
        from piper.config import SynthesisConfig

        pv = _load_piper_voice_cached(onnx_path, json_path)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            pv.synthesize_wav(clean_text, wf, syn_config=SynthesisConfig(length_scale=length_scale))
        return buf.getvalue()

    wav_bytes = await asyncio.to_thread(_run_synth)
    if len(wav_bytes) <= 44 or wav_bytes[:4] != b"RIFF":
        raise RuntimeError("Piper TTS produced invalid WAV output")
    return wav_bytes


async def synthesize_speech_wav(
    text: str,
    engine: str = "piper_tts",
    voice: Optional[str] = None,
    speed: int = 155,
    anti_clip: bool = True,
    models_dir: Optional[str | Path] = None,
) -> Tuple[bytes, str, str]:
    """Synthesize WonderEcho-ready 16 kHz mono WAV (default: offline ``piper_tts``; supports ``auto``/``edge_tts``/``espeak``).

    Args:
        text: Spoken text message.
        engine: ``"piper_tts"`` (default), ``"auto"``, ``"edge_tts"``, or ``"espeak"``.
        voice: Optional voice actor ID (auto-selected per engine when omitted or mismatched).
        speed: Speaking speed in WPM (default ``155``).
        anti_clip: Whether to apply WonderEcho anti-clipping EQ via ``ffmpeg``.
        models_dir: Optional override for ``TWINSCAN_MODELS_DIR``.

    Returns:
        Tuple ``(wav_bytes, actual_engine, actual_voice)``.
    """
    clean_text = "".join(ch for ch in str(text or "") if 32 <= ord(ch) <= 126).strip()[:400]
    if not clean_text:
        raise ValueError("Spoken text must not be empty")

    eng = str(engine or "piper_tts").strip().lower()
    if eng == "espeak-ng":
        eng = "espeak"
    if eng not in VALID_VOICE_ENGINES:
        raise ValueError(f"Unsupported TTS engine: {engine!r}. Must be one of {sorted(VALID_VOICE_ENGINES)}")

    edge_ids = {v["id"] for v in EDGE_TTS_VOICES}
    piper_ids = {v["id"] for v in PIPER_TTS_VOICES}
    espeak_ids = {v["id"] for v in ESPEAK_VOICES}

    order = ["edge_tts", "piper_tts", "espeak"] if eng == "auto" else [eng]
    last_error: Optional[Exception] = None

    for candidate in order:
        if candidate == "edge_tts":
            chosen_voice = voice if (voice in edge_ids) else DEFAULT_EDGE_VOICE
            try:
                mp3_bytes = await synthesize_edge_tts_mp3(clean_text, voice=chosen_voice, speed=speed)
                wav_bytes = await asyncio.to_thread(
                    condition_audio_for_wonderecho, mp3_bytes, "mp3", bool(anti_clip)
                )
                return wav_bytes, "edge_tts", chosen_voice
            except Exception as exc:
                last_error = exc
                sys.stderr.write(f"[voice.cascade] edge_tts failed, falling back: {exc}\n")
                if eng != "auto":
                    raise

        elif candidate == "piper_tts":
            chosen_voice = voice if (voice in piper_ids) else DEFAULT_PIPER_VOICE
            try:
                raw_wav = await synthesize_piper_tts_wav(
                    clean_text, voice_id=chosen_voice, speed=speed, models_dir=models_dir
                )
                wav_bytes = await asyncio.to_thread(
                    condition_audio_for_wonderecho, raw_wav, "wav", bool(anti_clip)
                )
                return wav_bytes, "piper_tts", chosen_voice
            except Exception as exc:
                last_error = exc
                sys.stderr.write(f"[voice.cascade] piper_tts failed, falling back: {exc}\n")
                if eng != "auto":
                    raise

        elif candidate == "espeak":
            chosen_voice = voice if (voice in espeak_ids) else DEFAULT_ESPEAK_VOICE
            raw_wav, actual_espeak = await asyncio.to_thread(
                synthesize_tts_wav, clean_text, chosen_voice, speed
            )
            wav_bytes = await asyncio.to_thread(
                condition_audio_for_wonderecho, raw_wav, "wav", bool(anti_clip)
            )
            return wav_bytes, actual_espeak, chosen_voice

    raise RuntimeError(f"All TTS engines failed: {last_error}")


def parse_voice_intent(transcript: str) -> Dict[str, Any]:
    """Map a natural-language voice transcript into a safe PuppyPi command intent.

    Args:
        transcript: Recognized or simulated user speech text.

    Returns:
        Dictionary ``{intent, action, target, reply_hint}``.
    """
    text = str(transcript or "").strip().lower()
    if not text:
        return {"intent": "none", "action": "none", "target": None, "reply_hint": "I did not hear a command."}

    if any(k in text for k in ("emergency stop", "e-stop", "estop", "freeze", "halt")):
        return {"intent": "stop", "action": "estop", "target": None, "reply_hint": "Stopping immediately."}
    if "stop patrol" in text or "end patrol" in text or "cancel patrol" in text:
        return {"intent": "stop_patrol", "action": "stop_patrol", "target": None, "reply_hint": "Stopping autonomous patrol."}
    if "start patrol" in text or "begin patrol" in text or "patrol" in text:
        return {"intent": "start_patrol", "action": "start_patrol", "target": None, "reply_hint": "Starting autonomous patrol."}
    if any(k in text for k in ("what do you see", "what is in front", "describe", "identify")):
        return {"intent": "describe_scene", "action": "deep_identify", "target": None, "reply_hint": "Checking camera view."}
    if any(k in text for k in ("who is", "who's in front", "recognize", "do you know me")):
        return {"intent": "who_is_there", "action": "recognize_face", "target": None, "reply_hint": "Checking who is in front of me."}

    m_follow = re.search(r"follow\s+(?:the\s+)?([a-z0-9 _-]+)", text)
    if m_follow:
        target = m_follow.group(1).strip()
        if target in ("line", "the line", "path"):
            return {"intent": "line_follow", "action": "line_follow", "target": "line", "reply_hint": "Activating line following."}
        return {"intent": "follow_target", "action": "follow", "target": target, "reply_hint": f"Looking for {target} to follow."}

    if "stop" in text:
        return {"intent": "stop", "action": "estop", "target": None, "reply_hint": "Stopping now."}
    if "go home" in text or "reset" in text:
        return {"intent": "go_home", "action": "go_home", "target": None, "reply_hint": "Returning to home stance."}
    if "lie down" in text or "lay down" in text or "sleep" in text:
        return {"intent": "lie_down", "action": "action:lie_down.d6ac", "target": None, "reply_hint": "Lying down."}
    if "sit" in text:
        return {"intent": "sit", "action": "action:sit.d6ac", "target": None, "reply_hint": "Sitting down."}
    if "wave" in text or "say hello" in text or "say hi" in text:
        return {"intent": "wave", "action": "action:wave.d6ac", "target": None, "reply_hint": "Hello there!"}
    if "shake" in text:
        return {"intent": "shake_hands", "action": "action:shake_hands.d6ac", "target": None, "reply_hint": "Nice to meet you!"}
    if "bow" in text:
        return {"intent": "bow", "action": "action:bow.d6ac", "target": None, "reply_hint": "Bowing now."}
    if "nod" in text:
        return {"intent": "nod", "action": "action:nod.d6ac", "target": None, "reply_hint": "Yes!"}
    if "stand" in text:
        return {"intent": "stand", "action": "pose:Stand", "target": None, "reply_hint": "Standing up."}
    if "push up" in text or "push-up" in text:
        return {"intent": "push_up", "action": "action:push-up.d6ac", "target": None, "reply_hint": "Doing push-ups!"}
    if any(k in text for k in ("battery", "status report", "system status", "how are you")):
        return {"intent": "status_report", "action": "status_report", "target": None, "reply_hint": "Checking system status."}

    return {"intent": "chat", "action": "speak_only", "target": None, "reply_hint": f"I heard: {transcript}"}


_HDMI_SKIP_TOKENS = ("vc4hdmi", "hdmi", "bcm2835", "headphones", "loopback")
_USB_AUDIO_PREFER_TOKENS = ("usb pnp audio", "jmtek", "usb audio", "uac", "wonder", "echo", "usb")


def parse_usb_audio_card_index(aplay_text: str, arecord_text: str = "") -> Tuple[Optional[int], str]:
    """Detect the live USB audio ALSA card index and name from ``arecord -l`` / ``aplay -l``.

    Works across any ALSA card number (Card 2, Card 3, etc. after USB replug) while
    skipping Raspberry Pi onboard HDMI/bcm2835 devices.

    Args:
        aplay_text: Raw stdout from ``aplay -l``.
        arecord_text: Optional raw stdout from ``arecord -l`` (checked first for mic cards).

    Returns:
        Tuple ``(card_index, device_name)`` or ``(None, "")`` when no USB/non-HDMI card exists.
    """
    candidates: List[Tuple[int, str, str]] = []
    seen: set[int] = set()
    for blob in (arecord_text or "", aplay_text or ""):
        for ln in blob.splitlines():
            m = re.match(r"card\s+(\d+):\s+([^\[]+)\[([^\]]+)\]", ln.strip())
            if not m:
                continue
            idx = int(m.group(1))
            if idx in seen:
                continue
            seen.add(idx)
            name = m.group(3).strip()
            candidates.append((idx, name, ln.lower()))

    # Pass 1: Explicit USB / WonderEcho / JMTek / UAC audio match (ignoring HDMI/bcm2835)
    for idx, name, low in candidates:
        if any(skip in low for skip in _HDMI_SKIP_TOKENS):
            continue
        if any(tok in low for tok in _USB_AUDIO_PREFER_TOKENS):
            return idx, name

    # Pass 2: First non-HDMI, non-bcm2835 audio card
    for idx, name, low in candidates:
        if not any(skip in low for skip in _HDMI_SKIP_TOKENS):
            return idx, name

    return None, ""


_REMOTE_DETECT_CARD_SNIPPET = r"""
def detect_usb_audio_card(forced_card=None):
    if forced_card is not None:
        return int(forced_card), f"Card {int(forced_card)}"
    skip_toks = ("vc4hdmi", "hdmi", "bcm2835", "headphones", "loopback")
    pref_toks = ("usb pnp audio", "jmtek", "usb audio", "uac", "wonder", "echo", "usb")
    cands = []
    seen = set()
    for cmd in (["arecord", "-l"], ["aplay", "-l"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            out = r.stdout or ""
        except Exception:
            out = ""
        for ln in out.splitlines():
            m = re.match(r"card\s+(\d+):\s+([^\[]+)\[([^\]]+)\]", ln.strip())
            if not m:
                continue
            idx = int(m.group(1))
            if idx in seen:
                continue
            seen.add(idx)
            cands.append((idx, m.group(3).strip(), ln.lower()))
    for idx, name, low in cands:
        if any(s in low for s in skip_toks):
            continue
        if any(p in low for p in pref_toks):
            return idx, name
    for idx, name, low in cands:
        if not any(s in low for s in skip_toks):
            return idx, name
    return None, ""
"""


_VOICE_STATUS_SCRIPT = (
    "import json, os, re, subprocess\n"
    + _REMOTE_DETECT_CARD_SNIPPET
    + r"""
def run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

card_idx, dev_name = detect_usb_audio_card(None)
amixer_out = ""
if card_idx is not None:
    _, amixer_out, _ = run(["amixer", "-c", str(card_idx), "scontents"])

symlink_ok = os.path.exists("/dev/wonderecho")
serial_dev = "/dev/wonderecho" if symlink_ok else ("/dev/ttyUSB0" if os.path.exists("/dev/ttyUSB0") else "")

print(json.dumps({
    "audio_card_detected": card_idx is not None,
    "card_index": card_idx,
    "device_name": dev_name or "Not detected",
    "amixer_out": amixer_out,
    "serial_symlink_present": symlink_ok,
    "serial_device": serial_dev,
}))
"""
)


async def get_voice_status(
    ip: str,
    user: str,
    password: str,
    robot_id: str = "",
    asr_language: str = "English",
    wake_manager: Optional["WonderEchoWakeManager"] = None,
) -> Dict[str, Any]:
    """Inspect WonderEcho Pro live USB ALSA card speaker/mic levels and ``/dev/wonderecho`` status over SSH."""
    wake_state = wake_manager.get_status(robot_id) if wake_manager else {"active": False, "last_event": None}
    try:
        raw = await run_remote_python(
            ip=ip,
            user=user,
            password=password,
            python_source=_VOICE_STATUS_SCRIPT,
            payload={},
            timeout=18.0,
            retries=2,
        )
        detected = bool(raw.get("audio_card_detected"))
        card_idx = int(raw["card_index"]) if raw.get("card_index") is not None else None
        mixer = parse_amixer_controls(str(raw.get("amixer_out") or "")) if detected else {
            "speaker_volume_pct": 0,
            "speaker_muted": False,
            "mic_gain_pct": 0,
            "mic_muted": False,
        }
        return {
            "robot_id": robot_id,
            "audio_card_detected": detected,
            "card_index": card_idx,
            "device_name": str(raw.get("device_name") or "Not detected"),
            **mixer,
            "serial_symlink_present": bool(raw.get("serial_symlink_present")),
            "serial_device": str(raw.get("serial_device") or ""),
            "asr_language": asr_language,
            "wake_listener_active": bool(wake_state.get("active")),
            "last_wake_event": wake_state.get("last_event"),
            "error": None if detected else "No USB audio card detected on Pi 5 (WonderEcho USB audio disconnected).",
        }
    except Exception as exc:
        sys.stderr.write(f"[voice.status] Failed on {ip}: {exc}\n")
        return {
            "robot_id": robot_id,
            "audio_card_detected": False,
            "card_index": None,
            "device_name": "Unavailable",
            "speaker_volume_pct": 0,
            "speaker_muted": False,
            "mic_gain_pct": 0,
            "mic_muted": False,
            "serial_symlink_present": False,
            "serial_device": "",
            "asr_language": asr_language,
            "wake_listener_active": bool(wake_state.get("active")),
            "last_wake_event": wake_state.get("last_event"),
            "error": str(exc),
        }


_MIXER_SET_SCRIPT = (
    "import json, re, subprocess\n"
    + _REMOTE_DETECT_CARD_SNIPPET
    + r"""
card_idx, dev_name = detect_usb_audio_card(PAYLOAD.get("card_index"))
if card_idx is None:
    raise RuntimeError("No USB audio card detected on PuppyPi (re-seat WonderEcho USB plug).")
card = str(card_idx)
spk_vol = PAYLOAD.get("speaker_volume_pct")
mic_vol = PAYLOAD.get("mic_gain_pct")
spk_mute = PAYLOAD.get("speaker_mute")
mic_mute = PAYLOAD.get("mic_mute")

r_list = subprocess.run(["amixer", "-c", card, "scontrols"], capture_output=True, text=True, timeout=8)
controls = re.findall(r"Simple mixer control '([^']+)'", r_list.stdout)

spk_ctrl = next((c for c in controls if any(k in c.lower() for k in ("speaker", "pcm", "master", "headphone"))), "Speaker")
mic_ctrl = next((c for c in controls if any(k in c.lower() for k in ("mic", "capture"))), "Mic")

if spk_vol is not None:
    subprocess.run(["amixer", "-c", card, "sset", spk_ctrl, f"{int(spk_vol)}%"], capture_output=True, timeout=8)
if spk_mute is not None:
    subprocess.run(["amixer", "-c", card, "sset", spk_ctrl, "mute" if spk_mute else "unmute"], capture_output=True, timeout=8)
if mic_vol is not None:
    subprocess.run(["amixer", "-c", card, "sset", mic_ctrl, f"{int(mic_vol)}%"], capture_output=True, timeout=8)
if mic_mute is not None:
    subprocess.run(["amixer", "-c", card, "sset", mic_ctrl, "nocap" if mic_mute else "cap"], capture_output=True, timeout=8)

r_cur = subprocess.run(["amixer", "-c", card, "scontents"], capture_output=True, text=True, timeout=8)
print(json.dumps({"ok": True, "card_index": card_idx, "device_name": dev_name, "amixer_out": r_cur.stdout}))
"""
)


async def set_audio_mixer(
    ip: str,
    user: str,
    password: str,
    speaker_volume_pct: Optional[int] = None,
    mic_gain_pct: Optional[int] = None,
    speaker_mute: Optional[bool] = None,
    mic_mute: Optional[bool] = None,
    card_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Update WonderEcho Pro ALSA speaker volume, mic gain, and mute toggles over SSH (auto-detects USB card)."""
    payload: Dict[str, Any] = {"card_index": int(card_index) if card_index is not None else None}
    if speaker_volume_pct is not None:
        payload["speaker_volume_pct"] = max(0, min(100, int(speaker_volume_pct)))
    if mic_gain_pct is not None:
        payload["mic_gain_pct"] = max(0, min(100, int(mic_gain_pct)))
    if speaker_mute is not None:
        payload["speaker_mute"] = bool(speaker_mute)
    if mic_mute is not None:
        payload["mic_mute"] = bool(mic_mute)
    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_MIXER_SET_SCRIPT,
        payload=payload,
        timeout=18.0,
        retries=2,
    )
    parsed = parse_amixer_controls(str(res.get("amixer_out") or ""))
    if res.get("card_index") is not None:
        parsed["card_index"] = int(res["card_index"])
    if res.get("device_name"):
        parsed["device_name"] = str(res["device_name"])
    return parsed


_PLAY_WAV_SCRIPT = (
    "import base64, json, os, re, subprocess, zlib\n"
    + _REMOTE_DETECT_CARD_SNIPPET
    + r"""
card_idx, _ = detect_usb_audio_card(PAYLOAD.get("card_index"))
if card_idx is None:
    raise RuntimeError("No USB audio card detected on PuppyPi for speaker playback.")
device = f"plughw:{card_idx},0"
compressed = bool(PAYLOAD.get("compressed", False))
tmp_path = PAYLOAD.get("tmp_path")

if tmp_path:
    try:
        with open(tmp_path, "r", encoding="ascii") as fh:
            b64_data = fh.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    raw = base64.b64decode(b64_data)
else:
    raw = base64.b64decode(PAYLOAD["wav_b64"])

wav_bytes = zlib.decompress(raw) if compressed else raw
r = subprocess.run(["aplay", "-q", "-D", device, "-"], input=wav_bytes, capture_output=True, timeout=30)
if r.returncode != 0:
    r2 = subprocess.run(["aplay", "-q", "-"], input=wav_bytes, capture_output=True, timeout=30)
    if r2.returncode != 0:
        raise RuntimeError(f"aplay failed: {r.stderr.decode(errors='ignore')} / {r2.stderr.decode(errors='ignore')}")
print(json.dumps({"ok": True, "bytes_played": len(wav_bytes), "device": device, "card_index": card_idx}))
"""
)

_APPEND_WAV_CHUNK_SCRIPT = r"""
import json

tmp_path = PAYLOAD["tmp_path"]
chunk = PAYLOAD["chunk"]
mode = "w" if PAYLOAD.get("first") else "a"
with open(tmp_path, mode, encoding="ascii") as fh:
    fh.write(chunk)
print(json.dumps({"ok": True, "written": len(chunk)}))
"""

# Keep each SSH argv payload well below Linux's 128 KiB MAX_ARG_STRLEN limit.
_MAX_INLINE_B64_CHARS = 32_000


async def play_wav_on_robot(
    ip: str,
    user: str,
    password: str,
    wav_bytes: bytes,
    card_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Compress and stream WAV bytes safely under Linux ``MAX_ARG_STRLEN`` to PuppyPi's USB audio card."""
    z_bytes = zlib.compress(wav_bytes, level=6)
    b64_str = base64.b64encode(z_bytes).decode("ascii")
    card_val = int(card_index) if card_index is not None else None

    if len(b64_str) <= _MAX_INLINE_B64_CHARS:
        return await run_remote_python(
            ip=ip,
            user=user,
            password=password,
            python_source=_PLAY_WAV_SCRIPT,
            payload={"wav_b64": b64_str, "compressed": True, "card_index": card_val},
            timeout=25.0,
            retries=2,
        )

    tmp_path = f"/tmp/eigenia_play_{uuid.uuid4().hex}.b64"
    for idx in range(0, len(b64_str), _MAX_INLINE_B64_CHARS):
        chunk = b64_str[idx : idx + _MAX_INLINE_B64_CHARS]
        await run_remote_python(
            ip=ip,
            user=user,
            password=password,
            python_source=_APPEND_WAV_CHUNK_SCRIPT,
            payload={"tmp_path": tmp_path, "chunk": chunk, "first": idx == 0},
            timeout=20.0,
            retries=2,
        )

    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_PLAY_WAV_SCRIPT,
        payload={"tmp_path": tmp_path, "compressed": True, "card_index": card_val},
        timeout=35.0,
        retries=2,
    )


async def speak_text_on_robot(
    ip: str,
    user: str,
    password: str,
    text: str,
    engine: str = "piper_tts",
    voice: Optional[str] = None,
    speed: int = 155,
    anti_clip: bool = True,
) -> Dict[str, Any]:
    """Synthesize Offline Piper/Edge/eSpeak WAV with WonderEcho EQ and play it on PuppyPi's speaker."""
    wav_bytes, actual_engine, actual_voice = await synthesize_speech_wav(
        text=text,
        engine=engine,
        voice=voice,
        speed=speed,
        anti_clip=anti_clip,
    )
    await play_wav_on_robot(ip=ip, user=user, password=password, wav_bytes=wav_bytes)
    return {
        "ok": True,
        "text": text,
        "engine": actual_engine,
        "voice": actual_voice,
        "anti_clip": bool(anti_clip),
        "bytes_sent": len(wav_bytes),
    }


async def play_speaker_chime(
    ip: str,
    user: str,
    password: str,
    chime: str = "dong",
    card_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Play a synthesized confirmation/alert chime on PuppyPi's WonderEcho speaker."""
    wav_bytes = synthesize_chime_wav(chime)
    await play_wav_on_robot(ip=ip, user=user, password=password, wav_bytes=wav_bytes, card_index=card_index)
    return {"ok": True, "chime": chime, "bytes_sent": len(wav_bytes)}


_RECORD_WAV_SCRIPT = (
    "import base64, json, re, subprocess\n"
    + _REMOTE_DETECT_CARD_SNIPPET
    + r"""
dur = max(1, min(10, int(PAYLOAD.get("duration_sec", 4))))
card_idx, _ = detect_usb_audio_card(PAYLOAD.get("card_index"))
if card_idx is None:
    raise RuntimeError("No USB audio card detected on PuppyPi for microphone recording.")
device = f"plughw:{card_idx},0"
r = subprocess.run(
    ["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(dur), "-t", "wav", "-"],
    capture_output=True,
    timeout=dur + 10,
)
if r.returncode != 0 or len(r.stdout) < 44:
    raise RuntimeError(f"arecord failed on {device}: {r.stderr.decode(errors='ignore')}")
print(json.dumps({
    "ok": True,
    "card_index": card_idx,
    "audio_bytes": len(r.stdout),
    "wav_b64": base64.b64encode(r.stdout).decode("ascii"),
}))
"""
)


async def record_mic_on_robot(
    ip: str,
    user: str,
    password: str,
    duration_sec: int = 4,
    card_index: Optional[int] = None,
) -> bytes:
    """Record mono 16 kHz PCM WAV audio from PuppyPi's dynamically detected USB microphone."""
    dur = max(1, min(10, int(duration_sec)))
    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_RECORD_WAV_SCRIPT,
        payload={"duration_sec": dur, "card_index": int(card_index) if card_index is not None else None},
        timeout=float(dur + 20),
        retries=2,
    )
    return base64.b64decode(str(res.get("wav_b64") or ""))


_VOICE_HW_DIAG_SCRIPT = (
    "import json, os, re, subprocess\n"
    + _REMOTE_DETECT_CARD_SNIPPET
    + r"""
sudo_pw = os.environ.get("SUDO_PW", "")

def run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

_, lsusb_out, _ = run(["lsusb"])
usb_lines = [ln.strip() for ln in lsusb_out.splitlines() if ln.strip()]
_, arecord_out, _ = run(["arecord", "-l"])
_, aplay_out, _ = run(["aplay", "-l"])
card_idx, dev_name = detect_usb_audio_card(None)

amixer_out = ""
if card_idx is not None:
    _, amixer_out, _ = run(["amixer", "-c", str(card_idx), "scontents"])

symlink_ok = os.path.exists("/dev/wonderecho")
symlink_target = os.path.realpath("/dev/wonderecho") if symlink_ok else ""
_, throttled_out, _ = run(["vcgencmd", "get_throttled"])
_, temp_out, _ = run(["vcgencmd", "measure_temp"])

dmesg_out = ""
rc_dm, dm_stdout, _ = run(["dmesg", "-T"])
if rc_dm != 0 or not dm_stdout:
    try:
        r_dm = subprocess.run(
            ["sudo", "-S", "-p", "", "dmesg", "-T"],
            input=(sudo_pw + "\n"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        dmesg_out = r_dm.stdout or ""
    except Exception:
        dmesg_out = ""
else:
    dmesg_out = dm_stdout

dmesg_warnings = []
pat = re.compile(r"(usb|1a86|0c76|under-voltage|over-current|disconnect|cannot enable|reset)", re.IGNORECASE)
for ln in dmesg_out.splitlines():
    if pat.search(ln):
        dmesg_warnings.append(ln.strip())
dmesg_warnings = dmesg_warnings[-20:]

print(json.dumps({
    "usb_devices": usb_lines,
    "has_usb_audio_0c76": any("0c76:161f" in ln.lower() or "usb pnp audio" in ln.lower() for ln in usb_lines),
    "has_wonderecho_hub_1a86_8091": any("1a86:8091" in ln.lower() for ln in usb_lines),
    "has_ch340_1a86_7523": any("1a86:7523" in ln.lower() for ln in usb_lines),
    "arecord_l": arecord_out,
    "aplay_l": aplay_out,
    "audio_card_detected": card_idx is not None,
    "card_index": card_idx,
    "device_name": dev_name or "Not detected",
    "amixer_out": amixer_out,
    "serial_symlink_present": symlink_ok,
    "serial_target": symlink_target,
    "throttled": throttled_out,
    "cpu_temp": temp_out,
    "dmesg_usb_warnings": dmesg_warnings,
}))
"""
)


async def collect_voice_hardware_diagnostics(
    ip: str,
    user: str,
    password: str,
) -> Dict[str, Any]:
    """Collect WonderEcho USB, ALSA, serial symlink, power throttle, and ``dmesg`` diagnostics over SSH.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.

    Returns:
        Structured hardware diagnostic payload including parsed mixer levels and USB warnings.
    """
    raw = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_VOICE_HW_DIAG_SCRIPT,
        payload={},
        timeout=22.0,
        retries=2,
        env_vars={"SUDO_PW": password},
    )
    mixer = parse_amixer_controls(str(raw.get("amixer_out") or ""))
    return {
        **raw,
        **mixer,
    }


async def listen_and_process_voice_command(
    robot_id: str,
    ip: str,
    user: str,
    password: str,
    duration_sec: int = 4,
    execute_commands: bool = True,
    speak_reply: bool = True,
    simulated_transcript: Optional[str] = None,
    action_executor: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, Tuple[str, str]]]] = None,
) -> Dict[str, Any]:
    """Record mic audio (or accept ``simulated_transcript``), parse intent, execute action, and speak reply."""
    audio_bytes = 0
    transcript = (simulated_transcript or "").strip()

    if not transcript:
        wav_data = await record_mic_on_robot(ip=ip, user=user, password=password, duration_sec=duration_sec)
        audio_bytes = len(wav_data)
        # Analyze RMS energy to distinguish silence from speech when offline STT is unavailable
        pcm = wav_data[44:] if len(wav_data) > 44 else b""
        rms = 0.0
        if len(pcm) >= 2:
            n = len(pcm) // 2
            samples = struct.unpack(f"<{n}h", pcm[: n * 2])
            rms = math.sqrt(sum(s * s for s in samples) / max(1, n))
        transcript = (
            f"[Captured {duration_sec}s audio ({audio_bytes:,} B, RMS={int(rms)}) — enter or speak command]"
            if rms > 120
            else ""
        )

    parsed = parse_voice_intent(transcript)
    action_taken = "none"
    reply_text = parsed["reply_hint"]

    if execute_commands and action_executor is not None and parsed["intent"] not in ("none", "chat"):
        try:
            action_taken, custom_reply = await action_executor(parsed)
            if custom_reply:
                reply_text = custom_reply
        except Exception as exc:
            sys.stderr.write(f"[voice.listen] Action execution failed for {robot_id}: {exc}\n")
            action_taken = f"error:{exc}"
            reply_text = f"Sorry, I could not complete that command: {exc}"

    spoken = False
    if speak_reply and reply_text:
        try:
            await speak_text_on_robot(ip=ip, user=user, password=password, text=reply_text)
            spoken = True
        except Exception as exc:
            sys.stderr.write(f"[voice.listen] Speaking reply failed on {ip}: {exc}\n")

    return {
        "ok": True,
        "transcript": transcript,
        "intent": parsed["intent"],
        "action_taken": action_taken,
        "reply_text": reply_text,
        "spoken": spoken,
        "audio_bytes": audio_bytes,
    }


_POLL_WAKE_SCRIPT = r"""
import base64, json, os, select, termios

dev = "/dev/wonderecho" if os.path.exists("/dev/wonderecho") else "/dev/ttyUSB0"
if not os.path.exists(dev):
    print(json.dumps({"ok": False, "frames_b64": "", "error": "No WonderEcho serial device"}))
    raise SystemExit(0)

fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
buf = bytearray()
try:
    attrs = termios.tcgetattr(fd)
    attrs[4] = termios.B115200
    attrs[5] = termios.B115200
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    r, _, _ = select.select([fd], [], [], 2.0)
    if r:
        chunk = os.read(fd, 64)
        if chunk:
            buf.extend(chunk)
finally:
    os.close(fd)

print(json.dumps({"ok": True, "frames_b64": base64.b64encode(bytes(buf)).decode("ascii"), "device": dev}))
"""


class WonderEchoWakeManager:
    """Background manager polling ``/dev/wonderecho`` for ``AA 55 03 00 FB`` wake-word frames."""

    def __init__(self) -> None:
        """Initialize empty per-robot wake listener registry."""
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._last_event: Dict[str, Optional[Dict[str, Any]]] = {}

    def get_status(self, robot_id: str) -> Dict[str, Any]:
        """Return whether the wake listener is active for ``robot_id`` and its last event."""
        task = self._tasks.get(robot_id)
        active = bool(task is not None and not task.done())
        return {"active": active, "last_event": self._last_event.get(robot_id)}

    async def start(
        self,
        robot_id: str,
        ip: str,
        user: str,
        password: str,
        on_frame: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None,
    ) -> Dict[str, Any]:
        """Start background polling for WonderEcho Pro serial wake/command frames."""
        await self.stop(robot_id)

        async def _loop() -> None:
            while True:
                try:
                    res = await run_remote_python(
                        ip=ip,
                        user=user,
                        password=password,
                        python_source=_POLL_WAKE_SCRIPT,
                        payload={},
                        timeout=12.0,
                        retries=1,
                    )
                    raw_b64 = str(res.get("frames_b64") or "")
                    if raw_b64:
                        frame = parse_wonderecho_frame(base64.b64decode(raw_b64))
                        if frame:
                            frame["timestamp"] = datetime.now(timezone.utc).isoformat()
                            self._last_event[robot_id] = frame
                            if on_frame is not None:
                                await on_frame(frame)
                    await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    sys.stderr.write(f"[voice.wake] Poll error on {ip}: {exc}\n")
                    await asyncio.sleep(2.0)

        self._tasks[robot_id] = asyncio.create_task(_loop())
        return {"ok": True, "wake_listener_active": True}

    async def stop(self, robot_id: str) -> Dict[str, Any]:
        """Stop the background wake listener for ``robot_id``."""
        task = self._tasks.pop(robot_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return {"ok": True, "wake_listener_active": False}

    async def stop_all(self) -> None:
        """Stop all active wake listeners on server shutdown."""
        for rid in list(self._tasks.keys()):
            await self.stop(rid)
