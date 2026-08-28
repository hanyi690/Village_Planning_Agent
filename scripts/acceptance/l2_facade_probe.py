"""Run the L2 facade against a current persisted session and verify CAS replay."""

from __future__ import annotations

import argparse
import asyncio
import json


async def run(session_id: str) -> dict[str, object]:
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.modules.l2.application import L2Application, run_l2

    await PlanningRuntimeService.ensure_initialized()
    try:
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise RuntimeError(f"no persisted workflow state for session {session_id}")
        result = await run_l2(state)
        patch = result.to_state_patch()
        replay_state = {
            **state,
            **patch,
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **dict(patch.get("artifact_refs") or {}),
            },
        }
        reloaded = L2Application.load(replay_state)
        if reloaded is None:
            raise RuntimeError("L2Strategy could not be reloaded")
        if reloaded.model_dump(mode="json") != result.decision_set.model_dump(mode="json"):
            raise RuntimeError("reloaded L2Strategy differs from facade result")
        return {
            "session_id": session_id,
            "artifact_ref": result.artifact_ref.model_dump(mode="json"),
            "decision_count": len(result.decision_set.development_goals),
            "evidence_gap_count": len(result.decision_set.evidence_gaps),
            "reload_verified": True,
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
    return 0 if payload["reload_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
