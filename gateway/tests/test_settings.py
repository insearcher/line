import os

import pytest

from pathlib import Path

from line.settings import ConfigError, VoiceConfig, load_env_file

TEST_LIVEKIT_HMAC = "0" * 32
TEST_LIVEKIT_KEY = "test-livekit-value"
TEST_STT_KEY = "test-stt-value"
TEST_TTS_KEY = "test-tts-value"
TEST_TTS_VOICE = "test-tts-voice"
TEST_TTS_MODEL = "test-tts-model"


def test_voice_config_reads_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPGRAM_LANGUAGE", raising=False)
    monkeypatch.delenv("TTS_PROVIDER", raising=False)
    monkeypatch.delenv("TTS_LANGUAGE", raising=False)
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", TEST_LIVEKIT_KEY)
    monkeypatch.setenv("LIVEKIT_API_SECRET", TEST_LIVEKIT_HMAC)
    monkeypatch.setenv("DEEPGRAM_API_KEY", TEST_STT_KEY)
    monkeypatch.setenv("ELEVENLABS_API_KEY", TEST_TTS_KEY)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", TEST_TTS_VOICE)
    monkeypatch.setenv("ELEVENLABS_MODEL", TEST_TTS_MODEL)

    config = VoiceConfig.from_env()

    assert config.livekit_url == "wss://example.livekit.cloud"
    assert config.livekit_api_key == TEST_LIVEKIT_KEY
    assert config.livekit_api_secret == TEST_LIVEKIT_HMAC
    assert config.deepgram_api_key == TEST_STT_KEY
    assert config.deepgram_language == "en"
    assert config.tts_provider == "elevenlabs"
    assert config.tts_language == "en"
    assert config.elevenlabs_api_key == TEST_TTS_KEY
    assert config.elevenlabs_voice_id == TEST_TTS_VOICE
    assert config.elevenlabs_model == TEST_TTS_MODEL


def test_voice_config_reports_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "ELEVENLABS_MODEL",
        "TTS_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigError) as error:
        VoiceConfig.from_env()

    message = str(error.value)
    assert "LIVEKIT_URL" in message
    assert "DEEPGRAM_API_KEY" in message
    assert "ELEVENLABS_API_KEY" in message
    assert "ELEVENLABS_VOICE_ID" in message
    assert "ELEVENLABS_MODEL" in message


def test_load_env_file_populates_missing_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LIVEKIT_URL=wss://example.livekit.cloud",
                f"LIVEKIT_API_KEY={TEST_LIVEKIT_KEY}",
                f"LIVEKIT_API_SECRET={TEST_LIVEKIT_HMAC}",
                f"DEEPGRAM_API_KEY={TEST_STT_KEY}",
                f"ELEVENLABS_API_KEY={TEST_TTS_KEY}",
                f"ELEVENLABS_VOICE_ID={TEST_TTS_VOICE}",
                f"ELEVENLABS_MODEL={TEST_TTS_MODEL}",
            ]
        ),
        encoding="utf-8",
    )
    for key in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "ELEVENLABS_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    load_env_file(env_path)

    assert VoiceConfig.from_env().deepgram_api_key == TEST_STT_KEY


def test_load_env_file_accepts_string_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPGRAM_LANGUAGE=en-US\n", encoding="utf-8")
    monkeypatch.delenv("DEEPGRAM_LANGUAGE", raising=False)

    load_env_file(str(env_path))

    assert os.environ["DEEPGRAM_LANGUAGE"] == "en-US"
