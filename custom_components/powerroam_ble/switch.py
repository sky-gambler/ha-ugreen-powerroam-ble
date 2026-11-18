"""Output and setting switches for the UGREEN PowerRoam, all in the 0x16 block."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PowerRoamConfigEntry
from .ble import PowerRoamError
from .entity import PowerRoamEntity, translated_error

# Writes are serialised by the link's own lock.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PowerRoamSwitchDescription(SwitchEntityDescription):
    field: str


def _output(key: str, field: str) -> PowerRoamSwitchDescription:
    return PowerRoamSwitchDescription(
        key=key, translation_key=key, field=field, device_class=SwitchDeviceClass.OUTLET
    )


def _setting(key: str, field: str) -> PowerRoamSwitchDescription:
    return PowerRoamSwitchDescription(
        key=key, translation_key=key, field=field, entity_category=EntityCategory.CONFIG
    )


# Keys are the data keys protocol.telemetry() reports; fields are the 0x16
# names, each in protocol.WRITABLE_SWITCH_FIELDS.
SWITCHES: tuple[PowerRoamSwitchDescription, ...] = (
    _output("ac_output", "ac"),
    _output("dc_output", "dc"),
    _output("usb_output", "usb"),
    _setting("quiet_mode", "low_noise"),
    _setting("u_turbo", "ac_uturbo"),
    _setting("child_lock", "locking"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerRoamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(PowerRoamSwitch(device, description) for description in SWITCHES)


class PowerRoamSwitch(PowerRoamEntity, SwitchEntity):
    entity_description: PowerRoamSwitchDescription

    @property
    def is_on(self) -> bool | None:
        return self._device.data.get(self.entity_description.key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        try:
            await self._device.set_switch(self.entity_description.field, on, str(self.name))
        except PowerRoamError as err:
            raise translated_error(err) from err
