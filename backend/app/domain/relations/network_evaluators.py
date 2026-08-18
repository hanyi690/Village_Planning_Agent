"""Adapters for deterministic network relation evaluation.

This module is intentionally separate from the generic relation registry.  It
provides small, direct functions that can be used by the registry adapter,
solver, or final reconciliation without silently falling back to Euclidean
proximity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.contracts.planning.relation_parameters import AccessParameters, ConnectParameters, ServiceParameters
from app.domain.demand.facility_demand_model import DemandSnapshot
from app.spatial.network.network_graph import NetworkGraphSnapshot
from app.spatial.network.service_area import ServiceCoverageMeasurement, evaluate_facility_service


@dataclass(frozen=True)
class NetworkRelationMeasurement:
    status: Literal["satisfied", "violated", "not_reachable", "not_evaluable", "deferred"]
    connected: bool | None = None
    distance_m: float | None = None
    travel_time_min: float | None = None
    network_ref: str = ""
    diagnostics: tuple[str, ...] = ()

    @property
    def value(self) -> bool | float | None:
        if self.connected is not None:
            return self.connected
        return self.travel_time_min


def evaluate_connectivity(
    subject: Any,
    object_: Any,
    network: NetworkGraphSnapshot,
    parameters: ConnectParameters,
) -> NetworkRelationMeasurement:
    if network.network_ref != parameters.network_ref:
        return NetworkRelationMeasurement(
            status="not_evaluable",
            network_ref=parameters.network_ref,
            diagnostics=("network_ref_mismatch",),
        )
    route = network.route(subject, object_)
    if not route.reachable:
        return NetworkRelationMeasurement(
            status="not_reachable",
            connected=False,
            network_ref=network.network_ref,
            diagnostics=route.diagnostics,
        )
    # Endpoint tolerance applies to each connector, while the route object
    # includes both connectors in its reported distance.  Requiring a route
    # therefore prevents a nearby but disconnected geometry from passing.
    left = network.nearest_node(subject)
    right = network.nearest_node(object_)
    if left is None or right is None or left[1] > parameters.endpoint_tolerance_m or right[1] > parameters.endpoint_tolerance_m:
        return NetworkRelationMeasurement(
            status="not_reachable",
            connected=False,
            distance_m=route.distance_m,
            travel_time_min=route.travel_time_min,
            network_ref=network.network_ref,
            diagnostics=("endpoint_outside_snap_tolerance",),
        )
    return NetworkRelationMeasurement(
        status="satisfied",
        connected=True,
        distance_m=route.distance_m,
        travel_time_min=route.travel_time_min,
        network_ref=network.network_ref,
    )


def evaluate_access_via(
    subject: Any,
    object_: Any,
    network: NetworkGraphSnapshot,
    parameters: AccessParameters,
) -> NetworkRelationMeasurement:
    if network.network_ref != parameters.network_ref:
        return NetworkRelationMeasurement(
            status="not_evaluable",
            network_ref=parameters.network_ref,
            diagnostics=("network_ref_mismatch",),
        )
    route = network.route(subject, object_)
    if not route.reachable:
        return NetworkRelationMeasurement(
            status="not_reachable",
            connected=False,
            network_ref=network.network_ref,
            diagnostics=route.diagnostics,
        )
    status = "satisfied" if route.travel_time_min is not None and route.travel_time_min <= parameters.max_travel_time_min else "violated"
    return NetworkRelationMeasurement(
        status=status,
        connected=True,
        distance_m=route.distance_m,
        travel_time_min=route.travel_time_min,
        network_ref=network.network_ref,
        diagnostics=() if status == "satisfied" else ("travel_time_exceeds_threshold",),
    )


def evaluate_serve(
    facility: Any,
    demand: DemandSnapshot,
    network: NetworkGraphSnapshot,
    parameters: ServiceParameters,
) -> ServiceCoverageMeasurement:
    return evaluate_facility_service(facility, demand, network, parameters)


def evaluate_network_relation(
    relation_kind: str,
    subject: Any,
    object_: Any,
    network: NetworkGraphSnapshot,
    parameters: Any,
) -> NetworkRelationMeasurement | ServiceCoverageMeasurement:
    """Dispatch a closed-set network relation to its typed evaluator."""

    if relation_kind in {"connect", "connect_network"} and isinstance(parameters, ConnectParameters):
        return evaluate_connectivity(subject, object_, network, parameters)
    if relation_kind in {"access_via", "provide_access"} and isinstance(parameters, AccessParameters):
        return evaluate_access_via(subject, object_, network, parameters)
    if relation_kind in {"serve", "service"} and isinstance(parameters, ServiceParameters) and isinstance(object_, DemandSnapshot):
        return evaluate_serve(subject, object_, network, parameters)
    return NetworkRelationMeasurement(
        status="not_evaluable",
        network_ref=str(getattr(parameters, "network_ref", "") or ""),
        diagnostics=("network_relation_parameter_type_mismatch",),
    )


NETWORK_EVALUATORS = {
    "connect": evaluate_connectivity,
    "connect_network": evaluate_connectivity,
    "access_via": evaluate_access_via,
    "provide_access": evaluate_access_via,
    "serve": evaluate_serve,
}

evaluate_connect = evaluate_connectivity
evaluate_access = evaluate_access_via


__all__ = [
    "NETWORK_EVALUATORS",
    "NetworkRelationMeasurement",
    "evaluate_access_via",
    "evaluate_access",
    "evaluate_connect",
    "evaluate_connectivity",
    "evaluate_network_relation",
    "evaluate_serve",
]
