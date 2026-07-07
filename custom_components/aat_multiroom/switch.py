"""AAT Multiroom — device-level switches.

  * Power    — the amplifier's master power (PWRON / PWROFF / PWRGET). Different
               from per-zone stand-by (that's on the media_player) and from
               per-zone mute (that's the media_player's volume_mute).
  * Mute All — MUTEALL / UNMUTEALL across every zone.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AatCoordinator
from .entity import AatEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AatCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [AatPowerSwitch(coordinator, entry), AatMuteAllSwitch(coordinator, entry)]
    )


class AatPowerSwitch(AatEntity, SwitchEntity):
    """Master power switch for the AAT amplifier (PWRON / PWROFF)."""

    _attr_name = "Power"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator: AatCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._base_uid}_power"

    @property
    def is_on(self) -> bool | None:
        return None if self.coordinator.data is None else self.coordinator.data.power

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._execute(self.coordinator.client.power_on())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._execute(self.coordinator.client.power_off())


class AatMuteAllSwitch(AatEntity, SwitchEntity):
    """Global mute: ON = all zones muted, OFF = all zones unmuted."""

    _attr_name = "Mute All"
    _attr_icon = "mdi:volume-off"

    def __init__(self, coordinator: AatCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._base_uid}_mute_all"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        zones = self.coordinator.data.zones
        return bool(zones) and all(zs.mute for zs in zones.values())

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._execute(self.coordinator.client.mute_all())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._execute(self.coordinator.client.unmute_all())
