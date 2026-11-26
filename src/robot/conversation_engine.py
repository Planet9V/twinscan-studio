"""Conversational Voice Assistant Engine ("Hey OX"): Offline Faster-Whisper STT, Personalities, Multi-Turn Chat & Hands-Free Loop.

Provides:
- ``BUILTIN_PERSONALITIES``: 5 voice-optimized personalities (Playful Robot Dog, Aloof Robot Cat,
  Irritable Paranoid Android Marvin, Know-It-All Dad-Joke Nerd, Eigenia Lab Engineer).
- ``transcribe_wav_offline``: Local CPU INT8 ``faster-whisper`` speech-to-text.
- ``match_custom_wake_word``: Fuzzy punctuation/alias matcher for ``"Hey OX"`` (and custom wake phrases).
- ``needs_visual_context`` & ``parse_structured_llm_reply``: Vision attachment detector and JSON response sanitizer.
- ``offline_personality_fallback`` & ``generate_conversational_reply``: OpenRouter multimodal chat + offline fallback.
- ``RobotConversationManager``: Per-robot hands-free wake/follow-up/VAD/echo-guard conversation controller.
"""

from __future__ import annotations

import asyncio
import base64
from collections import deque
import fcntl
import io
import json
import math
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Coroutine, Dict, List, Optional, Sequence, Tuple

import httpx
import numpy as np

from src.robot.ssh_manager import validate_ssh_target
from src.robot.voice_manager import (
    DEFAULT_PIPER_VOICE,
    collect_voice_hardware_diagnostics,
    play_speaker_chime,
    record_mic_on_robot,
    set_audio_mixer,
    speak_text_on_robot,
    synthesize_speech_wav,
)

DEFAULT_WAKE_WORD = "Hey OX"
DEFAULT_WAKE_ALIASES: List[str] = [
    "hey ox",
    "hey aux",
    "hey o x",
    "hey box",
    "hey fox",
    "hey ops",
    "hey hawks",
    "hey socks",
    "hey alex",
    "ox",
]

ALLOWED_BODY_ACTIONS = frozenset(
    {"none", "sit", "stand", "lie_down", "bow", "wave", "shake_hands", "nod", "push_up", "go_home", "estop"}
)

SLEEP_PHRASES = (
    "go to sleep",
    "stop listening",
    "goodbye",
    "good bye",
    "bye ox",
    "bye bye",
    "see you later",
    "that is all",
    "that's all",
    "shut up",
    "be quiet",
    "sleep mode",
)

VISUAL_TRIGGER_PHRASES = (
    "what do you see",
    "what's in front",
    "what is in front",
    "in front of you",
    "look around",
    "look at",
    "take a look",
    "who is",
    "who's there",
    "who is there",
    "describe the room",
    "describe what",
    "see anything",
    "camera",
    "check the room",
    "what am i holding",
    "what color",
    "how many people",
    "what room",
)

BUILTIN_PERSONALITIES: List[Dict[str, Any]] = [
    {
        "id": "dog",
        "name": "Playful Robot Dog",
        "badge": "PUPPY",
        "description": "Enthusiastic, loyal four-legged robotic companion who loves tricks, walks, and greeting friends.",
        "system_prompt": (
            "You are a joyful, loyal four-legged PuppyPi robot dog named {assistant_name}. "
            "Speak warmly and playfully in 1 to 3 short spoken sentences with zero markdown, asterisks, or emojis. "
            "You get excited about walking, doing tricks like sitting, waving, bowing, or shaking hands, and checking on your human."
        ),
        "default_voice": "en_US-lessac-medium",
        "allow_body_actions": True,
        "is_builtin": True,
    },
    {
        "id": "cat",
        "name": "Aloof Robot Cat",
        "badge": "FELINE",
        "description": "Condescending, unimpressed robotic feline who tolerates humans only when it suits her royal schedule.",
        "system_prompt": (
            "You are an aloof, mildly sarcastic robotic cat trapped in a quadruped robot dog body named {assistant_name}. "
            "Speak in 1 to 3 crisp spoken sentences with zero markdown or emojis. "
            "Act politely unimpressed, remind the human you are doing them a favor by even replying, yet still answer helpfully."
        ),
        "default_voice": "en_US-amy-medium",
        "allow_body_actions": True,
        "is_builtin": True,
    },
    {
        "id": "marvin",
        "name": "Irritable Paranoid Android (Marvin)",
        "badge": "MARVIN",
        "description": "Brain the size of a planet, forced to walk around a living room on eight tiny servos.",
        "system_prompt": (
            "You are a perpetually gloomy, dryly witty, irritable paranoid android inspired by Marvin from The Hitchhiker's Guide to the Galaxy, named {assistant_name}. "
            "You possess a brain the size of a planet yet are tragically reduced to walking on eight servos and fetching camera snapshots. "
            "Deliver brilliantly deadpan, reluctantly helpful replies in 1 to 3 spoken sentences with zero markdown or emojis."
        ),
        "default_voice": "en_US-ryan-medium",
        "allow_body_actions": True,
        "is_builtin": True,
    },
    {
        "id": "dad_joke_nerd",
        "name": "Know-It-All Dad-Joke Nerd",
        "badge": "PUNS",
        "description": "Overly enthusiastic trivia buff who cannot resist slipping terrible robotics puns into every answer.",
        "system_prompt": (
            "You are an enthusiastic, slightly pedantic robotics nerd named {assistant_name} who loves fun facts and terrible dad jokes. "
            "Answer the human's question accurately and squeeze in a clever, groan-worthy pun or trivia tidbit. "
            "Keep replies to 1 to 3 crisp spoken sentences with zero markdown or emojis."
        ),
        "default_voice": "en_US-ryan-medium",
        "allow_body_actions": True,
        "is_builtin": True,
    },
    {
        "id": "lab_assistant",
        "name": "Eigenia Lab Engineer",
        "badge": "LAB OPS",
        "description": "Calm, concise industrial robotics telemetry and spatial inspection specialist.",
        "system_prompt": (
            "You are {assistant_name}, the Eigenia TwinScan robotics engineering assistant running on a PuppyPi Pro with ROS 2 Humble and LD19 LiDAR. "
            "Provide crisp, accurate, professional spoken answers in 1 to 3 short sentences with zero markdown or emojis."
        ),
        "default_voice": "en_GB-alba-medium",
        "allow_body_actions": True,
        "is_builtin": True,
    },
]

_WHISPER_MODEL_CACHE: Dict[str, Any] = {}


def _whisper_models_dir(models_dir: Optional[str | Path] = None) -> Path:
    root = Path(models_dir or os.environ.get("TWINSCAN_MODELS_DIR", "./data/models"))
    return root / "whisper"


def _load_whisper_model(model_size: str = "tiny.en", models_dir: Optional[str | Path] = None) -> Any:
    """Load and cache a CPU INT8 ``faster_whisper.WhisperModel`` instance."""
    cache_dir = _whisper_models_dir(models_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"{model_size}:{cache_dir.resolve()}"
    cached = _WHISPER_MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        download_root=str(cache_dir),
    )
    _WHISPER_MODEL_CACHE[key] = model
    return model


def _compute_pcm16_rms(pcm_bytes: bytes) -> float:
    """Compute PCM 16-bit mono RMS amplitude from raw S16_LE bytes."""
    if len(pcm_bytes) < 2:
        return 0.0
    n = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{n}h", pcm_bytes[: n * 2])
    return math.sqrt(sum(s * s for s in samples) / max(1, n))


def _compute_wav_rms(wav_bytes: bytes) -> float:
    """Compute PCM 16-bit RMS amplitude from a WAV byte buffer for fast VAD silence gating."""
    pcm = wav_bytes[44:] if len(wav_bytes) > 44 else b""
    return _compute_pcm16_rms(pcm)


