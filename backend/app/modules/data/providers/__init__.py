"""Provider subpackage - active data provider modules.

Active submodules:
- tianditu/: Used by fetcher.py, gis_context.py, accessibility.py, isochrone.py
- amap/: Used by POIProvider, connections/amap.py
- poi.py: Used by search_poi.py tool

Removed modules (base.py, base_types.py, orchestrator.py, adapters,
dem_provider.py, osm/) have been deleted. New data access should use
app.modules.data.catalog.DataCatalog.
"""

from __future__ import annotations

__all__ = []
