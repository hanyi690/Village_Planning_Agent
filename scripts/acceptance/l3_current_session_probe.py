"""Run a real L3 dimension from current-session L1/L2 artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any


def _load_ref(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if set(raw) == {"descriptor_digest"}:
        name = str(raw["descriptor_digest"] or "").removeprefix("sha256:")
        descriptor = Path(".run-tmp/descriptors") / f"{name}.json"
        if not descriptor.is_file():
            raise RuntimeError(f"CAS descriptor file not found: {descriptor}")
        raw = json.loads(descriptor.read_text(encoding="utf-8"))
    return raw


async def run(
    session_id: str,
    l1_ref_file: Path,
    l2_ref_file: Path,
    dimensions: tuple[str, ...],
) -> dict[str, Any]:
    from app.contracts.artifacts.ref import ArtifactRef
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.modules.l3.application import L3Application, run_l3
    from app.modules.l3.reasoning import analyze_l3_dimension

    l1_ref = ArtifactRef.model_validate(_load_ref(l1_ref_file))
    l2_ref = ArtifactRef.model_validate(_load_ref(l2_ref_file))
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
            "phase": "layer3",
            "context_version": str(state.get("context_version") or ""),
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                "l1_snapshot": l1_ref.model_dump(mode="json"),
                "l2_strategy": l2_ref.model_dump(mode="json"),
            },
        }
        if not state["context_version"]:
            raise RuntimeError("current-session checkpoint has no context_version")

        completed = list(
            (state.get("completed_dimensions") or {}).get("layer3", [])
        )
        dimension_results: list[dict[str, Any]] = []
        for dimension in dimensions:
            if dimension in completed:
                continue
            result = await analyze_l3_dimension(
                {
                    **state,
                    "dimension_key": dimension,
                    "completed_dimensions": {"layer3": completed},
                }
            )
            failures = list(result.get("provider_failures") or []) + list(
                result.get("dimension_failures") or []
            )
            if failures:
                raise RuntimeError(
                    f"L3 dimension {dimension} failed: "
                    f"{json.dumps(failures[0], ensure_ascii=False, default=str)}"
                )
            completed.append(dimension)
            state = {
                **state,
                **result,
                "completed_dimensions": {"layer3": completed},
            }
            dimension_results.append(
                {
                    "dimension": dimension,
                    "completed": True,
                    "pending_reports": len(result.get("pending_reports") or []),
                }
            )

        l3 = await run_l3(state)
        patch = l3.to_state_patch()
        replay_state = {
            **state,
            **patch,
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **dict(patch.get("artifact_refs") or {}),
            },
        }
        reloaded = L3Application().load(replay_state)
        if reloaded.model_dump(mode="json") != l3.program.model_dump(mode="json"):
            raise RuntimeError("reloaded PlanningProgram differs from facade result")
        if not l3.program.claims:
            raise RuntimeError("PlanningProgram contains no claims after real L3 dimension runs")
        return {
            "session_id": session_id,
            "dimensions": dimension_results,
            "claim_count": len(l3.program.claims),
            "intervention_count": len(l3.program.interventions),
            "evidence_gap_count": len(l3.program.evidence_gaps),
            "l1_snapshot_ref": l1_ref.model_dump(mode="json"),
            "l2_strategy_ref": l2_ref.model_dump(mode="json"),
            "planning_program_ref": l3.artifact_ref.model_dump(mode="json"),
            "l3_reload_verified": True,
        }
    finally:
        await PlanningRuntimeService.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--l1-ref-file", required=True, type=Path)
    parser.add_argument("--l2-ref-file", required=True, type=Path)
    parser.add_argument("--dimensions", nargs="*", default=["industry"])
    args = parser.parse_args()
    try:
        payload = asyncio.run(
            run(
                args.session_id,
                args.l1_ref_file,
                args.l2_ref_file,
                tuple(args.dimensions),
            )
        )
    except Exception as exc:  # noqa: BLE001 - probe must expose the runtime boundary error
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["l3_reload_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
