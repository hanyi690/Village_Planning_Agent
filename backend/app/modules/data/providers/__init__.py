"""Provider subpackage — deprecated, being phased out.

Only the following modules remain active:
- tianditu/: Used by fetcher.py, gis_context.py, accessibility.py, isochrone.py
- amap/: Used by POIProvider, connections/amap.py
- poi.py: Used by search_poi.py tool

All other modules (base.py, base_types.py, orchestrator.py, adapters,
dem_provider.py, osm/) have been removed. New code should use
app.modules.data.catalog.DataCatalog for data access.
"""

from __future__ import annotations

__all__ = []
