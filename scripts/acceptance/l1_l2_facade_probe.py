"""Run the current-session L1 -> L2 facade boundary without test fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json


async def run(session_id: str) -> dict[str, object]:
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.modules.l1.application import run_l1
    from app.modules.l2.application import L2Application, run_l2

    await PlanningRuntimeService.ensure_initialized()
    try:
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise RuntimeError(f"no persisted workflow state for session {session_id}")
        l1 = await run_l1(state)
        l1_patch = l1.to_state_patch()
        state_with_l1 = {
            **state,
            **l1_patch,
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **dict(l1_patch.get("artifact_refs") or {}),
            },
        }
        l2 = await run_l2(state_with_l1)
        l2_patch = l2.to_state_patch()
        replay_state = {
            **state_with_l1,
            **l2_patch,
            "artifact_refs": {
                **dict(state_with_l1.get("artifact_refs") or {}),
                **dict(l2_patch.get("artifact_refs") or {}),
            },
        }
        reloaded_l1 = l1.snapshot.__class__.model_validate(l1.snapshot.model_dump(mode="json"))
        reloaded_l2 = L2Application.load(replay_state)
        if reloaded_l2 is None:
            raise RuntimeError("L2Strategy could not be reloaded after L1 -> L2 handoff")
        if reloaded_l2.model_dump(mode="json") != l2.decision_set.model_dump(mode="json"):
            raise RuntimeError("reloaded L2Strategy differs from facade result")
        return {
            "session_id": session_id,
            "l1_fact_count": len(l1.snapshot.fact_records),
            "l1_snapshot_ref": l1.snapshot_ref.model_dump(mode="json"),
            "l2_strategy_ref": l2.artifact_ref.model_dump(mode="json"),
            "l2_decision_set_count": len(l2.decision_set.decision_sets),
            "l2_reload_verified": True,
            "l1_snapshot_serialization_verified": bool(reloaded_l1.fact_records),
        }
    finally:
        await PlanningRuntimeService.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()
    try:
        payload = asyncio.run(run(args.session_id))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["l2_reload_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
