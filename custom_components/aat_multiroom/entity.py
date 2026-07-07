"""Shared base entity for the AAT Multiroom integration.

Centralizes three things every platform needs, so identity and error handling
are defined once instead of copy-pasted into six files:

  * device_info keyed on the config entry_id (NOT the host IP) — the device
    registry survives a DHCP address change.
  * a stable unique_id prefix derived from entry_id.
  * _execute(): run a control command, surface protocol errors to the UI as a
    HomeAssistantError, then refresh the coordinator.
"""
from __future__ import annotations

import logging
from collections.abc import Coroutine
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .aat_protocol import AatError
from .const import DOMAIN
from .coordinator import AatCoordinator

_LOGGER = logging.getLogger(__name__)


class AatEntity(CoordinatorEntity[AatCoordinator]):
    """Base entity: entry-id identity, device_info, error-aware command helper."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AatCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._base_uid = entry.entry_id
        self._host = entry.data[CONF_HOST]

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data
        model = data.model if data and data.model else "Multiroom"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"AAT {model}",
            manufacturer="Advanced Audio Technologies",
            model=model,
            sw_version=data.firmware if data and data.firmware else None,
            configuration_url=None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    async def _execute(self, coro: Coroutine[Any, Any, None]) -> None:
        """Run a control command, surface errors to the UI, then refresh state."""
        try:
            await coro
        except AatError as err:
            _LOGGER.error("AAT command failed (%s): %s", self.entity_id or type(self).__name__, err)
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
