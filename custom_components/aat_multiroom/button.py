"""AAT Multiroom — device-level button entities.

Bulk / device operations that would otherwise need multiple service calls or
aren't reachable from a single zone entity:

  - Ligar todas as zonas    → ZTONALL   (one round-trip vs N × zone_on)
  - Desligar todas as zonas → ZSTDBYALL (one round-trip vs N × zone_off)
  - Mutar tudo              → MUTEALL
  - Desmutar tudo           → UNMUTEALL
  - Reiniciar dispositivo   → RESET     (remote reboot over TCP)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .aat_protocol import AatClient
from .const import DOMAIN
from .coordinator import AatCoordinator
from .entity import AatEntity


@dataclass(frozen=True)
class _ButtonDef:
    key: str
    name: str
    icon: str
    press: Callable[[AatClient], Coroutine[Any, Any, None]]


_DEVICE_BUTTONS: tuple[_ButtonDef, ...] = (
    _ButtonDef("zones_all_on", "Ligar todas as zonas", "mdi:speaker-multiple",
               lambda c: c.zone_on_all()),
    _ButtonDef("zones_all_off", "Desligar todas as zonas", "mdi:speaker-off",
               lambda c: c.zone_off_all()),
    _ButtonDef("mute_all", "Mutar tudo", "mdi:volume-mute",
               lambda c: c.mute_all()),
    _ButtonDef("unmute_all", "Desmutar tudo", "mdi:volume-high",
               lambda c: c.unmute_all()),
    _ButtonDef("reset", "Reiniciar dispositivo", "mdi:restart",
               lambda c: c.reset()),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AatCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AatDeviceButton(coordinator, entry, defn) for defn in _DEVICE_BUTTONS
    )


class AatDeviceButton(AatEntity, ButtonEntity):
    """Device-level button (bulk zone commands and reset)."""

    def __init__(
        self,
        coordinator: AatCoordinator,
        entry: ConfigEntry,
        defn: _ButtonDef,
    ) -> None:
        super().__init__(coordinator, entry)
        self._defn = defn
        self._attr_unique_id = f"{self._base_uid}_{defn.key}"
        self._attr_name = defn.name
        self._attr_icon = defn.icon
        if defn.key == "reset":
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self._execute(self._defn.press(self.coordinator.client))