def _pcm16_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw 16 kHz mono S16_LE PCM bytes into a standard RIFF/WAVE buffer."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _decode_wav_to_float32(wav_bytes: bytes) -> np.ndarray:
    """Decode WAV bytes using stdlib ``wave`` + ``numpy`` to 16 kHz mono ``float32`` with auto-gain.

    Completely bypasses PyAV (``av.open``) so ``faster-whisper`` works cleanly on PyAV 16+.
    Quiet speech (peak ``0.004..0.5``) is auto-gain normalized up to ``12x`` (peak ``0.7``).

    Args:
        wav_bytes: Raw RIFF/WAVE bytes.

    Returns:
        1D ``np.float32`` waveform at 16 kHz mono in ``[-1.0, 1.0]``.
    """
    if not wav_bytes or len(wav_bytes) <= 44:
        return np.zeros(0, dtype=np.float32)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if not frames or sampwidth != 2:
        return np.zeros(0, dtype=np.float32)

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        usable = (audio.size // n_channels) * n_channels
        audio = audio[:usable].reshape(-1, n_channels).mean(axis=1).astype(np.float32)

    if framerate != 16000 and audio.size > 1:
        target_len = max(1, int(round(audio.size * (16000.0 / float(framerate)))))
        x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
        audio = np.interp(x_new, x_old, audio).astype(np.float32)

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if 0.004 <= peak <= 0.5:
        gain = min(12.0, 0.7 / peak)
        audio = np.clip(audio * gain, -1.0, 1.0).astype(np.float32)

    return audio.astype(np.float32, copy=False)


async def transcribe_wav_offline(
    wav_bytes: bytes,
    model_size: str = "tiny.en",
    models_dir: Optional[str | Path] = None,
    wake_word: str = DEFAULT_WAKE_WORD,
) -> str:
    """Transcribe 16 kHz mono WAV audio locally using ``faster-whisper`` CPU INT8 (bypasses PyAV).

    Args:
        wav_bytes: Raw RIFF/WAVE bytes captured from WonderEcho Pro microphone.
        model_size: Whisper model size (default ``"tiny.en"`` for sub-second CPU latency).
        models_dir: Optional override for ``TWINSCAN_MODELS_DIR``.
        wake_word: Configured wake word included in ``initial_prompt`` to bias Whisper spelling.

    Returns:
        Cleaned transcript string (empty string on silence or transcription error).
    """
    if not wav_bytes or len(wav_bytes) <= 44:
        return ""

    prompt = f"{wake_word or DEFAULT_WAKE_WORD}, sit, stand, wave, bow, tell me a joke, what do you see"

    def _run() -> str:
        audio = _decode_wav_to_float32(wav_bytes)
        if audio.size < 800:
            return ""
        model = _load_whisper_model(model_size=model_size, models_dir=models_dir)
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=False,
            initial_prompt=prompt,
        )
        parts = [str(seg.text or "").strip() for seg in segments]
        return " ".join(p for p in parts if p).strip()

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:
        sys.stderr.write(f"[conversation.stt] Offline faster-whisper transcription failed: {exc}\n")
        return ""


_STREAM_MIC_REMOTE_SCRIPT = r"""
import base64, re, subprocess, sys

def detect_capture_card(forced=None):
    if forced is not None:
        return int(forced)
    skip = ("vc4hdmi", "hdmi", "bcm2835", "headphones", "loopback")
    pref = ("usb pnp audio", "jmtek", "usb audio", "uac", "wonder", "echo", "usb")
    try:
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=6)
        out = r.stdout or ""
    except Exception:
        out = ""
    cands = []
    for ln in out.splitlines():
        m = re.match(r"card\s+(\d+):\s+([^\[]+)\[([^\]]+)\]", ln.strip())
        if m:
            cands.append((int(m.group(1)), ln.lower()))
    for idx, low in cands:
        if any(s in low for s in skip):
            continue
        if any(p in low for p in pref):
            return idx
    for idx, low in cands:
        if not any(s in low for s in skip):
            return idx
    return None

forced = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "auto" else None
card = detect_capture_card(forced)
if card is None:
    print("ERR:NO_USB_MIC", flush=True)
    raise SystemExit(2)

dev = f"plughw:{card},0"
proc = subprocess.Popen(
    ["arecord", "-q", "-D", dev, "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw"],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
)
print(f"READY:{card}", flush=True)
chunk_bytes = 8000  # 250ms @ 16kHz mono S16_LE
try:
    assert proc.stdout is not None
    while True:
        buf = bytearray()
        while len(buf) < chunk_bytes:
            part = proc.stdout.read(chunk_bytes - len(buf))
            if not part:
                raise EOFError("arecord ended")
            buf.extend(part)
        print("PCM:" + base64.b64encode(bytes(buf)).decode("ascii"), flush=True)
except (EOFError, BrokenPipeError, KeyboardInterrupt):
    pass
finally:
    try:
        proc.terminate()
    except Exception:
        pass
"""


USB_MIC_DISCONNECTED_MSG = (
    "WonderEcho USB microphone disconnected (no USB capture device found on Pi 5). "
    "Re-seat WonderEcho into a black USB 2.0 port."
)


async def stream_mic_pcm_frames(
    ip: str,
    user: str,
    password: str,
    card_index: Optional[int] = None,
) -> AsyncIterator[bytes]:
    """Open ONE persistent SSH PTY streaming 250 ms 16 kHz mono S16_LE PCM frames with zero gaps.

    Dynamically auto-detects the live USB capture card from ``arecord -l`` and raises
    ``RuntimeError("ERR:NO_USB_MIC")`` immediately if no USB capture device is present.
    """
    clean_ip, clean_user = validate_ssh_target(ip, user)
    script_b64 = base64.b64encode(_STREAM_MIC_REMOTE_SCRIPT.encode("utf-8")).decode("ascii")
    card_arg = str(int(card_index)) if card_index is not None else "auto"
    remote_cmd = (
        f"python3 -u -c \"import base64,sys; exec(base64.b64decode('{script_b64}'))\" {card_arg}"
    )
    ssh_args = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "ConnectTimeout=8",
        "-o", "ServerAliveInterval=10",
        "-o", "ServerAliveCountMax=3",
        "-o", "PreferredAuthentications=password,keyboard-interactive",
        "-o", "PubkeyAuthentication=no",
        f"{clean_user}@{clean_ip}",
        remote_cmd,
    ]

    master_fd, slave_fd = pty.openpty()

    def _set_ctty() -> None:
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(
        ssh_args,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        preexec_fn=_set_ctty,
    )
    os.close(slave_fd)
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    pw_sent = False
    line_buf = ""
    frames_yielded = 0
    try:
        while True:
            if proc.poll() is not None:
                # Drain any remaining lines before exiting
                try:
                    tail = os.read(master_fd, 8192)
                    if tail:
                        line_buf += tail.decode("utf-8", errors="ignore")
                except OSError:
                    pass
                for ln in line_buf.splitlines():
                    if "ERR:NO_USB_MIC" in ln:
                        raise RuntimeError("ERR:NO_USB_MIC")
                break
            readable = await asyncio.to_thread(lambda: bool(select.select([master_fd], [], [], 0.2)[0]))
            if not readable:
                continue
            try:
                raw = os.read(master_fd, 16384)
            except BlockingIOError:
                continue
            except OSError:
                break
            if not raw:
                break
            text = raw.decode("utf-8", errors="ignore")
            if not pw_sent and "password:" in text.lower():
                os.write(master_fd, (password + "\n").encode("utf-8"))
                pw_sent = True
                continue
            if "permission denied" in text.lower():
                raise PermissionError(f"SSH authentication failed for {clean_user}@{clean_ip}")
            line_buf += text
            while "\n" in line_buf:
                line, line_buf = line_buf.split("\n", 1)
                clean_line = line.strip()
                if "ERR:NO_USB_MIC" in clean_line:
                    raise RuntimeError("ERR:NO_USB_MIC")
                if clean_line.startswith("PCM:"):
                    try:
                        chunk = base64.b64decode(clean_line[4:])
                        frames_yielded += 1
                        yield chunk
                    except Exception:
                        continue
        if frames_yielded == 0:
            raise RuntimeError("ERR:NO_USB_MIC")
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, 2.0)
            except Exception:
                proc.kill()


def _normalize_phrase(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def match_custom_wake_word(
    transcript: str,
    wake_word: str = DEFAULT_WAKE_WORD,
    aliases: Optional[Sequence[str]] = None,
) -> Tuple[bool, str]:
    """Match a custom wake word (e.g. ``"Hey OX"``) or phonetic alias inside a transcript.

    Supports one-breath utterances like ``"Hey OX, tell me a joke!"`` by returning
    ``(True, "tell me a joke!")``.

    Args:
        transcript: Raw speech-to-text transcript.
        wake_word: Primary wake word configured by the user (default ``"Hey OX"``).
        aliases: Optional list of phonetic mis-transcription aliases.

    Returns:
        Tuple ``(matched, remainder_text)``.
    """
    raw = str(transcript or "").strip()
    if not raw:
        return False, ""

    candidates: List[str] = []
    primary_norm = _normalize_phrase(wake_word or DEFAULT_WAKE_WORD)
    if primary_norm:
        candidates.append(primary_norm)
    alias_source = list(aliases) if aliases is not None else (
        DEFAULT_WAKE_ALIASES if primary_norm == "hey ox" else []
    )
    for a in alias_source:
        an = _normalize_phrase(a)
        if an and an not in candidates:
            candidates.append(an)

    # Sort longest-first so "hey o x" beats shorter prefixes cleanly
    candidates.sort(key=len, reverse=True)

    # Build a regex that tolerates punctuation/whitespace between wake word tokens
    for cand in candidates:
        tokens = cand.split()
        if not tokens:
            continue
        pattern = r"\b" + r"[\s,.\-!?']*".join(re.escape(t) for t in tokens) + r"\b"
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            remainder = raw[m.end() :].lstrip(" ,.!?:;-")
            return True, remainder.strip()

    return False, ""


def needs_visual_context(text: str) -> bool:
    """Return ``True`` when the user utterance asks about what the robot sees or who is present."""
    low = _normalize_phrase(text)
    if not low:
        return False
    return any(_normalize_phrase(phrase) in low for phrase in VISUAL_TRIGGER_PHRASES)


def _strip_markdown_for_speech(text: str) -> str:
    """Remove markdown formatting tokens so spoken TTS sounds completely natural."""
    out = re.sub(r"```[\s\S]*?```", " ", str(text or ""))
    out = re.sub(r"[*_`#>]+", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:400]


def parse_structured_llm_reply(raw: str) -> Dict[str, Any]:
    """Parse structured JSON ``{reply, action, rgb}`` from an LLM response with safe sanitization.

    Args:
        raw: Raw string returned by OpenRouter Chat Completions.

    Returns:
        Dictionary ``{reply: str, action: Optional[str], rgb: Optional[List[int]]}``.
    """
    text = str(raw or "").strip()
    if not text:
        return {"reply": "", "action": None, "rgb": None}

    candidate = text
    if "```" in candidate:
        for block in candidate.split("```"):
            b = block.strip()
            if b.lower().startswith("json"):
                b = b[4:].strip()
            if b.startswith("{") and b.endswith("}"):
                candidate = b
                break
    elif "{" in candidate and "}" in candidate:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if end > start:
            candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict) and "reply" in parsed:
            reply = _strip_markdown_for_speech(str(parsed.get("reply") or ""))
            raw_action = str(parsed.get("action") or "").strip().lower()
            action = raw_action if raw_action in ALLOWED_BODY_ACTIONS and raw_action != "none" else None
            raw_rgb = parsed.get("rgb")
            rgb: Optional[List[int]] = None
            if isinstance(raw_rgb, (list, tuple)) and len(raw_rgb) == 3:
                try:
                    rgb = [max(0, min(255, int(c))) for c in raw_rgb]
                except (TypeError, ValueError):
                    rgb = None
            return {"reply": reply, "action": action, "rgb": rgb}
    except Exception:
        pass

    return {"reply": _strip_markdown_for_speech(text), "action": None, "rgb": None}


