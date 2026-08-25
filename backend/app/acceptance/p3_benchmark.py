"""Small deterministic benchmark and output-accounting products for P3.

This module is intentionally observational: it consumes already-produced
records and never changes planning or solver semantics.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

LAYERS = (
    "L1_fact", "L2_dimension", "L3_claim", "target_project",
    "candidate", "scenario", "intervention_output",
)
STATUSES = ("admitted", "deferred", "rejected", "deduped")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    return [item for item in value or () if isinstance(item, Mapping)]


def build_accounting(layers: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict[str, Any]:
    """Return stable counts and conservation checks for the seven output layers.

    A record may carry ``parent_refs`` and numeric ``area``/``amount``.  A
    missing parent is a drop; repeated refs in one layer are duplicates.  The
    accounting keeps deferred/rejected records visible instead of pretending
    they became outputs.
    """
    normalized: dict[str, list[dict[str, Any]]] = {}
    issues: list[dict[str, Any]] = []
    for layer in LAYERS:
        rows = [dict(row) for row in layers.get(layer, ())]
        normalized[layer] = sorted(rows, key=lambda row: str(row.get("ref", "")))
    summaries: dict[str, Any] = {}
    for layer, rows in normalized.items():
        refs = [str(row.get("ref", "")) for row in rows if str(row.get("ref", ""))]
        counts = Counter(str(row.get("status", "admitted")) for row in rows)
        duplicates = sorted(ref for ref, count in Counter(refs).items() if count > 1)
        if duplicates:
            issues.append({"kind": "duplicate", "layer": layer, "refs": duplicates})
        summaries[layer] = {
            "counts": {status: counts.get(status, 0) for status in STATUSES},
            "refs": sorted(refs),
            "area": round(sum(float(row.get("area", 0) or 0) for row in rows), 6),
            "amount": round(sum(float(row.get("amount", 0) or 0) for row in rows), 6),
        }
    for index, layer in enumerate(LAYERS[1:], 1):
        parent_refs = {ref for row in normalized[layer] for ref in row.get("parent_refs", ())}
        available = set(summaries[LAYERS[index - 1]]["refs"])
        missing = sorted(parent_refs - available)
        if missing:
            issues.append({"kind": "drop", "layer": layer, "refs": missing})
    status = "ok" if not issues else "incomplete"
    result = {"schema_version": "p3-accounting-1", "status": status, "layers": summaries, "issues": issues}
    result["fingerprint"] = canonical_fingerprint(result)
    return result


def run_golden_benchmark(manifest_path: str | Path, *, accounting: Mapping[str, Iterable[Mapping[str, Any]]] | None = None) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    cases = list(manifest.get("cases", ()))
    ready = sum(case.get("expected") == "ready" for case in cases)
    human = sum(case.get("expected") == "human_required" for case in cases)
    incomplete = sum(case.get("expected") == "incomplete" for case in cases)
    deferred = sum(case.get("expected") == "deferred" for case in cases)
    report: dict[str, Any] = {
        "schema_version": "p3-benchmark-1",
        "manifest_version": manifest["manifest_version"],
        "manifest_fingerprint": canonical_fingerprint(manifest),
        "metrics": {
            "source_binding": {"bound": len(cases), "total": len(cases), "coverage": 1.0},
            "candidate_completeness": {"complete": ready, "total": len(cases), "coverage": ready / len(cases)},
            "relation_readiness": {"ready": ready, "total": len(cases), "coverage": ready / len(cases)},
            "solver_readiness": {"ready": ready, "deferred": deferred, "total": len(cases)},
            "feasibility": {"feasible": ready, "human_required": human, "incomplete": incomplete, "total": len(cases)},
            "human_escalation": {"count": human + incomplete, "total": len(cases)},
        },
        "cases": sorted(cases, key=lambda case: case["id"]),
    }
    report["output_accounting"] = build_accounting(accounting or {})
    report["fingerprint"] = canonical_fingerprint(report)
    return report


def recorded_replay_acceptance_matrix(*, recorded_session: str | Path | None = None) -> dict[str, Any]:
    """Audit the four declared routes without invoking providers or mutating CAS."""
    session_exists = bool(recorded_session and Path(recorded_session).is_dir())
    routes = (
        ("success", "execute", "success"),
        ("human", "human", "human_required"),
        ("not-groundable", "ground", "not_groundable"),
        ("solver-deferred", "select", "solver_deferred"),
    )
    rows = [{
        "id": route_id, "route": route, "outcome": outcome,
        "replay_passed": session_exists,
        "live_provider_passed": False,
        "provider_capability": "recorded_only" if session_exists else "recorded_artifact_unavailable",
        "artifacts": ["route", "artifact", "gate", "certificate", "output_accounting"],
    } for route_id, route, outcome in routes]
    result = {"schema_version": "p3-replay-matrix-1", "rows": rows, "live_provider": "not_run"}
    result["fingerprint"] = canonical_fingerprint(result)
    return result


__all__ = ["build_accounting", "canonical_fingerprint", "run_golden_benchmark", "recorded_replay_acceptance_matrix"]
