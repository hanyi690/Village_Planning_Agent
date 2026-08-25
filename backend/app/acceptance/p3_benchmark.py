"""Deterministic P3 benchmark, accounting, and recorded replay products.

P3 is a read-side acceptance boundary. It consumes explicit fixture or
recorded-session payloads and never changes planning, solver, or CAS state.
Every result below is computed from the payload; the manifest only supplies
expected values to compare against.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

LAYERS = (
    "L1_fact",
    "L2_dimension",
    "L3_claim",
    "target_project",
    "candidate",
    "scenario",
    "intervention_output",
)
STATUSES = ("admitted", "deferred", "rejected", "deduped")
_FATAL_ISSUES = frozenset(
    {
        "empty_layer",
        "missing_ref",
        "missing_parent",
        "drop",
        "invalid_status",
        "invalid_number",
    }
)
_REPLAY_ROUTES = (
    ("success", "execute", "success"),
    ("human", "human", "human_required"),
    ("not-groundable", "ground", "not_groundable"),
    ("solver-deferred", "select", "solver_deferred"),
)


def canonical_bytes(value: Any) -> bytes:
    """Return the exact canonical JSON bytes used by all P3 fingerprints."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if value is None or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _normalise_parent_refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Mapping):
        value = value.get("ref")
        return (str(value),) if value else ()
    if isinstance(value, (str, bytes)):
        return (str(value),)
    try:
        return tuple(sorted({str(item) for item in value if str(item)}))
    except TypeError:
        return (str(value),)


def _number(
    row: Mapping[str, Any],
    field: str,
    *,
    layer: str,
    ref: str,
    issues: list[dict[str, Any]],
) -> float:
    value = row.get(field, 0) or 0
    try:
        return float(value)
    except (TypeError, ValueError):
        issues.append({"kind": "invalid_number", "layer": layer, "ref": ref, "field": field})
        return 0.0


