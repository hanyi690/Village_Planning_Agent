"""Generic Data resource catalog independent of Bundle layer/field names."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts.data.source_contracts import (
    DataCapability,
    DataResourceCatalogSnapshot,
    SourceAdmissionDecision,
    SourceDataset,
    SourceFeature,
    SpatialRepresentation,
    source_local_cognition_ref,
)


def _kind(geometry: Mapping[str, Any] | None) -> str:
    value = str((geometry or {}).get("type") or "").casefold()
    if value in {"point", "multipoint"}:
        return "point"
    if value in {"linestring", "multilinestring"}:
        return "line"
    if value in {"polygon", "multipolygon"}:
        return "polygon"
    if value in {"multipatch", "multisurface", "polyhedral_surface"}:
        return "multipatch"
    return "unknown"


def _short_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _text(value: Any) -> str:
    return str(value or "").strip()


def _identity_ref(
    attributes: Mapping[str, Any],
    fallback: str,
    *,
    dataset_ref: str = "",
) -> str:
    """Read an optional physical-object key without imposing a schema.

    These keys are hints supplied by an upstream source (for example several
    line segments sharing a road id).  They are never required; when absent,
    each source feature remains its own world-model candidate.
    """

    global_scope = str(
        attributes.get("identity_scope")
        or attributes.get("entity_ref_scope")
        or ""
    ).strip().casefold()
    global_authority = str(
        attributes.get("identity_authority")
        or attributes.get("entity_ref_authority")
        or ""
    ).strip()
    for key in ("entity_ref", "physical_entity_ref"):
        value = attributes.get(key)
        if not _is_empty(value):
            if global_scope in {"global", "authoritative"} and global_authority:
                return f"global:{global_authority}:{value}"
            return f"source-key:{dataset_ref}:{key}:{value}"
    for key in (
        "road_ref",
        "place_ref",
        "parent_ref",
        "entity_id",
        "physical_id",
    ):
        value = attributes.get(key)
        if not _is_empty(value):
            return f"source-key:{dataset_ref}:{key}:{value}"
    return f"source:{dataset_ref}:{fallback}" if dataset_ref else fallback


def _crs_text(value: Any, fallback: str) -> str:
    """Normalize common GeoJSON/record CRS declarations without guessing."""

    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            value = properties.get("name") or properties.get("href")
        else:
            value = value.get("name") or value.get("href")
    text = str(value or "").strip()
    return text or str(fallback or "").strip()


_NORMALIZED_CRS = "EPSG:4326"


def _validated_wgs84_geometry(
    geometry: Mapping[str, Any],
    *,
    transform_ref: str,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """Validate a normalized geometry before granting spatial capability."""

    try:
        from shapely import make_valid
        from shapely.geometry import mapping as shapely_mapping, shape

        candidate = shape(dict(geometry))
        if candidate.is_empty:
            return None, (transform_ref, "empty_geometry")
        if not candidate.is_valid:
            source_kind = _kind(dict(geometry))
            repaired = make_valid(candidate)
            repaired_kind = _kind(dict(shapely_mapping(repaired)))
            if (
                repaired.is_empty
                or not repaired.is_valid
                or repaired_kind not in {"point", "line", "polygon"}
                or repaired_kind != source_kind
            ):
                return None, (transform_ref, "invalid_geometry")
            candidate = repaired
            transform_ref = (
                f"{transform_ref}|topology_repair:make_valid:"
                f"{source_kind}->{repaired_kind}"
            )
        bounds = tuple(float(value) for value in candidate.bounds)
        if len(bounds) == 4 and (
            not all(math.isfinite(value) for value in bounds)
            or bounds[0] < -180.0
            or bounds[2] > 180.0
            or bounds[1] < -90.0
            or bounds[3] > 90.0
        ):
            return None, (transform_ref, "wgs84_bounds_invalid")
        return dict(shapely_mapping(candidate)), (transform_ref,)
    except Exception as exc:
        return None, (transform_ref, f"geometry_validation_failed:{type(exc).__name__}")


def _normalize_geometry(
    geometry: Mapping[str, Any] | None,
    source_crs: str,
) -> tuple[dict[str, Any] | None, str, tuple[str, ...]]:
    """Return a WGS84 view plus an explicit, replayable transform record.

    Native geometry is never overwritten.  If a CRS cannot be interpreted,
    the normalized view remains ``None`` so downstream capability checks can
    fail closed instead of silently treating projected coordinates as lon/lat.
    """

    if not isinstance(geometry, Mapping):
        return None, "", ("missing_geometry",)
    source = str(source_crs or "").strip()
    source_fold = source.casefold()
    if source_fold in {"epsg:4326", "4326", "crs84", "urn:ogc:def:crs:ogc:1.3:crs84"}:
        normalized, trace = _validated_wgs84_geometry(
            geometry,
            transform_ref="identity",
        )
        return normalized, _NORMALIZED_CRS, trace
    if not source:
        return None, "", ("source_crs_missing",)
    try:
        from shapely.geometry import mapping as shapely_mapping, shape
        from shapely.ops import transform
        from pyproj import Transformer

        transformer = Transformer.from_crs(source, _NORMALIZED_CRS, always_xy=True)

        def apply(x: Any, y: Any, z: Any = None) -> Any:
            if z is None:
                return transformer.transform(x, y)
            tx, ty, tz = transformer.transform(x, y, z)
            return tx, ty, tz

        normalized = transform(apply, shape(dict(geometry)))
        normalized_geometry, trace = _validated_wgs84_geometry(
            dict(shapely_mapping(normalized)),
            transform_ref=f"{source}->{_NORMALIZED_CRS}",
        )
        return normalized_geometry, _NORMALIZED_CRS, trace
    except Exception as exc:
        return None, "", (
            f"{source}->{_NORMALIZED_CRS}:failed:{type(exc).__name__}",
        )


def _expand_geometry_records(records: Iterable[Any]) -> list[Any]:
    """Expand one logical record carrying several geometry fields.

    GIS exports frequently keep a point, footprint and service area on the
    same row (or expose them under ``geometries``/``geometry_fields``).  DATA
    keeps each representation addressable while preserving the shared
    ``entity_ref``/attributes.  Ordinary Feature/record inputs are returned
    unchanged, so this remains a lossless ingestion convenience rather than a
    schema requirement.
    """

    expanded: list[Any] = []
    for record in records:
        if not isinstance(record, Mapping):
            expanded.append(record)
            continue
        payload = dict(record)
        geometry_values: dict[str, Any] = {}
        properties = payload.get("properties")
        for key in ("geometries", "geometry_fields"):
            candidate = payload.get(key)
            if isinstance(candidate, Mapping):
                geometry_values.update({str(name): value for name, value in candidate.items()})
            property_candidate = (
                properties.get(key) if isinstance(properties, Mapping) else None
            )
            if isinstance(property_candidate, Mapping):
                geometry_values.update(
                    {str(name): value for name, value in property_candidate.items()}
                )
        for key, value in payload.items():
            if key.endswith("_geometry") and isinstance(value, Mapping):
                geometry_values.setdefault(key[:-9] or key, value)
        if isinstance(properties, Mapping):
            for key, value in properties.items():
                if key.endswith("_geometry") and isinstance(value, Mapping):
                    geometry_values.setdefault(key[:-9] or key, value)
        if not geometry_values:
            expanded.append(record)
            continue
        if isinstance(payload.get("geometry"), Mapping):
            geometry_values = {"geometry": payload["geometry"], **geometry_values}
        base_id = ""
        if isinstance(properties, Mapping):
            base_id = _text(properties.get("source_feature_ref") or properties.get("source_feature_id") or properties.get("id"))
        base_id = base_id or _text(payload.get("source_feature_ref") or payload.get("source_feature_id") or payload.get("id"))
        # A row carrying several geometries describes one logical physical
        # object, even though DATA exposes one source feature per geometry
        # representation.  Preserve that identity explicitly so KG can join
        # a point, footprint, service area, etc. without relying on centroid
        # coincidence or a particular layer name.  When the source omitted an
        # id, derive a stable row key from the non-geometry payload only.
        logical_entity_ref = ""
        for source in (properties if isinstance(properties, Mapping) else {}, payload):
            for key in ("entity_ref", "physical_entity_ref"):
                if not _is_empty(source.get(key)):
                    logical_entity_ref = str(source[key])
                    break
            if logical_entity_ref:
                break
        logical_entity_ref = logical_entity_ref or base_id
        if not logical_entity_ref:
            logical_entity_ref = f"record:{_short_digest({
                str(key): value
                for key, value in payload.items()
                if key not in {"geometry", "geometries", "geometry_fields"}
                and not str(key).endswith("_geometry")
            })}"
        part_ref = ""
        for source in (properties if isinstance(properties, Mapping) else {}, payload):
            for key in ("entity_part_ref", "part_ref", "physical_part_ref"):
                if not _is_empty(source.get(key)):
                    part_ref = str(source[key])
                    break
            if part_ref:
                break
        logical_part_ref = part_ref or logical_entity_ref
        geometry_crs_values: dict[str, Any] = {}
        for source in (payload, properties if isinstance(properties, Mapping) else {}):
            declared_crs = source.get("geometry_crs")
            if isinstance(declared_crs, Mapping):
                geometry_crs_values.update(
                    {str(name): value for name, value in declared_crs.items()}
                )
        for field_name, geometry_value in geometry_values.items():
            geometry = geometry_value
            field_crs = geometry_crs_values.get(field_name)
            if (
                isinstance(geometry_value, Mapping)
                and isinstance(geometry_value.get("geometry"), Mapping)
            ):
                geometry = geometry_value["geometry"]
                field_crs = geometry_value.get("crs") or field_crs
            field_crs = (
                field_crs
                or payload.get(f"{field_name}_crs")
                or (
                    properties.get(f"{field_name}_crs")
                    if isinstance(properties, Mapping)
                    else None
                )
            )
            clone = dict(payload)
            clone.pop("geometries", None)
            clone.pop("geometry_fields", None)
            for key in tuple(clone):
                if key.endswith("_geometry"):
                    clone.pop(key, None)
            clone["geometry"] = geometry
            clone["geometry_field"] = field_name
            if field_crs:
                clone["source_crs"] = field_crs
            if logical_entity_ref:
                clone.setdefault("entity_ref", logical_entity_ref)
                clone["__data_logical_entity_ref"] = logical_entity_ref
            if logical_part_ref:
                clone.setdefault("entity_part_ref", logical_part_ref)
                clone["__data_logical_part_ref"] = logical_part_ref
            source_ref = f"{base_id or logical_entity_ref}:{field_name}"
            clone["source_feature_ref"] = source_ref
            if isinstance(properties, Mapping):
                clone["properties"] = {
                    **dict(properties),
                    "source_feature_ref": source_ref,
                    "entity_ref": logical_entity_ref,
                    "entity_part_ref": logical_part_ref,
                }
            expanded.append(clone)
    return expanded


def _topology_repair_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["approval_ref", "method"],
        "properties": {
            "approval_ref": {"type": "string", "minLength": 1},
            "method": {
                "type": "string",
                "enum": ["make_valid", "node_and_polygonize"],
            },
        },
        "additionalProperties": False,
        "requires_approved_operation": True,
    }


def _operation_specs(
    geometry_kind: str,
    *,
    spatially_executable: bool,
    topology_repairable: bool = False,
) -> list[tuple[str, dict[str, Any]]]:
    """Declare only deterministic operations supported by this resource.

    The schema is part of the DATA capability contract.  SELECT/EXECUTE can
    therefore reject an underspecified operation before loading geometry.
    """

    specs: list[tuple[str, dict[str, Any]]] = [
        (
            "read",
            {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
                "method": "load_source_resource",
            },
        )
    ]
    if not spatially_executable:
        if topology_repairable and geometry_kind in {"line", "polygon"}:
            specs.append(("topology_repair", _topology_repair_schema()))
        return specs

    other_resource = {
        "type": "string",
        "minLength": 1,
        "description": "DATA resource_ref in the same frozen context",
    }
    specs.extend(
        (
            (
                "intersect",
                {
                    "type": "object",
                    "required": ["other_resource_ref"],
                    "properties": {"other_resource_ref": other_resource},
                    "additionalProperties": False,
                    "method": "deterministic_geometry_intersection",
                },
            ),
            (
                "within",
                {
                    "type": "object",
                    "required": ["container_resource_ref"],
                    "properties": {"container_resource_ref": other_resource},
                    "additionalProperties": False,
                    "method": "deterministic_topological_predicate",
                },
            ),
            (
                "buffer",
                {
                    "type": "object",
                    "required": ["distance", "distance_unit"],
                    "properties": {
                        "distance": {"type": "number", "exclusiveMinimum": 0},
                        "distance_unit": {"type": "string", "enum": ["m"]},
                    },
                    "additionalProperties": False,
                    "method": "metric_crs_buffer",
                    "requires_distance": True,
                },
            ),
            (
                "difference",
                {
                    "type": "object",
                    "required": ["subtract_resource_ref"],
                    "properties": {"subtract_resource_ref": other_resource},
                    "additionalProperties": False,
                    "method": "deterministic_geometry_difference",
                },
            ),
            (
                "representation_derivation",
                {
                    "type": "object",
                    "required": ["approval_ref"],
                    "properties": {
                        "approval_ref": {"type": "string", "minLength": 1}
                    },
                    "additionalProperties": False,
                    "method": "approved_source_geometry_derivation",
                    "output_geometry_kind": geometry_kind,
                    "requires_approved_operation": True,
                },
            ),
            (
                "snap",
                {
                    "type": "object",
                    "required": ["target_resource_ref", "tolerance", "tolerance_unit"],
                    "properties": {
                        "target_resource_ref": other_resource,
                        "tolerance": {"type": "number", "exclusiveMinimum": 0},
                        "tolerance_unit": {"type": "string", "enum": ["m"]},
                    },
                    "additionalProperties": False,
                    "method": "deterministic_snap",
                },
            ),
        )
    )

    if geometry_kind in {"line", "polygon"}:
        members = {
            "type": "array",
            "items": other_resource,
            "minItems": 1,
            "uniqueItems": True,
        }
        specs.extend(
            (
                (
                    "union",
                    {
                        "type": "object",
                        "required": ["operand_resource_refs"],
                        "properties": {"operand_resource_refs": members},
                        "additionalProperties": False,
                        "method": "deterministic_unary_union",
                    },
                ),
                (
                    "merge",
                    {
                        "type": "object",
                        "required": ["member_resource_refs", "method"],
                        "properties": {
                            "member_resource_refs": members,
                            "method": {
                                "type": "string",
                                "enum": ["topology_preserving_merge"],
                            },
                        },
                        "additionalProperties": False,
                    },
                ),
                (
                    "split",
                    {
                        "type": "object",
                        "required": ["splitter"],
                        "properties": {
                            "splitter": {
                                "type": "object",
                                "required": ["resource_ref"],
                                "properties": {"resource_ref": other_resource},
                                "additionalProperties": False,
                            }
                        },
                        "additionalProperties": False,
                        "method": "deterministic_geometry_split",
                    },
                ),
                (
                    "topology_repair",
                    _topology_repair_schema(),
                ),
            )
        )

    if geometry_kind in {"point", "line"}:
        specs.append(
            (
                "network_connection",
                {
                    "type": "object",
                    "required": ["target_resource_ref", "method"],
                    "properties": {
                        "target_resource_ref": other_resource,
                        "method": {
                            "type": "string",
                            "enum": [
                                "connect_point_to_network"
                                if geometry_kind == "point"
                                else "connect_line_endpoints"
                            ],
                        },
                    },
                    "additionalProperties": False,
                },
            )
        )

    if geometry_kind in {"point", "polygon"}:
        specs.append(
            (
                "point_placement",
                {
                    "type": "object",
                    "required": ["approval_ref"],
                    "properties": {
                        "approval_ref": {"type": "string", "minLength": 1}
                    },
                    "additionalProperties": False,
                    "method": (
                        "identity" if geometry_kind == "point" else "representative_point"
                    ),
                    "output_geometry_kind": "point",
                    "requires_approved_operation": True,
                },
            )
        )
    return specs


class DataResourceCatalog:
    """Index source features and purpose-specific representations.

    This adapter accepts GeoJSON-like records and arbitrary mappings. It never
    requires BSM, DLBM or a configured layer name; those values remain raw
    attributes when present.
    """

    def __init__(self, snapshot: DataResourceCatalogSnapshot):
        self.snapshot = snapshot
        self._datasets = {
            item.dataset_ref: item
            for item in (snapshot.datasets or (snapshot.dataset,))
        }
        # A source feature id is only human-readable within its dataset.  Keep
        # the qualified index authoritative and retain a bare-ref multimap for
        # backwards-compatible, fail-closed lookup of unambiguous refs.
        self._features = {
            f"{item.dataset_ref}:{item.source_feature_ref}": item
            for item in snapshot.features
        }
        self._features_by_ref: dict[str, list[SourceFeature]] = {}
        for item in snapshot.features:
            self._features_by_ref.setdefault(str(item.source_feature_ref), []).append(item)
        self._features_by_resource = {
            f"resource:{item.dataset_ref}:{item.source_feature_ref}": item
            for item in snapshot.features
        }
        self._representations = {
            item.representation_ref: item for item in snapshot.representations
        }
        self._representations_by_feature_ref: dict[
            str, list[SpatialRepresentation]
        ] = {}
        self._representations_by_feature_key: dict[
            tuple[str, str], list[SpatialRepresentation]
        ] = {}
        self._representations_by_entity: dict[
            str, list[SpatialRepresentation]
        ] = {}
        for item in snapshot.representations:
            source_ref = str(item.source_feature_ref)
            dataset_ref = str(item.dataset_ref)
            entity_ref = str(item.entity_ref)
            self._representations_by_feature_ref.setdefault(
                source_ref, []
            ).append(item)
            self._representations_by_feature_key.setdefault(
                (dataset_ref, source_ref), []
            ).append(item)
            if entity_ref:
                self._representations_by_entity.setdefault(
                    entity_ref, []
                ).append(item)
        self._features_by_entity: dict[str, list[SourceFeature]] = {}
        for feature in snapshot.features:
            claims = dict(feature.normalized_claims or {})
            aliases = {
                source_local_cognition_ref(
                    feature.dataset_ref,
                    feature.source_feature_ref,
                    logical_record_ref=str(
                        claims.get("source_logical_entity_ref") or ""
                    ),
                ),
                _identity_ref(
                    feature.raw_attributes or {},
                    feature.source_feature_ref,
                    dataset_ref=feature.dataset_ref,
                ),
            }
            for entity_ref in aliases:
                if entity_ref:
                    self._features_by_entity.setdefault(
                        entity_ref, []
                    ).append(feature)
        self._capabilities = {
            item.capability_ref: item for item in snapshot.capabilities
        }
        self._capabilities_by_resource: dict[str, list[DataCapability]] = {}
        self._capabilities_by_resource_operation: dict[
            tuple[str, str], list[DataCapability]
        ] = {}
        for item in snapshot.capabilities:
            resource_ref = str(item.resource_ref)
            operation = str(item.operation)
            self._capabilities_by_resource.setdefault(resource_ref, []).append(item)
            self._capabilities_by_resource_operation.setdefault(
                (resource_ref, operation), []
            ).append(item)

    def merge(
        self,
        *catalogs: "DataResourceCatalog",
        snapshot_id: str = "",
    ) -> "DataResourceCatalog":
        """Return a deterministic union of DATA catalogs.

        The union is keyed by stable source/representation/capability refs;
        duplicate refs are retained once.  This is the bridge used when a
        legacy Bundle and user-supplied files/services coexist in one
        session.  No layer or attribute schema is imposed by the merge.
        """

        all_catalogs = (self, *catalogs)
        datasets: dict[str, SourceDataset] = {}
        features: dict[str, SourceFeature] = {}
        representations: dict[str, SpatialRepresentation] = {}
        capabilities: dict[str, DataCapability] = {}
        admission_decisions: dict[str, SourceAdmissionDecision] = {}
        resource_map: dict[str, str] = {}
        for catalog in all_catalogs:
            snap = getattr(catalog, "snapshot", None)
            if snap is None:
                continue
            for item in tuple(getattr(snap, "datasets", ()) or ()) + (getattr(snap, "dataset", None),):
                if item is not None:
                    datasets.setdefault(str(item.dataset_ref), item)
            # Feature ids are only guaranteed unique within their source
            # dataset.  Namespace collisions deterministically instead of
            # silently dropping a second provider's feature from a mixed
            # session.  The qualified key is internal only; the feature object
            # keeps its human-readable, dataset-scoped ref.
            ref_map: dict[tuple[str, str], str] = {}
            feature_digest_map: dict[tuple[str, str], str] = {}
            resource_digest_map: dict[str, str] = {}
            resource_dataset_map: dict[str, str] = {}
            for item in getattr(snap, "features", ()) or ():
                old_ref = str(item.source_feature_ref)
                qualified_ref = f"{item.dataset_ref}:{old_ref}"
                ref_map[(str(item.dataset_ref), old_ref)] = qualified_ref
                features.setdefault(qualified_ref, item)
                feature_digest_map[(str(item.dataset_ref), old_ref)] = str(
                    features[qualified_ref].source_feature_digest
                )
                old_resource = f"resource:{item.dataset_ref}:{old_ref}"
                resource_map[old_resource] = f"resource:{qualified_ref}"
                resource_digest_map[old_resource] = feature_digest_map[
                    (str(item.dataset_ref), old_ref)
                ]
                resource_dataset_map[old_resource] = str(item.dataset_ref)
            for item in getattr(snap, "representations", ()) or ():
                dataset_ref = str(item.dataset_ref or "")
                if not dataset_ref:
                    dataset_ref = resource_dataset_map.get(
                        str(item.resource_ref or ""),
                        "",
                    )
                source_ref = str(item.source_feature_ref)
                rep_ref = str(item.representation_ref)
                if dataset_ref and not str(item.dataset_ref or ""):
                    rep_ref = (
                        f"representation:{dataset_ref}:"
                        f"{rep_ref.removeprefix('representation:')}"
                    )
                if rep_ref in representations:
                    rep_ref = f"{dataset_ref}:{rep_ref}" if dataset_ref else f"{source_ref}:{rep_ref}"
                    suffix = 2
                    while rep_ref in representations:
                        rep_ref = f"{dataset_ref}:{item.representation_ref}~{suffix}"
                        suffix += 1
                if rep_ref not in representations:
                    representations[rep_ref] = SpatialRepresentation.model_validate({
                        **item.model_dump(mode="python"),
                        "representation_ref": rep_ref,
                        "dataset_ref": dataset_ref,
                        "source_feature_ref": source_ref,
                        "geometry_ref": item.geometry_ref,
                        "resource_ref": resource_map.get(str(item.resource_ref), item.resource_ref),
                        "content_digest": feature_digest_map.get(
                            (dataset_ref, source_ref), item.content_digest
                        ),
                    })
            for item in getattr(snap, "capabilities", ()) or ():
                resource_ref = resource_map.get(str(item.resource_ref), str(item.resource_ref))
                capability_ref = str(item.capability_ref)
                if resource_ref != str(item.resource_ref):
                    capability_ref = f"{resource_ref}:{item.operation}"
                capabilities.setdefault(capability_ref, DataCapability.model_validate({
                    **item.model_dump(mode="python"),
                    "capability_ref": capability_ref,
                    "resource_ref": resource_ref,
                    "content_digest": resource_digest_map.get(
                        str(item.resource_ref),
                        item.content_digest,
                    ),
                }))
            for item in getattr(snap, "admission_decisions", ()) or ():
                admission_decisions.setdefault(str(item.decision_ref), item)
        if not datasets:
            raise ValueError("cannot merge empty data catalogs")
        primary = next(iter(datasets.values()))
        merged_snapshot_id = str(
            snapshot_id or getattr(self.snapshot, "snapshot_id", "") or ""
        )
        # A representation is executable only inside the immutable catalog
        # snapshot that publishes it.  Child catalogs may have carried their
        # own snapshot ids (or no id when built from raw records); once they
        # are merged, bind every representation to the merged snapshot while
        # retaining source dataset/version/URI lineage on its feature.
        representations = {
            key: item.model_copy(
                update={"source_snapshot_ref": merged_snapshot_id}
            )
            for key, item in representations.items()
        }
        capabilities = {
            key: item.model_copy(
                update={"source_snapshot_ref": merged_snapshot_id}
            )
            for key, item in capabilities.items()
        }
        merged_snapshot = DataResourceCatalogSnapshot(
            snapshot_id=merged_snapshot_id,
            dataset=primary,
            datasets=tuple(datasets.values()),
            features=tuple(features.values()),
            representations=tuple(representations.values()),
            capabilities=tuple(capabilities.values()),
            admission_decisions=tuple(admission_decisions.values()),
        )
        return DataResourceCatalog(merged_snapshot)

    @classmethod
    def from_records(
        cls,
        records: Iterable[Any],
        *,
        dataset_ref: str,
        name: str = "",
        version: str = "",
        crs: str = "",
        source_uris: Iterable[str] = (),
        layer_ref: str = "",
        snapshot_id: str = "",
        admission_decisions: Iterable[SourceAdmissionDecision | Mapping[str, Any]] = (),
    ) -> "DataResourceCatalog":
        source_uri_values = tuple(str(item) for item in source_uris if str(item))
        collection_crs = ""
        if isinstance(records, Mapping) and isinstance(records.get("features"), list):
            # RFC 7946 GeoJSON without a legacy ``crs`` member is WGS84.
            # Generic record mappings do not receive this assumption.
            collection_crs = _crs_text(records.get("crs"), "EPSG:4326")
            records = records["features"]
        elif isinstance(records, Mapping) and (
            "geometry" in records or "properties" in records or records.get("type") == "Feature"
        ):
            # Accept one GeoJSON Feature as naturally as a FeatureCollection;
            # iterating a mapping's keys would otherwise discard its geometry.
            collection_crs = _crs_text(
                records.get("crs"),
                "EPSG:4326" if records.get("type") == "Feature" else "",
            )
            records = [records]
        features: list[SourceFeature] = []
        representations: list[SpatialRepresentation] = []
        capabilities: list[DataCapability] = []
        seen_feature_refs: set[tuple[str, str]] = set()
        dataset_records: dict[str, list[tuple[str, Any]]] = {}
        dataset_crs_values: dict[str, set[str]] = {}
        for index, record in enumerate(_expand_geometry_records(records)):
            if isinstance(record, Mapping):
                payload = dict(record)
                geometry = payload.get("geometry")
                properties = payload.get("properties")
                if isinstance(properties, Mapping):
                    attributes = dict(properties)
                    attributes.update({key: value for key, value in payload.items() if key not in {"type", "geometry", "properties"}})
                else:
                    attributes = {key: value for key, value in payload.items() if key not in {"type", "geometry"}}
            else:
                geometry = getattr(record, "geometry", None)
                attributes = {}
                if hasattr(record, "model_dump"):
                    values = record.model_dump(mode="python")
                    geometry = values.pop("geometry", geometry)
                    attributes = values
                elif hasattr(record, "__dict__"):
                    attributes = dict(vars(record))
                    geometry = attributes.pop("geometry", geometry)
            if not isinstance(geometry, Mapping) and geometry is not None:
                try:
                    from shapely.geometry import mapping as shapely_mapping

                    geometry = shapely_mapping(geometry)
                except Exception:
                    geometry = None
            if not isinstance(geometry, Mapping):
                geometry = None
            attributes = dict(attributes or {})
            data_logical_entity_ref = str(
                attributes.pop("__data_logical_entity_ref", "") or ""
            )
            data_logical_part_ref = str(
                attributes.pop("__data_logical_part_ref", "") or ""
            )
            feature_dataset_ref = str(
                attributes.get("source_dataset_ref")
                or attributes.get("dataset_ref")
                or attributes.get("dataset")
                or dataset_ref
            )
            declared_kind = str(
                attributes.get("geometry_kind")
                or attributes.get("resource_kind")
                or ""
            ).casefold()
            source_feature_ref = str(
                attributes.get("source_feature_ref")
                or attributes.get("source_feature_id")
                or attributes.get("id")
                or f"{feature_dataset_ref}:feature:{index}"
            )
            feature_scope_key = (feature_dataset_ref, source_feature_ref)
            if feature_scope_key in seen_feature_refs:
                source_feature_ref = f"{source_feature_ref}~{index}"
                feature_scope_key = (feature_dataset_ref, source_feature_ref)
            seen_feature_refs.add(feature_scope_key)
            entity_ref = source_local_cognition_ref(
                feature_dataset_ref,
                source_feature_ref,
                logical_record_ref=data_logical_entity_ref,
            )
            feature_layer = str(
                attributes.get("layer_ref")
                or attributes.get("layer")
                or attributes.get("__source_layer")
                or layer_ref
                or ""
            )
            feature_crs = _crs_text(
                attributes.get("source_crs")
                or attributes.get("coordinate_reference_system")
                or attributes.get("crs")
                or attributes.get("__source_crs")
                or collection_crs,
                crs,
            )
            normalized_geometry, normalized_crs, crs_transform = _normalize_geometry(
                geometry,
                feature_crs,
            )
            normalization_diagnostics = []
            if geometry is not None and normalized_geometry is None:
                normalization_diagnostics.append("normalized_geometry_unavailable")
            normalization_diagnostics.extend(
                f"crs_transform:{item}"
                for item in crs_transform
                if item != "identity"
            )
            is_raster = geometry is None and declared_kind == "raster"
            feature = SourceFeature(
                source_feature_ref=source_feature_ref,
                dataset_ref=feature_dataset_ref,
                layer_ref=feature_layer,
                geometry=dict(geometry) if geometry is not None else None,
                normalized_geometry=normalized_geometry,
                geometry_kind=(
                    _kind(geometry)
                    if geometry is not None
                    else (declared_kind if declared_kind in {"point", "line", "polygon", "multipatch", "raster"} else "unknown")
                ),
                source_crs=feature_crs,
                normalized_crs=normalized_crs,
                crs_transform=crs_transform,
                raw_attributes=attributes,
                normalized_claims={
                    **(
                        {
                            "identity_scope": "source_record",
                            "source_logical_entity_ref": data_logical_entity_ref,
                        }
                        if data_logical_entity_ref
                        else {}
                    ),
                    **(
                        {"source_logical_part_ref": data_logical_part_ref}
                        if data_logical_part_ref
                        else {}
                    ),
                },
                validity_status=(
                    "valid"
                    if (geometry is not None and normalized_geometry is not None)
                    or (is_raster and bool(feature_crs))
                    else ("unknown" if geometry is not None else "missing")
                ),
                diagnostics=(
                    normalization_diagnostics
                    if geometry is not None
                    else (
                        []
                        if is_raster and feature_crs
                        else (["source_crs_missing"] if is_raster else ["missing_geometry"])
                    )
                ),
            )
            features.append(feature)
            dataset_records.setdefault(feature_dataset_ref, []).append((feature_layer, attributes))
            dataset_crs_values.setdefault(feature_dataset_ref, set()).add(feature_crs)
            resource_ref = f"resource:{feature_dataset_ref}:{source_feature_ref}"
            representation_ref = (
                f"representation:{feature_dataset_ref}:{source_feature_ref}:source_geometry"
            )
            representations.append(
                SpatialRepresentation(
                    representation_ref=representation_ref,
                    entity_ref=entity_ref,
                    dataset_ref=feature_dataset_ref,
                    source_feature_ref=source_feature_ref,
                    purpose="source_geometry",
                    geometry_kind=feature.geometry_kind,
                    geometry_ref=source_feature_ref,
                    resource_ref=resource_ref,
                    crs=(feature_crs if is_raster else normalized_crs),
                    source_crs=feature_crs,
                    normalized_crs=normalized_crs,
                    crs_transform=crs_transform,
                    source_snapshot_ref=snapshot_id,
                    content_digest=feature.source_feature_digest,
                    status=(
                        "available"
                        if normalized_geometry is not None or (is_raster and feature_crs)
                        else "unresolved"
                    ),
                )
            )
            operation_specs = _operation_specs(
                feature.geometry_kind,
                spatially_executable=(
                    feature.geometry_kind in {"point", "line", "polygon"}
                    and normalized_geometry is not None
                ),
                topology_repairable=(
                    "invalid_geometry" in crs_transform
                ),
            )
            for operation, parameters_schema in operation_specs:
                capability_ref = f"capability:{resource_ref}:{operation}"
                capabilities.append(
                    DataCapability(
                        capability_ref=capability_ref,
                        resource_ref=resource_ref,
                        operation=operation,
                        geometry_kind=feature.geometry_kind,
                        crs=(
                            normalized_crs
                            if normalized_geometry is not None
                            else feature_crs
                        ),
                        source_snapshot_ref=snapshot_id,
                        content_digest=feature.source_feature_digest,
                        parameters_schema=parameters_schema,
                    )
                )
        datasets: list[SourceDataset] = []
        for ref, rows in sorted(dataset_records.items()):
            crs_values = sorted(dataset_crs_values.get(ref, set()))
            dataset_crs = crs_values[0] if len(crs_values) == 1 else "mixed"
            row_uris = {
                str(attrs.get("source_uri") or attrs.get("source_url") or "").strip()
                for _, attrs in rows
            }
            datasets.append(
                SourceDataset(
                    dataset_ref=ref,
                    name=name if ref == dataset_ref else ref,
                    version=version,
                    crs=dataset_crs,
                    source_uris=tuple(sorted({item for item in (*source_uri_values, *row_uris) if item})),
                    layer_refs=tuple(sorted({layer for layer, _ in rows if layer})),
                    feature_count=len(rows),
                )
            )
        if not datasets:
            datasets.append(
                SourceDataset(
                    dataset_ref=dataset_ref,
                    name=name,
                    version=version,
                    crs=crs,
                    source_uris=source_uri_values,
                )
            )
        dataset = next((item for item in datasets if item.dataset_ref == dataset_ref), datasets[0])
        resolved_snapshot_id = (
            str(snapshot_id).strip()
            or f"data-snapshot:{dataset_ref}:{_short_digest([item.source_feature_digest for item in features])}"
        )
        representations = [
            item.model_copy(update={"source_snapshot_ref": resolved_snapshot_id})
            for item in representations
        ]
        capabilities = [
            item.model_copy(update={"source_snapshot_ref": resolved_snapshot_id})
            for item in capabilities
        ]
        snapshot = DataResourceCatalogSnapshot(
            snapshot_id=resolved_snapshot_id,
            dataset=dataset,
            datasets=tuple(datasets),
            features=tuple(features),
            representations=tuple(representations),
            capabilities=tuple(capabilities),
            admission_decisions=tuple(
                item
                if isinstance(item, SourceAdmissionDecision)
                else SourceAdmissionDecision.model_validate(item)
                for item in admission_decisions
            ),
        )
        return cls(snapshot)

    def get_feature(
        self, source_feature_ref: str, *, dataset_ref: str = ""
    ) -> SourceFeature | None:
        """Get a feature by qualified ref, or by an unambiguous bare ref."""

        ref = str(source_feature_ref)
        if dataset_ref:
            return self._features.get(f"{dataset_ref}:{ref}")
        if ref in self._features:
            return self._features[ref]
        matches = self._features_by_ref.get(ref, ())
        return matches[0] if len(matches) == 1 else None

    def get_representation(self, representation_ref: str) -> SpatialRepresentation | None:
        return self._representations.get(str(representation_ref))

    def representations_for_feature(
        self, source_feature_ref: str, *, dataset_ref: str = ""
    ) -> list[SpatialRepresentation]:
        """Return all purpose-specific views for one source feature."""

        ref = str(source_feature_ref)
        if dataset_ref:
            return list(
                self._representations_by_feature_key.get(
                    (str(dataset_ref), ref), ()
                )
            )
        return list(self._representations_by_feature_ref.get(ref, ()))

    def representations_for_entity(self, entity_ref: str) -> list[SpatialRepresentation]:
        """Return all source/derived representations linked to an entity."""

        ref = str(entity_ref)
        return list(self._representations_by_entity.get(ref, ()))

    def features_for_entity(self, entity_ref: str) -> list[SourceFeature]:
        """Return features by the shared non-authoritative DATA/KG identity."""

        ref = str(entity_ref)
        return list(self._features_by_entity.get(ref, ()))

    def resolve_geometry(
        self,
        resource_ref: str = "",
        geometry_ref: str = "",
        representation_ref: str = "",
        *,
        normalized: bool = True,
    ) -> dict[str, Any] | None:
        """Resolve executable geometry through a DATA-owned reference.

        GROUND/SELECT may carry these refs, but they never need to know the
        original Bundle collection or field names.  A missing geometry is
        explicit and remains non-executable until another representation is
        selected.
        """

        feature = None
        feature_dataset_ref = ""
        if representation_ref:
            representation = self._representations.get(str(representation_ref))
            if representation is not None:
                resource_ref = str(representation.resource_ref or resource_ref)
                geometry_ref = str(representation.geometry_ref or geometry_ref)
                feature_dataset_ref = str(representation.dataset_ref or "")
        if resource_ref:
            feature = self._features_by_resource.get(str(resource_ref))
        if feature is None and geometry_ref:
            feature = self.get_feature(geometry_ref, dataset_ref=feature_dataset_ref)
        geometry = (
            getattr(feature, "normalized_geometry", None)
            if normalized
            else getattr(feature, "geometry", None)
        )
        return dict(geometry) if isinstance(geometry, dict) else None

    def capabilities_for(self, resource_ref: str, operation: str = "") -> list[DataCapability]:
        normalized_resource_ref = str(resource_ref)
        if operation:
            return list(
                self._capabilities_by_resource_operation.get(
                    (normalized_resource_ref, str(operation)), ()
                )
            )
        return list(
            self._capabilities_by_resource.get(normalized_resource_ref, ())
        )

    def table_rows(self, *, limit: int = 32) -> list[dict[str, str]]:
        """Return a flat Context/LLM-safe feature/table inventory projection."""

        return [
            {
                "source_feature_ref": item.source_feature_ref,
                "layer_ref": item.layer_ref,
                "geometry_kind": item.geometry_kind,
                "source_crs": item.source_crs,
                "normalized_crs": item.normalized_crs,
                "normalization_status": (
                    "available" if item.normalized_geometry is not None else "unresolved"
                ),
                "feature_digest": item.source_feature_digest,
                "attribute_keys": ",".join(sorted(item.raw_attributes)),
                "attribute_preview": json.dumps(
                    item.raw_attributes,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )[:800],
                "validity_status": item.validity_status,
            }
            for item in tuple(self._features.values())[: max(1, int(limit))]
        ]


__all__ = ["DataResourceCatalog"]
