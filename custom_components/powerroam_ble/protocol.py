"""Codec for the UGREEN PowerRoam's Bluetooth LE status stream.

Derived from tanka8/ugreen-powerroam (MIT, see LICENSE), commit ed9fd31.
Two encoders: the 0x16 switch block (outputs and a few settings) and the
one-byte setting frames (light, operating mode, DC current, alert level).
Pure functions over bytes and dicts, no Home Assistant imports.

Frame: 5A A5 | prefix | cmd | len (u16 LE) | data | CRC-16/Modbus (u16 LE).
The unit replies with C0 A1 and takes commands with A1 C0. It concatenates
several frames per notification and pads with zeros.
"""

from __future__ import annotations

from dataclasses import dataclass

HEADER = b"\x5a\xa5"
REPLY_PREFIX = b"\xc0\xa1"
CMD_PREFIX = b"\xa1\xc0"

# A damaged length field is nearly always far larger than any real payload
# (the largest seen is 30 bytes); waiting for it would stall the stream.
MAX_DATA_LENGTH = 255

OP_FAULT = 0x01
OP_TEMPS = 0x04
OP_BATTERY = 0x09
OP_AC = 0x0B
OP_PORTS = 0x0C
OP_TOTALS = 0x0F
OP_WORK_MODE = 0x12
OP_LIGHT = 0x13
OP_DC_CHARGE = 0x14
OP_LOW_ALERT = 0x15
OP_SWITCHES = 0x16

# Opcodes the UGREEN app knows; anything else is kept for the diagnostics.
KNOWN_OPCODES = frozenset(
    {
        0x01,
        0x04,
        0x05,
        0x06,
        0x09,
        0x0B,
        0x0C,
        0x0F,
        0x10,
        0x11,
        0x12,
        0x13,
        0x14,
        0x15,
        0x16,
        0x17,
        0x21,
    }
)

TEMPERATURE_OFFSET = 40
NO_ESTIMATE = 0xFFFF
TEMPERATURE_KEYS = ("battery_temp_1", "battery_temp_2", "inverter_temp_1", "inverter_temp_2")
CELL_COUNT = 7

# 0x16 is a whole-state write, and the unit reports 12 fields but takes 11:
# low_battery_warning has no slot in a write, so every later field sits one
# byte earlier. Echoing reported bytes back shifted every setting (upstream
# turned battery care off that way); always decode to names and re-encode.
SWITCH_RECV_FIELDS = (
    "low_noise",
    "low_battery_warning",
    "usb",
    "dc",
    "ac_frequency_hz",
    "warning_voice",
    "ac_uturbo",
    "ac",
    "battery_health",
    "locking",
    "key_voice",
    "standby",
)
SWITCH_SEND_FIELDS = tuple(f for f in SWITCH_RECV_FIELDS if f != "low_battery_warning")
# Reported state, not settings: may change on its own while a write is in
# flight, so a write's echo check ignores it.
SWITCH_STATUS_FIELDS = frozenset({"low_battery_warning"})
# key_voice is 0x00 for on, both ways. ac_frequency_hz is kept as the raw
# byte, so writing it back is a true no-op whatever it means.
INVERTED_FIELDS = frozenset({"key_voice"})
RAW_FIELDS = frozenset({"ac_frequency_hz"})

SWITCH_OUTPUT_KEYS = {"usb": "usb_output", "dc": "dc_output", "ac": "ac_output"}
# The 0x16 fields HA may change: only those whose write is confirmed on a
# unit. Never standby (every output off, and the unit may stop answering
# until its button is pressed), ac_frequency_hz (60 Hz can harm devices),
# low_battery_warning (no slot in a write) or warning_voice (no such setting
# in the app). battery_health and key_voice stay read-only: on a GS1200 a
# write to them didn't take effect.
WRITABLE_SWITCH_FIELDS = frozenset({"ac", "dc", "usb", "low_noise", "ac_uturbo", "locking"})
# The rest of the block, shown read-only; checked against the app on a
# GS1200: U-Turbo is not inverted, the app's "Audio tones" is key_voice.
# warning_voice has no setting in the app and stays out. low_battery_warning
# is never written, so it is likely a state, not a setting.
SWITCH_SETTING_KEYS = {
    "low_noise": "quiet_mode",
    "low_battery_warning": "low_battery_warning",
    "ac_uturbo": "u_turbo",
    "battery_health": "battery_care",
    "locking": "child_lock",
    "key_voice": "key_beep",
    "standby": "standby",
}
# Raw byte → Hz; 0 read as 50 Hz on a unit the app shows at 50 Hz.
AC_FREQUENCY_HZ = {0: 50, 1: 60}

