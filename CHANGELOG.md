# Changelog

## 1.1.0

- Battery preservation and Audio tones are read-only diagnostic binary sensors instead of switches, and the integration no longer writes either field: a write to them didn't take effect on the GS1200. They come back as controls once a write is confirmed on a unit.
- After updating, remove the two orphaned switch entities (`switch.…_battery_preservation`, `switch.…_audio_tones`) in Settings → Entities.

## 1.0.0

First public release, tested on a PowerRoam 1200 (GS1200).

- Reads battery, input and output powers per port, remaining times, battery voltage, temperatures, cell voltages, health, cycles and capacity over Bluetooth LE, with no cloud or account.
- Works out Mode (charging, bypass, on battery, idle), Battery power and Energy remaining for the GS1200.
- Switches the AC, DC and USB outputs, quiet mode, U-Turbo, battery preservation, child safety lock and audio tones.
- Sets the light (Off, Low, High, Strobe, SOS), operating mode, DC charging current and low battery alert level.
- Every write builds on a freshly reported state and fails unless the unit confirms it; standby and AC frequency are never written.
- Fault sensor, diagnostics download without identifiers, and translations into 16 languages.

Known issues: switching Audio tones and Battery preservation doesn't take effect on the GS1200 yet.
