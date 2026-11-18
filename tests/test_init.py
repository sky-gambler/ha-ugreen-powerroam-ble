"""The integration end to end: entities, their names, actions and diagnostics."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import CONF_ADDRESS, CONF_NAME, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.powerroam_ble import ble
from custom_components.powerroam_ble.const import DOMAIN

from .conftest import ADDRESS, NAME, reply, stream
from .fake_unit import FakeUnit
from .frames import CHARGING

pytestmark = pytest.mark.usefixtures("mock_bluetooth")

PREFIX = "ugreen_powerroam_gs1200"


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A set-up entry whose link never connects; the tests feed it frames."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, title=NAME, data={CONF_ADDRESS: ADDRESS, CONF_NAME: NAME}
    )
    entry.add_to_hass(hass)
    with patch.object(ble.PowerRoamBle, "start"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)


def feed(entry: MockConfigEntry, payloads: dict[int, str] = CHARGING) -> None:
    device = entry.runtime_data
    device._on_notify(None, bytearray(stream(payloads)))
    device._notify_now()


async def test_entities_unavailable_until_the_first_frame(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    assert hass.states.get(f"sensor.{PREFIX}_battery").state == STATE_UNAVAILABLE
    assert hass.states.get(f"binary_sensor.{PREFIX}_connected").state == STATE_OFF


async def test_entities_named_from_translations(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    feed(entry)
    await hass.async_block_till_done()

    battery = hass.states.get(f"sensor.{PREFIX}_battery")
    assert battery.state == "98"
    assert battery.attributes["friendly_name"] == "UGREEN PowerRoam GS1200 Battery"
    assert hass.states.get(f"sensor.{PREFIX}_battery_voltage").state == "27.6"
    assert hass.states.get(f"sensor.{PREFIX}_mode").state == "charging"
    assert hass.states.get(f"sensor.{PREFIX}_discharge_time_remaining").state == "unknown"
    assert hass.states.get(f"switch.{PREFIX}_child_safety_lock").state == STATE_ON
    # Read-only until their write is confirmed on a unit.
    assert hass.states.get(f"binary_sensor.{PREFIX}_audio_tones").state == STATE_ON
    assert hass.states.get(f"binary_sensor.{PREFIX}_battery_preservation").state == STATE_OFF
    assert hass.states.get(f"switch.{PREFIX}_audio_tones") is None
    assert hass.states.get(f"switch.{PREFIX}_battery_preservation") is None
    light = hass.states.get(f"select.{PREFIX}_light")
    assert light.state == "off"
    assert light.attributes["options"] == ["off", "low", "high", "strobe", "sos"]
    assert hass.states.get(f"select.{PREFIX}_operating_mode").state == "standard"
    assert hass.states.get(f"select.{PREFIX}_dc_charging_current").state == "8"
    assert hass.states.get(f"select.{PREFIX}_low_battery_alert_level").state == "10"
    assert hass.states.get(f"binary_sensor.{PREFIX}_fault").state == STATE_OFF


async def test_switch_action_writes_and_confirms(
    hass: HomeAssistant, entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ble, "SWITCH_CONFIRM_WAIT", 1.0)
    async with FakeUnit(entry.runtime_data) as unit:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": f"switch.{PREFIX}_quiet_mode"}, blocking=True
        )
        assert len(unit.writes) == 1
        assert hass.states.get(f"switch.{PREFIX}_quiet_mode").state == STATE_OFF

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": f"select.{PREFIX}_light", "option": "sos"},
            blocking=True,
        )
        assert hass.states.get(f"select.{PREFIX}_light").state == "sos"


async def test_unconfirmed_change_is_reported(
    hass: HomeAssistant, entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ble, "SWITCH_CONFIRM_WAIT", 0.5)
    async with FakeUnit(entry.runtime_data, "silent"):
        with pytest.raises(HomeAssistantError) as err:
            await hass.services.async_call(
                "switch", "turn_off", {"entity_id": f"switch.{PREFIX}_u_turbo"}, blocking=True
            )
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "not_confirmed"
    # Home Assistant drops the trailing period of translated messages.
    assert str(err.value) == "The PowerRoam didn't confirm the U-Turbo change"


async def test_diagnostics_hold_no_identifiers(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry
) -> None:
    serial = b"G12XX0000000000" * 2
    mac = bytes.fromhex("aabbccddeeff")
    device = entry.runtime_data
    device._on_notify(None, bytearray(reply(0x05, serial) + reply(0x21, mac) + stream()))
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert diag["payloads"]["0x05"] == diag["payloads"]["0x21"] == "<private>"
    assert diag["payloads"]["0x16"] == CHARGING[0x16]
    text = str(diag)
    assert ADDRESS not in text and serial.hex() not in text and mac.hex() not in text
