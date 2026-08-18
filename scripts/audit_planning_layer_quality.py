"""Audit planning-layer materialization from one workflow run directory.

The audit intentionally reads only the explicit ``--run-dir``.  It never
opens ``data/gis/*/planned`` or invokes the standalone map renderer, so a
static baseline copy cannot be reported as workflow planning output.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.delivery.gate import summarize_planning_output
from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository


@dataclass(frozen=True)
class PlanningLayerQualityReport:
    run_dir: str
    status: str
    first_zero_stage: str
    artifact_files: int = 0
    target_count: int = 0
    candidate_count: int = 0
    selected_count: int = 0
    materialized_feature_count: int = 0
    planning_overlay_feature_count: int = 0
    non_baseline_feature_count: int = 0
    actual_change_count: int = 0
    orphan_feature_count: int = 0
    hard_relation_status_counts: dict[str, int] = field(default_factory=dict)
    spatial_yield: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _json_files(run_dir: Path) -> list[Path]:
    return [path for path in run_dir.rglob("*.json") if path.is_file()]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


_DELIVERY_ARTIFACT_KEYS = (
    "delivery_manifest",
    "delivery_spatial_snapshot",
    "render_layers",
    "planning_program",
    "grounding_result",
    "site_selection",
)


def _find_ref_directory(run_dir: Path) -> Path | None:
    """Find one explicit branch refs directory below ``run_dir``.

    A replay audit is commonly pointed at ``.../branches/<branch>`` while
    the CAS is a sibling of ``runs``.  The session-run form is also accepted
    for the live demo, where the branch refs are nested below ``runs``.
    """
    direct = run_dir / "refs"
    if direct.is_dir():
        return direct
    candidates = [
        path for path in run_dir.glob("runs/*/branches/*/refs")
        if path.is_dir()
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _find_cas_root(run_dir: Path) -> Path | None:
    """Locate the immutable CAS root without relying on process env state."""
    for candidate in (run_dir, *run_dir.parents):
        if (
            (candidate / "descriptors").is_dir()
            and (candidate / "blobs" / "sha256").is_dir()
        ):
            return candidate
    return None


def _read_ref_artifacts(
    run_dir: Path,
) -> tuple[dict[str, Any], list[str], int]:
    """Resolve delivery refs to payloads from their same-run CAS.

    Named refs intentionally contain only a descriptor digest.  Reading the
    ref JSON as if it were the artifact payload was the reason the standalone
    audit reported ``no_planning_output`` for valid replay branches.
    """
    refs_dir = _find_ref_directory(run_dir)
    cas_root = _find_cas_root(run_dir)
    if refs_dir is None or cas_root is None:
        return {}, [], 0
    repository = ContentAddressedArtifactRepository(cas_root)
    payloads: dict[str, Any] = {}
    evidence: list[str] = []
    resolved = 0
    for key in _DELIVERY_ARTIFACT_KEYS:
        ref_path = refs_dir / f"{key}.json"
        if not ref_path.is_file():
            continue
        ref = _read_json(ref_path)
        if not isinstance(ref, dict) or not ref.get("descriptor_digest"):
            continue
        try:
            descriptor_digest = str(ref["descriptor_digest"])
            descriptor = repository.get_descriptor(descriptor_digest)
            payloads[key] = repository.get_json(descriptor)
        except (OSError, ValueError, TypeError, KeyError):
            evidence.append(f"unable to resolve CAS artifact: {key}")
            continue
        resolved += 1
        evidence.append(
            f"resolved {key} descriptor to CAS blob: "
            f"{descriptor.descriptor_digest} -> {descriptor.digest}"
        )
    return payloads, evidence, resolved


def _derived_spatial_yield(payloads: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover stage counts when a delivery branch has no report sidecars."""
    result: list[dict[str, Any]] = []
    program = payloads.get("planning_program")
    if isinstance(program, dict) and isinstance(program.get("interventions"), list):
        result.append({"stage": "PlanningProgram", "output_count": len(program["interventions"])})
    grounding = payloads.get("grounding_result")
    if isinstance(grounding, dict):
        problem = grounding.get("problem")
        candidates = grounding.get("candidates")
        count = len(candidates) if isinstance(candidates, list) else 0
        if not count and isinstance(problem, dict):
            geometries = problem.get("candidate_geometries")
            count = len(geometries) if isinstance(geometries, list) else 0
        if count:
            result.append({"stage": "Grounding", "output_count": count})
    selection = payloads.get("site_selection")
    if isinstance(selection, dict):
        assignments = selection.get("target_assignments")
        if isinstance(assignments, list):
            placed = sum(
                1
                for item in assignments
                if isinstance(item, dict)
                and str(item.get("status") or "").lower()
                in {"placed", "selected", "ready", "complete"}
            )
            result.append({"stage": "Selection", "output_count": placed})
    return result


