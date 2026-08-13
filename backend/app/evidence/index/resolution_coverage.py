"""Resolution coverage audit for typed L1 facts against the evidence index."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ResolutionCoverage:
    total: int = 0
    resolved_entity: int = 0      # entity_ref + source_bsms (实体 + 空间范围)
    resolved_extent: int = 0      # source_bsms, no entity_ref (空间范围)
    entity_geometry: int = 0      # geometry_ref only (实体但未接地块)
    unresolved: int = 0
    by_role: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def resolved(self) -> int:
        return self.resolved_entity + self.resolved_extent + self.entity_geometry

    @property
    def rate(self) -> float:
        return self.resolved / self.total if self.total else 0.0

    @property
    def extent_rate(self) -> float:
        return (self.resolved_entity + self.resolved_extent) / self.total if self.total else 0.0

    def summary(self) -> str:
        return (
            f"coverage={self.rate:.1%} (entity+extent={self.extent_rate:.1%}) "
            f"total={self.total} entity={self.resolved_entity} "
            f"extent={self.resolved_extent} geometry={self.entity_geometry} "
            f"unresolved={self.unresolved}"
        )


def resolution_coverage(context: Any) -> ResolutionCoverage:
    """Resolve every typed L1 fact through the evidence index and tally coverage.

    "resolved" means the mention binds to a KG entity with a spatial extent
    (source_bsms) and/or a geometry reference.  A location that only resolves to
    the village-centre geometric fallback still counts as extent when the index
    returns it.
    """
    index = getattr(context, "evidence_index", None)
    cov = ResolutionCoverage()
    for fact in list(getattr(context, "location_facts", []) or []):
        name = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        ).strip()
        if not name:
            continue
        role = str(getattr(fact, "role", "unknown") or "unknown")
        cov.total += 1
        bucket = cov.by_role.setdefault(
            role,
            {
                "resolved_entity": 0,
                "resolved_extent": 0,
                "entity_geometry": 0,
                "unresolved": 0,
            },
        )
        result = None
        if index is not None:
            try:
                result = index.resolve_mention(name, role=role)
            except Exception:
                result = None
        if result is not None and result.status == "resolved" and result.candidates:
            candidate = result.candidates[0]
            if candidate.source_bsms and candidate.entity_ref:
                cov.resolved_entity += 1
                bucket["resolved_entity"] += 1
            elif candidate.source_bsms:
                cov.resolved_extent += 1
                bucket["resolved_extent"] += 1
            elif candidate.geometry_ref:
                cov.entity_geometry += 1
                bucket["entity_geometry"] += 1
            else:
                cov.unresolved += 1
                bucket["unresolved"] += 1
            continue
        cov.unresolved += 1
        bucket["unresolved"] += 1
    return cov


__all__ = ["ResolutionCoverage", "resolution_coverage"]
