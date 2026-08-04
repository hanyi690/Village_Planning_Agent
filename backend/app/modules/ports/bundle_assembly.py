"""BundleAssemblyPort — injectable GeoJSON-to-bundle merging.

Lets ``app.modules.kg`` (and other modules that must not import from
``app.modules.data``) merge raw GeoJSON layers into a canonical
``VillageBundle`` through a protocol, with the implementation living in the
data layer. Eliminates the historical ``kg -> data`` reverse dependency.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BundleAssemblyPort(Protocol):
    """Merge GeoJSON FeatureCollections into a canonical bundle."""

    def merge_geojson_into_bundle(
        self,
        bundle: Any,
        layer_key: str,
        geojson: dict[str, Any],
    ) -> int:
        """Merge ``geojson`` features under ``layer_key`` into ``bundle``.

        Returns the number of features merged.
        """


__all__ = ["BundleAssemblyPort"]