def _layer_lists(value: Any) -> list[list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return []
    result: list[list[dict[str, Any]]] = []
    for key in ("render_layers", "layers"):
        candidate = value.get(key)
        if isinstance(candidate, list) and all(isinstance(item, dict) for item in candidate):
            result.append(candidate)
    if value.get("layerType") or value.get("layer_type"):
        result.append([value])
    return result


def _features(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    data = value.get("data") or value.get("geojson") or value
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        return []
    return [feature for feature in data["features"] if isinstance(feature, dict)]


def _find_first_zero(spatial_yield: list[dict[str, Any]]) -> str:
    if not spatial_yield:
        # A run directory containing no immutable spatial-yield artifact has
        # not reached the delivery boundary.  The first *observable* missing
        # boundary is therefore DeliverySnapshot, rather than an invented
        # zero at an upstream stage.
        return "DeliverySnapshot"
    previous_positive = False
    for item in spatial_yield:
        output_count = int(item.get("output_count") or 0)
        if output_count > 0:
            previous_positive = True
        elif previous_positive:
            return str(item.get("stage") or "unknown")
    return "RenderLayers"


def audit_planning_layer_quality(
    run_dir: Path,
    *,
    require_complete_hard_relations: bool = True,
) -> PlanningLayerQualityReport:
    """Return a deterministic quality report for one explicit run directory."""
    run_dir = Path(run_dir).resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        return PlanningLayerQualityReport(
            run_dir=str(run_dir),
            status="no_planning_output",
            first_zero_stage="PlanningProgram",
            evidence=["run directory does not exist"],
        )

    files = _json_files(run_dir)
    ref_payloads, ref_evidence, resolved_ref_count = _read_ref_artifacts(run_dir)
    evidence: list[str] = list(ref_evidence)
    required_refs = {"delivery_manifest", "delivery_spatial_snapshot", "render_layers"}
    resolved_required_refs = required_refs.intersection(ref_payloads)
    refs_dir = _find_ref_directory(run_dir)
    if refs_dir is not None and resolved_required_refs != required_refs:
        missing = sorted(required_refs - resolved_required_refs)
        evidence.append("missing authoritative delivery refs: " + ", ".join(missing))
    layers: list[list[dict[str, Any]]] = []
    spatial_yield: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    relation_counts: dict[str, int] = {}
    actual_change_count = 0
    materialized_feature_count = 0
    payload_sources: list[tuple[str, Any]] = [
        (str(path.relative_to(run_dir)), _read_json(path))
        for path in files
        if path.parent.name != "refs"
    ]
    payload_sources.extend((f"CAS:{key}", payload) for key, payload in ref_payloads.items())
    for source, payload in payload_sources:
        if payload is None:
            continue
        if isinstance(payload, dict):
            if isinstance(payload.get("spatial_yield"), list):
                spatial_yield.extend(
                    item for item in payload["spatial_yield"] if isinstance(item, dict)
                )
            summary = payload.get("planning_output")
            if isinstance(summary, dict):
                actual_change_count = max(
                    actual_change_count, int(summary.get("actual_change_count") or 0)
                )
            change_summary = payload.get("change_summary")
            if isinstance(change_summary, dict):
                actual_change_count = max(
                    actual_change_count,
                    sum(int(change_summary.get(key) or 0) for key in (
                        "modified", "split", "merged", "created", "removed"
                    )),
                )
            relations = payload.get("relation_satisfaction") or payload.get("relations")
            if isinstance(relations, list):
                for relation in relations:
                    if isinstance(relation, dict):
                        status = str(relation.get("status") or "unknown")
                        relation_counts[status] = relation_counts.get(status, 0) + 1
            for layer_list in _layer_lists(payload):
                layers.append(layer_list)
        elif isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            # RenderLayers is persisted as the list itself, not wrapped in a
            # ``{"layers": ...}`` object.
            layers.append(payload)
        if "planned" in source.lower() and "current" not in source.lower():
            evidence.append(f"read workflow candidate: {source}")

    if not spatial_yield:
        spatial_yield.extend(_derived_spatial_yield(ref_payloads))
        if spatial_yield:
            evidence.append("derived spatial_yield stage counts from immutable artifacts")

    merged_layers: list[dict[str, Any]] = []
    for layer_list in layers:
        merged_layers.extend(layer_list)
    summary = summarize_planning_output(merged_layers, {"change_summary": {"modified": actual_change_count}})
    materialized_feature_count = sum(len(_features(layer)) for layer in merged_layers)
    target_count = sum(
        int(item.get("output_count") or 0)
        for item in spatial_yield
        if item.get("stage") == "PlanningProgram"
    )
    candidate_count = sum(
        int(item.get("output_count") or 0)
        for item in spatial_yield
        if item.get("stage") == "Grounding"
    )
    selected_count = sum(
        int(item.get("output_count") or 0)
        for item in spatial_yield
        if item.get("stage") == "Selection"
    )
    if not spatial_yield:
        evidence.append("no spatial_yield artifact found")
    if not merged_layers:
        evidence.append("no RenderLayers payload found")
    status = summary["status"]
    if refs_dir is not None and resolved_required_refs != required_refs:
        # A descriptor-only branch is authoritative only when all three
        # delivery artifacts can be resolved from the same CAS root.
        status = "no_planning_output"
    hard_incomplete = require_complete_hard_relations and any(
        status_name in relation_counts for status_name in (
            "pending", "not_evaluable", "deferred", "violated"
        )
    )
    if hard_incomplete and status == "ready":
        status = "partial"
    return PlanningLayerQualityReport(
        run_dir=str(run_dir),
        status=status,
        first_zero_stage=_find_first_zero(spatial_yield),
        artifact_files=len(files),
        target_count=target_count,
        candidate_count=candidate_count,
        selected_count=selected_count,
        materialized_feature_count=materialized_feature_count,
        planning_overlay_feature_count=int(summary["planning_overlay_feature_count"]),
        non_baseline_feature_count=int(summary["non_baseline_feature_count"]),
        actual_change_count=actual_change_count,
        orphan_feature_count=0,
        hard_relation_status_counts=relation_counts,
        spatial_yield=spatial_yield,
        evidence=evidence,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--allow-incomplete-hard-relations", action="store_true")
    args = parser.parse_args()
    report = audit_planning_layer_quality(
        args.run_dir,
        require_complete_hard_relations=not args.allow_incomplete_hard_relations,
    )
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.status in {"ready", "complete"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
