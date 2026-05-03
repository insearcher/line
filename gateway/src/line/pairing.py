from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import string
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4


PAIRING_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_PAIRING_TTL_SECONDS = 300


class PairingError(ValueError):
    pass


@dataclass(frozen=True)
class PairingSession:
    code: str
    expires_at: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PairingCredential:
    phone_id: str
    token: str
    mac_device_id: str


class PairingStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def start_pairing(
        self,
        *,
        server_url: str,
        ttl_seconds: int = DEFAULT_PAIRING_TTL_SECONDS,
        now: datetime | None = None,
    ) -> PairingSession:
        current_time = _utc_now(now)
        expires_at = current_time + timedelta(seconds=ttl_seconds)
        state = self._read_state()
        code = _new_pairing_code()
        state["pendingPairing"] = {
            "codeHash": _hash_secret("pair-code", normalize_pairing_code(code)),
            "createdAt": _format_time(current_time),
            "expiresAt": _format_time(expires_at),
            "serverUrl": server_url,
        }
        self._write_state(state)
        payload = {
            "v": 1,
            "serverUrl": server_url,
            "code": code,
            "macDeviceId": state["macDeviceId"],
            "expiresAt": _format_time(expires_at),
        }
        return PairingSession(
            code=code,
            expires_at=_format_time(expires_at),
            payload=payload,
        )

    def complete_pairing(
        self,
        *,
        code: str,
        device_name: str,
        now: datetime | None = None,
    ) -> PairingCredential:
        current_time = _utc_now(now)
        state = self._read_state()
        pending = state.get("pendingPairing")
        if pending is None:
            raise PairingError("No active pairing code")

        expires_at = _parse_time(pending["expiresAt"])
        if current_time > expires_at:
            state["pendingPairing"] = None
            self._write_state(state)
            raise PairingError("Pairing code expired")

        code_hash = _hash_secret("pair-code", normalize_pairing_code(code))
        if not secrets.compare_digest(code_hash, pending["codeHash"]):
            raise PairingError("Invalid pairing code")

        phone_id = str(uuid4())
        token = secrets.token_urlsafe(32)
        trusted_phones = dict(state.get("trustedPhones", {}))
        trusted_phones[phone_id] = {
            "deviceName": device_name.strip() or "iPhone",
            "tokenHash": _hash_secret("phone-token", token),
            "createdAt": _format_time(current_time),
            "lastSeenAt": None,
        }
        state["trustedPhones"] = trusted_phones
        state["pendingPairing"] = None
        self._write_state(state)
        return PairingCredential(
            phone_id=phone_id,
            token=token,
            mac_device_id=state["macDeviceId"],
        )

    def authenticate(self, token: str | None, *, now: datetime | None = None) -> bool:
        if not token:
            return False
        state = self._read_state()
        trusted_phones = dict(state.get("trustedPhones", {}))
        token_hash = _hash_secret("phone-token", token)
        for phone_id, phone in trusted_phones.items():
            if secrets.compare_digest(token_hash, phone.get("tokenHash", "")):
                phone = dict(phone)
                phone["lastSeenAt"] = _format_time(_utc_now(now))
                trusted_phones[phone_id] = phone
                state["trustedPhones"] = trusted_phones
                self._write_state(state)
                return True
        return False

    def _read_state(self) -> dict[str, Any]:
        if not self._path.exists():
            return _new_state()
        data = json.loads(self._path.read_text(encoding="utf-8"))
        data.setdefault("version", 1)
        data.setdefault("macDeviceId", str(uuid4()))
        data.setdefault("pendingPairing", None)
        data.setdefault("trustedPhones", {})
        return data

    def _write_state(self, state: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self._path)


def normalize_pairing_code(code: str) -> str:
    return "".join(character for character in code.upper() if character in string.ascii_uppercase + string.digits)


def format_pairing_instructions(session: PairingSession) -> str:
    return "\n".join(
        [
            f"Pairing code: {session.code}",
            f"Expires at: {session.expires_at}",
            f"Deep link: {_pairing_deep_link(session)}",
            "Payload JSON:",
            json.dumps(session.payload, ensure_ascii=False, sort_keys=True),
        ]
    )


def _new_state() -> dict[str, Any]:
    return {
        "version": 1,
        "macDeviceId": str(uuid4()),
        "pendingPairing": None,
        "trustedPhones": {},
    }


def _new_pairing_code() -> str:
    raw = "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _pairing_deep_link(session: PairingSession) -> str:
    query = urlencode(
        {
            "serverUrl": str(session.payload["serverUrl"]),
            "code": session.code,
            "macDeviceId": str(session.payload["macDeviceId"]),
            "expiresAt": session.expires_at,
        }
    )
    return f"line://pair?{query}"


def _hash_secret(kind: str, secret: str) -> str:
    return hashlib.sha256(f"line:{kind}:{secret}".encode("utf-8")).hexdigest()


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
