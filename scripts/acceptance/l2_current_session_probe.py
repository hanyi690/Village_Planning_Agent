"""Run real L2 dimensions from a current-session L1 artifact reference.

This is a runtime acceptance probe, not a test-suite entrypoint.  It deliberately
requires an explicit artifact-ref file so a historical checkpoint cannot be
silently substituted for the current run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any


DEFAULT_DIMENSIONS = (
    "resource_endowment",
    "planning_positioning",
    "development_goals",
    "planning_strategies",
)


async def run(session_id: str, l1_ref_file: Path, dimensions: tuple[str, ...]) -> dict[str, Any]:
    from app.contracts.artifacts.ref import ArtifactRef
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.modules.l2.application import L2Application, run_l2
    from app.modules.l2.reasoning import analyze_l2_dimension

    raw_ref = json.loads(l1_ref_file.read_text(encoding="utf-8"))
    if set(raw_ref) == {"descriptor_digest"}:
        descriptor_digest = str(raw_ref["descriptor_digest"] or "")
        descriptor_name = descriptor_digest.removeprefix("sha256:")
        descriptor_file = Path(".run-tmp/descriptors") / f"{descriptor_name}.json"
        if not descriptor_file.is_file():
            raise RuntimeError(f"CAS descriptor file not found: {descriptor_file}")
        raw_ref = json.loads(descriptor_file.read_text(encoding="utf-8"))
        if str(raw_ref.get("descriptor_digest") or "") != descriptor_digest:
            raise RuntimeError("CAS descriptor digest does not match the supplied ref pointer")
    l1_ref = ArtifactRef.model_validate(raw_ref)
    await PlanningRuntimeService.ensure_initialized()
    try:
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise RuntimeError(f"no persisted current-session state for {session_id}")
        if str(state.get("session_id") or session_id) != session_id:
            raise RuntimeError("checkpoint session identity does not match the requested session")

        state = {
            **state,
            "run_id": str(state.get("run_id") or session_id),
            "session_id": session_id,
            "phase": "layer2",
            "context_version": str(state.get("context_version") or ""),
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                "l1_snapshot": l1_ref.model_dump(mode="json"),
            },
        }
        if not state["context_version"]:
            raise RuntimeError("current-session checkpoint has no context_version")

        completed = list(
            (state.get("completed_dimensions") or {}).get("layer2", [])
        )
        dimension_results: list[dict[str, Any]] = []
        for dimension in dimensions:
            if dimension in completed:
                continue
            result = await analyze_l2_dimension(
                {
                    **state,
                    "dimension_key": dimension,
                    "completed_dimensions": {"layer2": completed},
                }
            )
            failures = list(result.get("provider_failures") or []) + list(
                result.get("dimension_failures") or []
            )
            if failures:
                raise RuntimeError(
                    f"L2 dimension {dimension} failed: "
                    f"{json.dumps(failures[0], ensure_ascii=False, default=str)}"
                )
            completed.append(dimension)
            state = {
                **state,
                **result,
                "completed_dimensions": {"layer2": completed},
                "artifact_refs": {
                    **dict(state.get("artifact_refs") or {}),
                    **dict(result.get("artifact_refs") or {}),
                },
            }
            dimension_results.append(
                {
                    "dimension": dimension,
                    "completed": True,
                    "pending_reports": len(result.get("pending_reports") or []),
                }
            )

        l2 = await run_l2(state)
        replay_state = {
            **state,
            **l2.to_state_patch(),
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **dict(l2.to_state_patch().get("artifact_refs") or {}),
            },
        }
        reloaded = L2Application.load(replay_state)
        if reloaded is None:
            raise RuntimeError("L2Strategy could not be reloaded from its CAS ref")
        if reloaded.model_dump(mode="json") != l2.decision_set.model_dump(mode="json"):
            raise RuntimeError("reloaded L2Strategy differs from facade result")
        if not l2.decision_set.decision_sets:
            raise RuntimeError("L2Strategy contains no decision sets after real dimension runs")
        return {
            "session_id": session_id,
            "dimensions": dimension_results,
            "decision_set_count": len(l2.decision_set.decision_sets),
            "objective_count": len(l2.decision_set.objectives),
            "evidence_gap_count": len(l2.decision_set.evidence_gaps),
            "l1_snapshot_ref": l1_ref.model_dump(mode="json"),
            "l2_strategy_ref": l2.artifact_ref.model_dump(mode="json"),
            "l2_reload_verified": True,
        }
    finally:
        await PlanningRuntimeService.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--l1-ref-file", required=True, type=Path)
    parser.add_argument("--dimensions", nargs="*", default=list(DEFAULT_DIMENSIONS))
    args = parser.parse_args()
    try:
        payload = asyncio.run(
            run(args.session_id, args.l1_ref_file, tuple(args.dimensions))
        )
    except Exception as exc:  # noqa: BLE001 - probe must expose the runtime boundary error
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["l2_reload_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
