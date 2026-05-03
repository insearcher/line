from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceConfig:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    deepgram_api_key: str
    deepgram_language: str = "ru"
    tts_provider: str = "elevenlabs"
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = ""

    @classmethod
    def from_env(cls) -> VoiceConfig:
        tts_provider = (os.getenv("TTS_PROVIDER") or "elevenlabs").strip().lower()
        required: dict[str, str | None] = {
            "LIVEKIT_URL": os.getenv("LIVEKIT_URL"),
            "LIVEKIT_API_KEY": os.getenv("LIVEKIT_API_KEY"),
            "LIVEKIT_API_SECRET": os.getenv("LIVEKIT_API_SECRET"),
            "DEEPGRAM_API_KEY": os.getenv("DEEPGRAM_API_KEY"),
        }
        if tts_provider == "elevenlabs":
            required["ELEVENLABS_API_KEY"] = os.getenv("ELEVENLABS_API_KEY")
            required["ELEVENLABS_VOICE_ID"] = os.getenv("ELEVENLABS_VOICE_ID")
            required["ELEVENLABS_MODEL"] = os.getenv("ELEVENLABS_MODEL")
        missing = [key for key, value in required.items() if not value]
        if missing:
            formatted = ", ".join(missing)
            raise ConfigError(f"Missing required environment variables: {formatted}")

        return cls(
            livekit_url=required["LIVEKIT_URL"] or "",
            livekit_api_key=required["LIVEKIT_API_KEY"] or "",
            livekit_api_secret=required["LIVEKIT_API_SECRET"] or "",
            deepgram_api_key=required["DEEPGRAM_API_KEY"] or "",
            deepgram_language=os.getenv("DEEPGRAM_LANGUAGE") or "ru",
            tts_provider=tts_provider,
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY"),
            elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID") or "",
            elevenlabs_model=os.getenv("ELEVENLABS_MODEL") or "",
        )


def load_env_file(path: str | Path) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
