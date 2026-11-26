"""Unit and API tests for WonderEcho Pro Voice Studio, 5-byte UART protocol, ALSA mixer, TTS/Chimes, and Udev Rules."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.robot.ssh_manager import _UDEV_RULES_CONTENT, install_puppypi_udev_rules
from src.robot.voice_manager import (
    _MAX_INLINE_B64_CHARS,
    WONDERECHO_EQ_FILTER,
    condition_audio_for_wonderecho,
    list_available_voices,
    parse_amixer_controls,
    parse_voice_intent,
    parse_wonderecho_frame,
    play_wav_on_robot,
    synthesize_chime_wav,
    synthesize_speech_wav,
    synthesize_tts_wav,
)


def _make_test_client() -> tuple[TestClient, str]:
    settings = Settings(database_url="", neo4j_uri="", openrouter_api_key="")
    repo = InMemoryTwinRepository()
    robot_store = InMemoryRobotStore()
    ai_store = InMemoryRobotAiStore()
    app = create_app(settings=settings, repository=repo, robot_store=robot_store, robot_ai_store=ai_store)
    robot = robot_store.upsert_robot(
        {
            "ip_address": "192.168.1.119",
            "name": "PuppyPi Test",
            "model": "Hiwonder PuppyPi Pro",
            "active_ros_distro": "ROS2 Humble",
            "ssh_user": "pi",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "battery_mv": 7640,
        },
        ssh_password="raspberrypi",
    )
    return TestClient(app), robot["id"]


def test_parse_wonderecho_frame_protocol() -> None:
    """Verify exact 5-byte WonderEcho Pro UART frames for wake, sleep, offline commands, and junk bytes."""
    wake = parse_wonderecho_frame(bytes([0xAA, 0x55, 0x03, 0x00, 0xFB]))
    assert wake is not None
    assert wake["event"] == "wake"
    assert wake["intent"] == "wake"

    sleep_evt = parse_wonderecho_frame(bytes([0x00, 0xFF, 0xAA, 0x55, 0x02, 0x00, 0xFB]))
    assert sleep_evt is not None
    assert sleep_evt["event"] == "sleep"

    stand = parse_wonderecho_frame(bytes([0xAA, 0x55, 0x00, 0x8A, 0xFB]))
    assert stand is not None
    assert stand["event"] == "offline_command"
    assert stand["intent"] == "stand"

    sit = parse_wonderecho_frame(bytes([0xAA, 0x55, 0x00, 0x8B, 0xFB]))
    assert sit is not None and sit["intent"] == "sit"

    wave = parse_wonderecho_frame(bytes([0xAA, 0x55, 0x00, 0x8D, 0xFB]))
    assert wave is not None and wave["intent"] == "wave"

    assert parse_wonderecho_frame(b"\x01\x02\x03") is None
    assert parse_wonderecho_frame(b"\xAA\x55\x03\x00\x00") is None


def test_parse_amixer_controls_speaker_and_mic() -> None:
    """Parse real live PuppyPi Card 2 amixer output where Mic Playback [off] and Capture [on] share one line."""
    sample = """
Simple mixer control 'Speaker',0
  Capabilities: pvolume pswitch pswitch-joined
  Playback channels: Front Left - Front Right
  Limits: Playback 0 - 1008
  Mono:
  Front Left: Playback 655 [65%] [-22.07dB] [on]
  Front Right: Playback 655 [65%] [-22.07dB] [on]
Simple mixer control 'Mic',0
  Capabilities: pvolume pvolume-joined cvolume cvolume-joined pswitch pswitch-joined cswitch cswitch-joined
  Playback channels: Mono
  Capture channels: Mono
  Limits: Playback 0 - 496 Capture 0 - 496
  Mono: Playback 322 [65%] [20.12dB] [off] Capture 322 [65%] [20.12dB] [on]
