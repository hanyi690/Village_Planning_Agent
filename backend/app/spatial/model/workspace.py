"""Typed spatial access opened by the data layer.

The workspace is the only spatial input passed into EXECUTE.  Its backing
bundle is private to this boundary; consumers use typed layer groups and do
not exchange a free-form ``gis_data`` mapping.
"""

from __future__ import annotations

from typing import Any

from app.data.model.snapshot import SessionDataSnapshot


class SpatialWorkspace:
    def __init__(self, snapshot: SessionDataSnapshot, bundle: Any) -> None:
        if bundle is None:
            raise ValueError("SpatialWorkspace requires a materialized data bundle")
        self.snapshot = snapshot
        self._bundle = bundle

    @classmethod
    def from_bundle(
        cls,
        bundle: Any,
        *,
        session_id: str,
        source: str = "data_catalog",
    ) -> "SpatialWorkspace":
        return cls(
            SessionDataSnapshot.from_bundle(bundle, session_id=session_id, source=source),
            bundle,
        )

    @property
    def village_name(self) -> str:
        return str(getattr(self._bundle, "village_name", "") or "")

    @property
    def metadata(self) -> Any:
        return self._bundle.metadata

    @property
    def input_document_refs(self) -> list[dict[str, Any]]:
        """Compact input-source refs owned by the data bundle."""
        return list(getattr(self._bundle.documents, "document_refs", []) or [])

    @property
    def report_refs(self) -> list[dict[str, Any]]:
        """Report manifest owned by the unified bundle retrieval boundary."""
        return list(getattr(self._bundle.documents, "report_refs", []) or [])

    def find_feature_by_bsm(self, bsm: str) -> tuple[str, str, Any] | None:
        """Resolve one bundle feature without scanning every geometry layer."""
        finder = getattr(self._bundle, "find_feature_by_bsm", None)
        if callable(finder):
            return finder(bsm)
        return None

    @property
    def points(self) -> Any:
        return self._bundle.points

    @property
    def lines(self) -> Any:
        return self._bundle.lines

    @property
    def polygons(self) -> Any:
        return self._bundle.polygons

    @property
    def rasters(self) -> Any:
        return self._bundle.rasters

    @property
    def tables(self) -> Any:
        return self._bundle.tables

    def current_parcels(self) -> list[Any]:
        return list(self.polygons.get("landuse_current") or [])

    def to_delivery_inputs(self) -> dict[str, Any]:
        """Materialize payloads only at the data→delivery adapter boundary."""
        return dict(self._bundle.to_geojson_dict())


__all__ = ["SpatialWorkspace"]
