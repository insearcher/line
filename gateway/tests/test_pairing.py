from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from urllib.parse import parse_qs, urlparse

import pytest

from line.pairing import PairingError, PairingStore, format_pairing_instructions, normalize_pairing_code


def test_pairing_code_completes_once_and_stores_only_hashes(tmp_path) -> None:
    store = PairingStore(tmp_path / "pairing.json")
    now = datetime(2026, 5, 2, 8, 0, tzinfo=UTC)

    session = store.start_pairing(
        server_url="http://192.0.2.10:8787",
        now=now,
    )
    state_before_pair = (tmp_path / "pairing.json").read_text(encoding="utf-8")

    assert session.code
    assert session.code not in state_before_pair
    assert session.payload["serverUrl"] == "http://192.0.2.10:8787"
    assert session.payload["code"] == session.code
    assert session.payload["macDeviceId"]

    credential = store.complete_pairing(
        code=session.code,
        device_name="Test iPhone",
        now=now + timedelta(seconds=5),
    )
    state_after_pair = json.loads((tmp_path / "pairing.json").read_text(encoding="utf-8"))

    assert credential.token
    assert credential.phone_id
    assert credential.mac_device_id == session.payload["macDeviceId"]
    assert credential.token not in json.dumps(state_after_pair)
    assert state_after_pair["pendingPairing"] is None
    assert state_after_pair["trustedPhones"][credential.phone_id]["deviceName"] == "Test iPhone"
    assert store.authenticate(credential.token) is True
    assert store.authenticate("wrong-token") is False

    with pytest.raises(PairingError, match="No active pairing code"):
        store.complete_pairing(code=session.code, device_name="Replay", now=now + timedelta(seconds=6))


def test_pairing_code_expires(tmp_path) -> None:
    store = PairingStore(tmp_path / "pairing.json")
    now = datetime(2026, 5, 2, 8, 0, tzinfo=UTC)

    session = store.start_pairing(
        server_url="http://127.0.0.1:8787",
        ttl_seconds=30,
        now=now,
    )

    with pytest.raises(PairingError, match="Pairing code expired"):
        store.complete_pairing(
            code=session.code,
            device_name="Late iPhone",
            now=now + timedelta(seconds=31),
        )


def test_pairing_code_normalization_accepts_spaces_and_dashes() -> None:
    assert normalize_pairing_code("ab-cd 23") == "ABCD23"


def test_pairing_instructions_include_gateway_invitation_deep_link(tmp_path) -> None:
    store = PairingStore(tmp_path / "pairing.json")
    now = datetime(2026, 5, 2, 8, 0, tzinfo=UTC)

    session = store.start_pairing(
        server_url="http://192.0.2.10:8787",
        ttl_seconds=300,
        now=now,
    )

    instructions = format_pairing_instructions(session)

    assert "Deep link: line://pair?" in instructions
    assert "QR code:" in instructions
    assert "\u2588\u2588" in instructions
    deep_link_line = next(line for line in instructions.splitlines() if line.startswith("Deep link: "))
    parsed = urlparse(deep_link_line.removeprefix("Deep link: "))
    query = parse_qs(parsed.query)
    assert parsed.scheme == "line"
    assert parsed.netloc == "pair"
    assert query["serverUrl"] == ["http://192.0.2.10:8787"]
    assert query["code"] == [session.code]
    assert query["macDeviceId"] == [session.payload["macDeviceId"]]
    assert query["expiresAt"] == [session.expires_at]
