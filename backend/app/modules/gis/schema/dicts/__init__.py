"""Code Dictionary Center — externalized, configurable encoding system.

Usage:
    from app.modules.gis.schema.dicts import get_center

    center = get_center()
    gbt21010 = center.encoding("gbt21010")
    zone = gbt21010.lookup("0101")  # {"code": "0101", "name": "水田", ...}

    appendix5 = center.encoding("appendix5")
    ghytbm = appendix5.lookup("2121")  # {"code": "2121", "name": "宅基地", ...}

Replaces hardcoded Python dicts with YAML-driven dictionaries.
"""

from .loader import CodeDictionary, ProposalTable, DictionaryCenter, get_center

__all__ = [
    "CodeDictionary",
    "ProposalTable",
    "DictionaryCenter",
    "get_center",
]
