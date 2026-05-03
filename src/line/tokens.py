from __future__ import annotations

from datetime import timedelta

from livekit import api

from line.settings import VoiceConfig


def generate_join_token(
    config: VoiceConfig,
    room: str,
    identity: str,
    ttl_minutes: int = 60,
) -> str:
    room = room.strip()
    identity = identity.strip()
    if not room:
        raise ValueError("room must not be blank")
    if not identity:
        raise ValueError("identity must not be blank")

    return (
        api.AccessToken(config.livekit_api_key, config.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_ttl(timedelta(minutes=ttl_minutes))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .to_jwt()
    )
