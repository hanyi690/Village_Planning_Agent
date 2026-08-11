import pytest


@pytest.mark.asyncio
async def test_instruction_rows_keep_fields_and_source_evidence(monkeypatch):
    from app.agent.explore.retrievers import instruction_retriever as module

    class FakeStore:
        async def get_layer_reports_with_sources(self, _session_id, layer):
            if layer != 1:
                return {}
            return {"infrastructure": {"content": "【INSTRUCTION】\n| 类型 | 名称 | 位置 | 描述 | 规模 |\n|---|---|---|---|---|\n| 设施 | 供水点 | 营仔村 | 饮水工程 | 5处 |"}}

    monkeypatch.setattr(module.ReportStore, "get_instance", lambda: FakeStore())
    facts, sources = await module.retrieve_from_instructions("s1", "infrastructure", "L1")

    assert len(facts) == 1
    fact = facts[0]
    assert fact.fields["位置"] == "营仔村"
    assert fact.fields["规模"] == "5处"
    assert fact.evidence_span == "设施 | 供水点 | 营仔村 | 饮水工程 | 5处"
    assert fact.source_locator.endswith("table-1:row-1")
    assert fact.spatial_refs == ["营仔村"]
    assert fact.confidence == 0.95
    assert sources[0].reference == "L1:infrastructure:instruction"


@pytest.mark.asyncio
async def test_unstructured_instruction_is_not_high_confidence(monkeypatch):
    from app.agent.explore.retrievers import instruction_retriever as module

    class FakeStore:
        async def get_layer_reports_with_sources(self, _session_id, layer):
            return {"x": {"content": "【INSTRUCTION】\n位置待核实"}} if layer == 1 else {}

    monkeypatch.setattr(module.ReportStore, "get_instance", lambda: FakeStore())
    facts, _ = await module.retrieve_from_instructions("s1", "x", "L1")

    assert facts[0].confidence == 0.6
    assert facts[0].status == "unstructured"
    assert facts[0].source_locator.endswith("line-2")
