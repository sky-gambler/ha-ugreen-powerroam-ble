# UGREEN PowerRoam (Bluetooth) for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Release](https://img.shields.io/github/v/release/sky-gambler/ha-ugreen-powerroam-ble)](https://github.com/sky-gambler/ha-ugreen-powerroam-ble/releases)
[![Validate](https://github.com/sky-gambler/ha-ugreen-powerroam-ble/actions/workflows/validate.yml/badge.svg)](https://github.com/sky-gambler/ha-ugreen-powerroam-ble/actions/workflows/validate.yml)
[![Tests](https://github.com/sky-gambler/ha-ugreen-powerroam-ble/actions/workflows/tests.yml/badge.svg)](https://github.com/sky-gambler/ha-ugreen-powerroam-ble/actions/workflows/tests.yml)

A local Home Assistant integration for UGREEN PowerRoam portable power stations. It talks to the unit directly over Bluetooth LE: no cloud, no UGREEN account. It reads everything the unit reports, switches its outputs and settings, and sets its light.

> [!NOTE]
> This is an independent project. It is not made, endorsed or supported by UGREEN. "UGREEN" and "PowerRoam" are trademarks of their owner and are used here only to say which devices the integration works with.

## Supported models

| Model | Status |
|---|---|
| **PowerRoam 1200 (GS1200)** | Tested: every value checked against the UGREEN app, every control tried on the unit; two controls don't take effect yet (see [Known issues](#known-issues)). |
| Other PowerRoam models that advertise as `ugreen gs…` | Likely to work (the protocol is shared), untested. Mode, Battery power and Energy remaining need the model's capacity and appear only for the GS1200 until someone reports another model. |

Have another model? Please [open a model report](https://github.com/sky-gambler/ha-ugreen-powerroam-ble/issues/new?template=new_model.yml) with a diagnostics file.

## Requirements

- Home Assistant 2026.3 or newer (developed and tested on 2026.10).
- A Bluetooth adapter Home Assistant can use, or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) with active connections, within range of the unit.
- The UGREEN app closed: the unit takes one Bluetooth connection at a time, and Home Assistant keeps it.

## Installation

### HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sky-gambler&repository=ha-ugreen-powerroam-ble&category=integration)

Or by hand: HACS → ⋮ → **Custom repositories** → `https://github.com/sky-gambler/ha-ugreen-powerroam-ble`, type **Integration**. Install **UGREEN PowerRoam (Bluetooth)**, then restart Home Assistant.

### Manual

Copy `custom_components/powerroam_ble` into your Home Assistant `config/custom_components/` folder and restart Home Assistant.

## Setup

Close the UGREEN app and switch the unit on. Home Assistant discovers it by its Bluetooth name and offers it under Settings → Devices & services. You can also add it there yourself: **Add integration → UGREEN PowerRoam (Bluetooth)** and pick the unit from the list.

## Entities

Entity names below are the English ones; the integration is translated into 16 languages.

### Sensors

| Entity | Notes |
|---|---|
| Battery | State of charge, % |
| Input power, Output power | W. Input power is charging power only: it reads 0 in bypass, when the unit is full and passes mains power straight through. |
| AC output power, DC output power, USB output power | W. USB is the sum of the two USB-C and two USB-A ports. |
| Charge time remaining, Discharge time remaining | The unit's own estimates, shown in hours; unknown when the unit has none (discharge time while charging). |
| Battery voltage | The pack's own figure, V. |
| Mode | Charging, Bypass, On battery or Idle; worked out by the integration, see below. |
| Battery power | W, positive while charging, negative while discharging; worked out, see below. |
| Energy remaining | kWh, capacity × state of charge. |
| Battery health, Battery cycles, Capacity remaining (Ah) | Diagnostic. |
| Battery temperature 1 / 2, Inverter temperature 1 / 2 | Diagnostic. Inverter temperature 1 reads about 1 °C while AC is off. |
| AC frequency | Diagnostic, read-only. |
| Cell voltage spread | Diagnostic: highest minus lowest of the cell voltages the unit reports. A spread that keeps growing is an early sign of a weak cell. |
| Cell 1–7 voltage, Fault bytes (raw), Signal strength | Diagnostic, disabled by default. |

### Binary sensors

| Entity | Notes |
|---|---|
| Fault | On when the unit's fault frame holds any non-zero byte. Its bits aren't mapped yet. |
| Low battery warning, Standby | Diagnostic, read-only. |
| Connected | Whether the Bluetooth link is up right now. |

### Controls

| Entity | Type |
|---|---|
| AC output, DC output, USB output | Switch |
| Quiet mode, U-Turbo, Battery preservation, Child safety lock, Audio tones | Switch (configuration); Battery preservation and Audio tones don't work yet, see [Known issues](#known-issues) |
| Light | Select: Off, Low, High, Strobe, SOS |
| Operating mode | Select: Standard (5 h), Eco (2 h), Always on (configuration) |
| DC charging current | Select: 4 A, 6 A, 8 A (configuration) |
| Low battery alert level | Select: 5 %, 10 %, 20 % (configuration) |

## How controls are written

Every change waits for the unit's next report of the current state, builds the write on that report (never on an older copy), sends it, and then waits up to 5 seconds for the unit to report the change. If there is no Bluetooth link, no report, no confirmation, or if any other setting moves at the same time, the action fails with an error and nothing is retried.

The outputs and the five configuration switches share one settings block that the unit only accepts as a whole, and whose layout differs from the one it reports. The integration therefore always decodes it into named fields and encodes it again; it never echoes raw bytes back.

Never written, by design:

- **Standby**: it turns every output off, and the unit may stop answering over Bluetooth until its button is pressed.
- **AC frequency**: a wrong value (60 Hz) can harm connected devices.
- **Low battery warning**: a status the unit reports; it has no place in a write.
- Firmware update and self-test commands.

## How some values are worked out

The unit doesn't report how much power flows into or out of the battery itself. The integration derives it from the unit's own discharge estimate: capacity × state of charge ÷ hours left. In bypass that gives about −2 W (the unit's own draw, or the rounding of its estimate), and close to the output power when the unit runs on battery.

- **Mode** is *Charging* while input power is above 5 W (*Bypass* if the battery is at 99 % or more), *Bypass* while the battery's own draw is under half the output, *On battery* otherwise, and *Idle* with nothing drawing.
- These values need the battery capacity, known for the GS1200 (1024 Wh).

## Known issues

- **Audio tones** and **Battery preservation** show the right state, but switching them from Home Assistant doesn't take effect on the GS1200 yet. Being investigated; the other controls work.
- **Fault** turns on for any non-zero fault byte; what each bit means is still unknown.

## Range and reliability

- Bluetooth range is the main limit. On a Raspberry Pi's built-in adapter at about −80 dBm the link drops every minute or so and comes back within seconds. Values are kept for 2 minutes after the last frame, so short drops don't blank them; *Connected* shows the link itself. A link that stays silent for 30 seconds is rebuilt.
- For a unit in another room, an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) with active connections next to it works far better than a distant adapter.
- The unit reports every 0.6 seconds; entities are updated at most every 10 seconds to spare the recorder.

## Security

The unit's Bluetooth has no pairing, password or encryption. Anyone within range can read it and switch its outputs, with or without this integration. While Home Assistant holds the connection, nobody else can connect, the UGREEN app included; to use the app, disable the integration entry first.

To report a vulnerability in the integration itself, see [SECURITY.md](SECURITY.md).

## Troubleshooting

- **Diagnostics**: Settings → Devices & services → UGREEN PowerRoam (Bluetooth) → ⋮ → **Download diagnostics**. It counts reconnects and CRC failures and holds the last payload of every frame type. The Bluetooth address, the serial numbers and the MAC are left out, so the file is safe to attach to an issue.
- **Debug logging** of every changed frame (serial and MAC frames are masked):

  ```yaml
  logger:
    logs:
      custom_components.powerroam_ble: debug
      custom_components.powerroam_ble.frames: debug
  ```

- The protocol, as far as it is known, is described in [docs/protocol.md](docs/protocol.md).

## How this was built

This integration was written with [Claude Code](https://claude.com/claude-code), Anthropic's AI coding agent, working with the maintainer. Claude Code did the protocol reverse engineering and wrote the code, the tests, this documentation and the translations. It started from [tanka8/ugreen-powerroam](https://github.com/tanka8/ugreen-powerroam), cross-checked the frames against [proam-cli](https://github.com/ilya-zlobintsev/proam-cli) and [powerroam-tui](https://github.com/axodentally/powerroam-tui), and mapped the remaining fields by comparing the unit's raw frames, captured through the diagnostics download, with what the UGREEN app showed at the same moment.

The maintainer ran every step on a real GS1200. Each decoded value was compared with the app or the unit's screen, and every control was tried on the unit; the two that don't work yet are listed under [Known issues](#known-issues). What hasn't been checked that way is marked as such in [docs/protocol.md](docs/protocol.md). The translations are machine-made; corrections from native speakers are welcome.

## Credits

- [tanka8/ugreen-powerroam](https://github.com/tanka8/ugreen-powerroam) (MIT): the original codec and connection handling this integration is derived from, including the fix from its PR #11 for a reconnect loop.
- [proam-cli](https://github.com/ilya-zlobintsev/proam-cli) (GPL-3.0) and [powerroam-tui](https://github.com/axodentally/powerroam-tui): protocol facts, light modes, setting tables and test frames. Only facts were used; no code was copied from them.
- [axis-esto/powerroam-reversing](https://github.com/axis-esto/powerroam-reversing): reverse-engineering notes.
- The UGREEN mark in the integration's brand images comes from [homarr-labs/dashboard-icons](https://github.com/homarr-labs/dashboard-icons) (Apache-2.0); the mark itself belongs to UGREEN.

## License

[MIT](LICENSE). The integration's folder carries the same licence, with the original author's notice.
