"""Final, independent validation of a relation-aware planning scenario.

The SELECT/ScenarioSolver relation rows are useful *hypotheses*.  They are
not evidence that EXECUTE produced the requested geometry.  This module
rebuilds an index from the authoritative :class:`PlannedState`, evaluates the
factors again, and emits a small serialisable report which can be persisted at
the VALIDATE boundary.

The implementation deliberately fails closed.  ``unknown``, ``pending``,
``deferred`` and ``not_evaluable`` are not interpreted as success, and a
``satisfied`` row without a measurement is also rejected.  This distinction
is important for delivery: a partial package may contain these findings, but
it must not be advertised as a fully validated plan.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from typing import Any, Iterable, Mapping, Sequence

from pydantic import BaseModel, Field

from app.contracts.planning.constraint_factor import (
    ConstraintFactor,
    RelationMeasurement,
    RelationSatisfaction,
)
from app.contracts.planning.relation_parameters import ServiceParameters
from app.contracts.planning.scenario import PlanningScenario, ScenarioFeature
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.contracts.spatial.planned_state_contracts import PlannedState
from app.domain.relations.service import RelationEvaluationContext, evaluate_relations
from app.domain.relations.network_evaluators import evaluate_network_relation


class FinalRelationFinding(BaseModel):
    """One auditable final-geometry validation finding."""

    code: str
    severity: str = "error"
    message: str
    relation_id: str = ""
    target_id: str = ""
    feature_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    status: str = ""
    expected: str = ""
    actual: str = ""


class FinalScenarioValidation(BaseModel):
    """Serializable result of independent final scenario validation."""

    schema_version: str = "1.0"
    scenario_id: str
    problem_fingerprint: str = ""
    final_fingerprint: str = ""
    evaluator_version: str = ""
    passed: bool = False
    status: str = "failed"
    final_features: list[ScenarioFeature] = Field(default_factory=list)
    satisfactions: list[RelationSatisfaction] = Field(default_factory=list)
    findings: list[FinalRelationFinding] = Field(default_factory=list)
    topology_findings: list[FinalRelationFinding] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    hard_blockers: list[str] = Field(default_factory=list)

def _text(value: Any) -> str:
    return str(value or "").strip()


def _geometry_kind(wkt_text: str) -> str:
    value = _text(wkt_text).upper()
    if value.startswith("MULTIPOLYGON") or value.startswith("POLYGON"):
        return "polygon"
    if value.startswith("MULTILINESTRING") or value.startswith("LINESTRING"):
        return "line"
    if value.startswith("MULTIPOINT") or value.startswith("POINT"):
        return "point"
    if value.startswith("TIN") or value.startswith("POLYHEDRALSURFACE"):
        return "multipatch"
    return "polygon"


def _item_geometry(item: Any) -> str:
    geometry = _text(getattr(item, "geometry", ""))
    if geometry:
        return geometry
    # PlannedFacility historically stored lon/lat separately.  Keeping this
    # fallback makes final validation work for old but otherwise typed output.
    if hasattr(item, "lon") and hasattr(item, "lat"):
        try:
            return f"POINT ({float(item.lon)} {float(item.lat)})"
        except (TypeError, ValueError):
            return ""
    return ""


def _state_records(planned_state: PlannedState) -> list[dict[str, Any]]:
    """Flatten every planning layer into final-feature identity records."""

    records: list[dict[str, Any]] = []
    layers = (
        ("parcel", "parcels"),
        ("zone", "zones"),
        ("overlay", "overlays"),
        ("facility", "facilities"),
        ("road", "roads"),
        ("axis", "axes"),
    )
    for kind, attr in layers:
        for index, item in enumerate(getattr(planned_state, attr, None) or []):
            geometry = _item_geometry(item)
            identity = (
                _text(getattr(item, "feature_id", ""))
                or _text(getattr(item, "lineage_id", ""))
                or _text(getattr(item, "candidate_id", ""))
                or _text(getattr(item, "zone_id", ""))
                or _text(getattr(item, "overlay_id", ""))
                or _text(getattr(item, "bsm", ""))
                or _text(getattr(item, "name", ""))
                or f"{kind}:{index}"
            )
            target_id = (
                _text(getattr(item, "target_ref", ""))
                or _text(getattr(item, "derived_from_target", ""))
                or _text(getattr(item, "derived_from_zone_target", ""))
                or _text(getattr(item, "project_ref", ""))
            )
            candidate_id = _text(getattr(item, "candidate_id", "")) or identity
            feature_id = _text(getattr(item, "feature_id", "")) or identity
            # An item without its own scenario identity is baseline/context
            # data. Never inherit the container scenario id, which would
            # manufacture lineage for unselected overlays.
            scenario_id = _text(getattr(item, "scenario_id", ""))
            relation_ids = list(getattr(item, "relation_ids", None) or [])
            source_refs = list(getattr(item, "source_refs", None) or [])
            source_refs.extend(
                ref
                for ref in (
                    f"planned-state:{kind}:{identity}",
                    _text(getattr(item, "geometry_ref", "")),
                    _text(getattr(item, "lineage_id", "")),
                )
                if ref
            )
            records.append(
                {
                    "kind": kind,
                    "identity": identity,
                    "target_id": target_id,
                    "candidate_id": candidate_id,
                    "feature_id": feature_id,
                    "geometry": geometry,
                    "geometry_kind": _geometry_kind(geometry),
                    "crs": _text(getattr(item, "crs", "")),
                    "scenario_id": scenario_id,
                    "relation_ids": sorted({_text(value) for value in relation_ids if _text(value)}),
                    "source_refs": sorted({_text(value) for value in source_refs if _text(value)}),
                }
            )
    return records


def _match_intent(record: Mapping[str, Any], intents: Sequence[ScenarioFeature]) -> ScenarioFeature | None:
    # Target-only matching lets an unrelated baseline geometry with the same
    # target claim a selected scenario intent. Candidate/feature identity is
    # the authoritative binding at this boundary.
    keys = {
        _text(record.get("feature_id")),
        _text(record.get("candidate_id")),
    }
    keys.discard("")
    if not keys:
        return None
    for intent in intents:
        if keys.intersection({intent.feature_id, intent.candidate_id}):
            return intent
    return None


def _to_final_features(
    scenario: PlanningScenario,
    planned_state: PlannedState,
    *,
    crs: str,
    external_feature_keys: set[str] | None = None,
) -> tuple[list[ScenarioFeature], list[FinalRelationFinding]]:
    records = _state_records(planned_state)
    intents = list(scenario.feature_intents)
    final: list[ScenarioFeature] = []
    findings: list[FinalRelationFinding] = []
    matched_intents: set[str] = set()
    for record in records:
        intent = _match_intent(record, intents)
        if intent is not None:
            matched_intents.add(intent.feature_id)
            feature_id = intent.feature_id
            target_id = intent.target_id
            candidate_id = intent.candidate_id
            relation_ids = sorted(set(intent.relation_ids) | set(record["relation_ids"]))
        else:
            feature_id = record["feature_id"]
            target_id = record["target_id"] or record["identity"]
            candidate_id = record["candidate_id"]
            relation_ids = list(record["relation_ids"])
            # Current/baseline features can be present in PlannedState.  They
            # are only orphan findings when the state explicitly claims the
            # scenario; this avoids treating the unchanged parcel inventory as
            # newly planned output.
            if _text(record.get("scenario_id")) == scenario.scenario_id:
                findings.append(
                    FinalRelationFinding(
                        code="orphan_final_feature",
                        message="final planned feature has no ScenarioFeature intent",
                        target_id=target_id,
                        feature_refs=[feature_id],
                        evidence_refs=list(record["source_refs"]),
                        expected="feature is represented by the selected scenario",
                        actual=record["kind"],
                    )
                )
        geometry = _text(record["geometry"])
        if not geometry:
            findings.append(
                FinalRelationFinding(
                    code="missing_final_geometry",
                    message="final planned feature has no geometry",
                    target_id=target_id,
                    feature_refs=[feature_id],
                    evidence_refs=list(record["source_refs"]),
                )
            )
        if not relation_ids:
            relation_ids = [f"selection:{target_id}:{candidate_id}"]
        final.append(
            ScenarioFeature(
                feature_id=feature_id,
                scenario_id=scenario.scenario_id,
                target_id=target_id,
                candidate_id=candidate_id,
                geometry_kind=record["geometry_kind"],
                geometry_wkt=geometry or "GEOMETRYCOLLECTION EMPTY",
                crs=_text(record["crs"]) or crs,
                generation_operation=f"final_materialize:{record['kind']}",
                source_refs=list(record["source_refs"]) or [f"planned-state:{record['identity']}"],
                relation_ids=relation_ids,
            )
        )

        if intent is not None and intent.geometry_kind != record["geometry_kind"]:
            findings.append(
                FinalRelationFinding(
                    code="geometry_kind_mismatch",
                    message="worker geometry kind differs from selected ScenarioFeature",
                    target_id=intent.target_id,
                    feature_refs=[intent.feature_id, feature_id],
                    evidence_refs=list(record["source_refs"]),
                    expected=intent.geometry_kind,
                    actual=record["geometry_kind"],
                )
            )
    external_keys = external_feature_keys or set()
    for intent in intents:
        is_external_reference = (
            intent.generation_operation == "relation_bundle_reference"
            or bool(
                external_keys.intersection({
                    intent.feature_id,
                    intent.target_id,
                    intent.candidate_id,
                    *(getattr(intent, "entity_refs", None) or []),
                    *(getattr(intent, "feature_bsms", None) or []),
                    *(getattr(intent, "source_bsms", None) or []),
                    *(getattr(intent, "source_feature_ids", None) or []),
                })
            )
        )
        if intent.feature_id not in matched_intents and not is_external_reference:
            findings.append(
                FinalRelationFinding(
                    code="missing_final_feature",
                    message="selected ScenarioFeature has no final materialized feature",
                    target_id=intent.target_id,
                    feature_refs=[intent.feature_id],
                    expected="final PlannedState feature with matching target/candidate",
                    actual="missing",
                )
            )
    return final, findings


def _parse_geometry(feature: ScenarioFeature):
    try:
        from shapely import wkt

        geometry = wkt.loads(feature.geometry_wkt)
        if geometry.is_empty or not geometry.is_valid:
            return None
        return geometry
    except Exception:
        return None


def validate_cross_layer_topology(
    features: Sequence[ScenarioFeature],
) -> list[FinalRelationFinding]:
    """Check topology across all planned layers, not just parcel polygons."""

    findings: list[FinalRelationFinding] = []
    geometries = {feature.feature_id: _parse_geometry(feature) for feature in features}
    for feature in features:
        geometry = geometries.get(feature.feature_id)
        if geometry is None:
            findings.append(
                FinalRelationFinding(
                    code="invalid_final_geometry",
                    message="final geometry is empty, invalid, or unparsable",
                    feature_refs=[feature.feature_id],
                )
            )

    polygons = [
        (feature, geometries[feature.feature_id])
        for feature in features
        if feature.geometry_kind == "polygon" and geometries.get(feature.feature_id) is not None
    ]
    line_features = [
        feature
        for feature in features
        if feature.geometry_kind == "line" and geometries.get(feature.feature_id) is not None
    ]
    point_features = [
        feature
        for feature in features
        if feature.geometry_kind == "point" and geometries.get(feature.feature_id) is not None
    ]
    # A planned road/axis must touch a planning polygon or a planned point;
    # otherwise the layer is spatially disconnected from the plan.
    for feature in line_features:
        geometry = geometries[feature.feature_id]
        connected = any(geometry.intersects(poly) or geometry.touches(poly) for _, poly in polygons)
        connected = connected or any(geometry.distance(geometries[point.feature_id]) <= 1e-8 for point in point_features)
        if not connected and (polygons or point_features):
            findings.append(
                FinalRelationFinding(
                    code="cross_layer_disconnected_line",
                    message="planned road/axis is disconnected from polygon and point layers",
                    feature_refs=[feature.feature_id],
                    expected="line intersects/touches a planned polygon or point",
                    actual=feature.geometry_kind,
                )
            )
    # Enforce point/area containment only when the scenario explicitly pairs
    # the facility with a footprint (same target or shared relation id).
    # Existing/preserve facilities are valid point-only outputs; checking them
    # against every unrelated polygon creates a false blocker and encourages
    # synthetic siting or centroid generation.
    for feature in point_features:
        geometry = geometries[feature.feature_id]
        feature_relations = set(feature.relation_ids)
        candidate_polygons = [
            (polygon_feature, polygon_geometry)
            for polygon_feature, polygon_geometry in polygons
            if (
                polygon_feature.target_id == feature.target_id
                or feature_relations.intersection(polygon_feature.relation_ids)
            )
        ]
        if candidate_polygons and not any(
            geometry.intersects(poly) or geometry.touches(poly)
            for _, poly in candidate_polygons
        ):
            findings.append(
                FinalRelationFinding(
                    code="cross_layer_orphan_point",
                    message="planned facility point is outside every planned area",
                    target_id=feature.target_id,
                    feature_refs=[feature.feature_id],
                    expected="facility intersects/touches a planned polygon",
                    actual="outside_planned_areas",
                )
            )
    return findings


def _finding_for_satisfaction(row: RelationSatisfaction) -> FinalRelationFinding | None:
    status = row.status
    relation = row.relation_id
    refs = sorted(set(row.subject_feature_refs + row.object_feature_refs))
    severity = "error" if row.criticality == "hard" else "warning"
    if status != "satisfied":
        return FinalRelationFinding(
            code=f"relation_{status}",
            severity=severity,
            message=f"final relation is {status}; it is not evidence of satisfaction",
            relation_id=relation,
            feature_refs=refs,
            evidence_refs=list(row.evidence_refs),
            status=status,
            expected="satisfied",
            actual=status,
        )
    if row.measurement is None:
        return FinalRelationFinding(
            code="relation_missing_measurement",
            severity=severity,
            message="satisfied relation has no final measurement",
            relation_id=relation,
            feature_refs=refs,
            status=status,
            expected="measurement and evaluation trace",
            actual="missing_measurement",
        )
    if not row.evaluation_trace or not row.evaluator_version:
        return FinalRelationFinding(
            code="relation_missing_trace",
            severity=severity,
            message="satisfied relation lacks evaluator version or trace",
            relation_id=relation,
            feature_refs=refs,
            status=status,
            expected="evaluator_version and evaluation_trace",
            actual="incomplete_trace",
        )
    return None


def validate_final_scenario(
    scenario: PlanningScenario,
    planned_state: PlannedState | None,
    problem: GroundedPlanningProblem,
    context: RelationEvaluationContext | None = None,
) -> FinalScenarioValidation:
    """Re-evaluate all factors against final worker geometry.

    ``scenario.relation_satisfactions`` is retained in the report for
    reconciliation, but it is never used as the final result.
    """

    context = context or RelationEvaluationContext()
    metric_crs = _text(getattr(context, "metric_crs", "")) or "EPSG:3857"
    evaluator_version = _text(getattr(context, "evaluator_version", "")) or "relation-evaluator-v1"
    if planned_state is None:
        # Preserve one explicit row per factor so downstream delivery can
        # explain the block instead of silently treating an empty output as a
        # valid zero-feature scenario.
        missing_rows = [
            RelationSatisfaction(
                relation_id=factor.factor_id.removeprefix("factor:"),
                scenario_id=scenario.scenario_id,
                subject_ref=factor.subject_ref,
                object_ref=factor.object_ref,
                status="not_evaluable",
                criticality="hard" if factor.hard else "soft",
                factor_ids=[factor.factor_id],
                evidence_refs=list(factor.evidence_refs),
                evaluator_version=evaluator_version,
                detail="planned_state is missing; final geometry cannot be evaluated",
            )
            for factor in problem.constraint_factors
        ]
        finding = FinalRelationFinding(
            code="missing_planned_state",
            message="final relation validation cannot run without PlannedState",
            expected="authoritative final PlannedState",
            actual="missing",
        )
        payload = {
            "scenario_id": scenario.scenario_id,
            "problem": problem.fingerprint,
            "satisfactions": [item.model_dump(mode="json") for item in missing_rows],
            "evaluator_version": evaluator_version,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return FinalScenarioValidation(
            scenario_id=scenario.scenario_id,
            problem_fingerprint=problem.fingerprint,
            final_fingerprint=fingerprint,
            evaluator_version=evaluator_version,
            passed=False,
            status="failed",
            satisfactions=missing_rows,
            findings=[finding],
            trace=["final-feature-index:0", "planned-state:missing", f"fingerprint:{fingerprint}"],
            hard_blockers=["missing_planned_state"],
        )
    external_features = list(
        (getattr(context, "reference_features", {}) or {}).values()
    )
    external_feature_keys = {
        str(value)
        for feature in external_features
        for value in (
            getattr(feature, "feature_id", ""),
            getattr(feature, "target_id", ""),
            getattr(feature, "candidate_id", ""),
            *(getattr(feature, "entity_refs", None) or []),
            *(getattr(feature, "feature_bsms", None) or []),
            *(getattr(feature, "source_bsms", None) or []),
            *(getattr(feature, "source_feature_ids", None) or []),
        )
        if str(value or "").strip()
    }
    final_features, identity_findings = _to_final_features(
        scenario,
        planned_state,
        crs=metric_crs,
        external_feature_keys=external_feature_keys,
    )
    final_features_index = {feature.feature_id: feature for feature in final_features}
    feature_keys: set[str] = set()
    for feature in final_features:
        feature_keys.update({feature.feature_id, feature.target_id, feature.candidate_id})
        feature_keys.update(getattr(feature, "entity_refs", None) or [])
        feature_keys.update(getattr(feature, "feature_bsms", None) or [])
        feature_keys.update(getattr(feature, "source_bsms", None) or [])
        feature_keys.update(getattr(feature, "source_feature_ids", None) or [])
    findings = list(identity_findings)
    findings.extend(
        FinalRelationFinding(
            code="external_relation_reference_diagnostic",
            severity="warning",
            message="external relation reference resolution was incomplete",
            actual=str(diagnostic),
            expected="unique bundle-authoritative external feature",
        )
        for diagnostic in tuple(
            getattr(context, "reference_diagnostics", ()) or ()
        )
    )
    for prior in scenario.relation_satisfactions:
        if prior.scenario_id and prior.scenario_id != scenario.scenario_id:
            findings.append(
                FinalRelationFinding(
                    code="relation_scenario_mismatch",
                    message="pre-execution relation belongs to a different scenario",
                    relation_id=prior.relation_id,
                    actual=prior.scenario_id,
                    expected=scenario.scenario_id,
                )
            )
    factors = list(problem.constraint_factors or [])
    factor_ids = {factor.factor_id.removeprefix("factor:") for factor in factors}
    for prior in scenario.relation_satisfactions:
        if prior.relation_id not in factor_ids:
            findings.append(
                FinalRelationFinding(
                    code="relation_factor_missing",
                    message="scenario relation has no executable factor in grounded problem",
                    relation_id=prior.relation_id,
                    status=prior.status,
                    expected="matching ConstraintFactor",
                    actual="missing",
                )
            )
    try:
        final_context = replace(context, scenario_id=scenario.scenario_id)
    except TypeError:
        final_context = RelationEvaluationContext(
            scenario_id=scenario.scenario_id,
            metric_crs=metric_crs,
            evaluator_version=evaluator_version,
            networks=getattr(context, "networks", {}) or {},
            demands=getattr(context, "demands", {}) or {},
            reference_features=getattr(context, "reference_features", {}) or {},
            reference_diagnostics=getattr(context, "reference_diagnostics", ()) or (),
            execution_trace=getattr(context, "execution_trace", None),
        )
    reference_features = list(
        (getattr(final_context, "reference_features", {}) or {}).values()
    )
    for feature in reference_features:
        feature_keys.update({feature.feature_id, feature.target_id, feature.candidate_id})
        feature_keys.update(getattr(feature, "entity_refs", None) or [])
        feature_keys.update(getattr(feature, "feature_bsms", None) or [])
        feature_keys.update(getattr(feature, "source_bsms", None) or [])
        feature_keys.update(getattr(feature, "source_feature_ids", None) or [])
    satisfactions = evaluate_relations(
        factors,
        [*final_features, *reference_features],
        final_context,
    )
    # ``serve`` has stronger input requirements than generic connect/access:
    # it must consume a typed DemandSnapshot and the network service-area
    # evaluator.  A generic network ``coverage_ratio`` method is not enough;
    # accepting it here would silently reintroduce nearest-facility/parcel
    # proxy semantics.
    feature_index: dict[str, list[ScenarioFeature]] = defaultdict(list)
    for feature in final_features:
        for key in (feature.feature_id, feature.target_id, feature.candidate_id):
            feature_index[key].append(feature)
    corrected: list[RelationSatisfaction] = []
    for factor, row in zip(factors, satisfactions):
        if factor.kind != "serve" or not isinstance(factor.parameters, ServiceParameters):
            corrected.append(row)
            continue
        params = factor.parameters
        network = final_context.networks.get(params.network_ref)
        demand = final_context.demands.get(params.demand_ref)
        subject = next(iter(feature_index.get(factor.subject_ref, ())), None)
        if network is None or demand is None or subject is None:
            corrected.append(
                row.model_copy(update={
                    "status": "not_evaluable",
                    "measurement": None,
                    "detail": "serve requires final facility feature, network and DemandSnapshot",
                    "evaluation_trace": ["serve:missing_typed_inputs"],
                })
            )
            continue
        from app.domain.network.snapshot import network_readiness

        network_status, network_diagnostics = network_readiness(network, params.network_ref)
        demand_status = getattr(demand, "readiness", "blocked")
        if network_status != "ready" or demand_status != "ready":
            corrected.append(
                row.model_copy(update={
                    "status": (
                        "deferred"
                        if network_status == "pending" or demand_status == "pending"
                        else "not_evaluable"
                    ),
                    "measurement": None,
                    "detail": ";".join([
                        *network_diagnostics,
                        *list(getattr(demand, "diagnostics", None) or []),
                    ]) or "typed service snapshots are not ready",
                    "evaluation_trace": ["serve:typed_snapshot_not_ready"],
                })
            )
            continue
        measurement = evaluate_network_relation("serve", subject, demand, network, params)
        status = getattr(measurement, "status", "not_evaluable")
        status = "violated" if status == "not_reachable" else status
        coverage = getattr(measurement, "coverage_ratio", None)
        corrected.append(
            row.model_copy(update={
                "status": status,
                "measurement": (
                    None
                    if coverage is None
                    else RelationMeasurement(
                        value=coverage,
                        unit="ratio",
                        threshold=params.min_coverage_ratio,
                        operator="gte",
                        method="network_service_area",
                        network_ref=params.network_ref,
                    )
                ),
                "evaluation_trace": [f"service:{params.demand_ref}:{params.network_ref}"],
                "detail": ";".join(getattr(measurement, "diagnostics", ()) or ()),
            })
        )
    satisfactions = corrected
    for row in satisfactions:
        if row.scenario_id != scenario.scenario_id:
            findings.append(
                FinalRelationFinding(
                    code="final_relation_scenario_mismatch",
                    message="final relation evaluator returned a different scenario id",
                    relation_id=row.relation_id,
                    actual=row.scenario_id,
                    expected=scenario.scenario_id,
                )
            )
        finding = _finding_for_satisfaction(row)
        if finding is not None:
            findings.append(finding)
        if not set(row.subject_feature_refs + row.object_feature_refs).issubset(feature_keys):
            findings.append(
                FinalRelationFinding(
                    code="relation_orphan_feature_ref",
                    message="relation refers to a feature absent from final feature index",
                    relation_id=row.relation_id,
                    feature_refs=sorted(set(row.subject_feature_refs + row.object_feature_refs) - feature_keys),
                    expected="feature refs resolve by feature/target/candidate id",
                    actual="orphan",
                )
            )
    topology_findings = validate_cross_layer_topology(final_features)
    findings.extend(topology_findings)
    hard_blockers = sorted(
        {
            finding.relation_id or finding.code
            for finding in findings
            if finding.severity == "error"
            and (
                finding.relation_id in {row.relation_id for row in satisfactions if row.criticality == "hard"}
                or finding.code.startswith(("missing_", "orphan_", "geometry_", "cross_layer_", "invalid_"))
            )
        }
    )
    payload = {
        "scenario_id": scenario.scenario_id,
        "problem": problem.fingerprint,
        "features": [item.model_dump(mode="json") for item in final_features],
        "satisfactions": [item.model_dump(mode="json") for item in satisfactions],
        "evaluator_version": evaluator_version,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    passed = not hard_blockers
    report_status = "complete" if passed and not findings else "partial" if passed else "failed"
    return FinalScenarioValidation(
        scenario_id=scenario.scenario_id,
        problem_fingerprint=problem.fingerprint,
        final_fingerprint=fingerprint,
        evaluator_version=evaluator_version,
        passed=passed,
        status=report_status,
        final_features=final_features,
        satisfactions=satisfactions,
        findings=findings,
        topology_findings=topology_findings,
        trace=[
            f"final-feature-index:{len(final_features)}",
            f"reference-feature-index:{len(reference_features)}",
            f"factor-evaluation:{len(satisfactions)}",
            f"topology-check:{len(topology_findings)}",
            f"fingerprint:{fingerprint}",
        ],
        hard_blockers=hard_blockers,
    )


__all__ = [
    "FinalRelationFinding",
    "FinalScenarioValidation",
    "validate_cross_layer_topology",
    "validate_final_scenario",
]
