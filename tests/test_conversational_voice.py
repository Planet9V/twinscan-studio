"""Unit and API tests for the Conversational Voice Assistant ("Hey OX"), Personalities, Piper Default & Hands-Free Loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.robot.conversation_engine import (
    BUILTIN_PERSONALITIES,
    USB_MIC_DISCONNECTED_MSG,
    RobotConversationManager,
    _decode_wav_to_float32,
    _pcm16_to_wav,
    match_custom_wake_word,
    needs_visual_context,
    offline_personality_fallback,
    parse_structured_llm_reply,
    transcribe_wav_offline,
)
from src.robot.voice_manager import (
    list_available_voices,
    parse_usb_audio_card_index,
    synthesize_chime_wav,
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
            "name": "PuppyPi OX",
            "model": "Hiwonder PuppyPi Pro",
            "active_ros_distro": "ROS2 Humble",
            "ssh_user": "pi",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "battery_mv": 7680,
        },
        ssh_password="raspberrypi",
    )
    return TestClient(app), robot["id"]


def test_match_custom_wake_word_hey_ox_and_aliases() -> None:
    """Verify 'Hey OX', punctuation, one-breath commands, phonetic aliases, and non-matches."""
    matched, rem = match_custom_wake_word("Hey OX, tell me a joke!")
    assert matched is True
    assert rem == "tell me a joke!"

    matched2, rem2 = match_custom_wake_word("hey aux")
    assert matched2 is True
    assert rem2 == ""

    matched3, rem3 = match_custom_wake_word("Uh, hey O X! What do you see?")
    assert matched3 is True
    assert rem3 == "What do you see?"

    matched4, rem4 = match_custom_wake_word("hey box sit down")
    assert matched4 is True
    assert rem4 == "sit down"

    matched_custom, rem_custom = match_custom_wake_word("Yo Jarvis, battery status", wake_word="Yo Jarvis", aliases=[])
    assert matched_custom is True
    assert rem_custom == "battery status"

    no_match, _ = match_custom_wake_word("good morning everyone")
    assert no_match is False


def test_needs_visual_context_and_structured_json_parser() -> None:
    """Verify visual question detection and structured LLM JSON reply parsing/sanitization."""
    assert needs_visual_context("Hey, what do you see in front of you?") is True
    assert needs_visual_context("Who is there right now?") is True
    assert needs_visual_context("Tell me a dad joke") is False

    parsed = parse_structured_llm_reply(
        '```json\n{"reply": "**Woof!** Ready to wave!", "action": "wave", "rgb": [0, 200, 300]}\n```'
    )
    assert parsed["reply"] == "Woof! Ready to wave!"
    assert parsed["action"] == "wave"
    assert parsed["rgb"] == [0, 200, 255]

    # Disallowed action is safely stripped to None
    parsed_bad = parse_structured_llm_reply('{"reply": "Sure.", "action": "rm_rf_root", "rgb": null}')
    assert parsed_bad["action"] is None
    assert parsed_bad["rgb"] is None

    # Plain non-JSON response falls back cleanly
    parsed_plain = parse_structured_llm_reply("Just a **plain** response.")
    assert parsed_plain["reply"] == "Just a plain response."
    assert parsed_plain["action"] is None


def test_offline_personality_fallback_all_five_personalities() -> None:
    """Verify all 5 built-in personalities produce distinct, in-character offline replies."""
    assert {p["id"] for p in BUILTIN_PERSONALITIES} == {"dog", "cat", "marvin", "dad_joke_nerd", "lab_assistant"}
    seen_replies = set()
    for p in BUILTIN_PERSONALITIES:
        res = offline_personality_fallback(
            "Tell me a joke!",
            personality_id=p["id"],
            assistant_name="OX",
            live_context={"battery_v": 7.68, "ros_mode": "ROS 2 Humble"},
        )
        assert res["reply"]
        assert res["source"] == "offline_fallback"
        seen_replies.add(res["reply"])
    assert len(seen_replies) == 5

    # Explicit body action request works offline
    sit_res = offline_personality_fallback("please sit down", personality_id="marvin", assistant_name="OX")
    assert sit_res["action"] == "sit"
    assert "servos" in sit_res["reply"].lower() or "sit" in sit_res["reply"].lower()


def test_default_voice_engine_is_offline_piper() -> None:
    """Verify Offline Piper Neural is the default TTS engine in catalog and robot config."""
    cat = list_available_voices()
    assert cat["default_engine"] == "piper_tts"
    assert cat["engines"][0]["id"] == "piper_tts"


def test_conversational_config_personalities_chat_and_hands_free_endpoints() -> None:
    """End-to-end API tests for config, 5 built-in + custom personalities, chat turns, history, hands-free & E-STOP."""
    client, robot_id = _make_test_client()
    fake_wav = synthesize_chime_wav("dong")

    with client:
        # 1. Default voice assistant config uses Hey OX + Offline Piper + Dog personality
        cfg = client.get(f"/api/robots/{robot_id}/voice/config")
        assert cfg.status_code == 200
        cdata = cfg.json()
        assert cdata["assistant_name"] == "OX"
        assert cdata["wake_word"] == "Hey OX"
        assert cdata["default_engine"] == "piper_tts"
        assert cdata["default_voice"] == "en_US-lessac-medium"
        assert cdata["personality_id"] == "dog"
        assert "hey aux" in cdata["wake_aliases"]

        # Update config to Marvin + custom follow-up window
        upd_cfg = client.put(
            f"/api/robots/{robot_id}/voice/config",
            json={"personality_id": "marvin", "followup_window_sec": 15, "wake_word": "Hey OX"},
        )
        assert upd_cfg.status_code == 200
        assert upd_cfg.json()["personality_id"] == "marvin"
        assert upd_cfg.json()["followup_window_sec"] == 15

        # 2. Personalities CRUD + built-in deletion guard
        plist = client.get("/api/voice/personalities")
        assert plist.status_code == 200
        assert len(plist.json()["personalities"]) == 5

        del_builtin = client.delete("/api/voice/personalities/marvin")
        assert del_builtin.status_code == 400

        created = client.post(
            "/api/voice/personalities",
            json={
                "name": "Pirate Captain",
                "badge": "PIRATE",
                "description": "Ahoy matey quadruped",
                "system_prompt": "Speak like a cheerful robotic pirate in 2 short sentences.",
                "default_voice": "en_US-ryan-medium",
                "allow_body_actions": True,
            },
        )
        assert created.status_code == 200
        custom_id = created.json()["personality"]["id"]
        assert created.json()["personality"]["is_builtin"] is False

        upd_p = client.put(f"/api/voice/personalities/{custom_id}", json={"badge": "CAPTAIN"})
        assert upd_p.status_code == 200
        assert upd_p.json()["personality"]["badge"] == "CAPTAIN"

        # 3. Conversational chat turn (offline fallback + action + TTS + multi-turn history)
        with (
            patch(
                "src.api.routes_voice.speak_text_on_robot",
                new=AsyncMock(
                    return_value={
                        "ok": True,
                        "text": "ok",
                        "engine": "piper_tts",
                        "voice": "en_US-lessac-medium",
                        "anti_clip": True,
                        "bytes_sent": 16000,
                    }
                ),
            ),
            patch(
                "src.api.routes_voice.speak_sentences_streaming",
                new=AsyncMock(
                    return_value={
                        "ok": True,
                        "text": "ok",
                        "engine": "piper_tts",
                        "voice": "en_US-lessac-medium",
                        "anti_clip": True,
                        "bytes_sent": 16000,
                    }
                ),
            ),
            patch("src.api.routes_voice.publish_pose", new=AsyncMock(return_value={"published": True})) as mock_pose,
            patch("src.api.routes_voice.set_rgb", new=AsyncMock(return_value={"published": True})),
        ):
            chat1 = client.post(
                f"/api/robots/{robot_id}/voice/chat",
                json={"message": "please sit down", "speak_reply": True, "attach_camera": "never", "execute_actions": True},
            )
            assert chat1.status_code == 200
            body1 = chat1.json()
            assert body1["ok"] is True
            assert body1["action_taken"] == "pose:sit"
            assert body1["spoken"] is True
            assert body1["engine_used"] == "piper_tts"
            mock_pose.assert_awaited_once()

        hist = client.get(f"/api/robots/{robot_id}/voice/conversation/history?limit=10")
        assert hist.status_code == 200
        turns = hist.json()["turns"]
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[1]["role"] == "assistant"

        cleared = client.delete(f"/api/robots/{robot_id}/voice/conversation/history")
        assert cleared.status_code == 200
        assert cleared.json()["cleared"] == 2

        # 4. Hands-free conversation start -> state -> E-STOP halts it cleanly -> stop
        with (
            patch("src.robot.conversation_engine.record_mic_on_robot", new=AsyncMock(return_value=fake_wav)),
            patch("src.robot.conversation_engine.transcribe_wav_offline", new=AsyncMock(return_value="")),
            patch("src.api.routes_robots.trigger_estop", new=AsyncMock(return_value={"estop": True})),
        ):
            st_start = client.post(f"/api/robots/{robot_id}/voice/conversation/start")
            assert st_start.status_code == 200
            assert st_start.json()["active"] is True
            assert st_start.json()["wake_word"] == "Hey OX"

            st_get = client.get(f"/api/robots/{robot_id}/voice/conversation/state")
            assert st_get.status_code == 200
            st_data = st_get.json()
            assert st_data["active"] is True
            assert "mic_rms" in st_data
            assert "noise_floor" in st_data

            # Global E-STOP must also halt active hands-free loop
            estop = client.post(f"/api/robots/{robot_id}/estop")
            assert estop.status_code == 200

            st_after = client.get(f"/api/robots/{robot_id}/voice/conversation/state")
            assert st_after.json()["active"] is False

            st_stop = client.post(f"/api/robots/{robot_id}/voice/conversation/stop")
            assert st_stop.status_code == 200
            assert st_stop.json()["active"] is False

        assert client.delete(f"/api/voice/personalities/{custom_id}").json()["deleted"] is True


@pytest.mark.asyncio
async def test_decode_wav_to_float32_auto_gain_and_transcribe_bypasses_pyav() -> None:
    """Verify stdlib wave+numpy decoder boosts quiet speech and passes np.ndarray float32 (never BytesIO) to Whisper."""
    # Synthesize 0.5s quiet 440 Hz sine wave with RMS ~25 (peak ~350/32768 ~= 0.0107)
    t = np.arange(8000, dtype=np.float32) / 16000.0
    quiet_pcm = (np.sin(2.0 * np.pi * 440.0 * t) * 350.0).astype(np.int16).tobytes()
    quiet_wav = _pcm16_to_wav(quiet_pcm, sample_rate=16000)

    decoded = _decode_wav_to_float32(quiet_wav)
    assert isinstance(decoded, np.ndarray)
    assert decoded.dtype == np.float32
    assert decoded.ndim == 1
    assert decoded.size == 8000
    # Auto-gain should amplify peak ~0.0107 by up to 12x -> peak > 0.10
    assert float(np.max(np.abs(decoded))) > 0.10

    captured: dict = {}

    class _FakeSeg:
        text = "Hey OX, tell me a joke"

    class _FakeModel:
        def transcribe(self, audio, **kwargs):
            captured["audio"] = audio
            captured["kwargs"] = kwargs
            return [_FakeSeg()], None

    with patch("src.robot.conversation_engine._load_whisper_model", return_value=_FakeModel()):
        out = await transcribe_wav_offline(quiet_wav, wake_word="Hey OX")
        assert out == "Hey OX, tell me a joke"
        assert isinstance(captured["audio"], np.ndarray)
        assert captured["audio"].dtype == np.float32
        assert captured["kwargs"]["vad_filter"] is False
        assert "Hey OX" in captured["kwargs"]["initial_prompt"]


def test_parse_usb_audio_card_index_detects_card3_and_skips_hdmi() -> None:
    """Verify dynamic ALSA card parser detects USB PnP Audio on Card 3 and skips HDMI Cards 0 & 1."""
    aplay_out = """
