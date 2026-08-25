"""Small deterministic master problem for cross-target resource coordination."""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field


class MasterCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    target_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    project_id: str = ""
    parcel_refs: tuple[str, ...] = ()
    network_refs: tuple[str, ...] = ()
    demand_by_ref: dict[str, float] = Field(default_factory=dict)


class MasterCertificate(BaseModel):
    status: Literal["feasible", "bounded_infeasible", "deferred"]
    selected_candidate_ids: dict[str, str] = Field(default_factory=dict)
    conflict_refs: tuple[str, ...] = ()
    blocker_refs: tuple[str, ...] = ()
    combinations_inspected: int = 0
    search_limit: int = 0
    fingerprint: str = ""

    def model_post_init(self, __context: object) -> None:
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        object.__setattr__(self, "fingerprint", hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest())


def coordinate_master(
    candidates: Iterable[MasterCandidate],
    *,
    parcel_capacity: dict[str, float] | None = None,
    network_capacity: dict[str, float] | None = None,
    demand_capacity: dict[str, float] | None = None,
    search_limit: int = 4096,
) -> MasterCertificate:
    """Enumerate one candidate per target and reject shared over-capacity choices.

    The bounded certificate is intentionally independent from local solver output:
    a locally feasible alternative is never promoted until this master check passes.
    """
    rows = sorted(candidates, key=lambda item: (item.target_id, item.candidate_id))
    by_target: dict[str, list[MasterCandidate]] = {}
    for row in rows:
        by_target.setdefault(row.target_id, []).append(row)
    if not by_target:
        return MasterCertificate(status="deferred", blocker_refs=("master_candidates_missing",), search_limit=search_limit)
    limits = {
        "parcel": parcel_capacity or {},
        "network": network_capacity or {},
        "demand": demand_capacity or {},
    }
    inspected = 0
    conflict_refs: set[str] = set()
    for product in itertools.product(*(by_target[key] for key in sorted(by_target))):
        inspected += 1
        if inspected > search_limit:
            return MasterCertificate(status="deferred", conflict_refs=tuple(sorted(conflict_refs)), blocker_refs=("master_search_bound_exceeded",), combinations_inspected=search_limit, search_limit=search_limit)
        used: dict[str, float] = {}
        for item in product:
            for ref in item.parcel_refs:
                used[f"parcel:{ref}"] = used.get(f"parcel:{ref}", 0.0) + 1.0
            for ref in item.network_refs:
                used[f"network:{ref}"] = used.get(f"network:{ref}", 0.0) + 1.0
            for ref, amount in item.demand_by_ref.items():
                used[f"demand:{ref}"] = used.get(f"demand:{ref}", 0.0) + float(amount)
        exceeded = [
            key for key, amount in used.items()
            if key.split(":", 1)[1] in limits[key.split(":", 1)[0]]
            and amount > float(limits[key.split(":", 1)[0]][key.split(":", 1)[1]]) + 1e-9
        ]
        if not exceeded:
            return MasterCertificate(status="feasible", selected_candidate_ids={item.target_id: item.candidate_id for item in product}, combinations_inspected=inspected, search_limit=search_limit)
        conflict_refs.update(exceeded)
    return MasterCertificate(status="bounded_infeasible", conflict_refs=tuple(sorted(conflict_refs)), combinations_inspected=inspected, search_limit=search_limit)


__all__ = ["MasterCandidate", "MasterCertificate", "coordinate_master"]
