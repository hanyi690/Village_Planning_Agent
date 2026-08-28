"""Run TARGET_PROJECTION from a current-session PlanningProgram artifact."""

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
) -> dict[str, Any]:
    from app.contracts.artifacts.ref import ArtifactRef
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.modules.target_projection.application import (
        TargetProjectionApplication,
        run_target_projection,
    )

    l1_ref = ArtifactRef.model_validate(_load_ref(l1_ref_file))
    l2_ref = ArtifactRef.model_validate(_load_ref(l2_ref_file))
    program_ref = ArtifactRef.model_validate(_load_ref(planning_program_ref_file))
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
                "l1_snapshot": l1_ref.model_dump(mode="json"),
                "l2_strategy": l2_ref.model_dump(mode="json"),
                "planning_program": program_ref.model_dump(mode="json"),
            },
        }
        result = await run_target_projection(state)
        patch = result.to_state_patch()
        replay_state = {
            **state,
            **patch,
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **dict(patch.get("artifact_refs") or {}),
            },
        }
        reloaded = TargetProjectionApplication.load(replay_state)
        if reloaded.model_dump(mode="json") != result.compilation.model_dump(mode="json"):
            raise RuntimeError("reloaded IntentCompilationResult differs from facade result")
        return {
            "session_id": session_id,
            "target_count": len(getattr(result.compilation, "targets", None) or []),
            "diagnostic_count": len(getattr(result.compilation, "diagnostics", None) or []),
            "planning_program_ref": program_ref.model_dump(mode="json"),
            "target_projection_ref": result.artifact_ref.model_dump(mode="json"),
            "target_projection_reload_verified": True,
        }
    finally:
        await PlanningRuntimeService.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--l1-ref-file", required=True, type=Path)
    parser.add_argument("--l2-ref-file", required=True, type=Path)
    parser.add_argument("--planning-program-ref-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = asyncio.run(
            run(
                args.session_id,
                args.l1_ref_file,
                args.l2_ref_file,
                args.planning_program_ref_file,
            )
        )
    except Exception as exc:  # noqa: BLE001 - probe must expose the runtime boundary error
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["target_projection_reload_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
