"""Code Dictionary Center — externalized, configurable encoding system.

Usage:
    from app.modules.gis.schema.dicts import get_center

    center = get_center()
    dlbm = center.get("dlbm")
    zone = dlbm.lookup("0101")  # {"code": "0101", "name": "水田", ...}

Replaces hardcoded Python dicts with YAML-driven dictionaries.
"""

from .loader import CodeDictionary, ProposalTable, DictionaryCenter, get_center

__all__ = [
    "CodeDictionary",
    "ProposalTable",
    "DictionaryCenter",
    "get_center",
]