# One-byte setting frames, reported and written with the same opcode and the
# option's number: opcode → (data key, {byte: option}). The tables are
# powerroam-tui's; proam-cli agrees on the light. Checked against the app on
# this GS1200 where it showed a value (8 A, 10 %, Standard; its brightness and
# screen frames match the tui too). Operating mode 2 is undefined and left out.
BYTE_SETTINGS = {
    OP_WORK_MODE: ("operating_mode", {0: "standard", 1: "eco", 3: "always_on"}),
    OP_LIGHT: ("light", {0: "off", 1: "low", 2: "high", 3: "strobe", 4: "sos"}),
    OP_DC_CHARGE: ("dc_charge_current", {0: "4", 1: "6", 2: "8"}),
    OP_LOW_ALERT: ("low_battery_alert", {0: "5", 1: "10", 2: "20"}),
}

# Opcodes whose payload identifies the unit (serial numbers, MAC); kept out
# of the diagnostics download.
PRIVATE_OPCODES = frozenset({0x05, 0x21})

# Thresholds of the derived mode, in watts. Below 5 W the unit's readings are
# noise; in bypass the battery's own draw (from the unit's discharge
# estimate) is a couple of watts against the desk's tens to hundreds.
ACTIVE_W = 5


@dataclass(frozen=True, slots=True)
class Frame:
    """One decoded frame; crc_ok False means nothing in it is trusted."""

    prefix: bytes
    cmd: int
    data: bytes
    crc_ok: bool


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def decode_stream(buf: bytes) -> tuple[list[Frame], int]:
    """Decode every complete frame in buf; return (frames, bytes consumed).

    The caller keeps the unconsumed tail as the head of the next buffer, so a
    frame split across notifications still decodes. A frame with a bad CRC is
    returned flagged, and decoding resumes one byte after its header, because
    its length field may be the damaged part.
    """
    frames: list[Frame] = []
    i = 0
    consumed = 0
    while i < len(buf) - 1:
        if buf[i : i + 2] != HEADER:
            i += 1
            continue
        if i + 7 > len(buf):
            break
        length = int.from_bytes(buf[i + 5 : i + 7], "little")
        if length > MAX_DATA_LENGTH:
            i += 1
            consumed = i
            continue
        total = length + 9
        if i + total > len(buf):
            break
        raw = buf[i : i + total]
        crc_ok = crc16_modbus(raw[2:-2]) == int.from_bytes(raw[-2:], "little")
        frames.append(Frame(prefix=raw[2:4], cmd=raw[4], data=raw[7:-2], crc_ok=crc_ok))
        i += total if crc_ok else 1
        consumed = i

    # Drop trailing bytes that can't start a frame (the zero padding), but keep
    # a lone 0x5A: it may be half a header split across two notifications.
    rest = buf[consumed:]
    index = rest.find(HEADER)
    if index > 0:
        consumed += index
    elif index == -1:
        consumed += len(rest) - (1 if rest.endswith(HEADER[:1]) else 0)
    return frames, consumed


def encode(cmd: int, data: bytes = b"") -> bytes:
    body = CMD_PREFIX + bytes([cmd]) + len(data).to_bytes(2, "little") + data
    return HEADER + body + crc16_modbus(body).to_bytes(2, "little")


def decode_switch_state(data: bytes) -> dict[str, int | bool] | None:
    """Decode a reported 0x16 block; None unless it has exactly 12 fields."""
    if len(data) != len(SWITCH_RECV_FIELDS):
        return None
    state: dict[str, int | bool] = {}
    for name, value in zip(SWITCH_RECV_FIELDS, data, strict=True):
        if name in RAW_FIELDS:
            state[name] = value
        elif name in INVERTED_FIELDS:
            state[name] = value == 0
        else:
            state[name] = value != 0
    return state


def encode_switch_state(state: dict[str, int | bool]) -> bytes:
    """Build a 0x16 write from a full decoded state, in the 11-field layout."""
    missing = [name for name in SWITCH_SEND_FIELDS if name not in state]
    if missing:
        raise ValueError(f"0x16 replaces every setting; missing {missing}")
    body = bytearray()
    for name in SWITCH_SEND_FIELDS:
        value = state[name]
        if name in RAW_FIELDS:
            body.append(int(value) & 0xFF)
        elif name in INVERTED_FIELDS:
            body.append(0x00 if value else 0x01)
        else:
            body.append(0x01 if value else 0x00)
    return encode(OP_SWITCHES, bytes(body))


def encode_setting(opcode: int, option: str) -> bytes:
    """Build a one-byte setting write: the option's number, as reported."""
    if opcode not in BYTE_SETTINGS:
        raise ValueError(f"0x{opcode:02x} is not a writable setting")
    for value, name in BYTE_SETTINGS[opcode][1].items():
        if name == option:
            return encode(opcode, bytes([value]))
    raise ValueError(f"unknown option {option!r} for 0x{opcode:02x}")


def decode_setting(opcode: int, data: bytes) -> str | None:
    """The option a one-byte setting frame reports; None if empty or undefined."""
    return BYTE_SETTINGS[opcode][1].get(data[0]) if data else None


def _u16(data: bytes, offset: int) -> int | None:
    if offset + 2 > len(data):
        return None
    return int.from_bytes(data[offset : offset + 2], "little")


