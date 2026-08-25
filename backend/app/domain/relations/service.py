"""Public relation evaluation service and execution context."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence

from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction
from app.contracts.planning.constraint_factor import RelationMeasurement
from app.contracts.planning.relation_parameters import (
    AccessParameters,
    ConnectParameters,
    ServiceParameters,
)
from app.contracts.planning.scenario import ScenarioFeature
from app.domain.demand.facility_demand_model import DemandSnapshot
from app.domain.network.snapshot import NetworkSnapshot, NetworkRef, network_readiness
from app.spatial.network.service_area import evaluate_facility_service

from .registry import RelationEvaluatorRegistry, build_default_relation_registry
from .temporal_evaluator import ExecutionTrace, evaluate_precedes


@dataclass(frozen=True)
class RelationEvaluationContext:
    scenario_id: str = ""
    metric_crs: str = "EPSG:3857"
    networks: Mapping[str, NetworkSnapshot | object] = field(default_factory=dict)
    # Demand snapshots are deliberately separate from feature geometry.  A
    # service relation must consume this typed demand input rather than infer
    # demand from a parcel centroid or the nearest existing facility.
    demands: Mapping[str, DemandSnapshot] = field(default_factory=dict)
    network_refs: Mapping[str, NetworkRef] = field(default_factory=dict)
    network_capacities: Mapping[str, float] = field(default_factory=dict)
    demand_capacities: Mapping[str, float] = field(default_factory=dict)
    # External entity/place-hint geometries are resolved from EvidenceGraph
    # identities and read from bundle authority before relation evaluation.
    # They are internal ScenarioFeature inputs, never EvidencePacket payloads.
    reference_features: Mapping[str, ScenarioFeature] = field(default_factory=dict)
    reference_diagnostics: tuple[str, ...] = ()
    execution_trace: ExecutionTrace | None = None
    evaluator_version: str = "relation-evaluator-v1"


class NetworkRelationEvaluator:
    """Adapter for deterministic network ports supplied by the caller."""

    def __init__(self, evaluator_key: str) -> None:
        self.evaluator_key = evaluator_key

    def evaluate(self, factor, features, context):
        relation_id = factor.factor_id.removeprefix("factor:")
        base = dict(
            relation_id=relation_id,
            scenario_id=context.scenario_id,
            subject_ref=factor.subject_ref,
            object_ref=factor.object_ref,
            criticality="hard" if factor.hard else "soft",
            factor_ids=[factor.factor_id],
            evidence_refs=list(factor.evidence_refs),
            evaluator_version=context.evaluator_version,
            evaluator_key=self.evaluator_key,
            source_snapshot_refs=list(factor.source_snapshot_refs),
            input_status=factor.input_status,
        )
        parameters = factor.parameters
        if factor.input_status != "ready":
            return RelationSatisfaction(
                **base,
                status="deferred" if factor.input_status == "pending" else "not_evaluable",
                detail=f"network relation input status is {factor.input_status}",
            )
        network_ref = str(getattr(parameters, "network_ref", "") or "")
        if not network_ref:
            return RelationSatisfaction(
                **base,
                status="deferred",
                detail="network relation is missing network_ref",
            )
        network = context.networks.get(network_ref)
        if network is None:
            return RelationSatisfaction(
                **base,
                status="not_evaluable",
                detail=f"network artifact is unavailable: {network_ref}",
            )
        readiness, readiness_diagnostics = network_readiness(network, network_ref)
        if readiness != "ready":
            return RelationSatisfaction(
                **base,
                status="deferred" if readiness == "pending" else "not_evaluable",
                detail=";".join(readiness_diagnostics) or "network snapshot is not ready",
            )
        subject = list(features.get(factor.subject_ref, ()))
        object_ = list(features.get(factor.object_ref, ()))
        is_service = self.evaluator_key == "serve" or factor.kind == "serve"
        if not subject or (not object_ and not is_service):
            return RelationSatisfaction(
                **base,
                status="not_evaluable",
                detail="network relation lacks subject/object features",
            )
        if is_service:
            if not isinstance(parameters, ServiceParameters):
                return RelationSatisfaction(
                    **base,
                    status="deferred",
                    detail="service parameters are not typed",
                )
            demand = (getattr(context, "demands", None) or {}).get(parameters.demand_ref)
            if not isinstance(demand, DemandSnapshot):
                return RelationSatisfaction(
                    **base,
                    status="not_evaluable",
                    detail=f"demand snapshot is unavailable: {parameters.demand_ref}",
                )
            if demand.readiness != "ready":
                return RelationSatisfaction(
                    **base,
                    status="deferred" if demand.readiness == "pending" else "not_evaluable",
                    detail=";".join(demand.diagnostics) or "demand snapshot is not ready",
                )
            if not hasattr(network, "route"):
                return RelationSatisfaction(
                    **base,
                    status="not_evaluable",
                    detail="network snapshot has no routing backend",
                )
            measurement = evaluate_facility_service(subject[0], demand, network, parameters)
            status = {
                "satisfied": "satisfied",
                "violated": "violated",
                "not_reachable": "not_evaluable",
                "not_evaluable": "not_evaluable",
                "deferred": "deferred",
            }[measurement.status]
            return RelationSatisfaction(
                **base,
                status=status,
                detail=";".join(measurement.diagnostics),
                score=float(measurement.coverage_ratio or 0.0),
                subject_feature_refs=[subject[0].feature_id],
                object_feature_refs=[parameters.demand_ref],
                measurement=RelationMeasurement(
                    value=measurement.coverage_ratio,
                    unit="ratio",
                    threshold=parameters.min_coverage_ratio,
                    operator="gte",
                    method="network_service_area_capacity",
                    network_ref=network_ref,
                ),
                evaluation_trace=[f"service:{network_ref}:{parameters.demand_ref}"],
            )
        result = _network_measure(network, self.evaluator_key, subject[0], object_[0], factor)
        if result is None:
            return RelationSatisfaction(
                **base,
                status="not_evaluable",
                detail=f"network does not implement evaluator {self.evaluator_key}",
            )
        value, threshold, operator, method = result
        passed = _compare(value, threshold, operator)
        status = "satisfied" if passed else "violated"
        return RelationSatisfaction(
            **base,
            status=status,
            subject_feature_refs=[subject[0].feature_id],
            object_feature_refs=[object_[0].feature_id],
            measurement=RelationMeasurement(
                value=value,
                unit="min" if self.evaluator_key in {"access", "access_via", "serve"} else "bool",
                threshold=threshold,
                operator=operator,
                method=method,
                network_ref=network_ref,
            ),
            evaluation_trace=[f"network:{network_ref}:{self.evaluator_key}"],
            score=1.0 if passed else 0.0,
        )


def _compare(value, threshold, operator: str) -> bool:
    if operator == "connected":
        return bool(value)
    if operator == "lte":
        return float(value) <= float(threshold)
    if operator == "gte":
        return float(value) >= float(threshold)
    if operator == "eq":
        return value == threshold
    return False


def _network_measure(network, key: str, subject, object_, factor):
    method = getattr(network, "evaluate_relation", None)
    if callable(method):
        value = method(key, subject, object_, factor)
    elif key == "connect" and callable(getattr(network, "is_connected", None)):
        value = network.is_connected(subject, object_)
    elif key in {"access", "access_via"} and callable(getattr(network, "travel_time_min", None)):
        value = network.travel_time_min(subject, object_)
    elif key == "serve" and callable(getattr(network, "coverage_ratio", None)):
        value = network.coverage_ratio(subject, object_)
    else:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    if key == "connect":
        return value, True, "connected", "network_connectivity"
    if key in {"access", "access_via"}:
        threshold = getattr(factor.parameters, "max_travel_time_min", None)
        if threshold is None:
            return None
        return value, threshold, "lte", "network_travel_time"
    if key == "serve":
        threshold = getattr(factor.parameters, "min_coverage_ratio", None)
        if threshold is None:
            return None
        return value, threshold, "gte", "network_service_coverage"
    return None


def index_relation_features(
    features: Sequence[ScenarioFeature],
) -> dict[str, list[ScenarioFeature]]:
    """Index planned and external features by every auditable identity key."""

    result: dict[str, list[ScenarioFeature]] = {}
    for feature in features:
        keys = (
            feature.feature_id,
            feature.target_id,
            feature.candidate_id,
            *list(getattr(feature, "entity_refs", None) or []),
            *list(getattr(feature, "feature_bsms", None) or []),
            *list(getattr(feature, "source_bsms", None) or []),
            *list(getattr(feature, "source_feature_ids", None) or []),
        )
        for key in keys:
            if not str(key or "").strip():
                continue
            result.setdefault(key, []).append(feature)
    return result


def evaluate_relations(
    factors: Sequence[ConstraintFactor],
    features: Sequence[ScenarioFeature],
    context: RelationEvaluationContext,
    *,
    registry: RelationEvaluatorRegistry | None = None,
) -> list[RelationSatisfaction]:
    """Evaluate all factors using deterministic geometry/temporal evaluators."""

    if registry is None:
        registry = build_default_relation_registry()
    indexed = index_relation_features(features)
    results: list[RelationSatisfaction] = []
    for factor in factors:
        if factor.evaluator_key == "precedes" or factor.kind == "precedes":
            results.append(
                evaluate_precedes(
                    factor,
                    context.execution_trace,
                    scenario_id=context.scenario_id,
                    evaluator_version=context.evaluator_version,
                    evaluator_key=factor.evaluator_key or factor.kind,
                    source_snapshot_refs=list(factor.source_snapshot_refs),
                    input_status=factor.input_status,
                )
            )
            continue
        evaluator = registry.get(factor.evaluator_key or factor.kind)
        if evaluator is None:
            results.append(
                RelationSatisfaction(
                    relation_id=factor.factor_id.removeprefix("factor:"),
                    scenario_id=context.scenario_id,
                    subject_ref=factor.subject_ref,
                    object_ref=factor.object_ref,
                    status="deferred",
                    criticality="hard" if factor.hard else "soft",
                    factor_ids=[factor.factor_id],
                    evidence_refs=list(factor.evidence_refs),
                    evaluator_version=context.evaluator_version,
                    detail=f"unsupported_evaluator:{factor.evaluator_key or factor.kind}",
                )
            )
            continue
        results.append(evaluator.evaluate(factor, indexed, context))
    return results


__all__ = [
    "RelationEvaluationContext",
    "evaluate_relations",
    "index_relation_features",
]
