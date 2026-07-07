"""AAT Multiroom Digital — async TCP protocol client.

Implements the AAT Digital Matrix Amplifier API (TCP/Serial/IR) Rev.12,
firmware V3.08+. Tested against the PMR-4; the protocol is shared across the
PMA/PMRH/PMR line, so PMR-5/6/7/8 (and the streamer PMR-9..13, matrix side)
speak the same commands.

Message format (ASCII, case-insensitive):
    Send:    [t<seq> <CMD> [par1 [par2 ...]]]
    Reply:   [r<seq> <CMD> [par1 [par2 ...]]]
    Notify:  [n<seq> <CMD> ...]    (unsolicited — sent when state changes from
                                    the wall panel, IR remote, or mobile app)

Sequence number is 001..999, three digits. Replies echo the request seq.
Notifications use their own counter.

Robustness notes (fork changes):
  * The device resets idle TCP connections after TCPTIMEOUT seconds. A read
    that returns EOF now tears the socket down and the command is retried once
    on a fresh connection, so the first command after an idle reset no longer
    fails in the user's face.
  * Device-level rejections (error codes 7/8/17/18) are detected and raised as
    AatCommandError instead of being silently swallowed. Detection is framing-
    safe and deliberately conservative: a normal reply always echoes the command
    name, so a bare error code in the command position (e.g. "[r001 8]") is
    unambiguously an error. We do NOT treat a value that merely equals an error
    code as a failure (e.g. VOLGET z 17 → params ["z","17"], not an error), which
    is why detection only inspects the command slot, never the params. See
    _check_reply().
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 5000
RESPONSE_TIMEOUT = 5.0
CONNECT_TIMEOUT = 5.0

# Per spec section 1.5: volume is 0..87 (each step = 1 dB)
VOLUME_MIN = 0
VOLUME_MAX = 87

# Per spec section 1.10: inputs 1..8 depending on model.
INPUT_MIN = 1
INPUT_MAX = 8

# Documented rejection codes (spec section 1.3.8 and per-command tables).
#   7  – command does not exist
#   8  – command only accepted while the PMR is powered on
#   17 – invalid zone number
#   18 – invalid parameter value
ERROR_CODES: dict[str, str] = {
    "7": "comando inexistente",
    "8": "comando só aceito com o amplificador ligado",
    "17": "número de zona inválido",
    "18": "valor de parâmetro inválido",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AatError(Exception):
    """Base error for AAT communication."""


class AatConnectionError(AatError):
    """Cannot reach the device or connection dropped."""


class AatProtocolError(AatError):
    """Received a malformed or unexpected message."""


class AatTimeout(AatError):
    """Timed out waiting for a response."""


class AatCommandError(AatError):
    """The device rejected the command (error code 7/8/17/18)."""

    def __init__(self, code: str, cmd: str) -> None:
        self.code = code
        self.cmd = cmd
        reason = ERROR_CODES.get(code, f"código {code}")
        super().__init__(f"{cmd} rejeitado pelo amplificador: {reason}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ZoneState:
    zone: int
    input: int = 1
    volume: int = 0
    mute: bool = False
    standby: bool = True   # True = zone is OFF (amplifier in stand-by)
    bass: int = 7          # 0..14, 7 = 0 dB
    treble: int = 7        # 0..14, 7 = 0 dB
    balance: int = 10      # 0..20, 10 = centered
    preamp: int = 0        # 0..7 (0 dB .. +14 dB)


@dataclass
class DeviceState:
    model: str = ""
    firmware: str = ""
    power: bool = False                          # whole device on/off
    zones: dict[int, ZoneState] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parser / encoder
# ---------------------------------------------------------------------------

# Anchored at start so we only ever match a single framed message.
_MSG_RE = re.compile(r"\[\s*([trnTRN])\s*(\d{3})\s+([^\s\]]+)([^\]]*)\]")


def parse_message(raw: str) -> Optional[tuple[str, int, str, list[str]]]:
    """Parse a single framed AAT message.

    Returns (type, seq, cmd, params) or None if it doesn't match.
    type is one of "t", "r", "n" (lowercase).
    """
    m = _MSG_RE.match(raw)
    if not m:
        return None
    msg_type = m.group(1).lower()
    seq = int(m.group(2))
    cmd = m.group(3).upper()
    params_raw = m.group(4).strip()
    params = params_raw.split() if params_raw else []
    return msg_type, seq, cmd, params


def encode_command(seq: int, cmd: str, *params) -> bytes:
    """Encode an outgoing command into ASCII bytes."""
    parts = [f"[t{seq:03d}", cmd.upper()]
    parts.extend(str(p) for p in params)
    return (" ".join(parts) + "]").encode("ascii")


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class AatClient:
    """Async TCP client for the AAT Multiroom Digital line."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        num_zones: int = 6,
    ) -> None:
        self._host = host
        self._port = port
        self._num_zones = num_zones
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._seq = 0
        self._lock = asyncio.Lock()
        self._buffer = ""

    # --- connection lifecycle -----------------------------------------------

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=CONNECT_TIMEOUT,
            )
            self._buffer = ""
            _LOGGER.debug("Connected to %s:%s", self._host, self._port)
        except (asyncio.TimeoutError, OSError) as err:
            raise AatConnectionError(
                f"Cannot connect to {self._host}:{self._port}: {err}"
            ) from err

    async def disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = None
        self._writer = None
        self._buffer = ""

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    # --- internal helpers ---------------------------------------------------

    def _next_seq(self) -> int:
        self._seq = (self._seq % 999) + 1
        return self._seq

    async def _read_message(self) -> tuple[str, int, str, list[str]]:
        """Read exactly one framed message from the socket."""
        assert self._reader is not None

        while True:
            # If we already have a full frame in the buffer, return it.
            start = self._buffer.find("[")
            if start != -1:
                end = self._buffer.find("]", start)
                if end != -1:
                    raw = self._buffer[start : end + 1]
                    self._buffer = self._buffer[end + 1 :]
                    parsed = parse_message(raw)
                    if parsed is None:
                        # Skip an unparseable frame instead of killing the read
                        # loop — keep draining the buffer for a valid frame.
                        _LOGGER.debug("Skipping unparseable frame: %r", raw)
                        continue
                    return parsed

            # Otherwise pull more bytes.
            try:
                chunk = await self._reader.read(4096)
            except OSError as err:
                raise AatConnectionError(f"Read failed: {err}") from err

            if not chunk:
                raise AatConnectionError("Connection closed by remote")
            self._buffer += chunk.decode("ascii", errors="ignore")

    @staticmethod
    def _check_reply(cmd: str, msg_cmd: str) -> None:
        """Raise AatCommandError if the reply signals a device rejection.

        Conservative, framing-safe detection: we raise only when a documented
        error code (7/8/17/18) sits where the command name should be — e.g.
        "[r001 8]". A valid echoed *value* that happens to equal an error code
        (e.g. VOLSET z 17) is never mistaken for an error because it lands in
        the params, not ``msg_cmd``. We intentionally do NOT reject on a
        command-name mismatch: the sequence number already pairs request and
        reply, and being lenient here avoids false errors if a firmware frames a
        reply slightly differently than the datasheet examples.
        """
        if msg_cmd in ERROR_CODES:
            raise AatCommandError(msg_cmd, cmd)

    async def send(self, cmd: str, *params) -> list[str]:
        """Send a command, await the matching reply, return reply params.

        Retries once on a fresh connection if the link was reset while idle
        (the AAT resets connections after TCPTIMEOUT). Raises AatCommandError
        if the device rejects the command.

        The retry fires only on AatConnectionError — the idle reset shows up as
        an EOF on read, which is a connection error. A plain AatTimeout is NOT
        retried: the command may already have executed on the device, and blind
        resends would double-apply the non-idempotent VOL+/VOL- steppers.
        """
        async with self._lock:
            for attempt in (1, 2):
                try:
                    return await self._send_once(cmd, *params)
                except AatConnectionError as err:
                    # Idle reset / half-open socket: drop it and retry once on a
                    # fresh connection so the first post-timeout command works.
                    await self.disconnect()
                    if attempt == 1:
                        _LOGGER.debug(
                            "%s failed (%s); reconnecting and retrying once", cmd, err
                        )
                        continue
                    raise
            raise AssertionError("unreachable")  # pragma: no cover

    async def _send_once(self, cmd: str, *params) -> list[str]:
        if not self.connected:
            await self.connect()

        seq = self._next_seq()
        data = encode_command(seq, cmd, *params)
        _LOGGER.debug("AAT TX: %s", data)

        try:
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), timeout=RESPONSE_TIMEOUT)
        except (OSError, asyncio.TimeoutError) as err:
            await self.disconnect()
            raise AatConnectionError(f"Write failed: {err}") from err

        loop = asyncio.get_running_loop()
        deadline = loop.time() + RESPONSE_TIMEOUT
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AatTimeout(f"No response for {cmd}")
            try:
                msg_type, msg_seq, msg_cmd, params_out = await asyncio.wait_for(
                    self._read_message(), timeout=remaining
                )
            except asyncio.TimeoutError as err:
                raise AatTimeout(f"No response for {cmd}") from err

            _LOGGER.debug(
                "AAT RX: type=%s seq=%d cmd=%s params=%s",
                msg_type, msg_seq, msg_cmd, params_out,
            )

            if msg_type == "n":
                # Unsolicited state change (wall panel / app / IR). Log and
                # keep waiting for our reply. (A future revision could feed
                # these into the coordinator for push updates.)
                _LOGGER.debug("AAT notification: %s %s", msg_cmd, params_out)
                continue
            if msg_type == "r" and msg_seq == seq:
                self._check_reply(cmd, msg_cmd)
                return params_out
            # Unexpected reply (wrong seq / stray frame) — drop and keep waiting.
            _LOGGER.debug(
                "Discarding unexpected message type=%s seq=%d cmd=%s",
                msg_type, msg_seq, msg_cmd,
            )

    # --- high-level commands ------------------------------------------------

    async def power_on(self) -> None:
        """Turn the whole MD on."""
        await self.send("PWRON")

    async def power_off(self) -> None:
        """Turn the whole MD off."""
        await self.send("PWROFF")

    async def get_power(self) -> bool:
        params = await self.send("PWRGET")
        return bool(params) and params[0].upper() == "ON"

    async def zone_on(self, zone: int) -> None:
        """Take zone out of stand-by (zone is now playing)."""
        await self.send("ZSTDBYOFF", zone)

    async def zone_off(self, zone: int) -> None:
        """Put zone in stand-by (amp powered down, line/sub muted)."""
        await self.send("ZSTDBYON", zone)

    async def zone_get_standby(self, zone: int) -> bool:
        """Return True if zone is in stand-by (i.e., the zone is OFF)."""
        params = await self.send("ZSTDBYGET", zone)
        return len(params) >= 2 and params[1].upper() == "ON"

    async def set_volume(self, zone: int, volume: int) -> None:
        v = max(VOLUME_MIN, min(VOLUME_MAX, int(volume)))
        await self.send("VOLSET", zone, v)

    async def volume_up(self, zone: int) -> None:
        await self.send("VOL+", zone)

    async def volume_down(self, zone: int) -> None:
        await self.send("VOL-", zone)

    async def get_volume(self, zone: int) -> int:
        params = await self.send("VOLGET", zone)
        return int(params[1]) if len(params) >= 2 else 0

    async def set_input(self, zone: int, input_num: int) -> None:
        await self.send("INPSET", zone, int(input_num))

    async def get_input(self, zone: int) -> int:
        params = await self.send("INPGET", zone)
        return int(params[1]) if len(params) >= 2 else 1

    async def mute_on(self, zone: int) -> None:
        await self.send("MUTEON", zone)

    async def mute_off(self, zone: int) -> None:
        await self.send("MUTEOFF", zone)

    async def get_mute(self, zone: int) -> bool:
        params = await self.send("MUTEGET", zone)
        return len(params) >= 2 and params[1].upper() == "ON"

    async def get_model(self) -> str:
        params = await self.send("MODEL")
        return params[0] if params else ""

    async def get_firmware(self) -> str:
        params = await self.send("VER")
        # Reply is e.g. "VER Multiroom V1.13" — params = ["Multiroom", "V1.13"].
        return " ".join(params) if params else ""

    async def zone_on_all(self) -> None:
        """Take all zones out of stand-by in one command (ZTONALL)."""
        await self.send("ZTONALL")

    async def zone_off_all(self) -> None:
        """Put all zones in stand-by in one command (ZSTDBYALL)."""
        await self.send("ZSTDBYALL")

    async def mute_all(self) -> None:
        """Mute all zones simultaneously."""
        await self.send("MUTEALL")

    async def unmute_all(self) -> None:
        """Unmute all zones simultaneously."""
        await self.send("UNMUTEALL")

    async def reset(self) -> None:
        """Reboot the AAT device over the network."""
        await self.send("RESET")

    async def set_bass(self, zone: int, value: int) -> None:
        """Set bass for a zone. value: 0..14 (7 = 0 dB)."""
        v = max(0, min(14, int(value)))
        await self.send("BASSSET", zone, v)

    async def set_treble(self, zone: int, value: int) -> None:
        """Set treble for a zone. value: 0..14 (7 = 0 dB)."""
        v = max(0, min(14, int(value)))
        await self.send("TREBLESET", zone, v)

    async def set_balance(self, zone: int, value: int) -> None:
        """Set balance for a zone. value: 0..20 (10 = center)."""
        v = max(0, min(20, int(value)))
        await self.send("BALSET", zone, v)

    async def set_preamp(self, zone: int, value: int) -> None:
        """Set preamp gain for a zone. value: 0..7 (0 = 0 dB, 7 = +14 dB)."""
        v = max(0, min(7, int(value)))
        await self.send("PREAMPSET", zone, v)

    async def get_all(self) -> DeviceState:
        """Read MODEL/VER/POWER + per-zone state in one call.

        Per spec section 1.13 the reply layout is:
            MODEL VER POWER TCPPORT TCPTIMEOUT
            then per zone (in order): INPUT VOLUME MUTE BASS TREBLE BALANCE PREAMP

        GETALL does NOT include zone stand-by, so we follow up with one
        ZSTDBYGET per zone (only while the device is powered on).
        """
        params = await self.send("GETALL")
        if len(params) < 5:
            raise AatProtocolError(f"GETALL response too short: {params}")

        state = DeviceState(
            model=params[0],
            firmware=params[1],
            power=params[2].upper() == "ON",
        )

        idx = 5  # skip model, ver, power, tcpport, tcptimeout
        per_zone = 7
        zone = 1
        while zone <= self._num_zones and idx + per_zone <= len(params):
            try:
                zs = ZoneState(
                    zone=zone,
                    input=int(params[idx + 0]),
                    volume=int(params[idx + 1]),
                    mute=params[idx + 2].upper() == "ON",
                    bass=int(params[idx + 3]),
                    treble=int(params[idx + 4]),
                    balance=int(params[idx + 5]),
                    preamp=int(params[idx + 6]),
                )
            except (ValueError, IndexError) as err:
                raise AatProtocolError(
                    f"Bad GETALL zone {zone} fields at idx {idx}: {params[idx:idx + per_zone]}"
                ) from err
            state.zones[zone] = zs
            idx += per_zone
            zone += 1

        # Stand-by is not returned by GETALL — pull it per zone.
        # Skip when device is OFF: all zones are implicitly in stand-by.
        if state.power:
            for z_num in state.zones:
                try:
                    state.zones[z_num].standby = await self.zone_get_standby(z_num)
                except AatError as err:
                    _LOGGER.warning("Could not read standby for zone %s: %s", z_num, err)
        else:
            for z_num in state.zones:
                state.zones[z_num].standby = True

        return state