def telemetry(frame: Frame) -> dict[str, int | float | bool | str | None]:
    """Map one status frame onto sensor keys; empty for frames carrying none.

    Offsets follow tanka8, confirmed there against a GS1200 and its cloud
    readings. The remaining times are minutes: 408 at 100 % and 138 W out is
    ~940 Wh of the GS1200's 1024 Wh.
    """
    if not frame.crc_ok or frame.prefix != REPLY_PREFIX:
        return {}
    d = frame.data
    out: dict[str, int | float | bool | str | None] = {}

    if frame.cmd == OP_TEMPS:
        for index, key in enumerate(TEMPERATURE_KEYS):
            raw = _u16(d, index * 2)
            if raw is None:
                break
            out[key] = raw - TEMPERATURE_OFFSET

    elif frame.cmd == OP_BATTERY:
        # Pack voltage in 0.1 V: 26.5 V at 78 % idle and 27.6 V charging, each
        # 8 × the average of the 7 cell voltages the frame carries, so the
        # pack is 8 cells in series (40 Ah × 25.6 V = 1024 Wh).
        if (value := _u16(d, 0)) is not None:
            out["battery_voltage"] = value / 10
        cells = []
        for cell in range(CELL_COUNT):
            millivolts = _u16(d, 2 + cell * 2)
            if millivolts is None:
                break
            cells.append(millivolts)
            out[f"cell_voltage_{cell + 1}"] = millivolts
        if len(cells) == CELL_COUNT:
            out["cell_spread"] = max(cells) - min(cells)
        if len(d) > 16:
            out["battery_health"] = d[16]
        if len(d) > 17:
            out["battery_cycles"] = d[17]
        # 0xFFFF means no estimate (charge time when not charging, discharge
        # time while charging).
        if (value := _u16(d, 19)) is not None:
            out["charge_time"] = None if value == NO_ESTIMATE else value
        if (value := _u16(d, 21)) is not None:
            out["discharge_time"] = None if value == NO_ESTIMATE else value
        if len(d) > 23:
            out["battery"] = d[23]
        # mAh: 31200 at 78 % on a GS1200, so 40000 when full.
        if (value := _u16(d, 24)) is not None:
            out["capacity_remaining"] = round(value / 1000, 1)

    elif frame.cmd == OP_TOTALS:
        if (value := _u16(d, 0)) is not None:
            out["input_power"] = value
        if (value := _u16(d, 2)) is not None:
            out["output_power"] = value

    elif frame.cmd == OP_AC:
        if (value := _u16(d, 6)) is not None:
            out["ac_output_power"] = value

    elif frame.cmd == OP_PORTS:
        if (value := _u16(d, 8)) is not None:
            out["dc_output_power"] = value
        # Two USB-C and two USB-A ports, summed into one figure.
        ports = [_u16(d, offset) for offset in (0, 2, 4, 6)]
        if all(port is not None for port in ports):
            out["usb_output_power"] = sum(ports)

    elif frame.cmd in BYTE_SETTINGS:
        if (option := decode_setting(frame.cmd, d)) is not None:
            out[BYTE_SETTINGS[frame.cmd][0]] = option

    elif frame.cmd == OP_SWITCHES:
        if (state := decode_switch_state(d)) is not None:
            for field, key in {**SWITCH_OUTPUT_KEYS, **SWITCH_SETTING_KEYS}.items():
                out[key] = state[field]
            if (hz := AC_FREQUENCY_HZ.get(int(state["ac_frequency_hz"]))) is not None:
                out["ac_frequency"] = hz

    elif frame.cmd == OP_FAULT:
        out["fault_raw"] = d.hex()
        out["fault"] = any(d)

    return out


def derived(
    data: dict[str, int | bool | str | None], capacity_wh: int | None
) -> dict[str, int | str]:
    """Values worked out from several frames; empty until all of them arrived.

    Input power is charging only and reads 0 in bypass, so the battery's real
    draw comes from the unit's own discharge estimate: capacity × % ÷ hours
    left. It is about 2 W in bypass and close to the output on battery; with
    no estimate (while charging) it counts as 0.
    """
    pct = data.get("battery")
    if capacity_wh is None or not isinstance(pct, int):
        return {}
    out: dict[str, int | str] = {"energy_remaining": round(capacity_wh * pct / 100)}
    pin, pout, left = (data.get(k) for k in ("input_power", "output_power", "discharge_time"))
    if not (isinstance(pin, int) and isinstance(pout, int)):
        return out
    draw = capacity_wh * pct / 100 / (left / 60) if isinstance(left, int) and left > 0 else 0.0
    if pin > ACTIVE_W:
        out["mode"] = "bypass" if pct >= 99 else "charging"
        out["battery_power"] = pin
    elif pout > ACTIVE_W and draw < pout / 2:
        out["mode"] = "bypass"
        out["battery_power"] = -round(draw)
    elif pout > ACTIVE_W:
        out["mode"] = "discharging"
        out["battery_power"] = -round(draw)
    else:
        out["mode"] = "idle"
        out["battery_power"] = 0
    return out