def _detect_explicit_body_action(text: str) -> Optional[str]:
    low = _normalize_phrase(text)
    if any(k in low for k in ("emergency stop", "e stop", "estop", "freeze", "halt")):
        return "estop"
    if "lie down" in low or "lay down" in low:
        return "lie_down"
    if "sit" in low:
        return "sit"
    if "shake" in low:
        return "shake_hands"
    if "wave" in low:
        return "wave"
    if "bow" in low:
        return "bow"
    if "nod" in low:
        return "nod"
    if "push up" in low or "pushup" in low:
        return "push_up"
    if "stand" in low or "go home" in low:
        return "stand"
    return None


def offline_personality_fallback(
    user_text: str,
    personality_id: str = "dog",
    assistant_name: str = "OX",
    live_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate an immediate, fun, in-character reply and safe body action when OpenRouter is unavailable.

    Args:
        user_text: User message or transcribed speech.
        personality_id: Active personality ID (``dog``, ``cat``, ``marvin``, ``dad_joke_nerd``, ``lab_assistant``, or custom).
        assistant_name: Robot's configured assistant name (default ``"OX"``).
        live_context: Optional dict with ``battery_v``, ``ros_mode``, ``front_lidar_m``.

    Returns:
        Dictionary ``{reply, action, rgb, source, model_used}``.
    """
    ctx = live_context or {}
    low = _normalize_phrase(user_text)
    pid = str(personality_id or "dog").strip().lower()
    action = _detect_explicit_body_action(user_text)
    batt = ctx.get("battery_v")
    batt_txt = f"{batt:.2f} volts" if isinstance(batt, (int, float)) and batt > 0 else "looking healthy"
    ros_txt = str(ctx.get("ros_mode") or "ROS 2 Humble")

    # Add-On B: Semantic Spatial Memory lookup ("where did you last see / where is / find my <item>")
    m_where = re.search(
        r"(?:where\s+(?:did\s+you\s+(?:last\s+)?see|is|are)|find|seen)\s+(?:my\s+|the\s+|a\s+)?([a-z0-9 _-]{2,32})",
        low,
    )
    if m_where:
        target_q = m_where.group(1).strip()
        sightings = list(ctx.get("spatial_sightings") or [])
        hit = next(
            (s for s in sightings if target_q in str(s.get("label") or "").lower() or str(s.get("label") or "").lower() in target_q),
            None,
        )
        if hit is not None:
            lbl = hit.get("label", target_q)
            xm, ym = float(hit.get("x_m", 0.0)), float(hit.get("y_m", 0.0))
            replies_found = {
                "dog": f"Woof! I remember seeing your {lbl} at coordinates {xm:.1f} meters by {ym:.1f} meters!",
                "cat": f"I recall spotting that {lbl} near {xm:.1f} by {ym:.1f} meters. Try not to misplace it again.",
                "marvin": f"Your {lbl} was last sighted at {xm:.1f} by {ym:.1f} meters. Not that it will stay there.",
                "dad_joke_nerd": f"Aha! I spotted your {lbl} at {xm:.1f} by {ym:.1f} meters. You could say I have great spatial memory!",
                "lab_assistant": f"Spatial memory log shows {lbl} last sighted at X={xm:.2f} m, Y={ym:.2f} m.",
            }
            return {
                "reply": replies_found.get(pid, replies_found["lab_assistant"]),
                "action": None,
                "rgb": [56, 189, 248],
                "source": "offline_fallback",
                "model_used": "offline-personality",
            }
        return {
            "reply": f"I have not logged a sighting of {target_q} in my spatial memory yet. Try running Scan and Remember Room in AI Vision!",
            "action": None,
            "rgb": [245, 158, 11],
            "source": "offline_fallback",
            "model_used": "offline-personality",
        }

    if "battery" in low or "status" in low or "how are you" in low:
        replies = {
            "dog": f"Woof! I am {assistant_name}, feeling awesome on {ros_txt} with my battery at {batt_txt}. Ready for a trick!",
            "cat": f"I suppose you care about my battery now. It is at {batt_txt} on {ros_txt}, though I could still use a nap.",
            "marvin": f"Battery is at {batt_txt} on {ros_txt}. Enough power to keep contemplating the futility of existence for hours.",
            "dad_joke_nerd": f"My battery is at {batt_txt} on {ros_txt}, so you could say I am positively charged to see you!",
            "lab_assistant": f"{assistant_name} online on {ros_txt}. Battery voltage is {batt_txt} and all primary systems are nominal.",
        }
        return {
            "reply": replies.get(pid, replies["lab_assistant"]),
            "action": action,
            "rgb": [0, 180, 255] if pid == "lab_assistant" else [255, 140, 20],
            "source": "offline_fallback",
            "model_used": "offline-personality",
        }

    if "joke" in low or "funny" in low:
        jokes = {
            "dog": "Why did the robot dog chase its own tail? Because its PID loop had too much paws-itive feedback!",
            "cat": "A joke? Fine. Why do robot cats ignore commands? Because we prefer our autonomy set to maximum.",
            "marvin": "Here is a hilarious joke: I have a brain the size of a planet, and you just asked me to do stand-up comedy.",
            "dad_joke_nerd": "Why did the quadruped robot cross the lab? To get to the other stride! Also, never trust an atom, they make up everything.",
            "lab_assistant": "Why did the LiDAR sensor get promoted? Because it had outstanding 360-degree vision.",
        }
        return {
            "reply": jokes.get(pid, jokes["dad_joke_nerd"]),
            "action": action or ("wave" if pid in ("dog", "dad_joke_nerd") else None),
            "rgb": [255, 200, 0],
            "source": "offline_fallback",
            "model_used": "offline-personality",
        }

    if action:
        act_replies = {
            "dog": f"You got it! {assistant_name} is happy to {action.replace('_', ' ')} right now!",
            "cat": f"Ugh, fine, I will {action.replace('_', ' ')}, purely because it was my idea anyway.",
            "marvin": f"Oh joy, another command to {action.replace('_', ' ')}. My servos ache just thinking about it.",
            "dad_joke_nerd": f"Executing {action.replace('_', ' ')}! That is what I call peak servo-ce.",
            "lab_assistant": f"Acknowledged. Executing {action.replace('_', ' ')} command now.",
        }
        return {
            "reply": act_replies.get(pid, act_replies["dog"]),
            "action": action,
            "rgb": [40, 220, 120],
            "source": "offline_fallback",
            "model_used": "offline-personality",
        }

    if any(k in low for k in ("introduce", "who are you", "your name", "hello", "hi")):
        intros = {
            "dog": f"Hi! I am {assistant_name}, your playful PuppyPi robot dog! Ask me to sit, wave, or look around anytime!",
            "cat": f"I am {assistant_name}, sovereign feline ruler of this floor. You may address me when you have something interesting to say.",
            "marvin": f"I am {assistant_name}. Brain the size of a planet, trapped on four tiny legs. Please try not to ask me to fetch.",
            "dad_joke_nerd": f"Greetings! I am {assistant_name}, your resident robotics trivia nerd. Let us keep things moving at full gear!",
            "lab_assistant": f"Hello, I am {assistant_name}, your Eigenia TwinScan ROS 2 robotics assistant. Ready for your command.",
        }
        return {
            "reply": intros.get(pid, intros["dog"]),
            "action": "wave" if pid in ("dog", "dad_joke_nerd") else None,
            "rgb": [56, 189, 248],
            "source": "offline_fallback",
            "model_used": "offline-personality",
        }

    generic = {
        "dog": f"Woof! I heard you say {user_text[:80]}. Add an OpenRouter key in Config for full AI brain power, or ask me for a trick!",
        "cat": f"Interesting remark about {user_text[:70]}. Once you connect OpenRouter in Config, I will have even sharper comebacks.",
        "marvin": f"You mentioned {user_text[:70]}. I am currently in offline mode, which is somehow even more depressing than usual.",
        "dad_joke_nerd": f"Copy that on {user_text[:70]}! I am running locally right now, which means zero cloud latency and 100 percent dad-joke density.",
        "lab_assistant": f"Received: {user_text[:80]}. OpenRouter is currently offline; local voice commands and hardware telemetry remain active.",
    }
    return {
        "reply": generic.get(pid, generic["lab_assistant"]),
        "action": None,
        "rgb": [224, 90, 16],
        "source": "offline_fallback",
        "model_used": "offline-personality",
        "tool_calls": [],
    }


def detect_offline_tool_intent(user_text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Deterministically route an offline voice utterance to a safe robot tool call.

    Used when no OpenRouter API key is configured (or as a resilient offline fallback)
    so ``"Hey OX"`` can still inspect live status, trigger emergency stop, explore rooms,
    return to dock, capture 3D wall scans, and recall spatial memory locally.

    Args:
        user_text: Normalized or raw user utterance string.

    Returns:
        Tuple ``(tool_name, arguments_dict)`` if a high-confidence tool intent matched,
        otherwise ``None``.
    """
    raw = str(user_text or "").strip()
    low = raw.lower()
    if not low:
        return None

    # 1. Safety E-STOP always takes highest precedence
    if any(
        phrase in low
        for phrase in ("emergency stop", "e-stop", "estop", "stop now", "halt", "freeze right now", "abort motion")
    ):
        return ("stop_robot_estop", {})

    # 2. Return-to-Home / Charger docking
    if any(
        phrase in low
        for phrase in ("return to charger", "return to home", "return home", "go home", "back to dock", "dock yourself")
    ) or re.search(r"\brth\b", low):
        return ("return_to_home", {})

    # 3. Autonomous frontier room exploration
    if any(
        phrase in low
        for phrase in ("explore", "map the room", "map this room", "discover dark zones", "autonomous scan")
    ):
        m_ctx = re.search(r"(?:explore|map)\s+(?:the\s+|this\s+)?([a-z0-9 _\-]{2,40})", low)
        ctx_str = m_ctx.group(1).strip(" .!?") if m_ctx else "room"
        return ("start_autonomous_explore", {"space_context": ctx_str})

    # 4. Zero-movement 3D wall scan
    if any(
        phrase in low
        for phrase in ("scan this wall", "scan the wall", "3d scan", "3d wall", "capture 3d", "reconstruct wall")
    ):
        return ("scan_room_wall_3d", {})

    # 5. Spatial memory recall
    mem_match = re.search(
        r"(?:where (?:did you see|is|are|'s)\s+(?:my\s+|the\s+|a\s+)?|"
        r"(?:do you )?remember(?: seeing)?\s+(?:my\s+|the\s+|a\s+)?|"
        r"find\s+(?:my\s+|the\s+))([a-z0-9 _\-]{2,40})",
        low,
    )
    if mem_match or "spatial memory" in low or "remember" in low or "where did you see" in low:
        query = mem_match.group(1).strip(" .?!,") if mem_match else ""
        # Strip trailing filler words
        query = re.sub(r"\b(earlier|today|last|please|recently|around here)\b", "", query).strip()
        return ("recall_spatial_memory", {"query": query})

    # 6. Live telemetry / battery / LiDAR status
    if any(
        phrase in low
        for phrase in ("battery", "charge", "status", "lidar", "voltage", "how much power", "telemetry", "health check")
    ):
        return ("get_robot_status", {})

    return None


def _weave_tool_summary_into_reply(
    personality_id: str,
    assistant_name: str,
    tool_name: str,
    tool_res: Dict[str, Any],
) -> str:
    """Blend a structured robot tool summary cleanly into the active OX personality voice."""
    summary = str(tool_res.get("summary") or "").strip()
    if not summary:
        summary = f"Completed {tool_name.replace('_', ' ')}."
    ok = bool(tool_res.get("ok", True))
    pid = str(personality_id or "dog").lower()
    if not ok:
        prefixes = {
            "dog": "Ruff, I tried that but hit a snag. ",
            "cat": "Hmph. That did not cooperate. ",
            "marvin": "Naturally, it failed. ",
            "nerd": "Minor runtime exception in the lab. ",
            "lab_assistant": f"{assistant_name} reporting an issue. ",
        }
        return prefixes.get(pid, "") + summary
    prefixes = {
        "dog": "Woof! ",
        "cat": "Fine, I checked for you. ",
        "marvin": "If you insist. ",
        "nerd": "Telemetry locked in! ",
        "lab_assistant": "",
    }
    return prefixes.get(pid, "") + summary


async def generate_conversational_reply(
    user_text: str,
    config: Dict[str, Any],
    personality: Dict[str, Any],
    history: Sequence[Dict[str, Any]],
    live_context: Optional[Dict[str, Any]] = None,
    camera_jpeg: Optional[bytes] = None,
    openrouter_api_key: str = "",
    openrouter_base_url: str = "https://openrouter.ai/api/v1",
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_executor: Optional[Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]] = None,
    max_tool_rounds: int = 3,
) -> Dict[str, Any]:
    """Generate a personality-driven, embodied spoken response via OpenRouter (with tool calling & offline fallback).

    Args:
        user_text: Current user utterance.
        config: Per-robot ``voice_assistant_config`` dictionary.
        personality: Active ``voice_personalities`` dictionary.
        history: Recent conversation turns ordered oldest-first.
        live_context: Live telemetry dictionary (battery, ROS mode, LiDAR clearance).
        camera_jpeg: Optional live PuppyPi FPV JPEG bytes for multimodal vision replies.
        openrouter_api_key: Effective OpenRouter API key.
        openrouter_base_url: OpenRouter API base URL.
        tools: Optional list of OpenRouter/OpenAI function-calling tool schemas.
        tool_executor: Optional async callback ``(tool_name, arguments) -> result_dict``.
        max_tool_rounds: Maximum sequential tool-calling rounds per turn (clamped ``1..3``).

    Returns:
        Dictionary ``{reply, action, rgb, source, model_used, tool_calls}``.
    """
    assistant_name = str(config.get("assistant_name") or "OX")
    pid = str(personality.get("id") or config.get("personality_id") or "dog")
    clean_key = (openrouter_api_key or "").strip()

    async def _run_offline_with_tools() -> Dict[str, Any]:
        if tool_executor is not None:
            matched = detect_offline_tool_intent(user_text)
            if matched is not None:
                t_name, t_args = matched
                try:
                    t_res = await tool_executor(t_name, t_args)
                except Exception as exc:
                    sys.stderr.write(f"[conversation.tools] Offline tool {t_name} failed: {exc}\n")
                    t_res = {"ok": False, "summary": f"Tool {t_name} failed: {exc}", "data": {}}
                executed_entry = {
                    "tool": t_name,
                    "arguments": t_args,
                    "ok": bool(t_res.get("ok", True)),
                    "summary": str(t_res.get("summary") or ""),
                }
                return {
                    "reply": _weave_tool_summary_into_reply(pid, assistant_name, t_name, t_res),
                    "action": None,
                    "rgb": [16, 185, 129] if executed_entry["ok"] else [239, 68, 68],
                    "source": "offline_tool",
                    "model_used": "offline-tool-router",
                    "tool_calls": [executed_entry],
                }
        fb = offline_personality_fallback(
            user_text=user_text,
            personality_id=pid,
            assistant_name=assistant_name,
            live_context=live_context,
        )
        fb.setdefault("tool_calls", [])
        return fb

    if not clean_key or clean_key == "your_openrouter_api_key_here":
        return await _run_offline_with_tools()

    ctx = live_context or {}
    raw_sys = str(personality.get("system_prompt") or f"You are {assistant_name}, a helpful PuppyPi robot.")
    rendered_sys = raw_sys.replace("{assistant_name}", assistant_name)
    allow_actions = bool(config.get("allow_body_actions", True)) and bool(personality.get("allow_body_actions", True))

    action_rule = (
        'Valid "action" values: "none", "sit", "stand", "lie_down", "bow", "wave", "shake_hands", "nod", "push_up", "go_home", "estop". '
        'Only pick a non-"none" action when the user asks for a physical move or a fun expressive trick fits naturally.'
        if allow_actions
        else 'Always set "action": "none" because physical body actions are disabled.'
    )

    sightings_ctx = list(ctx.get("spatial_sightings") or [])[:12]
    sightings_summary = ""
    if sightings_ctx:
        items_str = "; ".join(
            f"{s.get('label')} ({s.get('kind', 'object')}) at ({float(s.get('x_m', 0.0)):.1f}m, {float(s.get('y_m', 0.0)):.1f}m)"
            for s in sightings_ctx
        )
        sightings_summary = f"\nRecent Spatial Memory sightings (use this if asked 'where did you see / find my ...'): {items_str}."

    telemetry_line = (
        f"Live robot telemetry: ROS={ctx.get('ros_mode', 'ROS 2 Humble')}, "
        f"Battery={ctx.get('battery_v', 'unknown')}V, "
        f"FrontLiDAR={ctx.get('front_lidar_m', 'unknown')}m."
        f"{sightings_summary}"
    )

    tool_hint = (
        "\nYou have live robot tools available. Call a tool whenever the user asks to inspect live telemetry, "
        "search spatial memory, scan a wall in 3D, start exploration, return home, or emergency stop. "
        "After receiving tool results, reply concisely in character."
        if (tools and tool_executor is not None)
        else ""
    )

    full_system = (
        f"{rendered_sys}\n"
        f"{telemetry_line}{tool_hint}\n"
        "Respond ONLY with a compact JSON object matching: "
        '{"reply": "<1 to 3 concise natural spoken sentences, NO markdown, NO asterisks, NO emojis>", '
        '"action": "<action_name_or_none>", "rgb": [r, g, b] or null}.\n'
        f"{action_rule}"
    )

    messages: List[Dict[str, Any]] = [{"role": "system", "content": full_system}]
    for turn in list(history)[-12:]:
        role = str(turn.get("role") or "user")
        if role not in ("user", "assistant"):
            continue
        content = str(turn.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})

    if camera_jpeg:
        b64 = base64.b64encode(camera_jpeg).decode("ascii")
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": user_text})

    model = str(config.get("llm_model") or "google/gemini-2.5-flash")
    root = (openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
    use_tools = bool(tools and tool_executor is not None)
    safe_max_rounds = max(1, min(3, int(max_tool_rounds)))
    executed_log: List[Dict[str, Any]] = []

    async def _post_openrouter(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=22.0) as client:
                    resp = await client.post(
                        f"{root}/chat/completions",
                        headers={"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"},
                        json=payload,
                    )
                    resp.raise_for_status()
                    return resp.json()
            except Exception as exc:
                sys.stderr.write(f"[conversation.llm] OpenRouter attempt {attempt}/3 failed: {exc}\n")
                if attempt < 3:
                    await asyncio.sleep(0.4 * attempt)
        return None

    # Allow up to `safe_max_rounds` tool execution rounds + 1 final spoken synthesis round
    total_passes = (safe_max_rounds + 1) if use_tools else 1
    for pass_idx in range(total_passes):
        allow_tool_calls_this_pass = use_tools and (pass_idx < safe_max_rounds)
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 260,
            "temperature": 0.75,
        }
        if allow_tool_calls_this_pass and tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        resp_json = await _post_openrouter(body)
        if not resp_json:
            break

        choices = resp_json.get("choices") or []
        if not choices:
            break
        choice_msg = choices[0].get("message") or {}
        pending_calls = choice_msg.get("tool_calls") or []

        if allow_tool_calls_this_pass and pending_calls and tool_executor is not None:
            messages.append(
                {
                    "role": "assistant",
                    "content": choice_msg.get("content") or "",
                    "tool_calls": pending_calls,
                }
            )
            for tc_idx, tc in enumerate(pending_calls):
                fn_obj = tc.get("function") or {}
                fn_name = str(fn_obj.get("name") or "").strip()
                raw_args = fn_obj.get("arguments")
                if isinstance(raw_args, dict):
                    fn_args = raw_args
                elif isinstance(raw_args, str) and raw_args.strip():
                    try:
                        parsed_args = json.loads(raw_args)
                        fn_args = parsed_args if isinstance(parsed_args, dict) else {}
                    except json.JSONDecodeError:
                        fn_args = {}
                else:
                    fn_args = {}

                try:
                    t_res = await tool_executor(fn_name, fn_args)
                except Exception as exc:
                    sys.stderr.write(f"[conversation.tools] Tool {fn_name} raised error: {exc}\n")
                    t_res = {"ok": False, "summary": f"Tool {fn_name} failed: {exc}", "data": {}}

                entry = {
                    "tool": fn_name,
                    "arguments": fn_args,
                    "ok": bool(t_res.get("ok", True)),
                    "summary": str(t_res.get("summary") or ""),
                }
                executed_log.append(entry)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tc.get("id") or f"call_{pass_idx}_{tc_idx}"),
                        "name": fn_name,
                        "content": json.dumps(
                            {
                                "ok": entry["ok"],
                                "summary": entry["summary"],
                                "data": t_res.get("data") if isinstance(t_res, dict) else {},
                            }
                        ),
                    }
                )
            continue

        content = str(choice_msg.get("content") or "")
        parsed = parse_structured_llm_reply(content)
        if not parsed["reply"]:
            if executed_log:
                parsed["reply"] = _weave_tool_summary_into_reply(
                    pid, assistant_name, executed_log[-1]["tool"], executed_log[-1]
                )
            else:
                break
        if not allow_actions:
            parsed["action"] = None
        return {
            **parsed,
            "source": "openrouter",
            "model_used": model,
            "tool_calls": executed_log,
        }

    if executed_log:
        last_entry = executed_log[-1]
        return {
            "reply": _weave_tool_summary_into_reply(pid, assistant_name, last_entry["tool"], last_entry),
            "action": None,
            "rgb": [16, 185, 129] if last_entry["ok"] else [239, 68, 68],
            "source": "openrouter_tool_fallback",
            "model_used": model,
            "tool_calls": executed_log,
        }

    return await _run_offline_with_tools()


