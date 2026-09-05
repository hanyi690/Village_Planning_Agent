from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_l1_aggregate_propagates_manifest_from_ground_finalization(monkeypatch) -> None:
    from app.modules.ground.application import GroundApplication
    from app.modules.l1 import application as l1_application
    from app.workflow.layers.layer_aggregate_node import layer_aggregate_node

    async def fake_run_l1(_state):
        return SimpleNamespace(
            to_state_patch=lambda: {
                "artifact_refs": {"l1_snapshot": {"digest": "snapshot"}}
            }
        )

    async def fake_location_ground(_state):
        return {
            "artifact_refs": {
                "l1_observations": {"digest": "observations"},
                "l1_bindings": {"digest": "bindings"},
                "l1_world_projection": {"digest": "projection"},
                "world_model_current_snapshot": {"digest": "wm-current"},
                "l1_product_manifest": {"digest": "manifest"},
            }
        }

    monkeypatch.setattr(l1_application, "run_l1", fake_run_l1)
    monkeypatch.setattr(
        GroundApplication,
        "materialize_l1_locations",
        fake_location_ground,
    )

    patch = asyncio.run(
        layer_aggregate_node(
            {
                "session_id": "session-l1-finalization",
                "run_id": "run-l1-finalization",
                "phase": "layer1",
                "layer_just_completed": 1,
                "context_version": "context-v1",
                "context_ref": {"descriptor_digest": "context-ref"},
                "artifact_refs": {},
            }
        )
    )

    assert patch["artifact_refs"]["l1_product_manifest"]["digest"] == "manifest"
    assert patch["layer_just_completed"] is None