def _deduplicate_rows(
    layer: str,
    rows: list[Mapping[str, Any]],
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, raw in enumerate(rows):
        row = dict(raw)
        ref = str(row.get("ref") or "").strip()
        if not ref:
            ref = f"missing:{layer}:{index}"
            issues.append({"kind": "missing_ref", "layer": layer, "ref": ref})
        row["ref"] = ref
        row["parent_refs"] = list(_normalise_parent_refs(row.get("parent_refs")))
        status = str(row.get("status", "admitted"))
        if status not in STATUSES:
            issues.append({"kind": "invalid_status", "layer": layer, "ref": ref, "status": status})
            row["status"] = "rejected"
        grouped.setdefault(ref, []).append(row)

    unique: list[dict[str, Any]] = []
    deduped_refs: list[str] = []
    for ref, candidates in sorted(grouped.items()):
        ordered = sorted(candidates, key=canonical_bytes)
        winner = dict(ordered[0])
        unique.append(winner)
        if len(ordered) > 1:
            deduped_refs.append(ref)
            issues.append({"kind": "duplicate", "layer": layer, "refs": [ref]})
            statuses = {str(candidate.get("status", "admitted")) for candidate in ordered}
            if len(statuses) > 1:
                issues.append({"kind": "duplicate_status_conflict", "layer": layer, "ref": ref})
    return unique, deduped_refs


def _fingerprinted(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["fingerprint"] = canonical_fingerprint(result)
    return result


def build_accounting(layers: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict[str, Any]:
    """Build seven-layer accounting with real deduplication and conservation.

    Duplicate refs remain visible through the ``deduped`` count and
    ``deduped_refs`` list, but their numeric values are summed only once.
    Missing parents, empty layers, malformed statuses, and malformed numeric
    values remain fatal and make the accounting ``incomplete``.
    """

    normalized: dict[str, list[dict[str, Any]]] = {}
    issues: list[dict[str, Any]] = []
    for layer in LAYERS:
        rows = [dict(row) for row in _records(layers.get(layer, ()))]
        unique, _ = _deduplicate_rows(layer, rows, issues)
        normalized[layer] = sorted(unique, key=lambda row: str(row.get("ref", "")))
        if not rows:
            issues.append({"kind": "empty_layer", "layer": layer})

    summaries: dict[str, Any] = {}
    for layer, rows in normalized.items():
        refs = [str(row["ref"]) for row in rows]
        deduped_refs = sorted(
            {
                str(issue["refs"][0])
                for issue in issues
                if issue.get("kind") == "duplicate" and issue.get("layer") == layer
            }
        )
        counts = Counter(str(row.get("status", "admitted")) for row in rows)
        raw_rows = _records(layers.get(layer, ()))
        deduped_count = sum(
            1
            for raw in raw_rows
            if str(raw.get("ref") or "").strip() in set(deduped_refs)
        ) - len(deduped_refs)
        counts["deduped"] += max(deduped_count, 0)
        source_count = len(raw_rows)
        unique_count = len(rows)
        area = round(
            sum(_number(row, "area", layer=layer, ref=str(row["ref"]), issues=issues) for row in rows),
            6,
        )
        amount = round(
            sum(_number(row, "amount", layer=layer, ref=str(row["ref"]), issues=issues) for row in rows),
            6,
        )
        summaries[layer] = {
            "counts": {status: counts.get(status, 0) for status in STATUSES},
            "refs": refs,
            "deduped_refs": deduped_refs,
            "source_count": source_count,
            "unique_count": unique_count,
            "area": area,
            "amount": amount,
        }

    for index, layer in enumerate(LAYERS):
        if index == 0:
            continue
        previous_refs = set(summaries[LAYERS[index - 1]]["refs"])
        for row in normalized[layer]:
            parent_refs = set(_normalise_parent_refs(row.get("parent_refs")))
            if not parent_refs:
                issues.append({"kind": "missing_parent", "layer": layer, "ref": row["ref"], "refs": ["<none>"]})
                continue
            missing = sorted(parent_refs - previous_refs)
            if missing:
                issues.append({"kind": "drop", "layer": layer, "ref": row["ref"], "refs": missing})

    conservation_layers: dict[str, Any] = {}
    for layer, summary in summaries.items():
        accounted_count = sum(summary["counts"].values())
        layer_conservation = {
            "source_count": summary["source_count"],
            "unique_count": summary["unique_count"],
            "deduped_count": summary["counts"]["deduped"],
            "accounted_count": accounted_count,
            "source_equals_accounted": summary["source_count"] == accounted_count,
            "unique_plus_deduped_equals_source": (
                summary["unique_count"] + summary["counts"]["deduped"] == summary["source_count"]
            ),
        }
        layer_conservation["ok"] = all(
            layer_conservation[key]
            for key in ("source_equals_accounted", "unique_plus_deduped_equals_source")
        )
        conservation_layers[layer] = layer_conservation

    fatal_issues = [issue for issue in issues if issue.get("kind") in _FATAL_ISSUES]
    conservation = {
        "layers": conservation_layers,
        "overall_ok": not fatal_issues and all(item["ok"] for item in conservation_layers.values()),
        "fatal_issue_count": len(fatal_issues),
    }
    result = {
        "schema_version": "p3-accounting-2",
        "status": "ok" if conservation["overall_ok"] else "incomplete",
        "layers": summaries,
        "conservation": conservation,
        "issues": issues,
    }
    return _fingerprinted(result)


def _artifact_projection(fixture: Mapping[str, Any]) -> tuple[dict[str, str], str, list[dict[str, Any]]]:
    payloads = fixture.get("artifact_payloads")
    refs = fixture.get("artifact_refs")
    issues: list[dict[str, Any]] = []
    if not isinstance(payloads, Mapping) or not isinstance(refs, Mapping):
        return {}, canonical_fingerprint({}), [{"kind": "artifact_payload_missing"}]
    calculated = {
        str(key): canonical_fingerprint(value)
        for key, value in sorted(payloads.items(), key=lambda item: str(item[0]))
    }
    for key, digest in sorted(refs.items(), key=lambda item: str(item[0])):
        key = str(key)
        if key not in calculated:
            issues.append({"kind": "artifact_payload_missing", "ref": key})
        elif str(digest) != calculated[key]:
            issues.append({"kind": "artifact_digest_mismatch", "ref": key})
    for key in calculated:
        if key not in refs:
            issues.append({"kind": "artifact_ref_missing", "ref": key})
    return calculated, canonical_fingerprint(calculated), issues


def _case_outcome(fixture: Mapping[str, Any], accounting: Mapping[str, Any]) -> str:
    source = fixture.get("source_binding") or {}
    candidate = fixture.get("candidate") or {}
    relation = fixture.get("relation_readiness") or {}
    solver = fixture.get("solver_readiness") or {}
    if not source.get("bound") or not candidate.get("complete") or accounting.get("status") != "ok":
        return "incomplete"
    if not relation.get("ready"):
        return "human_required"
    if not solver.get("ready"):
        return "deferred"
    return "ready" if str(fixture.get("feasibility")) == "feasible" else "human_required"


def run_golden_benchmark(
    manifest_path: str | Path,
    *,
    accounting: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Compute benchmark metrics from fixture payloads and verify expectations."""

    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    cases = list(manifest.get("cases", ()))
    total = len(cases)
    computed_cases: list[dict[str, Any]] = []
    case_accounting: dict[str, Any] = {}
    source_bound = candidate_complete = relation_ready = solver_ready = 0
    outcome_counts = Counter()

    for case in cases:
        case_id = str(case.get("id", ""))
        fixture = case.get("fixture") if isinstance(case.get("fixture"), Mapping) else {}
        fixture_fp = canonical_fingerprint(fixture)
        artifact_refs, artifact_fp, artifact_issues = _artifact_projection(fixture)
        case_account = build_accounting(fixture.get("accounting", {}))
        case_accounting[case_id] = case_account
        computed_outcome = _case_outcome(fixture, case_account)
        outcome_counts[computed_outcome] += 1
        source_bound += int(bool((fixture.get("source_binding") or {}).get("bound")))
        candidate_complete += int(bool((fixture.get("candidate") or {}).get("complete")))
        relation_ready += int(bool((fixture.get("relation_readiness") or {}).get("ready")))
        solver_ready += int(bool((fixture.get("solver_readiness") or {}).get("ready")))

        expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
        checks = {
            "fixture_fingerprint": expected.get("fixture_fingerprint") == fixture_fp,
            "outcome": expected.get("outcome") == computed_outcome,
            "route": expected.get("route") == fixture.get("route"),
            "artifact_refs": sorted(expected.get("artifact_refs", ())) == sorted(artifact_refs),
            "artifact_fingerprint": expected.get("artifact_fingerprint") == artifact_fp,
            "accounting_fingerprint": expected.get("accounting_fingerprint") == case_account.get("fingerprint"),
            "accounting_status": expected.get("accounting_status") == case_account.get("status"),
            "artifacts_valid": not artifact_issues,
        }
        computed_cases.append(
            {
                "id": case_id,
                "scope": case.get("scope"),
                "fixture_fingerprint": fixture_fp,
                "fixture_bytes": len(canonical_bytes(fixture)),
                "computed_outcome": computed_outcome,
                "expected_outcome": expected.get("outcome"),
                "route": fixture.get("route"),
                "artifact_refs": sorted(artifact_refs),
                "artifact_fingerprint": artifact_fp,
                "accounting_fingerprint": case_account.get("fingerprint"),
                "accounting_status": case_account.get("status"),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    coverage = lambda count: count / total if total else 0.0
    metrics = {
        "source_binding": {"bound": source_bound, "total": total, "coverage": coverage(source_bound)},
        "candidate_completeness": {"complete": candidate_complete, "total": total, "coverage": coverage(candidate_complete)},
        "relation_readiness": {"ready": relation_ready, "total": total, "coverage": coverage(relation_ready)},
        "solver_readiness": {"ready": solver_ready, "deferred": outcome_counts["deferred"], "total": total, "coverage": coverage(solver_ready)},
        "feasibility": {
            "feasible": outcome_counts["ready"],
            "human_required": outcome_counts["human_required"],
            "incomplete": outcome_counts["incomplete"],
            "deferred": outcome_counts["deferred"],
            "total": total,
            "coverage": coverage(outcome_counts["ready"]),
        },
        "human_escalation": {
            "count": outcome_counts["human_required"] + outcome_counts["incomplete"],
            "total": total,
        },
    }
    actual_thresholds = {
        "source_binding_coverage": metrics["source_binding"]["coverage"],
        "candidate_completeness": metrics["candidate_completeness"]["coverage"],
        "relation_readiness": metrics["relation_readiness"]["coverage"],
        "solver_readiness": metrics["solver_readiness"]["coverage"],
        "feasibility": metrics["feasibility"]["coverage"],
    }
    threshold_results = {
        key: {
            "actual": actual,
            "required": float((manifest.get("thresholds") or {}).get(key, 0.0)),
            "passed": actual >= float((manifest.get("thresholds") or {}).get(key, 0.0)),
        }
        for key, actual in actual_thresholds.items()
    }

    if accounting is not None:
        output_accounting: dict[str, Any] = build_accounting(accounting)
    else:
        output_accounting = _fingerprinted(
            {
                "schema_version": "p3-output-accounting-by-case-1",
                "status": "ok" if all(item["status"] == "ok" for item in case_accounting.values()) else "incomplete",
                "cases": case_accounting,
            }
        )
    report: dict[str, Any] = {
        "schema_version": "p3-benchmark-2",
        "manifest_version": manifest["manifest_version"],
        "manifest_fingerprint": canonical_fingerprint(manifest),
        "manifest_bytes_fingerprint": "sha256:" + hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
        "metrics": metrics,
        "thresholds": threshold_results,
        "cases": sorted(computed_cases, key=lambda case: case["id"]),
        "output_accounting": output_accounting,
    }
    report["status"] = "passed" if all(
        case["passed"] for case in computed_cases
    ) and all(item["passed"] for item in threshold_results.values()) else "failed"
    return _fingerprinted(report)


def _unavailable_row(route_id: str, route: str, outcome: str, reason: str) -> dict[str, Any]:
    return {
        "id": route_id,
        "route": route,
        "outcome": outcome,
        "status": "unavailable",
        "replay_passed": False,
        "live_provider_passed": False,
        "provider_capability": "recorded_manifest_unavailable",
        "checks": {"route": False, "artifact": False, "gate": False, "certificate": False, "output_accounting": False},
        "artifacts": {
            "route": {"present": False},
            "artifact": {"present": False, "refs": []},
            "gate": {"present": False},
            "certificate": {"present": False},
            "output_accounting": {"present": False},
        },
        "reason": reason,
    }


def _verify_recorded_route(spec: Mapping[str, Any], provider_capability: str) -> dict[str, Any]:
    expected = spec.get("expected") if isinstance(spec.get("expected"), Mapping) else {}
    payloads = spec.get("artifact_payloads") if isinstance(spec.get("artifact_payloads"), Mapping) else {}
    refs = spec.get("artifact_refs") if isinstance(spec.get("artifact_refs"), Mapping) else {}
    calculated_refs = {
        str(key): canonical_fingerprint(value)
        for key, value in sorted(payloads.items(), key=lambda item: str(item[0]))
    }
    artifact_fp = canonical_fingerprint(calculated_refs)
    artifact_ok = bool(payloads) and bool(refs) and calculated_refs == {str(key): str(value) for key, value in refs.items()}

    gate = spec.get("gate") if isinstance(spec.get("gate"), Mapping) else {}
    certificate = spec.get("certificate") if isinstance(spec.get("certificate"), Mapping) else {}
    accounting = build_accounting(spec.get("accounting_input", {}))
    checks = {
        "route": spec.get("route") == expected.get("route") and spec.get("outcome") == expected.get("outcome"),
        "artifact": (
            artifact_ok
            and sorted(expected.get("artifact_refs", ())) == sorted(calculated_refs)
            and expected.get("artifact_fingerprint") == artifact_fp
        ),
        "gate": bool(gate) and gate.get("route") == expected.get("gate_route"),
        "certificate": (
            bool(certificate)
            and certificate.get("status") == expected.get("certificate_status")
            and expected.get("certificate_fingerprint") == canonical_fingerprint(certificate)
        ),
        "output_accounting": (
            accounting.get("status") == expected.get("accounting_status")
            and expected.get("accounting_fingerprint") == accounting.get("fingerprint")
        ),
    }
    passed = all(checks.values())
    return {
        "id": spec.get("id"),
        "route": spec.get("route"),
        "outcome": spec.get("outcome"),
        "status": "passed" if passed else "failed",
        "replay_passed": passed,
        "live_provider_passed": False,
        "provider_capability": provider_capability,
        "checks": checks,
        "artifacts": {
            "route": {"present": True, "route": spec.get("route"), "outcome": spec.get("outcome")},
            "artifact": {"present": bool(payloads), "refs": sorted(calculated_refs), "fingerprint": artifact_fp},
            "gate": {"present": bool(gate), "route": gate.get("route")},
            "certificate": {"present": bool(certificate), "status": certificate.get("status")},
            "output_accounting": {"present": True, "status": accounting.get("status"), "fingerprint": accounting.get("fingerprint")},
        },
        "reason": None if passed else "one or more recorded artifact checks failed",
    }


def recorded_replay_acceptance_matrix(*, recorded_session: str | Path | None = None) -> dict[str, Any]:
    """Verify four explicit recorded routes without invoking providers or CAS."""

    root = Path(recorded_session) if recorded_session else None
    manifest_path = root / "p3_replay_manifest.json" if root and root.is_dir() else None
    if not manifest_path or not manifest_path.is_file():
        rows = [_unavailable_row(route_id, route, outcome, "p3_replay_manifest.json is absent") for route_id, route, outcome in _REPLAY_ROUTES]
        return _fingerprinted(
            {
                "schema_version": "p3-replay-matrix-2",
                "status": "unavailable",
                "recorded_session": str(root) if root else None,
                "rows": rows,
                "live_provider": "not_run",
            }
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        rows = [_unavailable_row(route_id, route, outcome, f"invalid p3 replay manifest: {exc}") for route_id, route, outcome in _REPLAY_ROUTES]
        return _fingerprinted(
            {
                "schema_version": "p3-replay-matrix-2",
                "status": "unavailable",
                "recorded_session": str(root),
                "rows": rows,
                "live_provider": "not_run",
            }
        )

    provider_capability = str(manifest.get("provider_capability") or "recorded_only")
    specs = {str(spec.get("id")): spec for spec in manifest.get("routes", ()) if isinstance(spec, Mapping)}
    rows: list[dict[str, Any]] = []
    for route_id, route, outcome in _REPLAY_ROUTES:
        spec = specs.get(route_id)
        if spec is None:
            rows.append(_unavailable_row(route_id, route, outcome, "route record is absent"))
        else:
            rows.append(_verify_recorded_route(spec, provider_capability))
    return _fingerprinted(
        {
            "schema_version": "p3-replay-matrix-2",
            "status": "passed" if all(row["replay_passed"] for row in rows) else "failed",
            "recorded_session": str(root),
            "manifest_fingerprint": "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "rows": rows,
            "live_provider": "not_run",
        }
    )


__all__ = [
    "build_accounting",
    "canonical_bytes",
    "canonical_fingerprint",
    "recorded_replay_acceptance_matrix",
    "run_golden_benchmark",
]
