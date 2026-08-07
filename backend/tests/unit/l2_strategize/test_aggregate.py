"""L2 aggregate tests - merge fragments -> L2Strategy + gate + review."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.agent.l2_strategize.aggregate import l2_aggregate, merge_strategy_fragments
from app.agent.l2_strategize.gate import evaluate_l2_gate as real_evaluate_l2_gate
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l2_contracts import (
    L2Strategy,
    L2StrategyFragment,
)
from app.modules.schema.contracts.provenance import Provenance


def _frag(dim, *, goals=None, strategies=None, spatial_structure="", gaps=None):
    return L2StrategyFragment(
        dimension_key=dim,
        goals=goals or [],
        strategies=strategies or [],
        priorities=[],
        conflicts=[],
        evidence_gaps=gaps or [],
        strategy_issues=[],
        spatial_structure=spatial_structure,
        provenance=Provenance(
            source="l2_observe",
            run_id="r1",
            module="l2_strategize",
            trace=[f"fragment:{dim}"],
        ),
    )


def test_merge_strategy_fragments():
    f1 = _frag("planning_positioning", goals=["定位1"], spatial_structure="集聚提升类")
    f2 = _frag(
        "planning_strategies",
        goals=["定位1", "人口2000人"],
        strategies=["生态优先策略", "产业振兴策略"],
        gaps=[
            EvidenceGap(
                gap_id="g1",
                dimension="planning_strategies",
                description="缺人口数据",
                severity="warning",
            )
        ],
    )
    s = merge_strategy_fragments([f1, f2], run_id="r1")
    assert isinstance(s, L2Strategy)
    assert s.development_goals == ["定位1", "人口2000人"]
    assert s.implementation_priorities == ["生态优先策略", "产业振兴策略"]
    assert s.spatial_structure == "集聚提升类"
    assert len(s.dimension_provenance) == 2
    assert len(s.evidence_gaps) == 1
    assert [src.reference for src in s.sources] == ["l2_observe"]


@pytest.mark.asyncio
async def test_l2_aggregate_returns_refs(tmp_path, monkeypatch):
    fake_reports = {
        2: {
            "planning_strategies": {
                "content": "【规划策略】\n- 生态优先策略\n- 产业振兴策略\n",
                "summary": "",
                "report_id": "rpt-1",
            },
            "planning_positioning": {
                "content": "村庄分类：集聚提升类\nXX生态文化村\n",
                "summary": "",
                "report_id": "rpt-2",
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
        "app.agent.l2_strategize.aggregate.write_review_package",
        return_value="review-1",
    ) as mock_write, patch(
        "app.agent.l2_strategize.aggregate.evaluate_l2_gate",
        wraps=real_evaluate_l2_gate,
    ) as mock_gate:
        result = await l2_aggregate(
            {"session_id": "s1", "run_id": "r1", "context_version": "v1", "context_ref": {"session_id": "s1", "version": "v1"}},
            base_dir=str(tmp_path),
        )

    assert mock_gate.called
    assert mock_write.call_args.args[0].run_id == "r1"
    assert result["l2_strategy_ref"]["artifact_type"] == "L2Strategy"
    assert result["artifact_refs"]["l2_strategy"]["artifact_type"] == "L2Strategy"
    assert result["l2_gate_decision"]["stage"] == "l2"
    assert result["l2_review_id"] == "review-1"