**** List of PLAYBACK Hardware Devices ****
card 0: vc4hdmi0 [vc4-hdmi-0], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
card 1: vc4hdmi1 [vc4-hdmi-1], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
card 3: Device [USB PnP Audio Device], device 0: USB Audio [USB Audio]
"""
    arecord_out = """
**** List of CAPTURE Hardware Devices ****
card 3: Device [USB PnP Audio Device], device 0: USB Audio [USB Audio]
"""
    idx, name = parse_usb_audio_card_index(aplay_out, arecord_out)
    assert idx == 3
    assert "USB PnP Audio" in name

    # When ONLY HDMI cards exist, returns (None, "")
    hdmi_only = """
card 0: vc4hdmi0 [vc4-hdmi-0], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
card 1: vc4hdmi1 [vc4-hdmi-1], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
"""
    idx_none, name_none = parse_usb_audio_card_index(hdmi_only, "")
    assert idx_none is None
    assert name_none == ""


@pytest.mark.asyncio
async def test_usb_disconnect_error_surfaces_in_conversation_state() -> None:
    """Verify ERR:NO_USB_MIC immediately surfaces clear USB disconnect error and mic_rms=0.0."""
    import asyncio

    mgr = RobotConversationManager()

    async def _fail_stream(**kwargs):
        raise RuntimeError("ERR:NO_USB_MIC")
        yield b""  # pragma: no cover

    with (
        patch("src.robot.conversation_engine.set_audio_mixer", new=AsyncMock(return_value={})),
        patch("src.robot.conversation_engine.stream_mic_pcm_frames", side_effect=_fail_stream),
    ):
        await mgr.start(
            robot_id="r-usb-drop",
            ip="192.168.1.119",
            user="pi",
            password="raspberrypi",
            get_config_and_personality=lambda: (
                {"wake_word": "Hey OX", "personality_id": "dog", "followup_window_sec": 12},
                {"id": "dog", "name": "Playful Robot Dog"},
            ),
            run_turn=AsyncMock(return_value={"reply": "ok"}),
        )
        await asyncio.sleep(0.15)
        st = mgr.get_state("r-usb-drop")
        assert st["error"] == USB_MIC_DISCONNECTED_MSG
        assert st["mic_rms"] == 0.0
        await mgr.stop("r-usb-drop")


def test_voice_diagnostics_endpoint_all_six_checks_and_suggested_alias() -> None:
    """Verify POST /api/robots/{id}/voice/diagnostics returns all 6 checks and suggests a wake alias."""
    client, robot_id = _make_test_client()
    fake_wav = synthesize_chime_wav("wakeup")

    fake_hw = {
        "usb_devices": [
            "Bus 003 Device 005: ID 0c76:161f JMTek, LLC. USB PnP Audio Device",
            "Bus 003 Device 002: ID 1a86:8091 QinHeng Electronics USB HUB",
            "Bus 003 Device 004: ID 1a86:7523 QinHeng Electronics CH340 serial converter",
        ],
        "has_usb_audio_0c76": True,
        "has_wonderecho_hub_1a86_8091": True,
        "has_ch340_1a86_7523": True,
        "audio_card_detected": True,
        "card_index": 3,
        "device_name": "USB PnP Audio Device",
        "speaker_volume_pct": 80,
        "speaker_muted": False,
        "mic_gain_pct": 100,
        "mic_muted": False,
        "serial_symlink_present": True,
        "serial_target": "/dev/ttyUSB0",
        "throttled": "throttled=0x0",
        "cpu_temp": "temp=52.0'C",
        "dmesg_usb_warnings": ["usb 3-1: reset full-speed USB device"],
    }

    transcribe_replies = iter(["Hey OX, tell me a joke", "Hey Rocks, tell me a joke"])

    async def _fake_transcribe(wav_bytes, **kwargs):
        return next(transcribe_replies)

    with client:
        with (
            patch("src.robot.conversation_engine.collect_voice_hardware_diagnostics", new=AsyncMock(return_value=fake_hw)),
            patch("src.robot.conversation_engine.synthesize_speech_wav", new=AsyncMock(return_value=(fake_wav, "piper_tts", "en_US-lessac-medium"))),
            patch("src.robot.conversation_engine.transcribe_wav_offline", side_effect=_fake_transcribe),
            patch("src.robot.conversation_engine.record_mic_on_robot", new=AsyncMock(return_value=fake_wav)),
            patch("src.robot.conversation_engine.play_speaker_chime", new=AsyncMock(return_value={"ok": True})),
        ):
            r = client.post(
                f"/api/robots/{robot_id}/voice/diagnostics",
                json={"record_live_sec": 4, "test_speaker": True},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert data["card_index"] == 3
            assert data["total_count"] == 6
            check_ids = [c["id"] for c in data["checks"]]
            assert check_ids == [
                "usb_power",
                "alsa_audio",
                "serial_symlink",
                "piper_whisper_loopback",
                "live_mic_test",
                "speaker_test",
            ]
            assert data["live_mic_test"] is not None
            assert data["live_mic_test"]["recorded"] is True
            assert data["live_mic_test"]["wake_matched"] is False
            assert data["live_mic_test"]["suggested_alias"] == "hey rocks"
            assert len(data["usb_devices"]) == 3
            assert len(data["dmesg_usb_warnings"]) == 1
