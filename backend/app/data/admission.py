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
class P0BoundaryDecision:
    """Declaration-only result for the supported local MVP input slice."""

    accepted: bool
    state: str
    reason_code: str = ""
    reason: str = ""


def check_p0_local_boundary(
    *,
    declared_media_type: str,
    adapter_hint: str,
    declared_crs: str,
    declared_encoding: str,
    expected_role: str,
) -> P0BoundaryDecision:
    """Check declared capabilities without trusting filenames or properties.

    The P0 local slice includes only explicitly declared GeoJSON, Markdown
    and GeoTIFF file inputs. Provider observations are Evidence-owned and do
    not enter this local admission boundary.
    """

    media = _text(declared_media_type).casefold()
    if _text(expected_role).casefold() != "current_evidence":
        return P0BoundaryDecision(False, "POLICY_REJECTED", "non_current_role", "P0 admits current_evidence only")
    if _text(declared_encoding).casefold().replace("-", "") not in {"utf8", "utf"}:
        return P0BoundaryDecision(False, "ENCODING_UNRESOLVED", "encoding_unresolved", "P0 requires UTF-8 input")
    adapter = _text(adapter_hint).casefold()
    crs = _text(declared_crs).casefold()
    if media in {"geojson", "application/geo+json"}:
        if adapter != "file_vector":
            return P0BoundaryDecision(False, "UNSUPPORTED", "unsupported_adapter", "GeoJSON requires the file_vector adapter")
        if crs not in {"epsg:4326", "4326"}:
            return P0BoundaryDecision(False, "CRS_UNRESOLVED", "crs_unresolved", "P0 GeoJSON requires declared EPSG:4326")
        return P0BoundaryDecision(True, "ADMITTED")
    if media in {"text/markdown", "text/x-markdown", "markdown"}:
        if adapter != "document":
            return P0BoundaryDecision(False, "UNSUPPORTED", "unsupported_adapter", "Markdown requires the document adapter")
        if crs not in {"", "none", "non-spatial", "non_spatial"}:
            return P0BoundaryDecision(False, "CRS_UNRESOLVED", "non_spatial_crs_declared", "Markdown must declare no spatial CRS")
        return P0BoundaryDecision(True, "ADMITTED")
    if media in {"image/tiff", "image/geotiff", "application/geotiff", "geotiff"}:
        if adapter not in {"local_raster", "raster"}:
            return P0BoundaryDecision(False, "UNSUPPORTED", "unsupported_adapter", "GeoTIFF requires the local_raster adapter")
        if crs not in {"epsg:4326", "4326"}:
            return P0BoundaryDecision(False, "CRS_UNRESOLVED", "crs_unresolved", "P0 DEM requires declared EPSG:4326")
        return P0BoundaryDecision(True, "ADMITTED")
    return P0BoundaryDecision(False, "UNSUPPORTED", "unsupported_media", "P0 media type is outside the declared local input registry")


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
    "point", "line", "polygon", "multipatch", "raster",
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
        if feature.normalized_geometry is None:
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
        if representation.status != "available":
            issues.append(CognitionReadinessIssue(
                reason="spatial_representation_unresolved",
                source_feature_ref=_text(representation.source_feature_ref),
                source_digest=_text(representation.content_digest),
                missing_fields=("available_spatial_representation",),
            ))
    available_representation_keys = {
        (
            _text(representation.dataset_ref),
            _text(representation.source_feature_ref),
        )
        for representation in snapshot.representations
        if representation.status == "available"
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


def _legacy_collection_match(
    decision: SourceAdmissionDecision,
    feature: SourceFeature,
) -> bool:
    source_ref = _text(decision.source_ref)
    dataset_ref, _ = feature_key(feature)
    layer_ref = _text(feature.layer_ref)
    if not source_ref.startswith("legacy-bundle:") or not layer_ref:
        return False
    if not dataset_ref.startswith("session:"):
        return False
    session_ref = dataset_ref.removeprefix("session:")
    if ":documents" in session_ref:
        return False
    return (
        source_ref.startswith(f"legacy-bundle:{session_ref}:")
        and source_ref.endswith(f":{layer_ref}")
    )


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
    if not score and _legacy_collection_match(decision, feature):
        score = 2
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
    ranked = [
        (
            _decision_specificity(
                decision,
                feature,
                bare_ref_unique=bare_ref_unique,
            ),
            decision,
        )
        for decision in snapshot.admission_decisions
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
    return frozenset(
        feature_key(feature)
        for feature in snapshot.features
        if feature_admission_verdict(
            snapshot,
            feature,
            _bare_ref_unique=bare_counts[feature.source_feature_ref] == 1,
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
        and _text(representation.geometry_kind) == _text(feature.geometry_kind)
    )


def build_admission_index(
    snapshot: DataResourceCatalogSnapshot,
) -> CatalogAdmissionIndex:
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
    return CatalogAdmissionIndex(
        feature_keys=allowed_keys,
        resource_refs=resources,
        representation_refs=frozenset(representation_refs),
        representation_resource_refs=frozenset(representation_resources),
    )


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
    for feature in snapshot.features:
        verdict = feature_admission_verdict(
            snapshot,
            feature,
            _bare_ref_unique=bare_counts[feature.source_feature_ref] == 1,
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
) -> DataResourceCatalogSnapshot:
    """Return the immutable admitted view without retaining forbidden bodies."""

    bare_counts = Counter(
        feature.source_feature_ref for feature in snapshot.features
    )
    verdicts = {
        feature_key(feature): feature_admission_verdict(
            snapshot,
            feature,
            _bare_ref_unique=bare_counts[feature.source_feature_ref] == 1,
        )
        for feature in snapshot.features
    }
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
    return DataResourceCatalogSnapshot(
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


def assert_current_world_catalog(snapshot: DataResourceCatalogSnapshot) -> None:
    if (
        _text(snapshot.admission_policy_version)
        != CURRENT_WORLD_ADMISSION_POLICY_VERSION
    ):
        raise ValueError("DATA catalog uses an unsupported admission policy")
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
    "P0BoundaryDecision",
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
    "check_p0_local_boundary",
]
