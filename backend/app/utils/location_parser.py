"""Address hierarchy parser — extract province/city/county/town/village from location strings.

Supports formats:
  - "平远县泗水镇金田村"
  - "广东省梅州市平远县泗水镇金田村"
  - "金田村" (village name only)

Migrated from app.modules.data.fetcher.py (deleted).
"""

from __future__ import annotations

import re
from typing import Dict

_VILLAGE_PATTERN = re.compile(r'([^县市省镇]+村)(?![委会])')
_TOWN_PATTERN = re.compile(r'([^县市省]+镇)')
_COUNTY_PATTERN = re.compile(r'([^省市]+县)')
_CITY_PATTERN = re.compile(r'(.+市)')
_PROVINCE_PATTERN = re.compile(r'(.+省)')


def parse_location_hierarchy(location: str) -> Dict[str, str]:
    """Parse administrative hierarchy from an address string.

    Args:
        location: Address string e.g. "广东省梅州市平远县泗水镇金田村"

    Returns:
        Dict with keys: province, city, county, town, village
    """
    hierarchy = {"province": "", "city": "", "county": "", "town": "", "village": ""}

    village_match = _VILLAGE_PATTERN.search(location)
    if village_match:
        hierarchy["village"] = village_match.group(1)

    town_match = _TOWN_PATTERN.search(location)
    if town_match:
        hierarchy["town"] = town_match.group(1)

    county_match = _COUNTY_PATTERN.search(location)
    if county_match:
        hierarchy["county"] = county_match.group(1)

    city_match = _CITY_PATTERN.search(location)
    if city_match:
        hierarchy["city"] = city_match.group(1)

    province_match = _PROVINCE_PATTERN.search(location)
    if province_match:
        hierarchy["province"] = province_match.group(1)

    return hierarchy


def is_village_level_location(location: str) -> bool:
    """Check if a location string contains a village name."""
    return bool(_VILLAGE_PATTERN.search(location))


__all__ = ["parse_location_hierarchy", "is_village_level_location"]
