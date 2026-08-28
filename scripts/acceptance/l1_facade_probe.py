"""Run the canonical L1 facade against a persisted real planning session."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any


async def _run(session_id: str) -> dict[str, Any]:
    from app.infrastructure.runtime.planning_runtime_service import (
        PlanningRuntimeService,
    )
    from app.modules.l1.application import L1Application, run_l1

    await PlanningRuntimeService.ensure_initialized()
    try:
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise RuntimeError(f"no persisted workflow state for session {session_id}")
        result = await run_l1(state)
        replay_state = {
            **state,
            **result.to_state_patch(),
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **dict(result.to_state_patch().get("artifact_refs") or {}),
            },
        }
        reloaded = L1Application.load(replay_state)
        if reloaded is None:
            raise RuntimeError("L1Snapshot could not be reloaded from its CAS ref")
        if reloaded.model_dump(mode="json") != result.snapshot.model_dump(mode="json"):
            raise RuntimeError("reloaded L1Snapshot differs from facade result")
        facts = list(result.snapshot.fact_records)
        inferred = [
            fact for fact in facts if fact.inference_level == "inferred"
        ]
        return {
            "session_id": session_id,
            "snapshot_ref": result.snapshot_ref.model_dump(mode="json"),
            "fact_count": len(facts),
            "source_count": len(result.snapshot.sources),
            "inferred_fact_count": len(inferred),
            "location_mention_count": len(result.snapshot.location_mentions),
            "reload_verified": True,
        }
    finally:
        await PlanningRuntimeService.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args.session_id))
    except Exception as exc:  # noqa: BLE001 - probe must expose the boundary error
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["fact_count"] > 0 and result["source_count"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
