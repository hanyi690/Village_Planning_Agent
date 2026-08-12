"""Data-layer implementation of BundleAssemblyPort.

Wraps ``app.data.catalog.catalog._merge_geojson_into_bundle`` behind
the BundleAssemblyPort protocol so modules like ``app.infrastructure.kg`` can inject
it without importing from the data layer (eliminating the kg->data
reverse dependency).
"""

from __future__ import annotations

from typing import Any

from app.contracts.ports.bundle_assembly import BundleAssemblyPort


class DataBundleAssemblyAdapter:
    """BundleAssemblyPort implementation backed by the DataCatalog merger."""

    def merge_geojson_into_bundle(
        self,
        bundle: Any,
        layer_key: str,
        geojson: dict[str, Any],
    ) -> int:
        from app.data.catalog.catalog import _merge_geojson_into_bundle

        return _merge_geojson_into_bundle(bundle, layer_key, geojson)


__all__ = ["DataBundleAssemblyAdapter"]
