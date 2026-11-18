"""Fault, read-only settings and link state for the UGREEN PowerRoam."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PowerRoamConfigEntry
from .entity import PowerRoamEntity

# Pushed by the link; nothing to throttle.
PARALLEL_UPDATES = 0

# Any non-zero byte in the 0x01 frame; the bits aren't mapped yet.
FAULT = BinarySensorEntityDescription(
    key="fault", translation_key="fault", device_class=BinarySensorDeviceClass.PROBLEM
)

# The 0x16 fields HA doesn't write (the outputs and the other settings are
# switches, switch.py). Battery preservation and audio tones are settings
# too, but on a GS1200 a write to them didn't take effect, so they are only
# shown.
SETTINGS = tuple(
    BinarySensorEntityDescription(
        key=key, translation_key=key, entity_category=EntityCategory.DIAGNOSTIC
    )
    for key in ("battery_care", "key_beep", "low_battery_warning", "standby")
)

CONNECTED = BinarySensorEntityDescription(
    key="connected",
    translation_key="connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerRoamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(
        [
            PowerRoamFlag(device, FAULT),
            *(PowerRoamFlag(device, description) for description in SETTINGS),
            PowerRoamConnected(device, CONNECTED),
        ]
    )


class PowerRoamFlag(PowerRoamEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        return self._device.data.get(self.entity_description.key)


class PowerRoamConnected(PowerRoamEntity, BinarySensorEntity):
    """The link itself: drops show here while the values are held."""

    @property
    def is_on(self) -> bool:
        return self._device.link_up

    @property
    def available(self) -> bool:
        return True
