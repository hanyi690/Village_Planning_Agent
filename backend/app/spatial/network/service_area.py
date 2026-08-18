"""Capacity- and network-aware facility service-area measurement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shapely import wkt

from app.contracts.planning.relation_parameters import ServiceParameters
from app.domain.demand.facility_demand_model import DemandSnapshot, FacilityDemandPoint

from .network_graph import NetworkGraphSnapshot


ServiceStatus = Literal[
    "satisfied",
    "violated",
    "not_reachable",
    "not_evaluable",
    "deferred",
]


@dataclass(frozen=True)
class DemandServiceMeasurement:
    demand_id: str
    demand_value: float
    travel_time_min: float | None
    served_value: float
    reachable: bool
    facility_type_match: bool
    detail: str = ""


@dataclass(frozen=True)
class ServiceCoverageMeasurement:
    status: ServiceStatus
    facility_ref: str
    demand_ref: str
    facility_type: str
    network_ref: str
    coverage_ratio: float | None
    covered_demand: float
    eligible_demand: float
    capacity: float
    capacity_used: float
    max_travel_time_min: float
    min_coverage_ratio: float
    demand_measurements: tuple[DemandServiceMeasurement, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def value(self) -> float | None:
        return self.coverage_ratio

    @property
    def reachable(self) -> bool:
        return any(item.reachable for item in self.demand_measurements)


def _facility_geometry(facility):
    value = getattr(facility, "geometry_wkt", None) or getattr(facility, "wkt", None)
    if value:
        try:
            return wkt.loads(value)
        except Exception:
            return None
    return None


def evaluate_facility_service(
    facility,
    demand: DemandSnapshot,
    network: NetworkGraphSnapshot,
    parameters: ServiceParameters,
) -> ServiceCoverageMeasurement:
    """Measure demand served by one facility over the supplied road graph.

    Demand is filtered by ``facility_type`` and allocated in shortest-network
    travel-time order until capacity is exhausted.  A disconnected demand
    point is never served merely because its Euclidean distance is short.
    """

    facility_ref = str(
        getattr(facility, "feature_id", None)
        or getattr(facility, "target_id", None)
        or "facility"
    )
    geometry = _facility_geometry(facility)
    base = dict(
        facility_ref=facility_ref,
        demand_ref=demand.demand_ref,
        facility_type=parameters.facility_type,
        network_ref=parameters.network_ref,
        coverage_ratio=None,
        covered_demand=0.0,
        eligible_demand=0.0,
        capacity=float(parameters.capacity),
        capacity_used=0.0,
        max_travel_time_min=float(parameters.max_travel_time_min),
        min_coverage_ratio=float(parameters.min_coverage_ratio),
    )
    if geometry is None or geometry.is_empty or not geometry.is_valid:
        return ServiceCoverageMeasurement(
            status="not_evaluable",
            diagnostics=("facility_geometry_invalid",),
            **base,
        )
    if network.network_ref != parameters.network_ref:
        return ServiceCoverageMeasurement(
            status="not_evaluable",
            diagnostics=("network_ref_mismatch",),
            **base,
        )
    eligible: list[tuple[FacilityDemandPoint, float]] = []
    matching_demand = 0.0
    measurements: list[DemandServiceMeasurement] = []
    ineligible: list[FacilityDemandPoint] = []
    for point in demand.points:
        if point.facility_types and parameters.facility_type not in point.facility_types:
            ineligible.append(point)
            measurements.append(
                DemandServiceMeasurement(
                    demand_id=point.demand_id,
                    demand_value=point.demand_value,
                    travel_time_min=None,
                    served_value=0.0,
                    reachable=False,
                    facility_type_match=False,
                    detail="facility_type_mismatch",
                )
            )
            continue
        if point.demand_unit and point.demand_unit != parameters.capacity_unit:
            measurements.append(
                DemandServiceMeasurement(
                    demand_id=point.demand_id,
                    demand_value=point.demand_value,
                    travel_time_min=None,
                    served_value=0.0,
                    reachable=False,
                    facility_type_match=True,
                    detail="capacity_unit_mismatch",
                )
            )
            continue
        matching_demand += float(point.demand_value)
        route = network.route(geometry, point)
        travel = route.travel_time_min if route.reachable else None
        if route.reachable and travel is not None and travel <= parameters.max_travel_time_min:
            eligible.append((point, travel))
        else:
            measurements.append(
                DemandServiceMeasurement(
                    demand_id=point.demand_id,
                    demand_value=point.demand_value,
                    travel_time_min=travel,
                    served_value=0.0,
                    reachable=route.reachable,
                    facility_type_match=True,
                    detail=(
                        "travel_time_exceeds_threshold"
                        if route.reachable
                        else "network_components_disconnected"
                    ),
                )
            )
    # The denominator is all demand of the requested facility type.  Demand
    # outside the network component or travel-time threshold is unserved, not
    # silently removed from the coverage ratio.
    eligible_demand = matching_demand
    remaining_capacity = float(parameters.capacity)
    covered = 0.0
    for point, travel in sorted(eligible, key=lambda item: (item[1], item[0].demand_id)):
        served = min(float(point.demand_value), max(remaining_capacity, 0.0))
        remaining_capacity -= served
        covered += served
        measurements.append(
            DemandServiceMeasurement(
                demand_id=point.demand_id,
                demand_value=point.demand_value,
                travel_time_min=travel,
                served_value=served,
                reachable=True,
                facility_type_match=True,
                detail="served" if served >= point.demand_value else "capacity_limited",
            )
        )
    if eligible_demand <= 0:
        status: ServiceStatus = "not_evaluable"
        return ServiceCoverageMeasurement(
            status=status,
            demand_measurements=tuple(sorted(measurements, key=lambda item: item.demand_id)),
            diagnostics=("no_matching_demand_reachable_within_time",),
            coverage_ratio=0.0,
            **{key: value for key, value in base.items() if key != "coverage_ratio"},
        )
    ratio = covered / eligible_demand
    status = "satisfied" if ratio >= parameters.min_coverage_ratio else ("not_reachable" if covered <= 0 else "violated")
    return ServiceCoverageMeasurement(
        status=status,
        coverage_ratio=ratio,
        covered_demand=covered,
        eligible_demand=eligible_demand,
        capacity_used=covered,
        demand_measurements=tuple(sorted(measurements, key=lambda item: item.demand_id)),
        diagnostics=(),
        **{key: value for key, value in base.items() if key not in {"coverage_ratio", "covered_demand", "eligible_demand", "capacity_used"}},
    )


def service_area_features(
    facility,
    demand: DemandSnapshot,
    network: NetworkGraphSnapshot,
    parameters: ServiceParameters,
) -> tuple[str, ...]:
    """Return demand IDs actually served; useful for scenario overlays."""

    measurement = evaluate_facility_service(facility, demand, network, parameters)
    return tuple(
        item.demand_id
        for item in measurement.demand_measurements
        if item.served_value > 0
    )


__all__ = [
    "DemandServiceMeasurement",
    "ServiceCoverageMeasurement",
    "evaluate_facility_service",
    "service_area_features",
]