"""
    parsed = parse_amixer_controls(sample)
    assert parsed["speaker_volume_pct"] == 65
    assert parsed["speaker_muted"] is False
    assert parsed["mic_gain_pct"] == 65
    assert parsed["mic_muted"] is False


def test_condition_audio_for_wonderecho_eq_and_fallback() -> None:
    """Verify ffmpeg WonderEcho anti-clipping EQ filter args and graceful WAV fallback when ffmpeg is missing."""
    sample_wav = synthesize_chime_wav("dong")

    # 1. Mock ffmpeg invocation and confirm exact WonderEcho EQ filter chain & 16kHz mono PCM output
    captured_cmd: list[str] = []

    class _FakeProc:
        returncode = 0
        stdout = sample_wav
        stderr = b""

    def _fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _FakeProc()

    with patch("src.robot.voice_manager.subprocess.run", side_effect=_fake_run):
        out = condition_audio_for_wonderecho(sample_wav, input_format="wav", anti_clip=True)
        assert out == sample_wav
        assert "-af" in captured_cmd
        assert WONDERECHO_EQ_FILTER in captured_cmd
        assert "16000" in captured_cmd
        assert "pcm_s16le" in captured_cmd

    # 2. Missing ffmpeg gracefully returns original WAV bytes
    with patch("src.robot.voice_manager.subprocess.run", side_effect=FileNotFoundError("no ffmpeg")):
        out2 = condition_audio_for_wonderecho(sample_wav, input_format="wav", anti_clip=True)
        assert out2 == sample_wav


@pytest.mark.asyncio
async def test_synthesize_speech_wav_auto_cascade_edge_piper_espeak(tmp_path) -> None:
    """Verify auto TTS cascade tries edge_tts -> piper_tts -> espeak cleanly."""
    sample_wav = synthesize_chime_wav("wakeup")

    # 1. Edge Neural succeeds
    with (
        patch("src.robot.voice_manager.synthesize_edge_tts_mp3", new=AsyncMock(return_value=b"ID3" + b"\x00" * 1024)),
        patch("src.robot.voice_manager.condition_audio_for_wonderecho", return_value=sample_wav),
    ):
        wav, eng, voice = await synthesize_speech_wav("Hello world", engine="auto")
        assert wav[:4] == b"RIFF"
        assert eng == "edge_tts"
        assert voice == "en-US-AndrewMultilingualNeural"

    # 2. Edge fails -> automatically falls back to offline Piper Neural
    with (
        patch("src.robot.voice_manager.synthesize_edge_tts_mp3", new=AsyncMock(side_effect=RuntimeError("offline"))),
        patch("src.robot.voice_manager.synthesize_piper_tts_wav", new=AsyncMock(return_value=sample_wav)),
        patch("src.robot.voice_manager.condition_audio_for_wonderecho", return_value=sample_wav),
    ):
        wav, eng, voice = await synthesize_speech_wav("Hello offline", engine="auto", models_dir=tmp_path)
        assert wav[:4] == b"RIFF"
        assert eng == "piper_tts"
        assert voice == "en_US-lessac-medium"

    # 3. Both Edge and Piper fail -> automatically falls back to legacy eSpeak
    with (
        patch("src.robot.voice_manager.synthesize_edge_tts_mp3", new=AsyncMock(side_effect=RuntimeError("offline"))),
        patch("src.robot.voice_manager.synthesize_piper_tts_wav", new=AsyncMock(side_effect=RuntimeError("no model"))),
        patch("src.robot.voice_manager.condition_audio_for_wonderecho", return_value=sample_wav),
    ):
        wav, eng, voice = await synthesize_speech_wav("Hello fallback", engine="auto", models_dir=tmp_path)
        assert wav[:4] == b"RIFF"
        assert eng in ("espeak-ng", "espeak", "fallback-tone")
        assert voice == "en-us"

    # 4. Catalog detects cached Piper voice files in models_dir/piper/
    pdir = tmp_path / "piper"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "en_US-lessac-medium.onnx").write_bytes(b"0" * 100)
    (pdir / "en_US-lessac-medium.onnx.json").write_text("{}")
    cat = list_available_voices(models_dir=tmp_path)
    assert cat["default_engine"] == "piper_tts"
    assert "en_US-lessac-medium" in cat["cached_piper_voices"]


@pytest.mark.asyncio
async def test_play_wav_on_robot_chunks_large_payload_below_arg_limit() -> None:
    """Verify >150 KB incompressible WAV payload is zlib-compressed and chunked <= 32 KB per SSH call."""
    import os
    import zlib

    # 180 KB incompressible random payload (still >180 KB after zlib -> >240 KB base64 -> >= 8 chunks)
    big_wav = b"RIFF" + os.urandom(180_000)
    calls: list[dict] = []

    async def _fake_remote(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "bytes_played": len(big_wav), "device": "plughw:2,0"}

    with patch("src.robot.voice_manager.run_remote_python", side_effect=_fake_remote):
        res = await play_wav_on_robot("192.168.1.119", "pi", "raspberrypi", big_wav)
        assert res["ok"] is True

    # Multiple chunk writes + 1 final play call, and EVERY single SSH payload stays <= _MAX_INLINE_B64_CHARS
    assert len(calls) >= 7
    reassembled = ""
    tmp_path = None
    for c in calls[:-1]:
        p = c["payload"]
        assert len(p["chunk"]) <= _MAX_INLINE_B64_CHARS
        reassembled += p["chunk"]
        tmp_path = p["tmp_path"]
    final_payload = calls[-1]["payload"]
    assert final_payload["tmp_path"] == tmp_path
    assert final_payload["compressed"] is True
    import base64

    assert zlib.decompress(base64.b64decode(reassembled)) == big_wav


def test_synthesize_chime_and_tts_wav() -> None:
    """Verify synthesized chimes and TTS output produce valid RIFF/WAVE PCM payloads."""
    for name in ("dong", "wakeup", "success", "alert"):
        wav = synthesize_chime_wav(name)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert len(wav) > 1000

    tts_wav, engine = synthesize_tts_wav("Hello PuppyPi", voice="en-us", speed=155)
    assert tts_wav[:4] == b"RIFF"
    assert engine in ("espeak-ng", "espeak", "fallback-tone")


def test_parse_voice_intent_commands() -> None:
    """Verify natural language voice commands map to the expected robot intents."""
    assert parse_voice_intent("emergency stop now")["intent"] == "stop"
    assert parse_voice_intent("please stand up")["intent"] == "stand"
    assert parse_voice_intent("sit down boy")["intent"] == "sit"
    assert parse_voice_intent("lie down")["intent"] == "lie_down"
    assert parse_voice_intent("wave hello")["intent"] == "wave"
    assert parse_voice_intent("shake hands")["intent"] == "shake_hands"
    assert parse_voice_intent("start patrol")["intent"] == "start_patrol"
    assert parse_voice_intent("stop patrol")["intent"] == "stop_patrol"
    assert parse_voice_intent("follow me")["intent"] == "follow_target"
    assert parse_voice_intent("follow the line")["intent"] == "line_follow"
    assert parse_voice_intent("what do you see")["intent"] == "describe_scene"
    assert parse_voice_intent("who is in front")["intent"] == "who_is_there"
    assert parse_voice_intent("battery status report")["intent"] == "status_report"
    assert parse_voice_intent("")["intent"] == "none"


def test_udev_rules_two_stage_hub_matching() -> None:
    """Ensure persistent udev rules distinguish WonderEcho hub 1a86:8091 from direct LD19 LiDAR."""
    assert 'ENV{PUPPYPI_WONDERECHO_HUB}="1"' in _UDEV_RULES_CONTENT
    assert 'SYMLINK+="wonderecho"' in _UDEV_RULES_CONTENT
    assert 'ENV{PUPPYPI_WONDERECHO_HUB}!="1"' in _UDEV_RULES_CONTENT
    assert 'SYMLINK+="ldlidar"' in _UDEV_RULES_CONTENT


@pytest.mark.asyncio
async def test_install_puppypi_udev_rules_mocked() -> None:
    """Verify install_puppypi_udev_rules invokes remote python with SUDO_PW env."""
    fake_res = {
        "ok": True,
        "wonderecho_present": True,
        "ldlidar_present": False,
        "detail": "Installed /etc/udev/rules.d/99-puppypi-serial.rules",
    }
    with patch("src.robot.ssh_manager.run_remote_python", new=AsyncMock(return_value=fake_res)) as mock_run:
        res = await install_puppypi_udev_rules("192.168.1.119", "pi", "raspberrypi")
        assert res["ok"] is True
        assert res["wonderecho_present"] is True
        mock_run.assert_awaited_once()


def test_voice_api_endpoints_end_to_end() -> None:
    """Exercise all 8 WonderEcho Pro Voice & Udev FastAPI endpoints."""
    client, robot_id = _make_test_client()
    with client:
        fake_status = {
            "robot_id": robot_id,
            "audio_card_detected": True,
            "card_index": 2,
            "device_name": "UACDemoV1.0",
            "speaker_volume_pct": 85,
            "speaker_muted": False,
            "mic_gain_pct": 70,
            "mic_muted": False,
            "serial_symlink_present": True,
            "serial_device": "/dev/wonderecho",
            "asr_language": "English",
            "wake_listener_active": False,
            "last_wake_event": None,
        }
        with patch("src.api.routes_voice.get_voice_status", new=AsyncMock(return_value=fake_status)):
            r = client.get(f"/api/robots/{robot_id}/voice/status")
            assert r.status_code == 200
            data = r.json()
            assert data["audio_card_detected"] is True
            assert data["serial_device"] == "/dev/wonderecho"

        with patch("src.api.routes_voice.set_audio_mixer", new=AsyncMock(return_value={**fake_status, "speaker_volume_pct": 60})):
            r = client.put(f"/api/robots/{robot_id}/voice/mixer", json={"speaker_volume_pct": 60, "speaker_mute": False})
            assert r.status_code == 200
            assert r.json()["speaker_volume_pct"] == 60

        # GET /voice/voices catalog endpoint
        r_cat = client.get(f"/api/robots/{robot_id}/voice/voices")
        assert r_cat.status_code == 200
        cat = r_cat.json()
        assert cat["default_engine"] == "piper_tts"
        assert {e["id"] for e in cat["engines"]} == {"auto", "edge_tts", "piper_tts", "espeak"}
        assert any(v["id"] == "en-US-AndrewMultilingualNeural" for v in cat["voices"])
        assert any(v["id"] == "en_US-lessac-medium" for v in cat["voices"])

        with patch(
            "src.api.routes_voice.speak_text_on_robot",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "text": "Hello room",
                    "bytes_sent": 24000,
                    "engine": "edge_tts",
                    "voice": "en-US-AndrewMultilingualNeural",
                    "anti_clip": True,
                }
            ),
        ):
            r = client.post(
                f"/api/robots/{robot_id}/voice/speak",
                json={
                    "text": "Hello room",
                    "engine": "auto",
                    "voice": "en-US-AndrewMultilingualNeural",
                    "speed": 150,
                    "anti_clip": True,
                },
            )
            assert r.status_code == 200
            sp = r.json()
            assert sp["ok"] is True
            assert sp["engine"] == "edge_tts"
            assert sp["voice"] == "en-US-AndrewMultilingualNeural"
            assert sp["anti_clip"] is True

        with patch(
            "src.api.routes_voice.play_speaker_chime",
            new=AsyncMock(return_value={"ok": True, "chime": "wakeup"}),
        ):
            r = client.post(f"/api/robots/{robot_id}/voice/chime", json={"chime": "wakeup"})
            assert r.status_code == 200
            assert r.json()["chime"] == "wakeup"

        with (
            patch("src.api.routes_voice.publish_pose", new=AsyncMock(return_value={"published": True})) as mock_pose,
            patch("src.robot.voice_manager.speak_text_on_robot", new=AsyncMock(return_value={"ok": True})),
        ):
            r = client.post(
                f"/api/robots/{robot_id}/voice/listen",
                json={"simulated_transcript": "sit down please", "execute_commands": True, "speak_reply": True},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert body["intent"] == "sit"
            assert body["action_taken"] == "pose:sit"
            assert body["spoken"] is True
            mock_pose.assert_awaited_once()

        # Toggle wake listener ON then OFF
        with patch("src.robot.voice_manager.run_remote_python", new=AsyncMock(return_value={"ok": True, "frames_b64": ""})):
            r_on = client.post(f"/api/robots/{robot_id}/voice/wake-listener", json={"enabled": True})
            assert r_on.status_code == 200
            assert r_on.json()["wake_listener_active"] is True

            r_off = client.post(f"/api/robots/{robot_id}/voice/wake-listener", json={"enabled": False})
            assert r_off.status_code == 200
            assert r_off.json()["wake_listener_active"] is False

        # Voice logs should contain our speak, chime, and listen entries
        r_logs = client.get(f"/api/robots/{robot_id}/voice/logs?limit=10")
        assert r_logs.status_code == 200
        entries = r_logs.json()["entries"]
        assert len(entries) >= 3
        assert any(e["action_taken"] == "pose:sit" for e in entries)
        assert any(e["transcript"] == "Hello room" and "edge_tts" in e["action_taken"] for e in entries)

        # Udev rules installer endpoint
        with patch(
            "src.api.routes_voice.install_puppypi_udev_rules",
            new=AsyncMock(return_value={"ok": True, "wonderecho_present": True, "ldlidar_present": False, "detail": "ok"}),
        ):
            r_udev = client.post(f"/api/robots/{robot_id}/hardware/udev-rules")
            assert r_udev.status_code == 200
            assert r_udev.json()["wonderecho_present"] is True
