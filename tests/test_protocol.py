"""The codec: frames, telemetry, the 0x16 block and the one-byte settings."""

from __future__ import annotations

import pytest

from custom_components.powerroam_ble import protocol

from .conftest import reply, stream
from .frames import CHARGING, IDLE


def decode_all(payloads: dict[int, str]) -> dict:
    frames, _ = protocol.decode_stream(stream(payloads))
    data: dict = {}
    for frame in frames:
        data.update(protocol.telemetry(frame))
    return data


def test_stream_decodes_every_frame_and_skips_padding() -> None:
    raw = stream(IDLE)
    frames, consumed = protocol.decode_stream(raw)
    assert consumed == len(raw)
    assert [f.cmd for f in frames] == list(IDLE)
    assert all(f.crc_ok for f in frames)


def test_frame_split_across_notifications_is_kept() -> None:
    raw = reply(0x16, bytes.fromhex(IDLE[0x16]))
    frames, consumed = protocol.decode_stream(raw[:7])
    assert frames == [] and consumed == 0
    frames, consumed = protocol.decode_stream(raw)
    assert len(frames) == 1 and consumed == len(raw)


def test_bad_crc_is_flagged_and_decoding_resyncs() -> None:
    bad = bytearray(reply(0x13, b"\x01"))
    bad[-1] ^= 0xFF
    good = reply(0x12, b"\x00")
    frames, _ = protocol.decode_stream(bytes(bad) + good)
    assert [(f.cmd, f.crc_ok) for f in frames] == [(0x13, False), (0x12, True)]
    assert protocol.telemetry(frames[0]) == {}


def test_idle_capture_matches_the_app() -> None:
    data = decode_all(IDLE)
    assert data["battery"] == 78
    assert data["battery_voltage"] == 26.5
    assert data["capacity_remaining"] == 31.2
    assert data["cell_spread"] == 6
    assert data["battery_health"] == 100
    assert data["battery_cycles"] == 27
    assert data["discharge_time"] == 20661
    assert (data["battery_temp_1"], data["battery_temp_2"]) == (26, 29)
    assert data["fault"] is False
    # Settings as the app showed them.
    assert data["ac_frequency"] == 50
    assert data["u_turbo"] is True
    assert data["quiet_mode"] is True
    assert data["key_beep"] is True
    assert data["child_lock"] is False
    assert data["battery_care"] is False
    assert data["operating_mode"] == "standard"
    assert data["dc_charge_current"] == "8"
    assert data["low_battery_alert"] == "10"
    assert data["light"] == "off"
    assert (data["ac_output"], data["usb_output"]) == (False, True)


def test_charging_capture() -> None:
    data = decode_all(CHARGING)
    assert data["battery"] == 98
    assert data["battery_voltage"] == 27.6
    assert data["charge_time"] == 3
    assert data["discharge_time"] is None  # 0xFFFF: no estimate while charging
    assert (data["input_power"], data["output_power"], data["ac_output_power"]) == (240, 148, 148)
    assert (data["child_lock"], data["usb_output"], data["ac_output"]) == (True, False, True)


def test_switch_block_round_trip_keeps_every_field() -> None:
    reported = bytes.fromhex(IDLE[0x16])
    state = protocol.decode_switch_state(reported)
    assert state is not None
    written = protocol.decode_stream(protocol.encode_switch_state(state))[0][0]
    assert written.prefix == protocol.CMD_PREFIX
    # 12 reported, 11 written: low_battery_warning (index 1) has no slot.
    assert written.data == reported[:1] + reported[2:]


def test_switch_write_inverts_key_voice() -> None:
    state = protocol.decode_switch_state(bytes.fromhex(IDLE[0x16]))
    assert state is not None
    off = protocol.decode_stream(protocol.encode_switch_state({**state, "key_voice": False}))
    assert off[0][0].data[protocol.SWITCH_SEND_FIELDS.index("key_voice")] == 0x01


def test_switch_write_needs_the_whole_state() -> None:
    state = protocol.decode_switch_state(bytes.fromhex(IDLE[0x16]))
    assert state is not None
    del state["standby"]
    with pytest.raises(ValueError, match="standby"):
        protocol.encode_switch_state(state)


def test_short_switch_block_is_ignored() -> None:
    assert protocol.decode_switch_state(bytes(11)) is None


@pytest.mark.parametrize(
    ("mode", "frame"),
    [
        # proam-cli's own test frames (src/protocol/request.rs).
        ("off", "5aa5a1c0130100004c3f"),
        ("low", "5aa5a1c0130100018dff"),
        ("strobe", "5aa5a1c0130100030c3e"),
    ],
)
def test_light_write_matches_proam_cli(mode: str, frame: str) -> None:
    assert protocol.encode_setting(protocol.OP_LIGHT, mode).hex() == frame


@pytest.mark.parametrize(
    ("opcode", "option", "byte"),
    [
        (protocol.OP_WORK_MODE, "always_on", 3),
        (protocol.OP_DC_CHARGE, "4", 0),
        (protocol.OP_LOW_ALERT, "20", 2),
    ],
)
def test_setting_write_is_the_option_number(opcode: int, option: str, byte: int) -> None:
    frame = protocol.decode_stream(protocol.encode_setting(opcode, option))[0][0]
    assert (frame.cmd, frame.data) == (opcode, bytes([byte]))


@pytest.mark.parametrize(
    ("opcode", "option"),
    [
        (0x10, "low"),  # screen brightness: not writable
        (0x11, "1"),  # screen timeout: not writable
        (0x17, "off"),  # auto-off timers: not writable
        (protocol.OP_SWITCHES, "on"),
        (protocol.OP_WORK_MODE, "unknown"),  # mode 2 is undefined
        (protocol.OP_DC_CHARGE, "7"),
    ],
)
def test_unknown_settings_are_refused(opcode: int, option: str) -> None:
    with pytest.raises(ValueError):
        protocol.encode_setting(opcode, option)


def test_dangerous_fields_are_not_writable() -> None:
    refused = ("standby", "ac_frequency_hz", "warning_voice", "low_battery_warning")
    unconfirmed = ("battery_health", "key_voice")  # a GS1200 didn't apply these writes
    for field in refused + unconfirmed:
        assert field not in protocol.WRITABLE_SWITCH_FIELDS
    assert protocol.WRITABLE_SWITCH_FIELDS.issubset(protocol.SWITCH_SEND_FIELDS)


@pytest.mark.parametrize(
    ("data", "mode", "power"),
    [
        # (battery %, input W, output W, discharge minutes)
        ((50, 300, 120, None), "charging", 300),
        ((100, 20, 120, None), "bypass", 20),
        ((100, 0, 120, 25000), "bypass", -2),
        ((90, 0, 130, 408), "discharging", -136),
        ((78, 0, 0, 20661), "idle", 0),
    ],
)
def test_derived_mode_and_battery_power(data: tuple, mode: str, power: int) -> None:
    keys = ("battery", "input_power", "output_power", "discharge_time")
    data = dict(zip(keys, data, strict=True))
    out = protocol.derived(data, 1024)
    assert (out["mode"], out["battery_power"]) == (mode, power)
    assert out["energy_remaining"] == round(1024 * data["battery"] / 100)


def test_derived_needs_a_known_capacity_and_the_powers() -> None:
    assert protocol.derived({"battery": 50, "input_power": 0, "output_power": 0}, None) == {}
    assert protocol.derived({"battery": 50}, 1024) == {"energy_remaining": 512}


def test_private_frames_are_listed() -> None:
    assert {0x05, 0x21} <= protocol.PRIVATE_OPCODES
