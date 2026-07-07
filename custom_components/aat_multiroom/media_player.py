"""Media player entities for AAT Multiroom — one per zone.

Each zone is a media_player with power (= zone stand-by), volume, mute and
source selection. This is the primary UX for the amplifier.

device_class defaults to SPEAKER (the correct semantics). When the HomeKit
compatibility option is enabled it becomes TV, because that's the only HA
media-player rendering that HomeKit Bridge exposes with a real volume slider
in Apple Home. Non-HomeKit users get the honest SPEAKER class.
"""
from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AAT_VOLUME_MAX,
    CONF_HOMEKIT_COMPAT,
    CONF_NUM_ZONES,
    CONF_SOURCES,
    CONF_ZONE_NAMES,
    DEFAULT_HOMEKIT_COMPAT,
    DEFAULT_NUM_ZONES,
    DOMAIN,
    inputs_for_model,
)
from .coordinator import AatCoordinator
from .entity import AatEntity

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AatCoordinator = hass.data[DOMAIN][entry.entry_id]
    num_zones = entry.data.get(CONF_NUM_ZONES, DEFAULT_NUM_ZONES)
    zone_names: dict[str, str] = entry.options.get(CONF_ZONE_NAMES, {}) or {}
    sources: dict[str, str] = entry.options.get(CONF_SOURCES, {}) or {}
    homekit = entry.options.get(CONF_HOMEKIT_COMPAT, DEFAULT_HOMEKIT_COMPAT)

    async_add_entities(
        AatZoneMediaPlayer(
            coordinator=coordinator,
            entry=entry,
            zone=z,
            zone_name=zone_names.get(str(z)) or f"Zona {z}",
            sources=sources,
            homekit=homekit,
        )
        for z in range(1, num_zones + 1)
    )


class AatZoneMediaPlayer(AatEntity, MediaPlayerEntity):
    """One media_player entity per AAT zone."""

    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(
        self,
        coordinator: AatCoordinator,
        entry: ConfigEntry,
        zone: int,
        zone_name: str,
        sources: dict[str, str],
        homekit: bool,
    ) -> None:
        super().__init__(coordinator, entry)
        self._zone = zone
        self._sources_map = dict(sources)  # input number (str) -> friendly name
        self._sources_inverse = {v: int(k) for k, v in self._sources_map.items()}
        self._attr_unique_id = f"{self._base_uid}_zone_{zone}"
        self._attr_name = zone_name
        self._attr_device_class = (
            MediaPlayerDeviceClass.TV if homekit else MediaPlayerDeviceClass.SPEAKER
        )

    # --- helpers ------------------------------------------------------------

    @property
    def _zone_state(self):
        if not self.coordinator.data:
            return None
        return self.coordinator.data.zones.get(self._zone)

    # --- properties ---------------------------------------------------------

    @property
    def available(self) -> bool:
        return super().available and self._zone_state is not None

    @property
    def state(self) -> MediaPlayerState | None:
        zs = self._zone_state
        if zs is None:
            return None
        if not self.coordinator.data.power or zs.standby:
            return MediaPlayerState.OFF
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        zs = self._zone_state
        return None if zs is None else zs.volume / AAT_VOLUME_MAX

    @property
    def is_volume_muted(self) -> bool | None:
        zs = self._zone_state
        return None if zs is None else zs.mute

    @property
    def source(self) -> str | None:
        zs = self._zone_state
        if zs is None:
            return None
        return self._sources_map.get(str(zs.input)) or f"Entrada {zs.input}"

    @property
    def source_list(self) -> list[str]:
        if self._sources_map:
            return list(self._sources_map.values())
        # No custom names: fall back to the input count derived from the model
        # (honors auto-detection instead of hard-coding 6).
        model = self.coordinator.data.model if self.coordinator.data else ""
        return [f"Entrada {i}" for i in range(1, inputs_for_model(model) + 1)]

    # --- commands -----------------------------------------------------------

    async def async_turn_on(self) -> None:
        # Bring the master up first if it's off, then take the zone out of
        # stand-by. The whole sequence goes through _execute so a rejection
        # surfaces to the UI and state refreshes once at the end.
        client = self.coordinator.client
        power_off = bool(self.coordinator.data) and not self.coordinator.data.power

        async def _seq() -> None:
            if power_off:
                await client.power_on()
            await client.zone_on(self._zone)

        await self._execute(_seq())

    async def async_turn_off(self) -> None:
        await self._execute(self.coordinator.client.zone_off(self._zone))

    async def async_set_volume_level(self, volume: float) -> None:
        aat_vol = round(max(0.0, min(1.0, volume)) * AAT_VOLUME_MAX)
        await self._execute(self.coordinator.client.set_volume(self._zone, aat_vol))

    async def async_volume_up(self) -> None:
        await self._execute(self.coordinator.client.volume_up(self._zone))

    async def async_volume_down(self) -> None:
        await self._execute(self.coordinator.client.volume_down(self._zone))

    async def async_mute_volume(self, mute: bool) -> None:
        client = self.coordinator.client
        await self._execute(
            client.mute_on(self._zone) if mute else client.mute_off(self._zone)
        )

    async def async_select_source(self, source: str) -> None:
        input_num = self._sources_inverse.get(source)
        if input_num is None and source.lower().startswith("entrada"):
            try:
                input_num = int(source.split()[-1])
            except ValueError:
                input_num = None
        if input_num is None:
            return
        await self._execute(self.coordinator.client.set_input(self._zone, input_num))
