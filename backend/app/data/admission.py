"""Central current-world admission checks for generic DATA catalogs.

Source fields, filenames and layer names are observations, not authority for
whether a resource represents the current world.  Every feature consumed by
KG/EVIDENCE must therefore be covered by an immutable
``SourceAdmissionDecision``.  Planned, reference, control and unclassified
resources remain in the admission ledger but never enter current-world
projection or retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections import Counter
from collections import OrderedDict
from threading import RLock
from typing import Any

from app.contracts.data.source_contracts import (
    DataCapability,
    DataResourceCatalogSnapshot,
    SourceAdmissionDecision,
    SourceDataset,
    SourceFeature,
    SpatialRepresentation,
)


CURRENT_WORLD_ADMISSION_POLICY_VERSION = "current-world-admission-v1"


@dataclass(frozen=True)
class FeatureAdmissionVerdict:
    admitted: bool
    input_role: str
    status: str
    reason: str
    decision_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogAdmissionIndex:
    feature_keys: frozenset[tuple[str, str]]
    resource_refs: frozenset[str]
    representation_refs: frozenset[str]
    representation_resource_refs: frozenset[str]


_ADMISSION_INDEX_CACHE: OrderedDict[str, CatalogAdmissionIndex] = OrderedDict()
_ADMISSION_INDEX_CACHE_LOCK = RLock()
_ADMISSION_INDEX_CACHE_LIMIT = 32
_VALIDATED_CATALOG_CACHE: OrderedDict[str, bool] = OrderedDict()
_VALIDATED_CATALOG_CACHE_LIMIT = 64


@dataclass(frozen=True)
class CognitionReadinessIssue:
    """One blocking DATA defect that prevents a catalog entering KG.

    This is deliberately expressed in terms of generic resource and geometry
    contracts.  It does not infer business semantics from a layer name or a
    source attribute.  Non-spatial Markdown/table resources remain valid
    cognition input; only a resource claiming spatial content has to satisfy
    the executable spatial contract.
    """

    reason: str
    source_feature_ref: str = ""
    source_digest: str = ""
    missing_fields: tuple[str, ...] = ()
    earliest_resolution_stage: str = "data"


@dataclass(frozen=True)
class LocalAdmissionDecision:
    """Declaration-only result for the canonical local DATA input matrix."""

    accepted: bool
    state: str
    reason_code: str = ""
    reason: str = ""


def _remember_validated_catalog(snapshot: DataResourceCatalogSnapshot) -> None:
    """Record a snapshot produced by the central admission filter.

    ``current_world_snapshot`` has already evaluated every feature and rebuilt
    the dependent representation/capability sets.  Remembering that exact
    immutable digest avoids immediately repeating the same fail-closed scan
    when Context Runtime and WM perform their read-side guard checks.
    """

    cache_key = _text(snapshot.digest)
    if not cache_key:
        return
    with _ADMISSION_INDEX_CACHE_LOCK:
        _VALIDATED_CATALOG_CACHE[cache_key] = True
        _VALIDATED_CATALOG_CACHE.move_to_end(cache_key)
        while len(_VALIDATED_CATALOG_CACHE) > _VALIDATED_CATALOG_CACHE_LIMIT:
            _VALIDATED_CATALOG_CACHE.popitem(last=False)


def _admission_decision_index(
    snapshot: DataResourceCatalogSnapshot,
) -> dict[str, tuple[SourceAdmissionDecision, ...]]:
    """Index decisions by every source reference that can score as specific."""

    grouped: dict[str, list[SourceAdmissionDecision]] = {}
    for decision in snapshot.admission_decisions:
        grouped.setdefault(_text(decision.source_ref), []).append(decision)
    return {key: tuple(value) for key, value in grouped.items()}


def _feature_decision_candidates(
    feature: SourceFeature,
    *,
    bare_ref_unique: bool,
    decision_index: dict[str, tuple[SourceAdmissionDecision, ...]],
) -> tuple[SourceAdmissionDecision, ...]:
    """Return only decisions that can receive a positive specificity score."""

    keys = [feature_resource_ref(feature), _text(feature.dataset_ref)]
    if bare_ref_unique:
        keys.append(_text(feature.source_feature_ref))
    raw_dataset_ref = _text(
        (feature.raw_attributes or {}).get("source_dataset_ref")
    )
    if raw_dataset_ref:
        keys.append(raw_dataset_ref)
    seen: set[str] = set()
    result: list[SourceAdmissionDecision] = []
    for key in keys:
        for decision in decision_index.get(key, ()):
            if decision.decision_ref in seen:
                continue
            seen.add(decision.decision_ref)
            result.append(decision)
    return tuple(result)


def plan_catalog_invalidation(
    previous: DataResourceCatalogSnapshot | None,
    current: DataResourceCatalogSnapshot,
) -> dict[str, tuple[str, ...]]:
    """Return exact DATA-owned refs invalidated by a catalog revision.

    Invalidation is keyed by qualified source identity and content digest,
    never by list position.  Downstream caches can therefore invalidate only
    changed features and their dependent representations/capabilities while
    retaining unaffected source products.
    """

    if previous is None:
        return {
            "datasets": tuple(item.dataset_ref for item in current.datasets),
            "features": tuple(
                f"{item.dataset_ref}:{item.source_feature_ref}"
                for item in current.features
            ),
            "representations": tuple(item.representation_ref for item in current.representations),
            "capabilities": tuple(item.capability_ref for item in current.capabilities),
        }

    previous_features = {
        (item.dataset_ref, item.source_feature_ref): item.source_feature_digest
        for item in previous.features
    }
    current_features = {
        (item.dataset_ref, item.source_feature_ref): item.source_feature_digest
        for item in current.features
    }
    changed_feature_keys = {
        key for key in set(previous_features) | set(current_features)
        if previous_features.get(key) != current_features.get(key)
    }
    changed_feature_refs = {
        f"{dataset}:{feature}" for dataset, feature in changed_feature_keys
    }
    def _product_digest(item: Any) -> str:
        return hashlib.sha256(json.dumps(
            item.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    previous_representation_digests = {
        item.representation_ref: _product_digest(item)
        for item in previous.representations
    }
    current_representation_digests = {
        item.representation_ref: _product_digest(item)
        for item in current.representations
    }
    changed_representation_refs = set(
        ref
        for ref in set(previous_representation_digests) | set(current_representation_digests)
        if previous_representation_digests.get(ref) != current_representation_digests.get(ref)
    )
    changed_representation_refs.update(
        item.representation_ref
        for item in current.representations
        if (item.dataset_ref, item.source_feature_ref) in changed_feature_keys
    )
    previous_capability_digests = {
        item.capability_ref: _product_digest(item)
        for item in previous.capabilities
    }
    current_capability_digests = {
        item.capability_ref: _product_digest(item)
        for item in current.capabilities
    }
    changed_capability_refs = {
        ref
        for ref in set(previous_capability_digests) | set(current_capability_digests)
        if previous_capability_digests.get(ref) != current_capability_digests.get(ref)
    }
    changed_capability_refs.update(
        item.capability_ref
        for item in current.capabilities
        if item.resource_ref.removeprefix("resource:") in changed_feature_refs
    )
    previous_dataset_digests = {item.dataset_ref: item.digest for item in previous.datasets}
    current_dataset_digests = {item.dataset_ref: item.digest for item in current.datasets}
    return {
        "datasets": tuple(sorted(
            ref
            for ref in set(previous_dataset_digests) | set(current_dataset_digests)
            if previous_dataset_digests.get(ref) != current_dataset_digests.get(ref)
        )),
        "features": tuple(sorted(changed_feature_refs)),
        "representations": tuple(sorted(changed_representation_refs)),
        "capabilities": tuple(sorted(changed_capability_refs)),
    }


def check_local_admission_boundary(
    *,
    declared_media_type: str,
    adapter_hint: str,
    declared_crs: str,
    declared_encoding: str,
    expected_role: str,
) -> LocalAdmissionDecision:
    """Check the explicit local capability matrix without guessing metadata.

    Local vector containers and tables are accepted after deterministic
    decoding. Services and remote resources remain outside this write
    boundary.
    """

    media = _text(declared_media_type).casefold()
    if _text(expected_role).casefold() != "current_evidence":
        return LocalAdmissionDecision(False, "POLICY_REJECTED", "non_current_role", "local DATA admits current_evidence only")
    if _text(declared_encoding).casefold().replace("-", "") not in {"utf8", "utf"}:
        return LocalAdmissionDecision(False, "ENCODING_UNRESOLVED", "encoding_unresolved", "local DATA requires UTF-8 input")
    adapter = _text(adapter_hint).casefold()
    crs = _text(declared_crs).casefold()
    if media in {
        "geojson", "application/geo+json", "application/x-esri-shapefile",
        "application/x-shapefile", "application/geopackage+sqlite3",
        "application/vnd.google-earth.kml+xml", "application/gml+xml",
    }:
        if adapter != "file_vector":
            return LocalAdmissionDecision(False, "UNSUPPORTED", "unsupported_adapter", "local vector input requires the file_vector adapter")
        if crs not in {"epsg:4326", "4326"}:
            return LocalAdmissionDecision(False, "CRS_UNRESOLVED", "crs_unresolved", "local vector input requires declared EPSG:4326")
        return LocalAdmissionDecision(True, "ADMITTED")
    if media in {
        "text/csv", "text/tab-separated-values", "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        if adapter != "table":
            return LocalAdmissionDecision(False, "UNSUPPORTED", "unsupported_adapter", "table input requires the table adapter")
        if crs not in {"", "none", "non-spatial", "non_spatial"}:
            return LocalAdmissionDecision(False, "CRS_UNRESOLVED", "non_spatial_crs_declared", "table input must declare no spatial CRS")
        return LocalAdmissionDecision(True, "ADMITTED")
    if media in {"text/markdown", "text/x-markdown", "markdown"}:
        if adapter != "document":
            return LocalAdmissionDecision(False, "UNSUPPORTED", "unsupported_adapter", "Markdown requires the document adapter")
        if crs not in {"", "none", "non-spatial", "non_spatial"}:
            return LocalAdmissionDecision(False, "CRS_UNRESOLVED", "non_spatial_crs_declared", "Markdown must declare no spatial CRS")
        return LocalAdmissionDecision(True, "ADMITTED")
    if media in {"image/tiff", "image/geotiff", "application/geotiff", "geotiff"}:
        if adapter not in {"local_raster", "raster"}:
            return LocalAdmissionDecision(False, "UNSUPPORTED", "unsupported_adapter", "GeoTIFF requires the local_raster adapter")
        if crs not in {"epsg:4326", "4326"}:
            return LocalAdmissionDecision(False, "CRS_UNRESOLVED", "crs_unresolved", "GeoTIFF requires declared EPSG:4326")
        return LocalAdmissionDecision(True, "ADMITTED")
    return LocalAdmissionDecision(False, "UNSUPPORTED", "unsupported_media", "media type is outside the declared local input registry")


def _text(value: Any) -> str:
    return str(value or "").strip()


def feature_key(feature: SourceFeature) -> tuple[str, str]:
    return _text(feature.dataset_ref), _text(feature.source_feature_ref)


def feature_resource_ref(feature: SourceFeature) -> str:
    dataset_ref, source_feature_ref = feature_key(feature)
    return f"resource:{dataset_ref}:{source_feature_ref}"


_NON_SPATIAL_RESOURCE_KINDS = frozenset({
    "table", "document", "text", "markdown", "report", "image",
})
_SPATIAL_GEOMETRY_KINDS = frozenset({
    "point", "line", "polygon", "multipatch", "collection", "raster", "opaque",
})


def _resource_kind(feature: SourceFeature) -> str:
    return _text((feature.raw_attributes or {}).get("resource_kind")).casefold()


def _is_non_spatial_resource(feature: SourceFeature) -> bool:
    return _resource_kind(feature) in _NON_SPATIAL_RESOURCE_KINDS


def _is_spatial_feature(feature: SourceFeature) -> bool:
    return not _is_non_spatial_resource(feature)


def _is_spatial_representation(representation: SpatialRepresentation) -> bool:
    return _text(representation.geometry_kind).casefold() in _SPATIAL_GEOMETRY_KINDS


def cognition_readiness_issues(
    snapshot: DataResourceCatalogSnapshot,
) -> tuple[CognitionReadinessIssue, ...]:
    """Return all generic DATA defects that make a KG projection unsafe.

    Admission is intentionally checked by ``assert_cognition_ready_catalog``;
    this function focuses on DATA readability, geometry normalization and
    representation lineage.  Keeping it reusable lets the DATA gate and KG
    adapters fail on the exact same spatial facts.
    """

    issues: list[CognitionReadinessIssue] = []
    expected_snapshot_ref = _text(snapshot.snapshot_id)
    spatial_features = {
        feature_key(feature): feature
        for feature in snapshot.features
        if _is_spatial_feature(feature)
    }
    for decision in snapshot.admission_decisions:
        if decision.status == "quarantined":
            issues.append(CognitionReadinessIssue(
                reason="source_input_role_unclassified",
                source_feature_ref=decision.source_ref,
                source_digest=decision.source_digest,
                missing_fields=("input_role",),
                earliest_resolution_stage="human",
            ))
        elif decision.status == "admitted" and decision.input_role != "current_evidence":
            issues.append(CognitionReadinessIssue(
                reason="source_admission_invariant_broken",
                source_feature_ref=decision.source_ref,
                source_digest=decision.source_digest,
                missing_fields=("current_evidence_admission",),
                earliest_resolution_stage="human",
            ))
    if not snapshot.features:
        issues.append(CognitionReadinessIssue(
            reason="source_feature_inventory_empty",
            source_digest=snapshot.digest,
            missing_fields=("source_features",),
        ))
    elif not spatial_features:
        issues.append(CognitionReadinessIssue(
            reason="spatial_feature_inventory_empty",
            source_digest=snapshot.digest,
            missing_fields=("spatial_source_features",),
        ))
    for feature in snapshot.features:
        source_ref = _text(feature.source_feature_ref)
        source_digest = _text(feature.source_feature_digest)
        attributes = feature.raw_attributes or {}
        if _text(attributes.get("parse_status")).casefold() == "failed":
            issues.append(CognitionReadinessIssue(
                reason="source_readability_failed",
                source_feature_ref=source_ref,
                source_digest=source_digest,
                missing_fields=("parsed_source",),
            ))
            continue
        if _is_non_spatial_resource(feature):
            kind = _resource_kind(feature)
            if kind in {"document", "text", "markdown", "report"} and (
                _text(attributes.get("content_format")).casefold() != "markdown"
            ):
                issues.append(CognitionReadinessIssue(
                    reason="non_gis_text_not_markdown",
                    source_feature_ref=source_ref,
                    source_digest=source_digest,
                    missing_fields=("content_format=markdown",),
                ))
            continue
        if feature.geometry_kind == "raster":
            if not _text(feature.source_crs):
                issues.append(CognitionReadinessIssue(
                    reason="raster_crs_missing",
                    source_feature_ref=source_ref,
                    source_digest=source_digest,
                    missing_fields=("source_crs",),
                ))
            continue
        if feature.geometry is None:
            issues.append(CognitionReadinessIssue(
                reason="source_geometry_missing",
                source_feature_ref=source_ref,
                source_digest=source_digest,
                missing_fields=("geometry",),
            ))
            continue
        if feature.normalized_geometry is None and feature.geometry_kind != "opaque":
            trace = "|".join(
                _text(item)
                for item in feature.crs_transform
                if _text(item) and _text(item) != "identity"
            )
            issues.append(CognitionReadinessIssue(
                reason="geometry_normalization_unavailable"
                + (":" + trace if trace else ""),
                source_feature_ref=source_ref,
                source_digest=source_digest,
                missing_fields=(
                    ("source_crs",)
                    if not _text(feature.source_crs)
                    else ("normalized_geometry",)
                ),
            ))

    for representation in snapshot.representations:
        key = (_text(representation.dataset_ref), _text(representation.source_feature_ref))
        spatial = _is_spatial_representation(representation) or key in spatial_features
        if not spatial:
            continue
        if (
            not _text(representation.source_snapshot_ref)
            or _text(representation.source_snapshot_ref) != expected_snapshot_ref
            or not _text(representation.content_digest)
        ):
            issues.append(CognitionReadinessIssue(
                reason="representation_lineage_incomplete",
                source_feature_ref=_text(representation.source_feature_ref),
                source_digest=_text(representation.content_digest),
                missing_fields=("source_snapshot_ref", "content_digest"),
            ))
        expected_status = (
            "read_only"
            if key in spatial_features and spatial_features[key].geometry_kind == "opaque"
            else "available"
        )
        if representation.status != expected_status:
            issues.append(CognitionReadinessIssue(
                reason="spatial_representation_unresolved",
                source_feature_ref=_text(representation.source_feature_ref),
                source_digest=_text(representation.content_digest),
                missing_fields=(f"{expected_status}_spatial_representation",),
            ))
    available_representation_keys = {
        (
            _text(representation.dataset_ref),
            _text(representation.source_feature_ref),
        )
        for representation in snapshot.representations
        if (
            representation.status == "available"
            or (
                representation.status == "read_only"
                and spatial_features.get(key) is not None
                and spatial_features[key].geometry_kind == "opaque"
            )
        )
        and _text(representation.source_snapshot_ref) == expected_snapshot_ref
        and _text(representation.content_digest)
    }
    capability_resources = {
        _text(capability.resource_ref)
        for capability in snapshot.capabilities
        if _text(capability.resource_ref)
    }
    for key, feature in spatial_features.items():
        if key not in available_representation_keys:
            issues.append(CognitionReadinessIssue(
                reason="spatial_representation_missing",
                source_feature_ref=_text(feature.source_feature_ref),
                source_digest=_text(feature.source_feature_digest),
                missing_fields=("available_spatial_representation",),
            ))
        if feature_resource_ref(feature) not in capability_resources:
            issues.append(CognitionReadinessIssue(
                reason="spatial_capability_missing",
                source_feature_ref=_text(feature.source_feature_ref),
                source_digest=_text(feature.source_feature_digest),
                missing_fields=("data_capability",),
            ))
    for capability in snapshot.capabilities:
        if (
            not _text(capability.source_snapshot_ref)
            or _text(capability.source_snapshot_ref) != expected_snapshot_ref
            or not _text(capability.content_digest)
        ):
            issues.append(CognitionReadinessIssue(
                reason="capability_lineage_incomplete",
                source_digest=_text(capability.content_digest),
                missing_fields=("source_snapshot_ref", "content_digest"),
            ))
    return tuple(issues)


def _decision_specificity(
    decision: SourceAdmissionDecision,
    feature: SourceFeature,
    *,
    bare_ref_unique: bool,
) -> int:
    source_ref = _text(decision.source_ref)
    dataset_ref, source_feature_ref = feature_key(feature)
    resource_ref = feature_resource_ref(feature)
    score = 0
    if source_ref == resource_ref or (
        bare_ref_unique and source_ref == source_feature_ref
    ):
        score = 4
    raw_dataset_ref = _text(
        (feature.raw_attributes or {}).get("source_dataset_ref")
    )
    if not score and (
        source_ref == dataset_ref
        or raw_dataset_ref and source_ref == raw_dataset_ref
    ):
        score = 3
    if not score:
        return 0
    declared_digests = {
        _text((feature.raw_attributes or {}).get(key))
        for key in ("source_digest", "content_digest")
        if _text((feature.raw_attributes or {}).get(key))
    }
    if _text(decision.source_digest) in declared_digests:
        score += 10
    return score


def feature_admission_verdict(
    snapshot: DataResourceCatalogSnapshot,
    feature: SourceFeature,
    *,
    _bare_ref_unique: bool | None = None,
    _decision_candidates: tuple[SourceAdmissionDecision, ...] | None = None,
) -> FeatureAdmissionVerdict:
    """Resolve one feature's authoritative admission, failing closed.

    Reserved role/status attributes are checked only for contradictions.  They
    cannot admit a feature by themselves because arbitrary GIS attributes are
    untrusted claims; an admission decision is always required.
    """

    bare_ref_unique = (
        _bare_ref_unique
        if _bare_ref_unique is not None
        else sum(
            candidate.source_feature_ref == feature.source_feature_ref
            for candidate in snapshot.features
        ) == 1
    )
    decision_pool = (
        snapshot.admission_decisions
        if _decision_candidates is None
        else _decision_candidates
    )
    ranked = [
        (
            _decision_specificity(
                decision,
                feature,
                bare_ref_unique=bare_ref_unique,
            ),
            decision,
        )
        for decision in decision_pool
    ]
    best = max((score for score, _ in ranked), default=0)
    decisions = [decision for score, decision in ranked if score == best and score > 0]
    if not decisions:
        return FeatureAdmissionVerdict(
            admitted=False,
            input_role="unclassified",
            status="quarantined",
            reason="source_admission_decision_missing",
        )

    pairs = {(decision.input_role, decision.status) for decision in decisions}
    decision_refs = tuple(sorted({decision.decision_ref for decision in decisions}))
    if len(pairs) != 1:
        return FeatureAdmissionVerdict(
            admitted=False,
            input_role="unclassified",
            status="quarantined",
            reason="source_admission_decision_conflict",
            decision_refs=decision_refs,
        )
    input_role, status = next(iter(pairs))

    attributes = dict(feature.raw_attributes or {})
    declared_roles = {
        _text(attributes.get(key)).casefold()
        for key in ("input_role", "document_input_role")
        if _text(attributes.get(key))
    }
    declared_statuses = {
        _text(attributes.get("admission_status")).casefold()
        for _ in (0,)
        if _text(attributes.get("admission_status"))
    }
    if declared_roles and declared_roles != {"current_evidence"}:
        return FeatureAdmissionVerdict(
            admitted=False,
            input_role=input_role,
            status=status,
            reason="source_role_metadata_conflicts_with_current_world",
            decision_refs=decision_refs,
        )
    if declared_statuses and declared_statuses != {"admitted"}:
        return FeatureAdmissionVerdict(
            admitted=False,
            input_role=input_role,
            status=status,
            reason="source_status_metadata_conflicts_with_current_world",
            decision_refs=decision_refs,
        )

    admitted = input_role == "current_evidence" and status == "admitted"
    return FeatureAdmissionVerdict(
        admitted=admitted,
        input_role=input_role,
        status=status,
        reason=(
            "admitted_current_evidence"
            if admitted
            else "source_not_admitted_to_current_world"
        ),
        decision_refs=decision_refs,
    )


def admitted_feature_keys(
    snapshot: DataResourceCatalogSnapshot,
) -> frozenset[tuple[str, str]]:
    bare_counts = Counter(
        feature.source_feature_ref for feature in snapshot.features
    )
    decision_index = _admission_decision_index(snapshot)
    return frozenset(
        feature_key(feature)
        for feature in snapshot.features
        if feature_admission_verdict(
            snapshot,
            feature,
            _bare_ref_unique=bare_counts[feature.source_feature_ref] == 1,
            _decision_candidates=_feature_decision_candidates(
                feature,
                bare_ref_unique=bare_counts[feature.source_feature_ref] == 1,
                decision_index=decision_index,
            ),
        ).admitted
    )


def admitted_resource_refs(
    snapshot: DataResourceCatalogSnapshot,
) -> frozenset[str]:
    allowed = admitted_feature_keys(snapshot)
    return frozenset(
        feature_resource_ref(feature)
        for feature in snapshot.features
        if feature_key(feature) in allowed
    )


def _direct_representation_is_bound(
    snapshot: DataResourceCatalogSnapshot,
    representation: SpatialRepresentation,
    *,
    allowed_keys: frozenset[tuple[str, str]],
    feature_by_key: dict[tuple[str, str], SourceFeature] | None = None,
) -> bool:
    """Validate immutable direct feature lineage without trusting rep labels."""

    dataset_ref = _text(representation.dataset_ref)
    source_feature_ref = _text(representation.source_feature_ref)
    if not dataset_ref or not source_feature_ref:
        return False
    key = (dataset_ref, source_feature_ref)
    if key not in allowed_keys:
        return False
    features = feature_by_key or {
        feature_key(item): item for item in snapshot.features
    }
    feature = features.get(key)
    if feature is None:
        return False
    return (
        _text(representation.resource_ref) == feature_resource_ref(feature)
        and _text(representation.geometry_ref) == source_feature_ref
        and _text(representation.source_snapshot_ref) == _text(snapshot.snapshot_id)
        and _text(representation.content_digest)
        == _text(feature.source_feature_digest)
        and _text(representation.geometry_kind)
        == _text(
            getattr(feature, "normalized_geometry_kind", "unknown")
            if getattr(feature, "normalized_geometry", None) is not None
            else feature.geometry_kind
        )
    )


def build_admission_index(
    snapshot: DataResourceCatalogSnapshot,
) -> CatalogAdmissionIndex:
    cache_key = _text(snapshot.digest)
    if cache_key:
        with _ADMISSION_INDEX_CACHE_LOCK:
            cached = _ADMISSION_INDEX_CACHE.get(cache_key)
            if cached is not None:
                _ADMISSION_INDEX_CACHE.move_to_end(cache_key)
                return cached
    allowed_keys = admitted_feature_keys(snapshot)
    features = {
        feature_key(feature): feature for feature in snapshot.features
    }
    resources = frozenset(
        feature_resource_ref(feature)
        for feature in snapshot.features
        if feature_key(feature) in allowed_keys
    )
    representation_refs: set[str] = set()
    representation_resources: set[str] = set()
    for representation in snapshot.representations:
        dataset_ref = _text(representation.dataset_ref)
        source_feature_ref = _text(representation.source_feature_ref)
        representation_resource = _text(representation.resource_ref)
        has_direct_identity = bool(dataset_ref or source_feature_ref)
        if has_direct_identity:
            admitted = _direct_representation_is_bound(
                snapshot,
                representation,
                allowed_keys=allowed_keys,
                feature_by_key=features,
            )
        else:
            # A component list alone does not bind a derived geometry to the
            # exact components, geometry or digest it claims.  Until DATA
            # publishes a recomputable aggregate geometry/digest contract,
            # aggregate representations are not admitted to KG or execution.
            # This intentionally fails closed instead of treating arbitrary
            # component refs as a spatial identity.
            admitted = False
        if not admitted:
            continue
        representation_refs.add(_text(representation.representation_ref))
        if representation_resource:
            representation_resources.add(representation_resource)
    result = CatalogAdmissionIndex(
        feature_keys=allowed_keys,
        resource_refs=resources,
        representation_refs=frozenset(representation_refs),
        representation_resource_refs=frozenset(representation_resources),
    )
    if cache_key:
        with _ADMISSION_INDEX_CACHE_LOCK:
            _ADMISSION_INDEX_CACHE[cache_key] = result
            _ADMISSION_INDEX_CACHE.move_to_end(cache_key)
            while len(_ADMISSION_INDEX_CACHE) > _ADMISSION_INDEX_CACHE_LIMIT:
                _ADMISSION_INDEX_CACHE.popitem(last=False)
    return result


def is_admitted_representation(
    snapshot: DataResourceCatalogSnapshot,
    representation: SpatialRepresentation,
    *,
    index: CatalogAdmissionIndex | None = None,
) -> bool:
    resolved = index or build_admission_index(snapshot)
    return _text(representation.representation_ref) in resolved.representation_refs


def is_admitted_capability(
    snapshot: DataResourceCatalogSnapshot,
    capability: DataCapability,
    *,
    index: CatalogAdmissionIndex | None = None,
) -> bool:
    resolved = index or build_admission_index(snapshot)
    resource_ref = _text(capability.resource_ref)
    return (
        resource_ref in resolved.resource_refs
        or resource_ref in resolved.representation_resource_refs
    )


def non_admitted_feature_verdicts(
    snapshot: DataResourceCatalogSnapshot,
) -> tuple[tuple[SourceFeature, FeatureAdmissionVerdict], ...]:
    result = []
    bare_counts = Counter(
        feature.source_feature_ref for feature in snapshot.features
    )
    decision_index = _admission_decision_index(snapshot)
    for feature in snapshot.features:
        bare_ref_unique = bare_counts[feature.source_feature_ref] == 1
        verdict = feature_admission_verdict(
            snapshot,
            feature,
            _bare_ref_unique=bare_ref_unique,
            _decision_candidates=_feature_decision_candidates(
                feature,
                bare_ref_unique=bare_ref_unique,
                decision_index=decision_index,
            ),
        )
        if not verdict.admitted:
            result.append((feature, verdict))
    return tuple(result)


def _quarantine_decision(
    feature: SourceFeature,
    verdict: FeatureAdmissionVerdict,
) -> SourceAdmissionDecision:
    source_ref = feature_resource_ref(feature)
    material = {
        "source_ref": source_ref,
        "source_digest": feature.source_feature_digest,
        "reason": verdict.reason,
    }
    decision_ref = "data.admission." + hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return SourceAdmissionDecision(
        decision_ref=decision_ref,
        source_ref=source_ref,
        source_digest=feature.source_feature_digest,
        input_role="unclassified",
        status="quarantined",
        resource_kind=_text(
            (feature.raw_attributes or {}).get("resource_kind")
        ) or feature.geometry_kind,
        reason=verdict.reason,
        recovery_pointer=f"source-admission:{source_ref}",
    )


def current_world_snapshot(
    snapshot: DataResourceCatalogSnapshot,
    *,
    explicit_decisions_trusted: bool = False,
) -> DataResourceCatalogSnapshot:
    """Return the immutable admitted view without retaining forbidden bodies."""

    bare_counts = Counter(
        feature.source_feature_ref for feature in snapshot.features
    )
    decision_index = _admission_decision_index(snapshot)
    verdicts: dict[tuple[str, str], FeatureAdmissionVerdict] = {}
    for feature in snapshot.features:
        bare_ref_unique = bare_counts[feature.source_feature_ref] == 1
        if explicit_decisions_trusted:
            exact_decisions = tuple(
                decision
                for decision in decision_index.get(feature_resource_ref(feature), ())
                if _text(decision.source_digest)
                == _text(feature.source_feature_digest)
            )
            if len(exact_decisions) == 1:
                decision = exact_decisions[0]
                attributes = dict(feature.raw_attributes or {})
                declared_roles = {
                    _text(attributes.get(key)).casefold()
                    for key in ("input_role", "document_input_role")
                    if _text(attributes.get(key))
                }
                declared_statuses = {
                    _text(attributes.get("admission_status")).casefold()
                } if _text(attributes.get("admission_status")) else set()
                if (
                    decision.input_role == "current_evidence"
                    and decision.status == "admitted"
                    and (not declared_roles or declared_roles == {"current_evidence"})
                    and (not declared_statuses or declared_statuses == {"admitted"})
                ):
                    verdicts[feature_key(feature)] = FeatureAdmissionVerdict(
                        admitted=True,
                        input_role=decision.input_role,
                        status=decision.status,
                        reason="admitted_current_evidence",
                        decision_refs=(decision.decision_ref,),
                    )
                    continue
        verdicts[feature_key(feature)] = feature_admission_verdict(
            snapshot,
            feature,
            _bare_ref_unique=bare_ref_unique,
            _decision_candidates=_feature_decision_candidates(
                feature,
                bare_ref_unique=bare_ref_unique,
                decision_index=decision_index,
            ),
        )
    allowed_keys = frozenset(
        key for key, verdict in verdicts.items() if verdict.admitted
    )
    features = tuple(
        feature
        for feature in snapshot.features
        if feature_key(feature) in allowed_keys
    )
    original_index = build_admission_index(snapshot)
    representations = tuple(
        item
        for item in snapshot.representations
        if item.representation_ref in original_index.representation_refs
    )
    admitted_resources = set(original_index.resource_refs)
    admitted_resources.update(original_index.representation_resource_refs)
    capabilities = tuple(
        item
        for item in snapshot.capabilities
        if item.resource_ref in admitted_resources
    )

    decisions = {
        item.decision_ref: item for item in snapshot.admission_decisions
    }
    decision_by_ref = {
        item.decision_ref: item for item in snapshot.admission_decisions
    }
    for feature in snapshot.features:
        verdict = verdicts[feature_key(feature)]
        if verdict.admitted:
            continue
        matched = [
            decision_by_ref[ref]
            for ref in verdict.decision_refs
            if ref in decision_by_ref
        ]
        explicitly_separated = bool(matched) and all(
            item.status in {"control_only", "reference_only", "excluded"}
            and item.input_role != "current_evidence"
            for item in matched
        )
        already_quarantined = any(
            item.status == "quarantined" for item in matched
        )
        if explicitly_separated or already_quarantined:
            continue
        quarantine = _quarantine_decision(feature, verdict)
        decisions.setdefault(quarantine.decision_ref, quarantine)

    layer_refs_by_dataset: dict[str, set[str]] = {}
    counts_by_dataset: dict[str, int] = {}
    for feature in features:
        counts_by_dataset[feature.dataset_ref] = (
            counts_by_dataset.get(feature.dataset_ref, 0) + 1
        )
        if feature.layer_ref:
            layer_refs_by_dataset.setdefault(feature.dataset_ref, set()).add(
                feature.layer_ref
            )
    source_datasets = tuple(snapshot.datasets or (snapshot.dataset,))
    retained_dataset_refs = set(counts_by_dataset)
    retained_datasets = [
        item for item in source_datasets if item.dataset_ref in retained_dataset_refs
    ]
    if not retained_datasets:
        retained_datasets = [snapshot.dataset]

    def admitted_dataset(item: SourceDataset) -> SourceDataset:
        payload = item.model_dump(mode="python")
        payload.update({
            "feature_count": counts_by_dataset.get(item.dataset_ref, 0),
            "layer_refs": tuple(sorted(
                layer_refs_by_dataset.get(item.dataset_ref, set())
            )),
            "digest": "",
        })
        return SourceDataset.model_validate(payload)

    datasets = tuple(admitted_dataset(item) for item in retained_datasets)
    primary = next(
        (
            item for item in datasets
            if item.dataset_ref == snapshot.dataset.dataset_ref
        ),
        datasets[0],
    )
    result = DataResourceCatalogSnapshot(
        snapshot_id=snapshot.snapshot_id,
        dataset=primary,
        datasets=datasets,
        features=features,
        representations=representations,
        capabilities=capabilities,
        admission_decisions=tuple(
            decisions[key] for key in sorted(decisions)
        ),
        admission_policy_version=CURRENT_WORLD_ADMISSION_POLICY_VERSION,
    )
    _remember_validated_catalog(result)
    return result


def assert_current_world_catalog(snapshot: DataResourceCatalogSnapshot) -> None:
    if (
        _text(snapshot.admission_policy_version)
        != CURRENT_WORLD_ADMISSION_POLICY_VERSION
    ):
        raise ValueError("DATA catalog uses an unsupported admission policy")
    cache_key = _text(snapshot.digest)
    if cache_key:
        with _ADMISSION_INDEX_CACHE_LOCK:
            if _VALIDATED_CATALOG_CACHE.get(cache_key):
                _VALIDATED_CATALOG_CACHE.move_to_end(cache_key)
                return
    violations = non_admitted_feature_verdicts(snapshot)
    index = build_admission_index(snapshot)
    invalid_representations = [
        item.representation_ref
        for item in snapshot.representations
        if item.representation_ref not in index.representation_refs
    ]
    allowed_capability_resources = (
        index.resource_refs | index.representation_resource_refs
    )
    invalid_capabilities = [
        item.capability_ref
        for item in snapshot.capabilities
        if item.resource_ref not in allowed_capability_resources
    ]
    if not violations and not invalid_representations and not invalid_capabilities:
        if cache_key:
            with _ADMISSION_INDEX_CACHE_LOCK:
                _VALIDATED_CATALOG_CACHE[cache_key] = True
                _VALIDATED_CATALOG_CACHE.move_to_end(cache_key)
                while len(_VALIDATED_CATALOG_CACHE) > _VALIDATED_CATALOG_CACHE_LIMIT:
                    _VALIDATED_CATALOG_CACHE.popitem(last=False)
        return
    collections = sorted({
        f"{feature.dataset_ref}:{feature.layer_ref or '<unlayered>'}:"
        f"{verdict.reason}"
        for feature, verdict in violations
    })
    preview = ", ".join(collections[:8])
    suffix = "" if len(collections) <= 8 else f" (+{len(collections) - 8} more)"
    details = [preview + suffix] if preview else []
    if invalid_representations:
        details.append(
            f"representations={len(invalid_representations)}:"
            + ",".join(sorted(invalid_representations)[:3])
        )
    if invalid_capabilities:
        details.append(
            f"capabilities={len(invalid_capabilities)}:"
            + ",".join(sorted(invalid_capabilities)[:3])
        )
    raise ValueError(
        "DATA catalog contains sources not admitted to the current world: "
        + "; ".join(details)
    )


def assert_cognition_ready_catalog(snapshot: DataResourceCatalogSnapshot) -> None:
    """Fail closed unless DATA is safe to project into the World Model.

    Current-world admission answers *whose* information may enter cognition.
    This second gate answers whether its generic DATA contracts can be safely
    understood: spatial inputs must be parsed, CRS-normalized and represented
    with immutable available lineage.  Markdown/table inputs remain valid
    without geometry; deferred media is not a readiness failure by itself.
    """

    assert_current_world_catalog(snapshot)
    issues = cognition_readiness_issues(snapshot)
    if not issues:
        return
    preview = ", ".join(
        sorted({
            f"{item.source_feature_ref or '<representation>'}:{item.reason}"
            for item in issues
        })[:8]
    )
    suffix = "" if len(issues) <= 8 else f" (+{len(issues) - 8} more)"
    raise ValueError(
        "DATA catalog is not cognition-ready: " + preview + suffix
    )


__all__ = [
    "LocalAdmissionDecision",
    "FeatureAdmissionVerdict",
    "CatalogAdmissionIndex",
    "CognitionReadinessIssue",
    "CURRENT_WORLD_ADMISSION_POLICY_VERSION",
    "admitted_feature_keys",
    "admitted_resource_refs",
    "assert_cognition_ready_catalog",
    "assert_current_world_catalog",
    "build_admission_index",
    "cognition_readiness_issues",
    "feature_admission_verdict",
    "feature_key",
    "feature_resource_ref",
    "current_world_snapshot",
    "is_admitted_capability",
    "is_admitted_representation",
    "non_admitted_feature_verdicts",
    "check_local_admission_boundary",
    "plan_catalog_invalidation",
]
