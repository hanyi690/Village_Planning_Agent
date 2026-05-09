"""
Config module exports - Dimension configurations and wave config.
"""

from .loader import (
    get_dimension_config,
    get_dimension_layer,
    get_layer_dimensions,
    list_dimensions,
)

from .dependency import get_wave_config

__all__ = [
    "get_dimension_config",
    "get_dimension_layer",
    "get_layer_dimensions",
    "list_dimensions",
    "get_wave_config",
]