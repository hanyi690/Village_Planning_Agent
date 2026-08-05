"""Layer-name domain constants — layer numbering shared by planning pipeline layers.

Pure data: LAYER_NAMES (str key), LAYER_NAMES_BY_NUMBER (int key), get_layer_name().
Consumed by agent/bootstrap/phase_machine (re-export) and modules/planning_text.
"""

from __future__ import annotations

from typing import Dict


LAYER_NAMES: Dict[str, str] = {
    "layer1": "现状分析",
    "layer2": "规划思路",
    "layer3": "详细规划",
}

LAYER_NAMES_BY_NUMBER: Dict[int, str] = {
    1: "现状分析",
    2: "规划思路",
    3: "详细规划",
}


def get_layer_name(layer: int) -> str:
    return LAYER_NAMES_BY_NUMBER.get(layer, f"Layer {layer}")


__all__ = ["LAYER_NAMES", "LAYER_NAMES_BY_NUMBER", "get_layer_name"]
