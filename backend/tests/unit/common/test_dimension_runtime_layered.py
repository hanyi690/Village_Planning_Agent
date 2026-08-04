"""Tests for the layered cross-layer dependency helper (L3 split).

``load_layered_dependency_reports`` extends ``load_dependency_reports`` by
splitting the cross-layer deps of an L3 dimension into two separate strings:
L1 reports (``layer_depends_on``) and L2 reports (``phase_depends_on``),
instead of merging them. This lets the L3 worker feed ``analysis_report``
(L1) and ``planning_concept`` (L2) independently into the detailed prompt
template.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.common import dimension_runtime as dr


@pytest.mark.asyncio
async def test_load_layered_dependency_reports_splits_l1_l2_for_layer3():
    cfg = SimpleNamespace(
        depends_on=[],
        layer_depends_on=["land_use"],
        phase_depends_on=["planning_strategies"],
    )
    store = MagicMock()
    store.get_layer_reports = AsyncMock(
        side_effect=[
            {"land_use": "L1 土地利用报告内容"},
            {"planning_strategies": "L2 规划策略报告内容"},
        ]
    )
    with patch("app.services.report_store.ReportStore.get_instance", return_value=store):
        l1_deps, l2_deps, same_layer = await dr.load_layered_dependency_reports(
            "land_use_planning", cfg, 3, "s1", False
        )
    assert "L1 土地利用报告内容" in l1_deps
    assert "L2 规划策略报告内容" in l2_deps
    assert l1_deps != l2_deps
    assert "L2 规划策略报告内容" not in l1_deps
    assert "L1 土地利用报告内容" not in l2_deps
    assert same_layer == ""
    assert store.get_layer_reports.call_args_list[0].args[1] == 1
    assert store.get_layer_reports.call_args_list[1].args[1] == 2


@pytest.mark.asyncio
async def test_load_layered_dependency_reports_layer2_l2_deps_empty():
    cfg = SimpleNamespace(
        depends_on=[],
        layer_depends_on=["land_use"],
        phase_depends_on=["planning_strategies"],
    )
    store = MagicMock()
    store.get_layer_reports = AsyncMock(return_value={"land_use": "L1 土地利用报告内容"})
    with patch("app.services.report_store.ReportStore.get_instance", return_value=store):
        l1_deps, l2_deps, same_layer = await dr.load_layered_dependency_reports(
            "planning_strategies", cfg, 2, "s1", False
        )
    assert "L1 土地利用报告内容" in l1_deps
    assert l2_deps == ""
    assert same_layer == ""
    assert store.get_layer_reports.call_count == 1
    assert store.get_layer_reports.call_args_list[0].args[1] == 1
