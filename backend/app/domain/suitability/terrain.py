"""Deterministic terrain-only suitability assessment."""

from __future__ import annotations

from app.contracts.spatial.terrain_evidence import (
    TerrainEvidence,
    TerrainSuitabilityAssessment,
    TerrainSuitabilityPolicy,
)


def assess_terrain_suitability(
    evidence: TerrainEvidence,
    policy: TerrainSuitabilityPolicy,
) -> TerrainSuitabilityAssessment:
    """Evaluate measured evidence using caller-owned planning thresholds."""

    reasons: list[str] = []
    if evidence.status != "ready":
        reasons.append(f"terrain_evidence_{evidence.status}")
    if evidence.elevation.valid_fraction < policy.minimum_valid_fraction:
        reasons.append("terrain_valid_fraction_below_policy")
    slope_value = getattr(evidence.slope, policy.slope_statistic)
    if slope_value is None:
        reasons.append("terrain_slope_statistic_unavailable")
    if reasons:
        return TerrainSuitabilityAssessment(
            evidence_id=evidence.evidence_id,
            classification="unknown",
            score=0.0,
            hard_feasible=False,
            evaluated_slope_degrees=slope_value,
            reasons=tuple(reasons),
            policy=policy,
        )

    assert slope_value is not None
    if slope_value > policy.hard_max_slope_degrees:
        reasons.append("terrain_slope_exceeds_hard_maximum")
    if (
        policy.minimum_elevation_m is not None
        and evidence.elevation.minimum is not None
        and evidence.elevation.minimum < policy.minimum_elevation_m
    ):
        reasons.append("terrain_elevation_below_minimum")
    if (
        policy.maximum_elevation_m is not None
        and evidence.elevation.maximum is not None
        and evidence.elevation.maximum > policy.maximum_elevation_m
    ):
        reasons.append("terrain_elevation_above_maximum")
    if (
        policy.maximum_relief_m is not None
        and evidence.relief_m is not None
        and evidence.relief_m > policy.maximum_relief_m
    ):
        reasons.append("terrain_relief_exceeds_maximum")
    if reasons:
        return TerrainSuitabilityAssessment(
            evidence_id=evidence.evidence_id,
            classification="unsuitable",
            score=0.0,
            hard_feasible=False,
            evaluated_slope_degrees=slope_value,
            reasons=tuple(reasons),
            policy=policy,
        )

    if slope_value <= policy.preferred_max_slope_degrees:
        classification = "preferred"
        score = 1.0
    else:
        classification = "conditional"
        span = policy.hard_max_slope_degrees - policy.preferred_max_slope_degrees
        score = (
            1.0
            if span <= 0.0
            else (policy.hard_max_slope_degrees - slope_value) / span
        )
    return TerrainSuitabilityAssessment(
        evidence_id=evidence.evidence_id,
        classification=classification,
        score=max(0.0, min(1.0, score)),
        hard_feasible=True,
        evaluated_slope_degrees=slope_value,
        reasons=(),
        policy=policy,
    )


__all__ = ["assess_terrain_suitability"]
