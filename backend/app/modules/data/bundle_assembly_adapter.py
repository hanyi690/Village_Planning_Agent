"""Data-layer implementation of BundleAssemblyPort.

Wraps ``app.modules.data.catalog.catalog._merge_geojson_into_bundle`` behind
the BundleAssemblyPort protocol so modules like ``app.modules.kg`` can inject
it without importing from ``app.modules.data`` (eliminating the kg->data
reverse dependency).
"""

from __future__ import annotations

from typing import Any

from app.modules.ports.bundle_assembly import BundleAssemblyPort


class DataBundleAssemblyAdapter:
    """BundleAssemblyPort implementation backed by the DataCatalog merger."""

    def merge_geojson_into_bundle(
        self,
        bundle: Any,
        layer_key: str,
        geojson: dict[str, Any],
    ) -> int:
        from app.modules.data.catalog.catalog import _merge_geojson_into_bundle

        return _merge_geojson_into_bundle(bundle, layer_key, geojson)


__all__ = ["DataBundleAssemblyAdapter"]
