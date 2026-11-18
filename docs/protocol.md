# UGREEN PowerRoam Bluetooth protocol

What this integration knows about the protocol, and how sure it is. "Checked" means compared with the UGREEN app or the unit's screen on a GS1200; anything else is marked with its source.

## Link

- GATT service `ABF0` (not advertised), write characteristic `ABF1`, notify characteristic `ABF2` (`0000abfX-0000-1000-8000-00805f9b34fb`). No pairing or encryption.
- One connection at a time. The unit advertises as `ugreen gs<model>` (GS1200: `ugreen gs1200`) and stops advertising while connected.
- Once notifications are on, the unit pushes its whole state about every 0.6 s without being asked. Several frames share one notification, padded with zeros; a frame can be split across two notifications.

## Frame

```
5A A5 | prefix (2) | cmd (1) | length (u16 LE) | data (length) | CRC-16/Modbus (u16 LE)
```

- Prefix `C0 A1` from the unit, `A1 C0` to it.
- The CRC covers everything after `5A A5` up to the CRC itself.
- All multi-byte numbers are little-endian.

## Frames from the unit

| Op | Meaning | Layout | Status |
|---|---|---|---|
| `0x01` | Fault flags | 8 bytes; all zero means no fault | Bits unmapped |
| `0x04` | Temperatures | 4 × u16, °C + 40: battery 1, battery 2, inverter 1, inverter 2 | Checked; inverter 1 reads ~1 °C while AC is off |
| `0x05` | Serial numbers | 2 × 15 characters | Not decoded; kept out of diagnostics and logs |
| `0x06` | Firmware version | unknown | Not seen on the GS1200 |
| `0x09` | Battery | see below | Checked |
| `0x0B` | AC | u16 at 2: AC input power (W); u16 at 6: AC output power (W); u16 at 0 and 4 read 0 | Checked (2, 6); 0 and 4 probably the solar and car inputs |
| `0x0C` | Ports | u16 at 0, 2, 4, 6: USB-C 1, USB-C 2, USB-A 1, USB-A 2 (W); u16 at 8: DC (W) | From tanka8 |
| `0x0F` | Totals | u16 at 0: input power (W, charging only, 0 in bypass); u16 at 2: output power (W) | Checked |
| `0x10` | Screen brightness | 1 byte: 0 High, 1 Standard, 2 Low | powerroam-tui; 2 = Low checked |
| `0x11` | Screen timeout | 1 byte: 0 10 s, 1 30 s, 2 1 min, 3 5 min, 4 30 min, 5 never | powerroam-tui; 2 = 1 min checked |
| `0x12` | Operating mode | 1 byte: 0 Standard (5 h), 1 Eco (2 h), 2 unknown, 3 Always on | powerroam-tui; 0 = Standard checked |
| `0x13` | Light | 1 byte: 0 Off, 1 Low, 2 High, 3 Strobe, 4 SOS | proam-cli and powerroam-tui agree; checked on the unit |
| `0x14` | DC charging current | 1 byte: 0 4 A, 1 6 A, 2 8 A | powerroam-tui; 2 = 8 A checked |
| `0x15` | Low battery alert level | 1 byte: 0 5 %, 1 10 %, 2 20 % | powerroam-tui; 1 = 10 % checked (proam-cli reads it as a value, not a setting) |
| `0x16` | Settings block | 12 bytes, see below | Checked |
| `0x17` | Auto-off timers | 6 bytes: AC, DC, lamp, USB enable flags, time trigger, SoC trigger | powerroam-tui; all zero on the GS1200; not used |
| `0x21` | MAC address | 6 bytes | Not decoded; kept out of diagnostics and logs |

### `0x09` battery

| Offset | Field |
|---|---|
| 0 | u16 pack voltage, 0.1 V (26.5 V at 78 % idle, 27.6 V charging at 98 %) |
| 2–15 | 7 × u16 cell voltages, mV |
| 16 | battery health, % |
| 17 | cycle count (one byte) |
| 19 | u16 charge time remaining, minutes; `0xFFFF` = no estimate |
| 21 | u16 discharge time remaining, minutes; `0xFFFF` = no estimate (while charging) |
| 23 | state of charge, % |
| 24 | u16 remaining capacity, mAh (40 000 when full on the GS1200) |

The pack voltage is 8 × the average of the 7 reported cells, and 40 Ah × 25.6 V = 1024 Wh, so the GS1200 pack has 8 cells in series; the frame carries only 7 of their voltages.

## The `0x16` settings block

The unit reports 12 fields and accepts 11: `low_battery_warning` (index 1 when read) has no slot in a write, so every later field sits one byte earlier when written. Echoing the reported bytes back shifts every setting (one project turned battery care off that way). A write must decode the report into named fields, change one, and encode all 11 again. One byte per field, 1 = on unless noted.

| Read index | Write index | Field | Notes |
|---|---|---|---|
| 0 | 0 | quiet mode (`low_noise`) | |
| 1 | – | low battery warning | Reported state, never written |
| 2 | 1 | USB output | |
| 3 | 2 | DC output | |
| 4 | 3 | AC frequency | Raw byte; 0 = 50 Hz checked. Never written by this integration |
| 5 | 4 | `warning_voice` | No matching setting in the app; meaning unknown |
| 6 | 5 | U-Turbo | Not inverted (checked; the reversing notes say otherwise) |
| 7 | 6 | AC output | |
| 8 | 7 | battery preservation (`battery_health`) | Read checked; a write didn't take effect on the GS1200, so the integration doesn't write it |
| 9 | 8 | child safety lock | |
| 10 | 9 | audio tones (`key_voice`) | **Inverted**: 0 = on (read checked). A write didn't take effect on the GS1200, so the integration doesn't write it |
| 11 | 10 | standby | Every output off; never written by this integration |

## Writes

- **`0x16`**: the whole block as above, `A1 C0` prefix.
- **One-byte settings** (`0x12`, `0x13`, `0x14`, `0x15`): the option's number, with the same opcode the unit reports it in. Example, light Low: `5A A5 A1 C0 13 01 00 01 8D FF`.
- The unit confirms a write by reporting the new value in its next push. It doesn't answer otherwise.

Never send:

- `5A A5` without the `A1 C0` prefix: the firmware-update path.
- `0x03`: self-test; the unit restarts and switches its outputs off.
- `0x16` with standby set.
