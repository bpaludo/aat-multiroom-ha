"""Tests for the AAT protocol parser/encoder.

Run with:  pytest tests/ -v
Also runnable standalone: python tests/test_protocol.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "aat_multiroom"))

import aat_protocol  # noqa: E402
from aat_protocol import (  # noqa: E402
    AatClient,
    AatCommandError,
    AatTimeout,
    DeviceState,
    encode_command,
    parse_message,
)
from const import inputs_for_model, zones_for_model  # noqa: E402


# ---------------------------------------------------------------------------
# encode_command
# ---------------------------------------------------------------------------

def test_encode_pwron():
    assert encode_command(1, "PWRON") == b"[t001 PWRON]"

def test_encode_pwrtog():
    assert encode_command(2, "PWRTOG") == b"[t002 PWRTOG]"

def test_encode_volset():
    assert encode_command(1, "VOLSET", 1, 15) == b"[t001 VOLSET 1 15]"

def test_encode_volget():
    assert encode_command(2, "VOLGET", 4) == b"[t002 VOLGET 4]"

def test_encode_inpset():
    assert encode_command(1, "INPSET", 1, 1) == b"[t001 INPSET 1 1]"

def test_encode_zstdbyon():
    assert encode_command(7, "ZSTDBYON", 1) == b"[t007 ZSTDBYON 1]"

def test_encode_seq_max():
    assert encode_command(999, "PWRON") == b"[t999 PWRON]"


# ---------------------------------------------------------------------------
# parse_message
# ---------------------------------------------------------------------------

def test_parse_pwron_reply():
    assert parse_message("[r001 PWRON]") == ("r", 1, "PWRON", [])

def test_parse_pwrtog_on():
    assert parse_message("[r001 PWRTOG ON]") == ("r", 1, "PWRTOG", ["ON"])

def test_parse_volget():
    assert parse_message("[r002 VOLGET 4 40]") == ("r", 2, "VOLGET", ["4", "40"])

def test_parse_volset():
    assert parse_message("[r001 VOLSET 1 15]") == ("r", 1, "VOLSET", ["1", "15"])

def test_parse_zstdbyget_on():
    assert parse_message("[r001 ZSTDBYGET 4 ON]") == ("r", 1, "ZSTDBYGET", ["4", "ON"])

def test_parse_muteget():
    assert parse_message("[r002 MUTEGET 4 OFF]") == ("r", 2, "MUTEGET", ["4", "OFF"])

def test_parse_notification_powerdown():
    assert parse_message("[n001 POWERDOWN]") == ("n", 1, "POWERDOWN", [])

def test_parse_model_uppercase():
    assert parse_message("[R001 MODEL PMR4]") == ("r", 1, "MODEL", ["PMR4"])

def test_parse_ver_multi_token():
    assert parse_message("[R001 VER Multiroom V1.13]") == ("r", 1, "VER", ["Multiroom", "V1.13"])

def test_parse_lowercase_type():
    assert parse_message("[t005 VOLSET 1 15]") == ("t", 5, "VOLSET", ["1", "15"])

def test_parse_garbage_returns_none():
    assert parse_message("not a message") is None

def test_parse_muteall():
    assert parse_message("[r001 MUTEALL]") == ("r", 1, "MUTEALL", [])

def test_parse_ztonall():
    assert parse_message("[r001 ZTONALL]") == ("r", 1, "ZTONALL", [])

def test_parse_bassset():
    assert parse_message("[r001 BASSSET 1 14]") == ("r", 1, "BASSSET", ["1", "14"])

def test_parse_balset():
    assert parse_message("[r001 BALSET 2 10]") == ("r", 1, "BALSET", ["2", "10"])


# ---------------------------------------------------------------------------
# get_all — PMR-7 spec example (6 zones)
# ---------------------------------------------------------------------------

SPEC_PMR7_GETALL = (
    "PMR7 V1.13 OFF 12345 60 "
    "6 30 OFF 14 14 20 7 "  # zone 1
    "5 30 OFF 14 14 20 7 "  # zone 2
    "5 30 OFF 14 14 20 7 "  # zone 3
    "5 30 OFF 14 14 20 7 "  # zone 4
    "5 30 OFF 14 14 20 7 "  # zone 5
    "5 30 OFF 14 14 20 7"   # zone 6
)


class _FakeStream:
    """Minimal asyncio stream pair that replays canned responses."""

    def __init__(self, replies: list[bytes]) -> None:
        self._replies = replies
        self._writes: list[bytes] = []
        self._buf = b""

    def write(self, data: bytes) -> None:
        self._writes.append(data)
        if self._replies:
            self._buf += self._replies.pop(0)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        pass

    def is_closing(self) -> bool:
        return False

    async def wait_closed(self) -> None:
        return None

    async def read(self, n: int) -> bytes:
        if not self._buf:
            await asyncio.sleep(0.001)
            return b""
        chunk = self._buf[:n]
        self._buf = self._buf[n:]
        return chunk


def test_getall_pmr7():
    """Parse the spec example for PMR-7 (6 zones, device OFF → standby skipped)."""

    async def run() -> DeviceState:
        client = AatClient("dummy", num_zones=6)
        reply = f"[r001 GETALL {SPEC_PMR7_GETALL}]".encode("ascii")
        # Device is OFF in the spec example, so ZSTDBYGET is NOT called.
        stream = _FakeStream([reply])
        client._reader = stream  # type: ignore[assignment]
        client._writer = stream  # type: ignore[assignment]
        return await client.get_all()

    state = asyncio.run(run())

    assert state.model == "PMR7"
    assert state.firmware == "V1.13"
    assert state.power is False
    assert len(state.zones) == 6

    z1 = state.zones[1]
    assert z1.input == 6
    assert z1.volume == 30
    assert z1.mute is False
    assert z1.bass == 14
    assert z1.treble == 14
    assert z1.balance == 20
    assert z1.preamp == 7
    # Device is OFF → all zones set to standby=True without ZSTDBYGET
    assert z1.standby is True

    z6 = state.zones[6]
    assert z6.input == 5
    assert z6.volume == 30


def test_getall_power_on_fetches_standby():
    """When device is ON, ZSTDBYGET is called per zone."""

    async def run() -> DeviceState:
        client = AatClient("dummy", num_zones=2)
        getall_payload = "PMR4 V1.17 ON 5000 0 1 20 OFF 7 7 10 0 2 15 OFF 7 7 10 0"
        reply = f"[r001 GETALL {getall_payload}]".encode("ascii")
        zstdby_replies = [
            f"[r{i + 2:03d} ZSTDBYGET {i + 1} OFF]".encode("ascii")
            for i in range(2)
        ]
        stream = _FakeStream([reply, *zstdby_replies])
        client._reader = stream  # type: ignore[assignment]
        client._writer = stream  # type: ignore[assignment]
        return await client.get_all()

    state = asyncio.run(run())

    assert state.power is True
    assert state.zones[1].standby is False
    assert state.zones[2].standby is False


# ---------------------------------------------------------------------------
# Volume/brightness helpers (inline — avoids importing HA deps from light.py)
# ---------------------------------------------------------------------------

AAT_VOLUME_MAX = 87


def _volume_to_brightness(volume: int) -> int:
    if volume <= 0:
        return 0
    return max(1, round(volume / AAT_VOLUME_MAX * 255))


def _brightness_to_volume(brightness: int) -> int:
    if brightness <= 0:
        return 0
    return max(1, round(brightness / 255 * AAT_VOLUME_MAX))


def test_volume_to_brightness_zero():
    assert _volume_to_brightness(0) == 0

def test_volume_to_brightness_max():
    assert _volume_to_brightness(87) == 255

def test_brightness_to_volume_zero():
    assert _brightness_to_volume(0) == 0

def test_brightness_to_volume_max():
    assert _brightness_to_volume(255) == 87

def test_brightness_roundtrip():
    for vol in range(0, 88):
        b = _volume_to_brightness(vol)
        v2 = _brightness_to_volume(b)
        assert abs(v2 - vol) <= 1, f"roundtrip failed for volume {vol}: got {v2}"


# ---------------------------------------------------------------------------
# Error-code detection (fork addition)
# ---------------------------------------------------------------------------

def test_error_code_reply_raises():
    """A bare error code in the command slot ('[r001 8]') is a rejection."""

    async def run() -> None:
        client = AatClient("dummy")
        stream = _FakeStream([b"[r001 8]"])  # error 8: PMR off
        client._reader = stream  # type: ignore[assignment]
        client._writer = stream  # type: ignore[assignment]
        await client.power_on()

    try:
        asyncio.run(run())
    except AatCommandError as err:
        assert err.code == "8"
    else:
        raise AssertionError("expected AatCommandError for '[r001 8]'")


def test_value_equal_to_error_code_is_not_an_error():
    """A valid echoed value that equals an error code must NOT be flagged."""

    async def run() -> int:
        client = AatClient("dummy")
        # VOLGET zone 1 = 17 (a legit volume that collides with error code 17)
        stream = _FakeStream([b"[r001 VOLGET 1 17]"])
        client._reader = stream  # type: ignore[assignment]
        client._writer = stream  # type: ignore[assignment]
        return await client.get_volume(1)

    assert asyncio.run(run()) == 17


def test_retry_after_idle_reset():
    """First read hits EOF (idle TCPTIMEOUT reset); command retries and succeeds."""

    async def run() -> bool:
        client = AatClient("dummy")
        dead = _FakeStream([])            # read() → b"" → treated as EOF
        # Attempt 1 uses seq 001 (dies); the retry sends seq 002, and the
        # device echoes that seq — so the good reply is 002, not 001.
        good = _FakeStream([b"[r002 PWRGET ON]"])
        streams = [dead, good]

        async def fake_connect() -> None:
            s = streams.pop(0)
            client._reader = s   # type: ignore[assignment]
            client._writer = s   # type: ignore[assignment]
            client._buffer = ""

        client.connect = fake_connect  # type: ignore[method-assign]
        return await client.get_power()

    assert asyncio.run(run()) is True


def test_timeout_does_not_retry():
    """A plain response timeout raises AatTimeout WITHOUT a resend.

    Retrying a timeout would double-apply non-idempotent VOL+/VOL- steppers, so
    the retry is restricted to AatConnectionError (idle reset = EOF).
    """
    writes: list[bytes] = []

    class _HangStream(_FakeStream):
        def write(self, data: bytes) -> None:
            writes.append(data)  # capture, but never produce a reply

        async def read(self, n: int) -> bytes:
            await asyncio.sleep(3600)  # never yields — forces a read timeout
            return b""

    async def run() -> None:
        client = AatClient("dummy")
        stream = _HangStream([])
        client._reader = stream  # type: ignore[assignment]
        client._writer = stream  # type: ignore[assignment]
        saved = aat_protocol.RESPONSE_TIMEOUT
        aat_protocol.RESPONSE_TIMEOUT = 0.05  # keep the test fast
        try:
            await client.volume_up(1)
        finally:
            aat_protocol.RESPONSE_TIMEOUT = saved

    raised = False
    try:
        asyncio.run(run())
    except AatTimeout:
        raised = True
    assert raised, "expected AatTimeout"
    assert len(writes) == 1, f"command must be sent once, not retried; got {len(writes)}"


# ---------------------------------------------------------------------------
# MODEL → topology derivation (fork addition)
# ---------------------------------------------------------------------------

def test_zones_for_model():
    assert zones_for_model("PMR7") == 6
    assert zones_for_model("PMR5") == 6   # 4 inputs / 6 zones
    assert zones_for_model("PMR6") == 4   # 6 inputs / 4 zones
    assert zones_for_model("PMR-7") == 6  # tolerates the dash form
    assert zones_for_model("PMR8") == 2

def test_inputs_for_model():
    assert inputs_for_model("PMR7") == 6
    assert inputs_for_model("PMR5") == 4
    assert inputs_for_model("PMR8") == 5

def test_unknown_model_uses_fallback():
    assert zones_for_model("WHATEVER", fallback=6) == 6
    assert inputs_for_model("WHATEVER", fallback=6) == 6


if __name__ == "__main__":
    # Keep standalone execution for quick local runs without pytest.
    import subprocess, sys
    result = subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"], check=False)
    sys.exit(result.returncode)