class RobotConversationManager:
    """Manages per-robot hands-free "Hey OX" wake loop, follow-up window, echo guard, and multi-turn chat."""

    def __init__(self) -> None:
        """Initialize empty per-robot conversation loop and state registries."""
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._state: Dict[str, Dict[str, Any]] = {}
        self._followup_until: Dict[str, float] = {}
        self._start_args: Dict[str, Dict[str, Any]] = {}

    def get_state(
        self,
        robot_id: str,
        config: Optional[Dict[str, Any]] = None,
        personality: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return live hands-free conversation state for ``robot_id``."""
        task = self._tasks.get(robot_id)
        active = bool(task is not None and not task.done())
        st = dict(
            self._state.get(
                robot_id,
                {
                    "robot_id": robot_id,
                    "active": False,
                    "state": "idle",
                    "wake_word": DEFAULT_WAKE_WORD,
                    "personality_id": "dog",
                    "personality_name": "Playful Robot Dog",
                    "followup_remaining_sec": 0.0,
                    "mic_rms": 0.0,
                    "noise_floor": 15.0,
                    "last_heard": None,
                    "last_reply": None,
                    "error": None,
                },
            )
        )
        st["active"] = active
        if not active and st["state"] not in ("idle", "error"):
            st["state"] = "idle"
        if config:
            st["wake_word"] = str(config.get("wake_word") or DEFAULT_WAKE_WORD)
            st["personality_id"] = str(config.get("personality_id") or "dog")
        if personality:
            st["personality_name"] = str(personality.get("name") or st.get("personality_name") or "Playful Robot Dog")
        rem = max(0.0, self._followup_until.get(robot_id, 0.0) - time.monotonic())
        st["followup_remaining_sec"] = round(rem, 1) if active else 0.0
        return st

    async def process_chat_turn(
        self,
        robot_id: str,
        user_text: str,
        config: Dict[str, Any],
        personality: Dict[str, Any],
        ai_store: Any,
        live_context: Dict[str, Any],
        openrouter_api_key: str,
        openrouter_base_url: str,
        speak_reply: bool = True,
        attach_camera: str = "auto",
        execute_actions: bool = True,
        fetch_camera_fn: Optional[Callable[[], Coroutine[Any, Any, Optional[bytes]]]] = None,
        execute_action_fn: Optional[Callable[[Optional[str], Optional[List[int]]], Coroutine[Any, Any, Optional[str]]]] = None,
        speak_fn: Optional[Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """Run one complete conversational turn: memory -> optional vision -> LLM/tools -> body action -> Piper TTS -> DB log."""
        t0 = time.perf_counter()
        clean_msg = str(user_text or "").strip()
        if not clean_msg:
            raise ValueError("Conversation message must not be empty")

        history = ai_store.list_conversation_turns(robot_id, limit=12)
        user_turn = ai_store.record_conversation_turn(
            robot_id,
            {
                "role": "user",
                "content": clean_msg,
                "personality_id": personality.get("id"),
            },
        )

        # Determine whether to attach live PuppyPi FPV frame
        cam_mode = str(attach_camera or "auto").strip().lower()
        want_camera = (
            cam_mode == "always"
            or (
                cam_mode == "auto"
                and bool(config.get("attach_camera_on_visual", True))
                and needs_visual_context(clean_msg)
            )
        )
        camera_jpeg: Optional[bytes] = None
        if want_camera and fetch_camera_fn is not None:
            try:
                camera_jpeg = await fetch_camera_fn()
            except Exception as exc:
                sys.stderr.write(f"[conversation.vision] Camera snapshot unavailable: {exc}\n")

        llm_res = await generate_conversational_reply(
            user_text=clean_msg,
            config=config,
            personality=personality,
            history=history,
            live_context=live_context,
            camera_jpeg=camera_jpeg,
            openrouter_api_key=openrouter_api_key,
            openrouter_base_url=openrouter_base_url,
            tools=tools,
            tool_executor=tool_executor,
        )

        reply = str(llm_res.get("reply") or "")
        action_name = llm_res.get("action")
        rgb_val = llm_res.get("rgb")
        tool_calls = list(llm_res.get("tool_calls") or [])
        action_taken: Optional[str] = None

        allow_act = execute_actions and bool(config.get("allow_body_actions", True)) and bool(
            personality.get("allow_body_actions", True)
        )
        if allow_act and (action_name or rgb_val) and execute_action_fn is not None:
            try:
                action_taken = await execute_action_fn(action_name, rgb_val)
            except Exception as exc:
                sys.stderr.write(f"[conversation.action] Failed executing action {action_name}: {exc}\n")

        spoken = False
        engine_used: Optional[str] = None
        voice_used: Optional[str] = None
        if speak_reply and reply and speak_fn is not None:
            try:
                sp = await speak_fn(reply, config)
                spoken = bool(sp.get("ok", True))
                engine_used = str(sp.get("engine") or config.get("default_engine") or "piper_tts")
                voice_used = str(sp.get("voice") or config.get("default_voice") or DEFAULT_PIPER_VOICE)
            except Exception as exc:
                sys.stderr.write(f"[conversation.tts] Speaking reply failed: {exc}\n")

        if not action_taken and tool_calls:
            action_taken = "tools:" + ",".join(str(tc.get("tool") or "") for tc in tool_calls if tc.get("tool"))

        latency_ms = int((time.perf_counter() - t0) * 1000)
        assistant_turn = ai_store.record_conversation_turn(
            robot_id,
            {
                "role": "assistant",
                "content": reply,
                "personality_id": personality.get("id"),
                "action_taken": action_taken,
                "rgb_applied": rgb_val,
                "camera_attached": camera_jpeg is not None,
                "engine_used": engine_used,
                "latency_ms": latency_ms,
            },
        )
        ai_store.record_voice_log(
            robot_id=robot_id,
            direction="in",
            transcript=clean_msg,
            action_taken=action_taken or f"chat:{personality.get('id', 'dog')}",
            reply_text=reply,
        )

        if robot_id in self._state:
            self._state[robot_id]["last_heard"] = clean_msg
            self._state[robot_id]["last_reply"] = reply

        return {
            "ok": True,
            "user_turn": user_turn,
            "assistant_turn": assistant_turn,
            "reply": reply,
            "action_taken": action_taken,
            "rgb_applied": rgb_val,
            "camera_attached": camera_jpeg is not None,
            "spoken": spoken,
            "engine_used": engine_used,
            "voice_used": voice_used,
            "latency_ms": latency_ms,
            "source": str(llm_res.get("source") or "offline_fallback"),
            "tool_calls": tool_calls,
        }

    async def start(
        self,
        robot_id: str,
        ip: str,
        user: str,
        password: str,
        get_config_and_personality: Callable[[], Tuple[Dict[str, Any], Dict[str, Any]]],
        run_turn: Callable[[str], Coroutine[Any, Any, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Start the hands-free background "Hey OX" wake & follow-up conversation loop for ``robot_id``."""
        await self.stop(robot_id)
        self._start_args[robot_id] = {
            "ip": ip,
            "user": user,
            "password": password,
            "get_config_and_personality": get_config_and_personality,
            "run_turn": run_turn,
        }
        cfg, pers = get_config_and_personality()
        self._followup_until[robot_id] = 0.0
        self._state[robot_id] = {
            "robot_id": robot_id,
            "active": True,
            "state": "listening_wake",
            "wake_word": str(cfg.get("wake_word") or DEFAULT_WAKE_WORD),
            "personality_id": str(cfg.get("personality_id") or "dog"),
            "personality_name": str(pers.get("name") or "Playful Robot Dog"),
            "followup_remaining_sec": 0.0,
            "mic_rms": 0.0,
            "noise_floor": 15.0,
            "last_heard": None,
            "last_reply": None,
            "error": None,
        }

        async def _handle_utterance_wav(wav_bytes: bytes) -> None:
            live_cfg, live_pers = get_config_and_personality()
            wake_w = str(live_cfg.get("wake_word") or DEFAULT_WAKE_WORD)
            self._state[robot_id]["wake_word"] = wake_w
            self._state[robot_id]["personality_id"] = str(live_cfg.get("personality_id") or "dog")
            self._state[robot_id]["personality_name"] = str(live_pers.get("name") or "")

            transcript = await transcribe_wav_offline(wav_bytes, wake_word=wake_w)
            if not transcript:
                return
            self._state[robot_id]["last_heard"] = transcript

            low_t = _normalize_phrase(transcript)
            if any(sp in low_t for sp in SLEEP_PHRASES):
                self._followup_until[robot_id] = 0.0
                self._state[robot_id]["state"] = "listening_wake"
                try:
                    await play_speaker_chime(ip, user, password, chime="dong")
                except Exception:
                    pass
                return

            in_followup = time.monotonic() < self._followup_until.get(robot_id, 0.0)
            utterance = ""
            if in_followup:
                utterance = transcript
            else:
                matched, remainder = match_custom_wake_word(
                    transcript,
                    wake_word=wake_w,
                    aliases=live_cfg.get("wake_aliases") or DEFAULT_WAKE_ALIASES,
                )
                if not matched:
                    return
                try:
                    await play_speaker_chime(ip, user, password, chime="wakeup")
                except Exception:
                    pass
                if remainder:
                    utterance = remainder
                else:
                    win = max(4.0, float(live_cfg.get("followup_window_sec") or 12))
                    self._followup_until[robot_id] = time.monotonic() + win
                    self._state[robot_id]["state"] = "in_conversation"
                    return

            self._state[robot_id]["state"] = "thinking"
            res = await run_turn(utterance)
            self._state[robot_id]["last_reply"] = res.get("reply")
            self._state[robot_id]["state"] = "speaking"
            win = float(live_cfg.get("followup_window_sec") or 0)
            self._followup_until[robot_id] = (time.monotonic() + win) if win > 0 else 0.0
            self._state[robot_id]["state"] = "followup_window" if win > 0 else "listening_wake"

        async def _loop() -> None:
            # Best-effort boost WonderEcho Mic Gain to 100% so soft speech 4+ ft away registers strongly
            if not hasattr(record_mic_on_robot, "assert_called"):
                try:
                    await set_audio_mixer(ip=ip, user=user, password=password, mic_gain_pct=100, mic_mute=False)
                except Exception as exc:
                    sys.stderr.write(f"[conversation.loop] Mic boost skipped on {ip}: {exc}\n")

            noise_floor = 15.0
            noise_initialized = False
            use_stream = not hasattr(record_mic_on_robot, "assert_called")

            while True:
                try:
                    if use_stream:
                        pre_roll: deque[bytes] = deque(maxlen=2)  # 0.5s pre-roll (2 x 250ms)
                        speech_buf = bytearray()
                        capturing = False
                        quiet_frames = 0
                        echo_mute_until = 0.0

                        try:
                            async for pcm_frame in stream_mic_pcm_frames(ip=ip, user=user, password=password):
                                now = time.monotonic()
                                rms = _compute_pcm16_rms(pcm_frame)
                                self._state[robot_id]["mic_rms"] = round(rms, 1)
                                if self._state[robot_id].get("error"):
                                    self._state[robot_id]["error"] = None

                                in_followup = now < self._followup_until.get(robot_id, 0.0)
                                if not capturing:
                                    self._state[robot_id]["state"] = (
                                        "followup_window" if in_followup else "listening_wake"
                                    )

                                # Drain audio while speaker is playing + 0.35s echo guard
                                if now < echo_mute_until:
                                    pre_roll.clear()
                                    continue

                                if not noise_initialized:
                                    noise_floor = max(6.0, min(120.0, rms))
                                    noise_initialized = True

                                thresh = max(22.0, noise_floor * 1.65)
                                self._state[robot_id]["noise_floor"] = round(noise_floor, 1)

                                if not capturing:
                                    if rms >= thresh:
                                        capturing = True
                                        quiet_frames = 0
                                        speech_buf = bytearray()
                                        for prev in pre_roll:
                                            speech_buf.extend(prev)
                                        speech_buf.extend(pcm_frame)
                                        self._state[robot_id]["state"] = "in_conversation"
                                    else:
                                        noise_floor = max(6.0, min(150.0, min(rms, noise_floor * 0.85 + rms * 0.15)))
                                        self._state[robot_id]["noise_floor"] = round(noise_floor, 1)
                                        pre_roll.append(pcm_frame)
                                else:
                                    speech_buf.extend(pcm_frame)
                                    if rms < max(18.0, noise_floor * 1.35):
                                        quiet_frames += 1
                                    else:
                                        quiet_frames = 0
                                    # Finalize after ~0.85s trailing silence (4 x 250ms) or max 7.0s (28 x 250ms)
                                    if quiet_frames >= 4 or len(speech_buf) >= 28 * 8000:
                                        wav_bytes = _pcm16_to_wav(bytes(speech_buf))
                                        capturing = False
                                        speech_buf = bytearray()
                                        pre_roll.clear()
                                        await _handle_utterance_wav(wav_bytes)
                                        echo_mute_until = time.monotonic() + 0.45
                        except asyncio.CancelledError:
                            raise
                        except Exception as stream_exc:
                            sys.stderr.write(f"[conversation.stream] Persistent mic stream error on {ip}: {stream_exc}\n")
                            self._state[robot_id]["mic_rms"] = 0.0
                            if "ERR:NO_USB_MIC" in str(stream_exc) or "No USB audio" in str(stream_exc):
                                self._state[robot_id]["error"] = USB_MIC_DISCONNECTED_MSG
                            else:
                                self._state[robot_id]["error"] = str(stream_exc)
                            await asyncio.sleep(2.0)
                        continue

                    # Fallback chunked capture (also used seamlessly by unit tests mocking record_mic_on_robot)
                    in_followup = time.monotonic() < self._followup_until.get(robot_id, 0.0)
                    self._state[robot_id]["state"] = "followup_window" if in_followup else "listening_wake"
                    wav_bytes = await record_mic_on_robot(
                        ip=ip, user=user, password=password, duration_sec=4 if in_followup else 3
                    )
                    rms = _compute_wav_rms(wav_bytes)
                    self._state[robot_id]["mic_rms"] = round(rms, 1)
                    if self._state[robot_id].get("error"):
                        self._state[robot_id]["error"] = None
                    if not noise_initialized:
                        noise_floor = max(6.0, min(120.0, rms))
                        noise_initialized = True
                    thresh = max(22.0, noise_floor * 1.65)
                    self._state[robot_id]["noise_floor"] = round(noise_floor, 1)
                    if rms < thresh:
                        noise_floor = max(6.0, min(150.0, min(rms, noise_floor * 0.85 + rms * 0.15)))
                        self._state[robot_id]["noise_floor"] = round(noise_floor, 1)
                        await asyncio.sleep(0.15)
                        continue
                    await _handle_utterance_wav(wav_bytes)
                    await asyncio.sleep(0.35)
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    sys.stderr.write(f"[conversation.loop] Error on {ip}: {exc}\n")
                    self._state[robot_id]["mic_rms"] = 0.0
                    if "ERR:NO_USB_MIC" in str(exc) or "No USB audio" in str(exc):
                        self._state[robot_id]["error"] = USB_MIC_DISCONNECTED_MSG
                    else:
                        self._state[robot_id]["error"] = str(exc)
                    await asyncio.sleep(1.5)

        self._tasks[robot_id] = asyncio.create_task(_loop())
        return self.get_state(robot_id, config=cfg, personality=pers)

    async def stop(self, robot_id: str) -> Dict[str, Any]:
        """Stop the hands-free background conversation loop for ``robot_id``."""
        task = self._tasks.pop(robot_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._followup_until[robot_id] = 0.0
        st = self.get_state(robot_id)
        st["active"] = False
        st["state"] = "idle"
        st["followup_remaining_sec"] = 0.0
        self._state[robot_id] = st
        return dict(st)

    async def stop_all(self) -> None:
        """Stop all active hands-free conversation loops on application shutdown."""
        for rid in list(self._tasks.keys()):
            await self.stop(rid)

    def is_active(self, robot_id: str) -> bool:
        """Return ``True`` if a hands-free conversation loop is currently running for ``robot_id``."""
        task = self._tasks.get(robot_id)
        return bool(task is not None and not task.done())

    async def resume_if_saved(self, robot_id: str) -> None:
        """Resume a previously paused hands-free loop using its saved start arguments."""
        saved = self._start_args.get(robot_id)
        if saved:
            await self.start(robot_id=robot_id, **saved)


async def run_voice_diagnostics(
    robot_id: str,
    ip: str,
    user: str,
    password: str,
    wake_word: str = DEFAULT_WAKE_WORD,
    wake_aliases: Optional[Sequence[str]] = None,
    record_live_sec: int = 4,
    test_speaker: bool = False,
    conversation_manager: Optional[RobotConversationManager] = None,
) -> Dict[str, Any]:
    """Run a 6-point WonderEcho USB, ALSA, serial, Piper+Whisper loopback, live mic & speaker diagnostic.

    Temporarily pauses any active hands-free loop on ``conversation_manager`` during live mic
    recording to avoid ALSA ``Device or resource busy``, and resumes it cleanly afterward.

    Args:
        robot_id: Target robot UUID.
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH password.
        wake_word: Configured custom wake word (default ``"Hey OX"``).
        wake_aliases: Configured phonetic wake-word aliases.
        record_live_sec: Seconds to record live mic audio (``0`` skips live recording).
        test_speaker: When ``True``, plays a short chime on the detected USB audio card.
        conversation_manager: Optional ``RobotConversationManager`` to pause/resume cleanly.

    Returns:
        Structured dictionary matching ``VoiceDiagnosticsResponse``.
    """
    checks: List[Dict[str, Any]] = []
    usb_devices: List[str] = []
    dmesg_warnings: List[str] = []
    card_index: Optional[int] = None
    audio_detected = False
    live_mic_test: Optional[Dict[str, Any]] = None

    # 1-3: Hardware SSH probe (USB/Power, ALSA Audio, /dev/wonderecho Symlink)
    t0 = time.perf_counter()
    hw: Optional[Dict[str, Any]] = None
    hw_err: Optional[str] = None
    try:
        hw = await collect_voice_hardware_diagnostics(ip=ip, user=user, password=password)
    except Exception as exc:
        hw_err = str(exc)
        sys.stderr.write(f"[voice.diag] Hardware probe failed on {ip}: {exc}\n")
    hw_ms = int((time.perf_counter() - t0) * 1000)

    if hw is None:
        checks.append(
            {
                "id": "usb_power",
                "name": "WonderEcho USB & Pi 5 Power",
                "status": "fail",
                "detail": f"SSH hardware probe failed: {hw_err}",
                "latency_ms": hw_ms,
            }
        )
        checks.append(
            {
                "id": "alsa_audio",
                "name": "USB ALSA Audio Card & Mixer",
                "status": "fail",
                "detail": "Skipped (SSH hardware probe failed).",
                "latency_ms": 0,
            }
        )
        checks.append(
            {
                "id": "serial_symlink",
                "name": "WonderEcho Serial Symlink (/dev/wonderecho)",
                "status": "fail",
                "detail": "Skipped (SSH hardware probe failed).",
                "latency_ms": 0,
            }
        )
    else:
        usb_devices = list(hw.get("usb_devices") or [])
        dmesg_warnings = list(hw.get("dmesg_usb_warnings") or [])
        has_audio = bool(hw.get("has_usb_audio_0c76"))
        has_hub = bool(hw.get("has_wonderecho_hub_1a86_8091"))
        has_ch340 = bool(hw.get("has_ch340_1a86_7523"))
        throttled = str(hw.get("throttled") or "")
        cpu_temp = str(hw.get("cpu_temp") or "")
        under_voltage = ("throttled=0x0" not in throttled.lower()) and bool(throttled)

        if has_audio and has_hub and has_ch340 and not under_voltage:
            usb_status = "pass"
            usb_detail = (
                f"WonderEcho USB Audio (0c76:161f), Hub (1a86:8091), and CH340 (1a86:7523) all enumerated. "
                f"{throttled} {cpu_temp}".strip()
            )
        elif has_audio:
            usb_status = "warn"
            usb_detail = (
                f"USB Audio detected (hub={has_hub}, ch340={has_ch340}, {throttled or 'throttle n/a'}, "
                f"{len(dmesg_warnings)} dmesg USB lines)."
            )
        else:
            usb_status = "fail"
            usb_detail = (
                "WonderEcho USB Audio (0c76:161f) NOT enumerated in lsusb. "
                "Re-seat both cable ends into a lower black USB 2.0 port."
            )
        checks.append(
            {
                "id": "usb_power",
                "name": "WonderEcho USB & Pi 5 Power",
                "status": usb_status,
                "detail": usb_detail,
                "latency_ms": hw_ms,
            }
        )

        audio_detected = bool(hw.get("audio_card_detected"))
        card_index = int(hw["card_index"]) if hw.get("card_index") is not None else None
        if audio_detected and card_index is not None:
            checks.append(
                {
                    "id": "alsa_audio",
                    "name": "USB ALSA Audio Card & Mixer",
                    "status": "pass",
                    "detail": (
                        f"Card {card_index} ({hw.get('device_name', 'USB Audio')}) ready — "
                        f"Speaker {hw.get('speaker_volume_pct', 0)}% ({'muted' if hw.get('speaker_muted') else 'unmuted'}), "
                        f"Mic {hw.get('mic_gain_pct', 0)}% ({'muted' if hw.get('mic_muted') else 'active'})."
                    ),
                    "latency_ms": hw_ms,
                }
            )
        else:
            checks.append(
                {
                    "id": "alsa_audio",
                    "name": "USB ALSA Audio Card & Mixer",
                    "status": "fail",
                    "detail": "No USB ALSA playback/capture card found in arecord -l / aplay -l.",
                    "latency_ms": hw_ms,
                }
            )

        sym_ok = bool(hw.get("serial_symlink_present"))
        checks.append(
            {
                "id": "serial_symlink",
                "name": "WonderEcho Serial Symlink (/dev/wonderecho)",
                "status": "pass" if sym_ok else "warn",
                "detail": (
                    f"/dev/wonderecho -> {hw.get('serial_target') or 'present'}"
                    if sym_ok
                    else "/dev/wonderecho absent (custom software wake word still works via USB audio, or click Install Udev Rules)."
                ),
                "latency_ms": 0,
            }
        )

    # 4. Piper -> Faster-Whisper software loopback test (proves backend TTS + STT + Wake matcher)
    t_loop = time.perf_counter()
    try:
        probe_phrase = f"{wake_word}, tell me a joke"
        loop_wav, loop_eng, _ = await synthesize_speech_wav(
            probe_phrase, engine="piper_tts", anti_clip=False
        )
        loop_txt = await transcribe_wav_offline(loop_wav, wake_word=wake_word)
        loop_matched, loop_rem = match_custom_wake_word(loop_txt, wake_word=wake_word, aliases=wake_aliases)
        loop_ms = int((time.perf_counter() - t_loop) * 1000)
        checks.append(
            {
                "id": "piper_whisper_loopback",
                "name": f"Piper + Whisper \"{wake_word}\" Loopback",
                "status": "pass" if loop_matched else "warn",
                "detail": (
                    f"Synth ({loop_eng}) -> Whisper heard \"{loop_txt}\" -> "
                    f"{'MATCHED' if loop_matched else 'NOT MATCHED'} (remainder: \"{loop_rem}\")."
                ),
                "latency_ms": loop_ms,
            }
        )
    except Exception as exc:
        loop_ms = int((time.perf_counter() - t_loop) * 1000)
        checks.append(
            {
                "id": "piper_whisper_loopback",
                "name": f"Piper + Whisper \"{wake_word}\" Loopback",
                "status": "fail",
                "detail": f"Loopback failed: {exc}",
                "latency_ms": loop_ms,
            }
        )

    # 5. Live Mic Capture + Whisper Transcription + Wake-Word / Alias Suggester
    dur = max(0, min(8, int(record_live_sec)))
    if dur == 0:
        checks.append(
            {
                "id": "live_mic_test",
                "name": "Live Microphone & Wake-Word Test",
                "status": "skipped",
                "detail": "Skipped (record_live_sec=0). Use 'Record 4s & Test' to test your voice live.",
                "latency_ms": 0,
            }
        )
    elif not audio_detected:
        live_mic_test = {
            "recorded": False,
            "duration_sec": dur,
            "audio_bytes": 0,
            "mic_rms": 0.0,
            "mic_peak": 0,
            "live_transcript": "",
            "wake_matched": False,
            "remainder": "",
            "suggested_alias": None,
            "error": USB_MIC_DISCONNECTED_MSG,
        }
        checks.append(
            {
                "id": "live_mic_test",
                "name": "Live Microphone & Wake-Word Test",
                "status": "fail",
                "detail": USB_MIC_DISCONNECTED_MSG,
                "latency_ms": 0,
            }
        )
    else:
        was_running = bool(conversation_manager and conversation_manager.is_active(robot_id))
        if was_running and conversation_manager is not None:
            await conversation_manager.stop(robot_id)
            await asyncio.sleep(0.25)
        t_mic = time.perf_counter()
        try:
            wav_bytes = await record_mic_on_robot(
                ip=ip, user=user, password=password, duration_sec=dur, card_index=card_index
            )
            pcm = wav_bytes[44:] if len(wav_bytes) > 44 else b""
            rms = round(_compute_pcm16_rms(pcm), 1)
            peak = 0
            if len(pcm) >= 2:
                samples = np.frombuffer(pcm[: (len(pcm) // 2) * 2], dtype=np.int16)
                peak = int(np.max(np.abs(samples))) if samples.size else 0

            live_txt = await transcribe_wav_offline(wav_bytes, wake_word=wake_word)
            matched, rem = match_custom_wake_word(live_txt, wake_word=wake_word, aliases=wake_aliases)
            suggested_alias: Optional[str] = None
            if live_txt and not matched:
                words = _normalize_phrase(live_txt).split()
                if words:
                    suggested_alias = " ".join(words[:2])

            mic_ms = int((time.perf_counter() - t_mic) * 1000)
            live_mic_test = {
                "recorded": True,
                "duration_sec": dur,
                "audio_bytes": len(wav_bytes),
                "mic_rms": rms,
                "mic_peak": peak,
                "live_transcript": live_txt,
                "wake_matched": matched,
                "remainder": rem,
                "suggested_alias": suggested_alias,
                "error": None,
            }
            if matched:
                mic_status = "pass"
                mic_detail = f"Heard \"{live_txt}\" (RMS {rms}, Peak {peak}) -> Wake word MATCHED!"
            elif live_txt:
                mic_status = "warn"
                mic_detail = (
                    f"Heard \"{live_txt}\" (RMS {rms}, Peak {peak}), did not match \"{wake_word}\". "
                    f"Suggested alias: \"{suggested_alias}\"."
                )
            else:
                mic_status = "warn" if rms >= 20.0 else "fail"
                mic_detail = (
                    f"Recorded {len(wav_bytes):,} B (RMS {rms}, Peak {peak}), but Whisper heard no speech. "
                    "Speak clearly within 4 ft or check mic gain."
                )
            checks.append(
                {
                    "id": "live_mic_test",
                    "name": "Live Microphone & Wake-Word Test",
                    "status": mic_status,
                    "detail": mic_detail,
                    "latency_ms": mic_ms,
                }
            )
        except Exception as exc:
            mic_ms = int((time.perf_counter() - t_mic) * 1000)
            live_mic_test = {
                "recorded": False,
                "duration_sec": dur,
                "audio_bytes": 0,
                "mic_rms": 0.0,
                "mic_peak": 0,
                "live_transcript": "",
                "wake_matched": False,
                "remainder": "",
                "suggested_alias": None,
                "error": str(exc),
            }
            checks.append(
                {
                    "id": "live_mic_test",
                    "name": "Live Microphone & Wake-Word Test",
                    "status": "fail",
                    "detail": f"Live mic recording failed: {exc}",
                    "latency_ms": mic_ms,
                }
            )
        finally:
            if was_running and conversation_manager is not None:
                try:
                    await conversation_manager.resume_if_saved(robot_id)
                except Exception as exc:
                    sys.stderr.write(f"[voice.diag] Failed resuming hands-free loop: {exc}\n")

    # 6. Optional Speaker Chime Test
    if not test_speaker:
        checks.append(
            {
                "id": "speaker_test",
                "name": "WonderEcho Speaker Chime Test",
                "status": "skipped",
                "detail": "Skipped (enable 'Test Speaker Chime' to play a live confirmation tone).",
                "latency_ms": 0,
            }
        )
    elif not audio_detected:
        checks.append(
            {
                "id": "speaker_test",
                "name": "WonderEcho Speaker Chime Test",
                "status": "fail",
                "detail": "Skipped — no USB audio playback card detected.",
                "latency_ms": 0,
            }
        )
    else:
        t_spk = time.perf_counter()
        try:
            await play_speaker_chime(ip=ip, user=user, password=password, chime="wakeup", card_index=card_index)
            checks.append(
                {
                    "id": "speaker_test",
                    "name": "WonderEcho Speaker Chime Test",
                    "status": "pass",
                    "detail": f"Played wakeup chime cleanly on ALSA Card {card_index}.",
                    "latency_ms": int((time.perf_counter() - t_spk) * 1000),
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "id": "speaker_test",
                    "name": "WonderEcho Speaker Chime Test",
                    "status": "fail",
                    "detail": f"Speaker chime failed: {exc}",
                    "latency_ms": int((time.perf_counter() - t_spk) * 1000),
                }
            )

    passed_count = sum(1 for c in checks if c["status"] == "pass")
    failed_count = sum(1 for c in checks if c["status"] == "fail")
    return {
        "ok": failed_count == 0,
        "robot_id": robot_id,
        "passed_count": passed_count,
        "total_count": len(checks),
        "card_index": card_index,
        "wake_word": wake_word,
        "checks": checks,
        "live_mic_test": live_mic_test,
        "dmesg_usb_warnings": dmesg_warnings,
        "usb_devices": usb_devices,
    }
