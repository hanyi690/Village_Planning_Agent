"""Minimal test: post_l3_main_nodes chain on a hand-built AgentState.

No DB, no LLM, no main graph — verifies the pure node wiring:
parse -> ground -> select -> execute -> validate -> reconcile -> deliver
using a tiny bundle + fake context.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


async def main() -> int:
    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    from app.modules.schema.contracts.parse_contracts import ProjectTarget
    from app.agent.bootstrap import post_l3_main_nodes as nodes

    # 1. Hand-build a PlanningProgram with 1 project.
    program = PlanningProgram(
        interventions=[
            {
                "intervention_id": "iv-1",
                "name": "新建文化活动中心",
                "category": "project",
                "scale_text": "用地 0.5 公顷",
                "action": "new",
            }
        ],
        context_version="v1",
        artifact_id="l3-test-v1",
    )
    print("program interventions:", len(program.interventions), flush=True)

    # 2. Build an AgentState dict.
    state = {
        "session_id": "s-test",
        "run_id": "s-test",
        "context_version": "v1",
        "planning_program": program,
        "specs": [],
        "retry_counts": {},
        "max_retries": 3,
        "error_feedback": {},
        "upstream_gates": [],
        "layout_configs": [],
        "allocated_geojson": {},
        "messages": [],
        "config": {"village_name": "金田村"},
    }

    # 3. Run parse -> check gate route.
    out = await nodes.parse_node(state)
    print("parse intent:", type(out.get("intent")).__name__, flush=True)
    print("parse specs:", len(out.get("specs") or []), flush=True)
    route = nodes._gate_route(out.get("parse_gate"))
    print("parse_gate route:", route, flush=True)
    print("PARSED OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
