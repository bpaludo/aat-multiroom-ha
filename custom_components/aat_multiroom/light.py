"""AAT Multiroom — zones exposed as Light entities (brightness = volume).

OPT-IN. These entities only exist when the "HomeKit compatibility" option is
enabled. They are a deliberate "abuse" of the Light primitive so that Apple
Home (via HomeKit Bridge) renders each zone with a visible brightness slider —
the only way to get a volume slider for HA-bridged audio in iOS Casa. If you
don't use HomeKit, leave the option off and use the media_player entities.

Mapping:
    Light on / off            <-> ZSTDBYOFF / ZSTDBYON  (zone amp out of / into stand-by)
    Light brightness 0..100%  <->  AAT volume 0..87 (1 dB per step)
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AAT_VOLUME_MAX,
    CONF_HOMEKIT_COMPAT,
    CONF_NUM_ZONES,
    CONF_ZONE_NAMES,
    DEFAULT_HOMEKIT_COMPAT,
    DEFAULT_NUM_ZONES,
    DOMAIN,
)
from .coordinator import AatCoordinator
from .entity import AatEntity


def _volume_to_brightness(volume: int) -> int:
    """AAT 0..87 -> HA brightness 0..255."""
    if volume <= 0:
        return 0
    return max(1, round(volume / AAT_VOLUME_MAX * 255))


def _brightness_to_volume(brightness: int) -> int:
    """HA brightness 1..255 -> AAT 1..87."""
    if brightness <= 0:
        return 0
    return max(1, round(brightness / 255 * AAT_VOLUME_MAX))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    # Opt-in: only create the light-as-volume entities in HomeKit mode.
    if not entry.options.get(CONF_HOMEKIT_COMPAT, DEFAULT_HOMEKIT_COMPAT):
        return

    coordinator: AatCoordinator = hass.data[DOMAIN][entry.entry_id]
    num_zones = entry.data.get(CONF_NUM_ZONES, DEFAULT_NUM_ZONES)
    zone_names: dict[str, str] = entry.options.get(CONF_ZONE_NAMES, {}) or {}

    async_add_entities(
        AatZoneLight(
            coordinator,
            entry,
            zone,
            zone_names.get(str(zone)) or f"Zona {zone}",
        )
        for zone in range(1, num_zones + 1)
    )


class AatZoneLight(AatEntity, LightEntity):
    """Zone exposed as a Light: on/off + brightness (= volume)."""

    _attr_icon = "mdi:speaker"
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self,
        coordinator: AatCoordinator,
        entry: ConfigEntry,
        zone: int,
        zone_name: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._zone = zone
        self._attr_unique_id = f"{self._base_uid}_zone_{zone}_light"
        self._attr_name = f"{zone_name} (volume)"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        if not self.coordinator.data.power:
            return False
        zs = self.coordinator.data.zones.get(self._zone)
        return None if zs is None else not zs.standby

    @property
    def brightness(self) -> int | None:
        if self.coordinator.data is None:
            return None
        zs = self.coordinator.data.zones.get(self._zone)
        return None if zs is None else _volume_to_brightness(zs.volume)

    async def async_turn_on(self, **kwargs: Any) -> None:
        client = self.coordinator.client
        power_off = bool(self.coordinator.data) and not self.coordinator.data.power

        async def _seq() -> None:
            if power_off:
                await client.power_on()
            await client.zone_on(self._zone)
            if ATTR_BRIGHTNESS in kwargs:
                await client.set_volume(
                    self._zone, _brightness_to_volume(kwargs[ATTR_BRIGHTNESS])
                )

        await self._execute(_seq())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._execute(self.coordinator.client.zone_off(self._zone))
