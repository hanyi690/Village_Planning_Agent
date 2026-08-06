"""gis_agent_node tests — post-L3 chain invocation + AgentState write-back."""

from types import SimpleNamespace

import pytest

from app.agent.bootstrap.gis_agent_entry import gis_agent_node
from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest


def _bundle():
    from app.modules.schema.types.canonical import VillageBundle

    return VillageBundle(village_name="金田村")


def _mock_global_checkpointer(monkeypatch):
    async def fake_get_global_checkpointer():
        return object()

    monkeypatch.setattr(
        "app.database.engine.get_global_checkpointer", fake_get_global_checkpointer
    )


def _context():
    return SimpleNamespace(
        bundle=_bundle(),
        gazetteer=None,
        kg_session_ref="kg-1",
        village_name="金田村",
        context_version="v1",
        reports={},
        report_summary_index={},
        constraint_index=None,
        village_anchors=[],
    )


@pytest.mark.asyncio
async def test_gis_agent_node_writes_delivery_manifest(monkeypatch):
    manifest = DeliveryManifest(statutory_complete=True)

    async def fake_build_planning_context(*a, **k):
        return _context()

    async def fake_l3_aggregate(state):
        raise RuntimeError("no reports")

    class FakeChainResult:
        def __init__(self, data):
            self._d = data

        def get(self, key, default=None):
            return self._d.get(key, default)

    async def fake_chain_ainvoke(self, state, config=None):
        return FakeChainResult(
            {
                "delivery_manifest": manifest,
                "layout_configs": [],
                "validation_report": SimpleNamespace(overall_passed=True),
                "reconciliation_report": SimpleNamespace(),
                "export_result": {"status": "completed", "exported_files": []},
                "render_result": [],
                "render_artifact": {},
                "execution_errors": [],
            }
        )

    class FakeChain:
        async def ainvoke(self, state, config=None):
            return await fake_chain_ainvoke(self, state, config)

    monkeypatch.setattr(
        "app.services.context.build_planning_context", fake_build_planning_context
    )
    monkeypatch.setattr(
        "app.agent.l3_plan.aggregate.l3_aggregate", fake_l3_aggregate
    )
    _mock_global_checkpointer(monkeypatch)
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_chain.build_post_l3_chain", lambda checkpointer=None: FakeChain()
    )

    out = await gis_agent_node(
        {
            "session_id": "s1",
            "config": {"village_name": "金田村"},
            "user_uploaded_data": {},
            "messages": [],
        }
    )
    assert out["delivery_manifest"] is manifest
    assert out["validation_report_ref"] is not None
    assert out["reconciliation_report_ref"] is not None
    # legacy gis_* fields removed (use delivery_manifest)
    assert "gis_layout_configs" not in out
    assert "gis_validation_result" not in out
    assert "gis_export_result" not in out
    assert any(m.content for m in out["messages"])


@pytest.mark.asyncio
async def test_gis_agent_node_merges_user_uploads(monkeypatch):
    from app.modules.schema.types.canonical import VillageBundle

    manifest = DeliveryManifest(statutory_complete=False)

    async def fake_build_planning_context(*a, **k):
        return _context()

    async def fake_l3_aggregate(state):
        raise RuntimeError("no reports")

    class FakeChain:
        async def ainvoke(self, state, config=None):
            return {
                "delivery_manifest": manifest,
                "layout_configs": [],
                "validation_report": SimpleNamespace(overall_passed=False),
                "reconciliation_report": None,
                "export_result": None,
                "render_result": [],
                "render_artifact": {},
                "execution_errors": [],
            }

    monkeypatch.setattr(
        "app.services.context.build_planning_context", fake_build_planning_context
    )
    monkeypatch.setattr(
        "app.agent.l3_plan.aggregate.l3_aggregate", fake_l3_aggregate
    )
    _mock_global_checkpointer(monkeypatch)
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_chain.build_post_l3_chain", lambda checkpointer=None: FakeChain()
    )

    out = await gis_agent_node(
        {
            "session_id": "s1",
            "config": {"village_name": "金田村"},
            "user_uploaded_data": {
                "landuse_current": {
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}, "properties": {"BSM": "P1"}},
                    ],
                }
            },
            "messages": [],
        }
    )
    assert out["delivery_manifest"] is manifest


