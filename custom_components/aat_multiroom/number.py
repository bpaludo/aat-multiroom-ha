"""AAT Multiroom — zone parameter number entities (bass, treble, balance, preamp).

Each zone exposes four sliders:
  - Graves (bass):     0..14  (7 = 0 dB, steps of 2 dB, range ±14 dB)
  - Agudos (treble):   0..14  (7 = 0 dB, steps of 2 dB, range ±14 dB)
  - Balanço (balance): 0..20  (10 = center, 0 = full left, 20 = full right)
  - Pré-Amp (preamp):  0..7   (0 = 0 dB, 7 = +14 dB)

Values come from GETALL polling — no extra round-trips needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .aat_protocol import AatClient, ZoneState
from .const import CONF_NUM_ZONES, CONF_ZONE_NAMES, DEFAULT_NUM_ZONES, DOMAIN
from .coordinator import AatCoordinator
from .entity import AatEntity


@dataclass(frozen=True)
class _NumberDef:
    key: str
    name: str
    icon: str
    native_min: float
    native_max: float
    get_value: Callable[[ZoneState], int]
    set_value: Callable[[AatClient, int, int], Coroutine[Any, Any, None]]


_ZONE_NUMBERS: tuple[_NumberDef, ...] = (
    _NumberDef("bass", "Graves", "mdi:equalizer", 0, 14,
               lambda zs: zs.bass, lambda c, z, v: c.set_bass(z, v)),
    _NumberDef("treble", "Agudos", "mdi:equalizer-outline", 0, 14,
               lambda zs: zs.treble, lambda c, z, v: c.set_treble(z, v)),
    _NumberDef("balance", "Balanço", "mdi:pan-horizontal", 0, 20,
               lambda zs: zs.balance, lambda c, z, v: c.set_balance(z, v)),
    _NumberDef("preamp", "Pré-Amp", "mdi:amplifier", 0, 7,
               lambda zs: zs.preamp, lambda c, z, v: c.set_preamp(z, v)),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AatCoordinator = hass.data[DOMAIN][entry.entry_id]
    num_zones = entry.data.get(CONF_NUM_ZONES, DEFAULT_NUM_ZONES)
    zone_names: dict[str, str] = entry.options.get(CONF_ZONE_NAMES, {}) or {}

    async_add_entities(
        AatZoneNumber(
            coordinator=coordinator,
            entry=entry,
            zone=zone,
            zone_name=zone_names.get(str(zone)) or f"Zona {zone}",
            defn=defn,
        )
        for zone in range(1, num_zones + 1)
        for defn in _ZONE_NUMBERS
    )


class AatZoneNumber(AatEntity, NumberEntity):
    """Zone parameter exposed as a number slider."""

    _attr_native_step = 1.0
    _attr_mode = NumberMode.SLIDER
    # EQ/balance/preamp are tuning knobs — keep them in the device's
    # Configuration section instead of cluttering the main controls.
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: AatCoordinator,
        entry: ConfigEntry,
        zone: int,
        zone_name: str,
        defn: _NumberDef,
    ) -> None:
        super().__init__(coordinator, entry)
        self._zone = zone
        self._defn = defn
        self._attr_unique_id = f"{self._base_uid}_zone_{zone}_{defn.key}"
        self._attr_name = f"{zone_name} {defn.name}"
        self._attr_icon = defn.icon
        self._attr_native_min_value = defn.native_min
        self._attr_native_max_value = defn.native_max

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self._zone in self.coordinator.data.zones
        )

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        zs = self.coordinator.data.zones.get(self._zone)
        return float(self._defn.get_value(zs)) if zs is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self._execute(
            self._defn.set_value(self.coordinator.client, self._zone, int(value))
        )
