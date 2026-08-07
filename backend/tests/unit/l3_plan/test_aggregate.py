"""L3 aggregate tests - merge fragments -> PlanningProgram + gate + review."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.agent.l3_plan.aggregate import l3_aggregate, merge_program_fragments
from app.agent.l3_plan.gate import evaluate_l3_gate as real_evaluate_l3_gate
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l3_contracts import (
    InterventionDependency,
    L3ProgramFragment,
    PlanningIntervention,
    PlanningProgram,
)
from app.modules.schema.contracts.provenance import Provenance


def _frag(dim, *, interventions=None, dependencies=None, gaps=None, omissions=None):
    return L3ProgramFragment(
        dimension_key=dim,
        interventions=interventions or [],
        dependencies=dependencies or [],
        evidence_gaps=gaps or [],
        program_issues=[],
        omissions=omissions or [],
        provenance=Provenance(
            source="l3_plan",
            run_id="r1",
            module="l3_plan",
            trace=[f"fragment:{dim}"],
        ),
    )


def test_merge_program_fragments():
    f1 = _frag(
        "industry",
        interventions=[PlanningIntervention(intervention_id="i1", name="休闲农业园")],
    )
    f2 = _frag(
        "project_bank",
        interventions=[
            PlanningIntervention(intervention_id="i1", name="休闲农业园"),
            PlanningIntervention(intervention_id="i2", name="游客服务中心"),
        ],
        dependencies=[
            InterventionDependency(from_intervention_id="i1", to_intervention_id="i2")
        ],
        gaps=[
            EvidenceGap(
                gap_id="g1",
                dimension="project_bank",
                description="缺时序",
                severity="warning",
            )
        ],
        omissions=["消防通道"],
    )
    p = merge_program_fragments([f1, f2], run_id="r1")
    assert isinstance(p, PlanningProgram)
    # dedup by intervention_id: i1 appears once
    assert len(p.interventions) == 2
    names = [i.name for i in p.interventions]
    assert "休闲农业园" in names and "游客服务中心" in names
    assert len(p.dependencies) == 1
    assert p.omissions == ["消防通道"]
    assert len(p.evidence_gaps) == 1
    assert len(p.dimension_provenance) == 2
    assert [s.reference for s in p.sources] == ["l3_plan"]


@pytest.mark.asyncio
async def test_l3_aggregate_returns_refs(tmp_path, monkeypatch):
    fake_reports = {
        3: {
            "project_bank": {
                "content": "【INSTRUCTION】\n| 类型 | 名称 | 位置 | 描述 | 规模 |\n|---|---|---|---|---|\n| 项目 | 休闲农业园 | 村东侧 | 描述 | 30公顷 |\n",
                "summary": "",
                "report_id": "rpt-1",
            },
        }
    }

    async def fake_get_layer_reports_with_sources(self, session_id, layer):
        return fake_reports.get(layer, {})

    monkeypatch.setattr(
        "app.services.report_store.ReportStore.get_layer_reports_with_sources",
        fake_get_layer_reports_with_sources,
    )

    with patch(
        "app.agent.l3_plan.aggregate.write_review_package",
        return_value="review-1",
    ) as mock_write, patch(
        "app.agent.l3_plan.aggregate.evaluate_l3_gate",
        wraps=real_evaluate_l3_gate,
    ) as mock_gate:
        result = await l3_aggregate(
            {"session_id": "s1", "run_id": "r1", "context_version": "v1", "context_ref": {"session_id": "s1", "version": "v1"}},
            base_dir=str(tmp_path),
        )

    assert mock_gate.called
    assert mock_write.call_args.args[0].run_id == "r1"
    assert result["l3_program_ref"]["artifact_type"] == "PlanningProgram"
    assert result["artifact_refs"]["planning_program"]["artifact_type"] == "PlanningProgram"
    assert result["l3_gate_decision"]["stage"] == "l3"
    assert result["l3_review_id"] == "review-1"
