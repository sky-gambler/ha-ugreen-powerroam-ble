# Security policy

## Supported versions

Only the latest release gets fixes.

## Reporting a vulnerability

Please report it privately through GitHub: **Security → Report a vulnerability** on this repository. Don't open a public issue for it. Reports are answered on a best-effort basis, usually within a week.

In scope is anything the integration itself does wrong, for example:

- writing a setting or command outside its allow-list (see [How controls are written](README.md#how-controls-are-written));
- a Bluetooth address, serial number or MAC leaking into diagnostics or logs;
- a crafted Bluetooth frame crashing or stalling Home Assistant.

## Not a vulnerability of this integration

The PowerRoam's Bluetooth has no pairing, password or encryption: anyone within range can read the unit and switch its outputs, with or without this integration. That is how the device works, and the integration can't change it; see [Security](README.md#security) in the README.
