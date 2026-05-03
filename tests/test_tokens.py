import pytest

from line.settings import VoiceConfig
from line.tokens import generate_join_token

TEST_LIVEKIT_HMAC = "0" * 32
TEST_LIVEKIT_KEY = "test-livekit-value"
TEST_STT_KEY = "test-stt-value"
TEST_TTS_KEY = "test-tts-value"


def test_generate_join_token_returns_jwt() -> None:
    config = VoiceConfig(
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key=TEST_LIVEKIT_KEY,
        livekit_api_secret=TEST_LIVEKIT_HMAC,
        deepgram_api_key=TEST_STT_KEY,
        elevenlabs_api_key=TEST_TTS_KEY,
    )

    token = generate_join_token(config=config, room="line-dev", identity="iphone")

    assert token.count(".") == 2


def test_generate_join_token_rejects_blank_room() -> None:
    config = VoiceConfig(
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key=TEST_LIVEKIT_KEY,
        livekit_api_secret=TEST_LIVEKIT_HMAC,
        deepgram_api_key=TEST_STT_KEY,
        elevenlabs_api_key=TEST_TTS_KEY,
    )

    with pytest.raises(ValueError, match="room"):
        generate_join_token(config=config, room="", identity="iphone")
