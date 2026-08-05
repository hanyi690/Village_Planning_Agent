"""Acceptance tests for Stage-2 evidence-backed structuring."""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

from app.modules.spatial_ops.road.schemas import Stage2StructureConfig
from app.modules.spatial_ops.road.text_structurer import structure_road_requirements


def _write_workbook(path: Path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "需求表"
    sheet.append([
        "类型",
        "设施名称",
        "数量",
        "是否独立用地",
        "所在空间位置（自然村）",
        "服务对象",
        "覆盖程度（户）",
        "备注",
    ])
    sheet.append(["公共服务设施", "卫生站", "", "是", "村东产业区", "服务本村", "覆盖全村", "新建"])
    sheet.append([
        "基础设施",
        "道路交通",
        "村道硬化",
        "是",
        "①甲村-乙村",
        "服务本村",
        "覆盖全村",
        "①新增4m宽，1.5km长",
    ])
    workbook.save(path)


def _write_geojson(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [115.0, 24.0]},
                        "properties": {"name": "甲村"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _config(tmp_path: Path, output_name: str) -> Stage2StructureConfig:
    workbook = tmp_path / "需求.xlsx"
    if not workbook.exists():
        _write_workbook(workbook)
    project_document = tmp_path / "项目.md"
    project_document.write_text("# 项目说明\n", encoding="utf-8")
    constraint_document = tmp_path / "规划.md"
    constraint_document.write_text(
        "生态保护红线范围内严禁开发建设。\n"
        "生产建设活动应尽可能避免地质灾害区域。\n",
        encoding="utf-8",
    )
    location_source = tmp_path / "current_points.geojson"
    _write_geojson(location_source)
    return Stage2StructureConfig(
        demand_workbook=workbook,
        current_workbook=None,
        project_documents=(project_document,),
        constraint_documents=(constraint_document,),
        location_sources=(location_source,),
        output_dir=tmp_path / output_name,
        village_name="测试村",
    )


def test_unresolved_place_is_null_and_blocks_automatic_planning(tmp_path: Path) -> None:
    result = structure_road_requirements(_config(tmp_path, "run"))
    demands = json.loads(result.demand_points_path.read_text(encoding="utf-8"))["features"]
    projects = json.loads(result.road_projects_path.read_text(encoding="utf-8"))["projects"]

    health = next(item for item in demands if item["properties"]["demand_type"] == "healthcare")
    assert health["geometry"] is None
    assert health["properties"]["location_status"] == "unresolved"
    assert health["properties"]["evidence"]["source_row"] == 2
    assert health["properties"]["requires_human_confirmation"] is True

    assert len(projects) == 1
    project = projects[0]
    assert project["start_location_status"] == "matched"
    assert project["end_location_status"] == "unresolved"
    assert project["planning_status"] == "blocked_needs_location_confirmation"
    assert project["min_width_m"] == pytest.approx(4.0)
    assert project["proposed_length_m"] == pytest.approx(1500.0)
    assert project["evidence"]["source_cell_range"] == "需求表!A3:H3"


def test_constraints_keep_text_evidence_and_missing_buffer_requires_review(tmp_path: Path) -> None:
    result = structure_road_requirements(_config(tmp_path, "constraints"))
    constraints = json.loads(result.road_constraints_path.read_text(encoding="utf-8"))["constraints"]

    ecological = next(item for item in constraints if item["target_layer"] == "ecological_protection")
    hazard = next(item for item in constraints if item["target_layer"] == "geological_hazard_points")
    assert ecological["severity"] == "hard"
    assert "严禁开发建设" in ecological["evidence"]["source_text"]
    assert ecological["evidence"]["source_line"] == 1
    assert hazard["buffer_m"] is None
    assert hazard["requires_human_confirmation"] is True


def test_same_inputs_produce_identical_primary_outputs(tmp_path: Path) -> None:
    first = structure_road_requirements(_config(tmp_path, "first"))
    second = structure_road_requirements(_config(tmp_path, "second"))
    for first_path, second_path in (
        (first.demand_points_path, second.demand_points_path),
        (first.road_projects_path, second.road_projects_path),
        (first.road_constraints_path, second.road_constraints_path),
    ):
        assert first_path.read_bytes() == second_path.read_bytes()


def test_planned_road_geometry_is_rejected_as_location_source(tmp_path: Path) -> None:
    config = _config(tmp_path, "blocked")
    planned_road = tmp_path / "planned" / "road.geojson"
    planned_road.parent.mkdir()
    _write_geojson(planned_road)
    unsafe = Stage2StructureConfig(
        demand_workbook=config.demand_workbook,
        current_workbook=None,
        project_documents=config.project_documents,
        constraint_documents=config.constraint_documents,
        location_sources=(planned_road,),
        output_dir=config.output_dir,
    )
    with pytest.raises(ValueError, match="cannot be used for location matching"):
        unsafe.validate()
