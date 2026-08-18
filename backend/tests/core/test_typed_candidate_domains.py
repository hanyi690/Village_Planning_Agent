from __future__ import annotations

from types import SimpleNamespace

from app.contracts.spatial.grounding_contracts import CandidateSite
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.domain.ground.candidate_domain_builder import (
    build_candidate_domains,
    candidate_domain_status,
)


def _candidate(
    target_id: str,
    *,
    kind: str,
    role: str,
    wkt: str,
) -> CandidateSite:
    geometry = CandidateGeometry(
        target_id=target_id,
        kind=kind,
        role=role,
        wkt=wkt,
        source_ref="artifact:geometry:1",
        source_bsms=["P-1"],
    )
    return CandidateSite(
        site_id=f"site-{target_id}",
        target_ref=target_id,
        expected_output_kind="line" if kind == "line" else "point",
        available_geometry_wkt=wkt,
        geometry=geometry,
    )


def test_candidate_domain_reuses_geometry_candidate_id() -> None:
    candidate = _candidate(
        "road-1",
        kind="line",
        role="execution_geometry",
        wkt="LINESTRING (0 0, 1 1)",
    )

    domains = build_candidate_domains([candidate])

    assert domains[0].status == "resolved"
    assert domains[0].candidate_ids == [candidate.geometry.candidate_id]
    assert domains[0].candidate_geometry_refs == [candidate.geometry.candidate_id]
    assert candidate.candidate_id == candidate.geometry.candidate_id


def test_scope_and_corridor_are_candidate_only_not_executable() -> None:
    scope = _candidate(
        "zone-1",
        kind="polygon",
        role="scope_geometry",
        wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
    )
    corridor = _candidate(
        "road-1",
        kind="polygon",
        role="corridor_candidate",
        wkt="POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))",
    )

    assert scope.geometry.is_executable is False
    assert corridor.geometry.is_executable is False
    assert candidate_domain_status(scope) == "candidate_only"
    assert candidate_domain_status(corridor) == "candidate_only"
    assert {domain.status for domain in build_candidate_domains([scope, corridor])} == {
        "candidate_only"
    }
