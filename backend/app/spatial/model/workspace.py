"""Typed spatial access opened by the data layer.

The workspace is the only spatial input passed into EXECUTE.  Its backing
bundle is private to this boundary; consumers use typed layer groups and do
not exchange a free-form ``gis_data`` mapping.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.data.model.snapshot import SessionDataSnapshot


def _current_world_catalog(catalog: Any) -> Any:
    """Project a catalog at the workspace boundary; raw DATA never escapes."""

    snapshot = getattr(catalog, "snapshot", catalog)
    if snapshot is None:
        raise ValueError("SpatialWorkspace requires a normalized catalog")
    from app.data.admission import assert_current_world_catalog, current_world_snapshot
    from app.data.resource_catalog import DataResourceCatalog

    projected = current_world_snapshot(snapshot)
    assert_current_world_catalog(projected)
    return DataResourceCatalog(projected)


def _legacy_planned_output_keys() -> frozenset[str]:
    """Return Bundle-owned output groups from explicit adapter metadata.

    This compatibility decision is allowed to know the legacy registry.  It
    does not inspect arbitrary uploaded layer names or business attributes.
    """

    from app.data.model.layer_registry import get_planned_output_bundle_keys

    return get_planned_output_bundle_keys()


def _is_legacy_planned_output_collection(
    value: Any,
    *,
    registered: frozenset[str] | None = None,
) -> bool:
    """Use names only to reject legacy output collections, never to admit."""

    key = str(value or "").strip().casefold()
    known = registered if registered is not None else _legacy_planned_output_keys()
    return (
        key in {str(item).casefold() for item in known}
        or "planned" in key
        or "planning_result" in key
        or "planning_output" in key
        or "规划" in key
    )


class SpatialWorkspace:
    def __init__(self, snapshot: SessionDataSnapshot, bundle: Any = None, catalog: Any = None) -> None:
        if bundle is None and catalog is None:
            raise ValueError("SpatialWorkspace requires a data bundle or generic catalog")
        self.snapshot = snapshot
        self._bundle = bundle
        self._catalog = _current_world_catalog(catalog) if catalog is not None else None

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

    @classmethod
    def from_data_catalog(
        cls,
        catalog: Any,
        *,
        session_id: str,
        village_name: str = "",
        source: str = "data_catalog",
    ) -> "SpatialWorkspace":
        """Open a DATA-only workspace without constructing a Bundle."""

        admitted_catalog = _current_world_catalog(catalog)
        snapshot = SessionDataSnapshot.from_data_catalog(
            admitted_catalog,
            session_id=session_id,
            village_name=village_name,
            source=source,
        )
        return cls(snapshot, catalog=admitted_catalog)

    @property
    def village_name(self) -> str:
        return str(
            getattr(self._bundle, "village_name", "")
            or getattr(self.snapshot, "village_name", "")
            or ""
        )

    @property
    def metadata(self) -> Any:
        if self._bundle is not None:
            return self._bundle.metadata
        crs = next(
            (
                str(getattr(item, "crs", "") or "")
                for item in self.snapshot.collections
                if str(getattr(item, "crs", "") or "").strip()
            ),
            "EPSG:4326",
        )
        return type("DataMetadata", (), {"crs": crs})()

    @property
    def source_crs(self) -> str:
        """Return the best CRS declared by the data snapshot.

        The canonical bundle currently serializes geometries as WGS84, but
        ingestion adapters may preserve a different source CRS in collection
        metadata.  Keeping this lookup in the data-owned workspace prevents
        downstream KG/grounding code from hard-coding a CRS or inspecting the
        legacy bundle fields directly.
        """

        for collection in self.snapshot.collections:
            value = str(getattr(collection, "crs", "") or "").strip()
            if value and value.casefold() not in {"unknown", "none", "null"}:
                return value
        metadata = self.metadata
        for key in ("crs", "source_crs", "coordinate_reference_system"):
            value = str(getattr(metadata, key, "") or "").strip()
            if value and value.casefold() not in {"unknown", "none", "null"}:
                return value
        return "EPSG:4326"

    @property
    def input_document_refs(self) -> list[dict[str, Any]]:
        """Compact input-source refs owned by the data bundle."""
        return list(getattr(getattr(self._bundle, "documents", None), "document_refs", []) or [])

    @property
    def report_refs(self) -> list[dict[str, Any]]:
        """Report manifest owned by the unified bundle retrieval boundary."""
        return list(getattr(getattr(self._bundle, "documents", None), "report_refs", []) or [])

    def find_feature_by_bsm(self, bsm: str) -> tuple[str, str, Any] | None:
        """Resolve one bundle feature without scanning every geometry layer."""
        finder = getattr(self._bundle, "find_feature_by_bsm", None)
        if callable(finder):
            return finder(bsm)
        return None

    @property
    def points(self) -> Any:
        return self._bundle.points if self._bundle is not None else {}

    @property
    def lines(self) -> Any:
        return self._bundle.lines if self._bundle is not None else {}

    @property
    def polygons(self) -> Any:
        return self._bundle.polygons if self._bundle is not None else {}

    @property
    def rasters(self) -> Any:
        return self._bundle.rasters if self._bundle is not None else type("DataRasters", (), {"all_rasters": {}})()

    @property
    def tables(self) -> Any:
        return self._bundle.tables if self._bundle is not None else type("DataTables", (), {"all_tables": {}})()

    def current_parcels(self) -> list[Any]:
        return list(self.polygons.get("landuse_current") or [])

    def iter_source_features(self) -> list[Any]:
        """Return all vector source features without layer-name assumptions."""

        if self._catalog is not None:
            return list(
                getattr(getattr(self._catalog, "snapshot", None), "features", ()) or ()
            )
        result: list[Any] = []
        seen: set[int] = set()
        excluded = _legacy_planned_output_keys()
        for group_name, group in (
            ("points", self.points),
            ("lines", self.lines),
            ("polygons", self.polygons),
        ):
            if group is None or not hasattr(group, "keys"):
                continue
            for layer in group.keys():
                if _is_legacy_planned_output_collection(
                    layer,
                    registered=excluded,
                ):
                    continue
                for feature in list(group.get(layer) or []):
                    marker = id(feature)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    result.append(feature)
        return result

    def query_resources(
        self,
        *,
        geometry_kind: str = "",
        layer_ref: str = "",
        attributes: dict[str, Any] | None = None,
        limit: int = 256,
    ) -> list[Any]:
        """Query source features by generic descriptors before legacy layers."""

        wanted_kind = str(geometry_kind or "").casefold()
        wanted_layer = str(layer_ref or "").casefold()
        attributes = attributes or {}
        result: list[Any] = []
        for feature in self.iter_source_features():
            feature_geometry = getattr(feature, "geometry", None)
            if wanted_kind and str(getattr(feature, "geometry_kind", "") or "").casefold() not in {wanted_kind, ""}:
                try:
                    from shapely.geometry import shape

                    actual = str(shape(feature_geometry).geom_type).casefold()
                    if not (wanted_kind == "point" and actual in {"point", "multipoint"}) and not (wanted_kind == "line" and actual in {"linestring", "multilinestring"}) and not (wanted_kind == "polygon" and actual in {"polygon", "multipolygon"}):
                        continue
                except Exception:
                    continue
            feature_layer = str(getattr(feature, "layer_ref", "") or getattr(feature, "layer_type", "") or "").casefold()
            if wanted_layer and wanted_layer not in feature_layer:
                continue
            raw = getattr(feature, "_raw", None) or getattr(feature, "raw_attributes", None) or {}
            if any(str(raw.get(key, "")) != str(value) for key, value in attributes.items()):
                continue
            result.append(feature)
            if len(result) >= max(1, int(limit)):
                break
        return result

    def to_resource_catalog(self, *, snapshot_id: str = "") -> Any:
        """Build the generic Data resource index without exposing Bundle fields.

        This is the migration seam used by KG/GROUND/SELECT.  The legacy
        bundle remains private to ``SpatialWorkspace``; callers receive only
        source features, representations and capabilities.
        """

        if self._catalog is not None:
            return self._catalog

        from app.data.resource_catalog import DataResourceCatalog

        records: list[Any] = []
        admission_decisions: list[dict[str, Any]] = []
        excluded = _legacy_planned_output_keys()

        def record_admission(collection: str, *, planned_output: bool) -> None:
            source_ref = (
                f"legacy-bundle:{self.snapshot.session_id}:{collection}"
            )
            status = "excluded" if planned_output else "admitted"
            role = "planned_output" if planned_output else "current_evidence"
            material = {
                "source_ref": source_ref,
                "source_digest": self.snapshot.digest,
                "input_role": role,
                "status": status,
                "resource_kind": "vector_collection",
            }
            admission_decisions.append({
                "decision_ref": "data.admission." + hashlib.sha256(
                    json.dumps(
                        material,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()[:24],
                **material,
                "reason": (
                    "legacy_adapter_declared_planned_output"
                    if planned_output
                    else "legacy_adapter_declared_source_input"
                ),
                "recovery_pointer": "",
            })

        def catalog_record(feature: Any, *, collection: str) -> dict[str, Any]:
            if hasattr(feature, "model_dump"):
                values = dict(feature.model_dump(mode="python"))
            elif hasattr(feature, "__dict__"):
                values = dict(vars(feature))
            elif isinstance(feature, dict):
                values = dict(feature)
            else:
                values = {}
            geometry = values.pop("geometry", getattr(feature, "geometry", None))
            raw = values.get("_raw")
            if not isinstance(raw, dict):
                raw = getattr(feature, "_raw", None)
            raw = raw if isinstance(raw, dict) else {}
            for key in (
                "source_feature_id",
                "source_uri",
                "source_content_digest",
                "source_geometry_digest",
            ):
                if raw.get(key) not in (None, "", [], {}):
                    values.setdefault(key, raw[key])
            values.setdefault("layer_ref", str(collection))
            values.setdefault("source_collection", str(collection))
            return {"geometry": geometry, "properties": values}

        for group_name, group in (
            ("points", self.points),
            ("lines", self.lines),
            ("polygons", self.polygons),
        ):
            if group is None:
                continue
            keys = group.keys() if callable(getattr(group, "keys", None)) else []
            for key in keys:
                if _is_legacy_planned_output_collection(
                    key,
                    registered=excluded,
                ):
                    record_admission(
                        f"{group_name}:{key}",
                        planned_output=True,
                    )
                    continue
                record_admission(
                    f"{group_name}:{key}",
                    planned_output=False,
                )
                records.extend(
                    catalog_record(feature, collection=str(key))
                    for feature in (group.get(key) or [])
                )
        # Non-vector resources participate in the same catalog as bounded
        # descriptors.  Their payloads stay in DATA-owned stores; only stable
        # refs and lightweight metadata cross into KG/LLM context.
        for resource_kind, group in (("raster", self.rasters), ("table", self.tables)):
            values = getattr(group, f"all_{resource_kind}s", {}) or {}
            for key, resource in values.items():
                if _is_legacy_planned_output_collection(
                    key,
                    registered=excluded,
                ):
                    record_admission(
                        f"{resource_kind}:{key}",
                        planned_output=True,
                    )
                    continue
                record_admission(
                    f"{resource_kind}:{key}",
                    planned_output=False,
                )
                attrs: dict[str, Any] = {
                    "layer_ref": str(key),
                    "resource_kind": resource_kind,
                    "source_collection": str(key),
                }
                if resource is not None:
                    for field_name in ("path", "crs", "resolution", "band_count", "source_uri"):
                        value = getattr(resource, field_name, None)
                        if value not in (None, "", [], {}):
                            attrs[field_name] = value
                records.append({
                    "id": f"{resource_kind}:{key}",
                    "geometry": None,
                    "properties": attrs,
                })
        return DataResourceCatalog.from_records(
            records,
            dataset_ref=f"session:{self.snapshot.session_id}",
            name=self.village_name,
            version=self.snapshot.digest,
            crs=self.source_crs,
            snapshot_id=snapshot_id or self.snapshot.snapshot_id,
            admission_decisions=admission_decisions,
        )

    def attach_resource_catalog(self, catalog: Any) -> None:
        """Attach the normalized DATA catalog used by downstream stages.

        A session may combine a compatibility Bundle with uploaded/service
        records.  Keeping the merged catalog on the workspace makes capability
        checks and source iteration see the same universe as KG/GROUND/SELECT,
        while the private Bundle remains available to legacy adapters.
        """

        if catalog is None or getattr(catalog, "snapshot", None) is None:
            raise ValueError("attach_resource_catalog requires a normalized catalog")
        self._catalog = _current_world_catalog(catalog)

    def to_delivery_inputs(self) -> dict[str, Any]:
        """Materialize payloads only at the data→delivery adapter boundary."""
        raw_bundle = (
            dict(self._bundle.to_geojson_dict()) if self._bundle is not None else {}
        )
        excluded = _legacy_planned_output_keys()
        result = {
            key: value
            for key, value in raw_bundle.items()
            if not _is_legacy_planned_output_collection(
                str(key).removesuffix("_geojson"),
                registered=excluded,
            )
        }
        # Always expose the normalized source universe as an additional
        # immutable layer.  For DATA-only sessions this is the current
        # baseline; for mixed sessions it preserves external resources for
        # lineage and delivery without overwriting Bundle land-use layers.
        features = []
        for feature in list(
            getattr(getattr(self._catalog, "snapshot", None), "features", ()) or ()
        ):
            geometry = getattr(feature, "geometry", None)
            if geometry is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    **dict(getattr(feature, "raw_attributes", {}) or {}),
                    "source_feature_ref": str(getattr(feature, "source_feature_ref", "") or ""),
                    "source_dataset_ref": str(getattr(feature, "dataset_ref", "") or ""),
                    "source_layer_ref": str(getattr(feature, "layer_ref", "") or ""),
                    "source_crs": str(getattr(feature, "source_crs", "") or ""),
                },
            })
        if features:
            result["data_catalog_geojson"] = {
                "type": "FeatureCollection",
                "features": features,
            }
        if result:
            return result
        raise ValueError("SpatialWorkspace has no materializable source features")


__all__ = ["SpatialWorkspace"]
