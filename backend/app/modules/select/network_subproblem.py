"""Network subproblem and bounded-repair cuts for ScenarioSolver."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from pydantic import BaseModel, Field

from app.contracts.ground.constraint_factor import (
    ConstraintFactor,
    RelationMeasurement,
    RelationSatisfaction,
)
from app.contracts.ground.relation_parameters import ServiceParameters
from app.contracts.select.scenario import PlanningScenario, ScenarioFeature
from app.modules.l2.facility_demand_model import DemandSnapshot
from app.spatial.relations.network_evaluators import evaluate_network_relation
from app.spatial.network.snapshot import network_readiness
from app.spatial.network.service_area import evaluate_facility_service


class ScenarioCut(BaseModel):
    """A deterministic no-good/replacement hint emitted by a subproblem."""

    cut_id: str = ""
    relation_id: str
    target_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    network_ref: str = ""
    reason: str
    diagnostics: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.cut_id:
            payload = self.model_dump(mode="json", exclude={"cut_id"})
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            self.cut_id = f"cut:{digest[:24]}"


def _feature(features: Mapping[str, list[ScenarioFeature]], ref: str) -> ScenarioFeature | None:
    rows = list(features.get(ref, ()))
    return rows[0] if rows else None


def evaluate_network_subproblem(
    factor: ConstraintFactor,
    features: Mapping[str, list[ScenarioFeature]],
    *,
    networks: Mapping[str, object],
    demands: Mapping[str, DemandSnapshot] | None = None,
    scenario_id: str = "",
    evaluator_version: str = "relation-evaluator-v1",
) -> RelationSatisfaction:
    """Evaluate connect/access/serve using the supplied network artifact.

    ``serve`` is intentionally handled here because a demand snapshot is not
    a ScenarioFeature and must not be approximated by a nearest existing
    facility.
    """

    relation_id = factor.factor_id.removeprefix("factor:")
    criticality = "hard" if factor.hard else "soft"
    base = dict(
        relation_id=relation_id,
        scenario_id=scenario_id,
        subject_ref=factor.subject_ref,
        object_ref=factor.object_ref,
        criticality=criticality,
        factor_ids=[factor.factor_id],
        evidence_refs=list(factor.evidence_refs),
        evaluator_version=evaluator_version,
    )
    parameters = factor.parameters
    network_ref = str(getattr(parameters, "network_ref", "") or "")
    if not network_ref:
        return RelationSatisfaction(**base, status="deferred", detail="network_ref_missing")
    network = networks.get(network_ref)
    if network is None:
            return RelationSatisfaction(**base, status="not_evaluable", detail=f"network_unavailable:{network_ref}")
    readiness, readiness_diagnostics = network_readiness(network, network_ref)
    if readiness != "ready":
        return RelationSatisfaction(
            **base,
            status="deferred" if readiness == "pending" else "not_evaluable",
            detail=";".join(readiness_diagnostics) or "network_snapshot_not_ready",
        )
    subject = _feature(features, factor.subject_ref)
    object_feature = _feature(features, factor.object_ref)
    # A service relation's object is a demand snapshot, not a planned
    # geometry.  It is therefore valid for object_ref to be a demand/entity
    # reference with no ScenarioFeature.
    is_service = factor.evaluator_key in {"serve", "service"} or factor.kind == "serve"
    if subject is None or (object_feature is None and not is_service):
        return RelationSatisfaction(**base, status="not_evaluable", detail="network_feature_missing")

    if is_service:
        if not isinstance(parameters, ServiceParameters):
            return RelationSatisfaction(**base, status="deferred", detail="service_parameters_missing")
        demand_map = demands or {}
        demand = demand_map.get(parameters.demand_ref)
        if demand is None:
            return RelationSatisfaction(**base, status="not_evaluable", detail=f"demand_unavailable:{parameters.demand_ref}")
        if demand.readiness != "ready":
            return RelationSatisfaction(
                **base,
                status="deferred" if demand.readiness == "pending" else "not_evaluable",
                detail=";".join(demand.diagnostics) or "demand_snapshot_not_ready",
            )
        measurement = evaluate_facility_service(subject, demand, network, parameters)
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
            subject_feature_refs=[subject.feature_id],
            object_feature_refs=[object_feature.feature_id] if object_feature is not None else [parameters.demand_ref],
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

    measurement = evaluate_network_relation(
        factor.evaluator_key or factor.kind,
        subject,
        object_feature,
        network,
        parameters,
    )
    status = getattr(measurement, "status", "not_evaluable")
    if status == "not_reachable":
        status = "not_evaluable"
    if factor.evaluator_key in {"connect", "connect_network"}:
        value = getattr(measurement, "connected", None)
        operator = "connected"
        threshold = True
        unit = "bool"
    else:
        value = getattr(measurement, "travel_time_min", None)
        operator = "lte"
        threshold = getattr(parameters, "max_travel_time_min", None)
        unit = "min"
    return RelationSatisfaction(
        **base,
        status=status,
        detail=";".join(getattr(measurement, "diagnostics", ()) or ()),
        score=1.0 if status == "satisfied" else 0.0,
        subject_feature_refs=[subject.feature_id],
        object_feature_refs=[object_feature.feature_id],
        measurement=RelationMeasurement(
            value=value,
            unit=unit,
            threshold=threshold,
            operator=operator,
            method="network_shortest_path",
            network_ref=network_ref,
        ),
        evaluation_trace=[f"network:{network_ref}:{factor.evaluator_key or factor.kind}"],
    )


def derive_network_cuts(
    provisional: PlanningScenario,
    problem: Any,
) -> list[ScenarioCut]:
    """Turn failed network measurements into stable no-good/replacement cuts."""

    factors = {item.factor_id.removeprefix("factor:"): item for item in problem.constraint_factors}
    cuts: list[ScenarioCut] = []
    for satisfaction in provisional.relation_satisfactions:
        factor = factors.get(satisfaction.relation_id)
        if factor is None or factor.evaluator_key not in {
            "connect", "connect_network", "access_via", "provide_access", "serve", "service"
        }:
            continue
        if satisfaction.status == "satisfied":
            continue
        selection_by_target = {
            item.target_id: list(item.candidate_ids)
            for item in provisional.target_selections
        }
        selected = [
            candidate_id
            for ref in (factor.subject_ref, factor.object_ref)
            for candidate_id in selection_by_target.get(ref, [])
        ]
        cuts.append(ScenarioCut(
            relation_id=satisfaction.relation_id,
            target_ids=sorted({factor.subject_ref, factor.object_ref} - {""}),
            candidate_ids=sorted(set(selected)),
            network_ref=str(getattr(factor.parameters, "network_ref", "") or ""),
            reason=satisfaction.detail or satisfaction.status,
            diagnostics=[satisfaction.status],
        ))
    return sorted(cuts, key=lambda item: item.cut_id)


__all__ = ["ScenarioCut", "derive_network_cuts", "evaluate_network_subproblem"]
