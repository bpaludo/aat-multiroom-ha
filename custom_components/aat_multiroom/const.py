"""Constants for the AAT Multiroom integration."""
from __future__ import annotations

DOMAIN = "aat_multiroom"

# Config entry / config flow keys
CONF_NUM_ZONES = "num_zones"
CONF_ZONE_NAMES = "zone_names"
CONF_SOURCES = "sources"  # mapping of input number -> friendly name
CONF_HOMEKIT_COMPAT = "homekit_compat"  # expose zones as Light + media_player TV class

# Defaults
DEFAULT_PORT = 5000
DEFAULT_NUM_ZONES = 6  # PMR-7 (our reference device); overridden by MODEL detection
DEFAULT_NUM_INPUTS = 6
DEFAULT_SCAN_INTERVAL = 20  # seconds between background polls
DEFAULT_HOMEKIT_COMPAT = False

# Volume scaling: AAT goes 0..87, HA media_player expects 0.0..1.0.
AAT_VOLUME_MAX = 87

# Zones and inputs per model (API spec Rev.12, cover page). The MODEL reply
# comes without the dash, e.g. "PMR7". Keyed by that uppercase form so we can
# derive the topology from the device instead of asking the user.
#   inputs = number of selectable matrix inputs (streamer inputs 7/8 included
#   for the PMR-9..13 streamer models).
MODEL_ZONES: dict[str, int] = {
    "PMA1": 4, "PMA2": 6,
    "PMRH2": 2, "PMRH4": 4, "PMRH6": 6,
    "PMR4": 4, "PMR5": 6, "PMR6": 4, "PMR7": 6, "PMR8": 2,
    "PMR9": 4, "PMR10": 6, "PMR11": 4, "PMR12": 6, "PMR13": 2,
}
MODEL_INPUTS: dict[str, int] = {
    "PMA1": 4, "PMA2": 4,
    "PMRH2": 6, "PMRH4": 6, "PMRH6": 6,
    "PMR4": 4, "PMR5": 4, "PMR6": 6, "PMR7": 6, "PMR8": 5,
    "PMR9": 7, "PMR10": 7, "PMR11": 8, "PMR12": 8, "PMR13": 6,
}
MAX_NUM_ZONES = 6   # platform maximum across all models
MAX_NUM_INPUTS = 8  # platform maximum across all models


def normalize_model(model: str) -> str:
    """Normalize a MODEL reply to the MODEL_ZONES/MODEL_INPUTS key form."""
    return "".join(model.upper().split()).replace("-", "")


def zones_for_model(model: str, fallback: int = DEFAULT_NUM_ZONES) -> int:
    """Number of zones for a model string, falling back when unknown."""
    return MODEL_ZONES.get(normalize_model(model), fallback)


def inputs_for_model(model: str, fallback: int = DEFAULT_NUM_INPUTS) -> int:
    """Number of inputs for a model string, falling back when unknown."""
    return MODEL_INPUTS.get(normalize_model(model), fallback)
