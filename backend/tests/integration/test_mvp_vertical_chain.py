"""MVP 纵向链骨架测试（smoke/type 级，无重型计算）。

本文件只做轻量断言：
  - 夹具目录/文件存在且可解析（GeoJSON 仅用 json 解析，不加载 geopandas）；
  - typed artifacts 可导入（app.modules.schema.contracts.*）；
  - 后 L3 链构建函数可导入；
  - planning context 构建函数可导入（标记 slow，仅 import 不调用）。

不调用 LLM、不打开数据库、不运行 LangGraph 链、不加载 GIS 重型计算。

运行：cd backend && python -m pytest tests/integration/test_mvp_vertical_chain.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_GIS_FILENAMES = (
    "admin_boundary_line.geojson",
    "annotation.geojson",
    "boundary.geojson",
    "construction_zone.geojson",
    "ecological_protection.geojson",
    "farmland_protection.geojson",
    "geological_hazard_points.geojson",
    "historical_protection.geojson",
    "landuse.geojson",
    "road.geojson",
)


@pytest.fixture(scope="module")
def mvp_village_dir() -> Path:
    """解析 MVP 金田村固定回放夹具目录。"""
    return _BACKEND_DIR / "tests" / "fixtures" / "mvp_village"


def test_fixture_files_present(mvp_village_dir: Path) -> None:
    gis_dir = mvp_village_dir / "gis"
    assert gis_dir.is_dir()
    missing = [
        name for name in _GIS_FILENAMES if not (gis_dir / name).is_file()
    ]
    assert not missing, f"missing gis files: {missing}"
    assert (mvp_village_dir / "current_report.md").is_file()


def test_fixture_gis_files_readable(mvp_village_dir: Path) -> None:
    gis_dir = mvp_village_dir / "gis"
    for name in _GIS_FILENAMES:
        data = json.loads((gis_dir / name).read_text(encoding="utf-8-sig"))
        assert isinstance(data.get("features"), list), name


def test_report_markdown_readable(mvp_village_dir: Path) -> None:
    report = mvp_village_dir / "current_report.md"
    text = report.read_text(encoding="utf-8-sig")
    assert text.strip(), "current_report.md is empty"
    assert "金田村" in text
    assert "现状报告" in text


def test_mvp_artifacts_importable() -> None:
    from app.modules.schema.contracts.delivery_manifest_contracts import (
        DeliveryManifest,
    )
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan
    from app.modules.schema.contracts.grounding_contracts import GroundingResult
    from app.modules.schema.contracts.l1_contracts import L1Snapshot
    from app.modules.schema.contracts.l2_contracts import L2Strategy
    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    from app.modules.schema.contracts.parcel_change_contracts import (
        ParcelChangeSet,
    )
    from app.modules.schema.contracts.parse_result_contracts import (
        IntentCompilationResult,
    )
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.reconciliation_contracts import (
        ReconciliationReport,
    )
    from app.modules.schema.contracts.selection_contracts import (
        SiteSelectionDecision,
    )
    from app.modules.schema.contracts.validation_report_contracts import (
        ValidationReport,
    )

    artifacts = {
        "L1Snapshot": L1Snapshot,
        "L2Strategy": L2Strategy,
        "PlanningProgram": PlanningProgram,
        "IntentCompilationResult": IntentCompilationResult,
        "GroundingResult": GroundingResult,
        "SiteSelectionDecision": SiteSelectionDecision,
        "ExecutionPlan": ExecutionPlan,
        "ParcelChangeSet": ParcelChangeSet,
        "PlannedState": PlannedState,
        "ValidationReport": ValidationReport,
        "ReconciliationReport": ReconciliationReport,
        "DeliveryManifest": DeliveryManifest,
    }
    for name, cls in artifacts.items():
        assert cls is not None, name


def test_post_l3_chain_constructible() -> None:
    from app.agent.bootstrap.post_l3_chain import build_post_l3_chain

    assert callable(build_post_l3_chain)


@pytest.mark.slow
def test_context_smoke() -> None:
    from app.services.context.planning_context import build_planning_context

    assert callable(build_planning_context)
