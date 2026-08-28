"""Run SELECT from current-session TARGET_PROJECTION and GROUND artifacts."""

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
    planning_program_ref_file: Path,
    target_projection_ref_file: Path,
    grounding_result_ref_file: Path,
) -> dict[str, Any]:
    from app.contracts.artifacts.ref import ArtifactRef
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.modules.select.application import SelectApplication, run_select

    refs = {
        "l1_snapshot": ArtifactRef.model_validate(_load_ref(l1_ref_file)),
        "l2_strategy": ArtifactRef.model_validate(_load_ref(l2_ref_file)),
        "planning_program": ArtifactRef.model_validate(_load_ref(planning_program_ref_file)),
        "target_projection": ArtifactRef.model_validate(_load_ref(target_projection_ref_file)),
        "grounding_result": ArtifactRef.model_validate(_load_ref(grounding_result_ref_file)),
    }
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
            "phase": "post_l3",
            "context_version": str(state.get("context_version") or ""),
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **{key: value.model_dump(mode="json") for key, value in refs.items()},
            },
        }
        result = await run_select(state)
        patch = result.to_state_patch()
        replay_state = {
            **state,
            **patch,
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **dict(patch.get("artifact_refs") or {}),
            },
        }
        if result.scenario_set is not None:
            loaded = SelectApplication.load_scenario_set(replay_state)
            if loaded is None:
                raise RuntimeError("SELECT scenario artifact was not reloadable")
            if loaded.model_dump(mode="json") != result.scenario_set.model_dump(mode="json"):
                raise RuntimeError("reloaded ScenarioSet differs from SELECT result")
        gate = result.gate_ref
        return {
            "session_id": session_id,
            "grounding_result_ref": refs["grounding_result"].model_dump(mode="json"),
            "select_gate_ref": gate.model_dump(mode="json"),
            "scenario_set_present": result.scenario_set is not None,
            "scenario_count": len(result.scenario_set.scenarios) if result.scenario_set else 0,
            "select_artifact_keys": sorted(result.artifact_refs),
            "select_boundary_verified": True,
        }
    finally:
        await PlanningRuntimeService.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--l1-ref-file", required=True, type=Path)
    parser.add_argument("--l2-ref-file", required=True, type=Path)
    parser.add_argument("--planning-program-ref-file", required=True, type=Path)
    parser.add_argument("--target-projection-ref-file", required=True, type=Path)
    parser.add_argument("--grounding-result-ref-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = asyncio.run(
            run(
                args.session_id,
                args.l1_ref_file,
                args.l2_ref_file,
                args.planning_program_ref_file,
                args.target_projection_ref_file,
                args.grounding_result_ref_file,
            )
        )
    except Exception as exc:  # noqa: BLE001 - probe exposes the runtime boundary error
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["select_boundary_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
