"""Config flow for the AAT Multiroom integration.

Two-step user flow:
  1. Connection — host + TCP port. Validates by connecting and issuing
     MODEL/VER, and derives the number of zones/inputs from the MODEL reply so
     the user never has to know their model's topology.
  2. Naming    — friendly names for each zone and input, plus the HomeKit
     compatibility toggle.

Options flow lets the user re-edit names and the HomeKit toggle later.
Reconfigure lets the user change host/port (e.g. to the AAT's secondary TCP
port) and override the zone count for models we don't recognize.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .aat_protocol import AatClient, AatError
from .const import (
    CONF_HOMEKIT_COMPAT,
    CONF_NUM_ZONES,
    CONF_SOURCES,
    CONF_ZONE_NAMES,
    DEFAULT_HOMEKIT_COMPAT,
    DEFAULT_NUM_ZONES,
    DEFAULT_PORT,
    DOMAIN,
    MAX_NUM_ZONES,
    inputs_for_model,
    zones_for_model,
)

_LOGGER = logging.getLogger(__name__)


CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)


async def _async_test_connection(host: str, port: int) -> tuple[str, str]:
    """Try to talk to the AAT. Returns (model, firmware) or raises AatError."""
    client = AatClient(host, port)
    try:
        await client.connect()
        model = await client.get_model()
        firmware = await client.get_firmware()
        return model, firmware
    finally:
        await client.disconnect()


def _default_zone_names(num_zones: int) -> dict[str, str]:
    return {str(i): f"Zona {i}" for i in range(1, num_zones + 1)}


def _default_sources(num_inputs: int) -> dict[str, str]:
    return {str(i): f"Entrada {i}" for i in range(1, num_inputs + 1)}


class AatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._connection: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            try:
                model, firmware = await _async_test_connection(host, port)
            except AatError as err:
                _LOGGER.warning("AAT connection test failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                self._connection = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_NUM_ZONES: zones_for_model(model),
                    "num_inputs": inputs_for_model(model),
                    "model": model,
                    "firmware": firmware,
                }
                return await self.async_step_naming()

        return self.async_show_form(
            step_id="user",
            data_schema=CONNECTION_SCHEMA,
            errors=errors,
        )

    async def async_step_naming(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect friendly names for zones and sources, and the HomeKit toggle."""
        num_zones = self._connection[CONF_NUM_ZONES]
        num_inputs = self._connection["num_inputs"]
        model = self._connection.get("model", "")

        if user_input is not None:
            zone_names = {
                str(i): user_input[f"zone_{i}"] for i in range(1, num_zones + 1)
            }
            sources = {
                str(i): user_input[f"source_{i}"]
                for i in range(1, num_inputs + 1)
                if user_input.get(f"source_{i}", "").strip()
            }
            title = model or "AAT Multiroom"
            data = {
                CONF_HOST: self._connection[CONF_HOST],
                CONF_PORT: self._connection[CONF_PORT],
                CONF_NUM_ZONES: num_zones,
                "model": model,
            }
            options = {
                CONF_ZONE_NAMES: zone_names,
                CONF_SOURCES: sources,
                CONF_HOMEKIT_COMPAT: user_input.get(
                    CONF_HOMEKIT_COMPAT, DEFAULT_HOMEKIT_COMPAT
                ),
            }
            return self.async_create_entry(title=title, data=data, options=options)

        zone_defaults = _default_zone_names(num_zones)
        source_defaults = _default_sources(num_inputs)

        schema_dict: dict[Any, Any] = {}
        for i in range(1, num_zones + 1):
            schema_dict[vol.Required(f"zone_{i}", default=zone_defaults[str(i)])] = str
        for i in range(1, num_inputs + 1):
            schema_dict[
                vol.Optional(f"source_{i}", default=source_defaults[str(i)])
            ] = str
        schema_dict[
            vol.Optional(CONF_HOMEKIT_COMPAT, default=DEFAULT_HOMEKIT_COMPAT)
        ] = bool

        return self.async_show_form(
            step_id="naming",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"model": model or "AAT", "zones": str(num_zones)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AatOptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host / TCP port after install, and override zone count.

        Useful when you want HA to use the AAT's secondary TCP port (default
        1024) so the AAT mobile app can keep port 5000, or when the MODEL isn't
        auto-recognized and the zone count needs a manual value.
        """
        entry = self._get_reconfigure_entry()

        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            try:
                model, firmware = await _async_test_connection(host, port)
            except AatError as err:
                _LOGGER.warning("AAT reconfigure connection test failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                num_zones = user_input.get(CONF_NUM_ZONES) or zones_for_model(model)
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NUM_ZONES: num_zones,
                        "model": model,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Optional(
                        CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                    vol.Optional(
                        CONF_NUM_ZONES,
                        default=entry.data.get(CONF_NUM_ZONES, DEFAULT_NUM_ZONES),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_NUM_ZONES)),
                }
            ),
            errors=errors,
        )


class AatOptionsFlow(OptionsFlow):
    """Edit zone names, sources, and the HomeKit toggle after initial setup.

    Note: do NOT set ``self.config_entry`` manually — the framework provides it
    automatically since HA 2024.11 and explicit assignment is deprecated.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        num_zones = self.config_entry.data[CONF_NUM_ZONES]
        model = self.config_entry.data.get("model", "")
        num_inputs = inputs_for_model(model)

        current_zone_names: dict[str, str] = (
            self.config_entry.options.get(CONF_ZONE_NAMES) or _default_zone_names(num_zones)
        )
        current_sources: dict[str, str] = (
            self.config_entry.options.get(CONF_SOURCES) or _default_sources(num_inputs)
        )
        current_homekit = self.config_entry.options.get(
            CONF_HOMEKIT_COMPAT, DEFAULT_HOMEKIT_COMPAT
        )

        if user_input is not None:
            zone_names = {
                str(i): user_input[f"zone_{i}"] for i in range(1, num_zones + 1)
            }
            sources = {
                str(i): user_input[f"source_{i}"]
                for i in range(1, num_inputs + 1)
                if user_input.get(f"source_{i}", "").strip()
            }
            return self.async_create_entry(
                title="",
                data={
                    CONF_ZONE_NAMES: zone_names,
                    CONF_SOURCES: sources,
                    CONF_HOMEKIT_COMPAT: user_input.get(
                        CONF_HOMEKIT_COMPAT, current_homekit
                    ),
                },
            )

        schema_dict: dict[Any, Any] = {}
        for i in range(1, num_zones + 1):
            schema_dict[
                vol.Required(f"zone_{i}", default=current_zone_names.get(str(i), f"Zona {i}"))
            ] = str
        for i in range(1, num_inputs + 1):
            schema_dict[
                vol.Optional(f"source_{i}", default=current_sources.get(str(i), ""))
            ] = str
        schema_dict[
            vol.Optional(CONF_HOMEKIT_COMPAT, default=current_homekit)
        ] = bool

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))
