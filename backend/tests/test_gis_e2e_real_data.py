"""GIS 系统端到端真实数据测试 — 金田村。

验证完整工作流：L3 报告 + 真实 GeoJSON → PlanningKG → SPARQL 查询 → 约束分配 → 多层布局 → 验证。

不使用 mock LLM。直接顺序调用工具，模拟理想 ReAct 路径。
真实数据：660 地块、12 维度 L3 报告、7 个 GIS 图层。
"""

import json
import pytest
from langgraph.types import Command
from langchain_core.messages import ToolMessage

from app.services.modules.gis.layout.kg import PlanningKG
from app.services.modules.gis.layout.kg.query import query_kg, QUERY_TEMPLATES
from app.services.modules.gis.layout.optimizer import ConstraintDrivenAllocator
from app.services.modules.gis.layout.engine import SpatialLayoutEngine
from app.services.modules.gis.layout.validator import LayoutValidator
from app.services.modules.gis.layout.planning_intent import Direction, Density
from app.tools.gis.layout_tools import (
    build_knowledge_graph,
    query_knowledge_graph,
    detect_conflicts,
    allocate_zones,
    generate_layout,
    validate_layout,
    _dict_to_intent,
)
from tests.fixtures.gis_e2e import (
    load_landuse_current,
    load_boundary,
    load_protection_zones,
    load_road_current,
    load_construction_zone,
    load_hazard_points,
    load_l3_reports_for_kg,
    load_gis_data_for_agent,
    make_real_intent,
)


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    """Build full ToolCall dict required by InjectedToolCallId."""
    return {"name": name, "args": args, "type": "tool_call", "id": call_id}


def _extract_result(command: Command) -> dict:
    """Extract result payload from Command.update["messages"][0].content."""
    assert isinstance(command, Command), f"Expected Command, got {type(command)}"
    messages = command.update.get("messages", [])
    assert len(messages) > 0, "Command.update has no messages"
    assert isinstance(messages[0], ToolMessage), f"Expected ToolMessage, got {type(messages[0])}"
    return json.loads(messages[0].content)


# ============================================
# 测试 1：PlanningKG 真实构建
# ============================================

class TestKGBuildFromRealData:
    """验证 PlanningKG.build_from_reports 在真实金田村数据上构建成功。"""

    def test_kg_has_600_plus_triples(self, l3_reports_for_kg, landuse_geojson):
        """KG 应包含 ≥600 triples（660 parcels × ~10 triples/parcel + constraints）。"""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)

        triple_count = kg.get_triple_count()
        assert triple_count >= 600, f"Expected ≥600 triples, got {triple_count}"
        assert kg._parcel_count == 660, f"Expected 660 parcels, got {kg._parcel_count}"

    def test_kg_has_real_constraints(self, l3_reports_for_kg, landuse_geojson):
        """KG 应从 L3 报告提取 ≥3 个约束（construction_cap, farmland_min, ecological_redline_min）。"""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)

        constraints = kg.get_constraints()
        assert len(constraints) >= 3, f"Expected ≥3 constraints, got {len(constraints)}"

        # 验证包含关键约束类型
        constraint_fields = {c.get("field", "") for c in constraints}
        assert "construction_area_ha" in constraint_fields, "Missing construction_area_ha constraint"
        assert "farmland_area_ha" in constraint_fields, "Missing farmland_area_ha constraint"
        assert "ecological_redline_ha" in constraint_fields, "Missing ecological_redline_ha constraint"

    def test_kg_turtle_serialization_roundtrip(self, l3_reports_for_kg, landuse_geojson):
        """KG Turtle 序列化/反序列化应保留所有 triples。"""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)

        turtle_str = kg.to_turtle()
        assert len(turtle_str) > 1000, f"Turtle string too short: {len(turtle_str)}"

        kg2 = PlanningKG.from_turtle(turtle_str, village_name="金田村")
        assert kg2.get_triple_count() == kg.get_triple_count(), "Turtle roundtrip lost triples"


# ============================================
# 测试 2：SPARQL 查询返回真实结果
# ============================================

class TestSPARQLQueryRealKG:
    """验证 SPARQL 查询模板在真实 KG 上返回非空结果。"""

    @pytest.fixture(scope="class")
    def real_kg(self, l3_reports_for_kg, landuse_geojson):
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        return kg

    def test_get_constraints_returns_non_empty(self, real_kg):
        """get_constraints 模板应返回 ≥3 个约束。"""
        results = query_kg(real_kg, "get_constraints")
        assert len(results) >= 3, f"Expected ≥3 constraints, got {len(results)}"

    def test_count_by_zone_type_returns_parcels(self, real_kg):
        """count_by_zone_type 应返回各 zone_type 的地块统计。"""
        results = query_kg(real_kg, "count_by_zone_type")
        assert len(results) > 0, "Expected non-empty zone_type count"
        # 至少应包含农业用地或生态绿地
        zone_types = {r.get("zone_type", "") for r in results}
        assert any(zt for zt in zone_types), "No zone_type in results"

    def test_get_parcels_by_dlbm_returns_parcel(self, real_kg):
        """get_parcels_by_dlbm(dlbm='2121') 应返回宅基地地块。"""
        results = query_kg(real_kg, "get_parcels_by_dlbm", dlbm="2121")
        assert len(results) > 0, "Expected non-empty parcels for DLBM=2121"

    def test_get_indicators_returns_values(self, real_kg):
        """get_indicators 应返回规划指标。"""
        results = query_kg(real_kg, "get_indicators")
        assert len(results) > 0, "Expected non-empty indicators"


# ============================================
# 测试 3：约束驱动分配在真实 660 地块上
# ============================================

class TestAllocateZonesRealLanduse:
    """验证 ConstraintDrivenAllocator 在真实 660 地块上工作。

    Bug A 暴露：engine.py 传入 4 个分区名，allocator 期望 7 个 zone_type。
    修复前：所有地块落到 _fill_unassigned 兜底（assigned_zone = current_zone）。
    修复后：allocator 能正确按 4 个分区名分配。
    """

    def test_allocate_returns_660_features(self, landuse_geojson, l3_reports_for_kg):
        """分配器应返回 660 个 features（每个地块都有 assigned_zone）。"""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        constraints = kg.get_constraints()

        # 使用 4 个规划分区名（engine.py 当前的做法）
        targets = {
            "永久基本农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农地区": 1881.54,
        }

        allocator = ConstraintDrivenAllocator()
        result = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets,
            constraints=constraints,
            mode="greedy",
        )

        features = result.get("features", [])
        assert len(features) > 0, "Allocator returned no features"

        # 每个 feature 都应有 assigned_zone
        for f in features:
            assert "assigned_zone" in f.get("properties", {}), "Feature missing assigned_zone"

    def test_allocate_assigned_zone_is_planning_zone_name(self, landuse_geojson):
        """Bug B 修复后：assigned_zone 应是 4 个规划分区名之一。"""
        targets = {
            "永久基本农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农地区": 1881.54,
        }

        allocator = ConstraintDrivenAllocator()
        result = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets,
            constraints=[],
            mode="greedy",
        )

        valid_zones = {"永久基本农田保护区", "村庄建设区", "生态保护区", "一般农地区"}
        features = result.get("features", [])
        assigned_zones = {f["properties"].get("assigned_zone", "") for f in features}
        # 修复后应全部是 4 个分区名
        non_valid = assigned_zones - valid_zones
        assert not non_valid, f"assigned_zone contains non-planning-zone names: {non_valid}"


# ============================================
# 测试 4：SpatialLayoutEngine 完整布局生成
# ============================================

class TestGenerateLayoutRealPipeline:
    """验证 SpatialLayoutEngine.generate_layout 在真实数据上生成多图层。"""

    def test_generate_layout_produces_multiple_layers(
        self, landuse_geojson, boundary_geojson, protection_zones,
        road_geojson, hazard_points_geojson, l3_reports_for_kg
    ):
        """generate_layout 应生成 ≥3 个图层配置。"""
        engine = SpatialLayoutEngine()
        engine.build_kg(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)

        intent = _dict_to_intent(make_real_intent())

        configs = engine.generate_layout(
            intent=intent,
            boundary_geojson=boundary_geojson,
            landuse_current_geojson=landuse_geojson,
            protection_zones=protection_zones,
            road_geojson=road_geojson,
            hazard_points_geojson=hazard_points_geojson,
        )

        assert len(configs) >= 3, f"Expected ≥3 layers, got {len(configs)}"

        # 验证每个 config 是有效的 GISLayerConfig
        layer_types = set()
        for c in configs:
            assert "layerType" in c, f"Config missing layerType: {c.keys()}"
            # 配置可能用 "data" 或 "geojson" 字段存放 GeoJSON
            data = c.get("data") or c.get("geojson")
            assert data is not None, f"Config missing data/geojson: {c.keys()}"
            layer_types.add(c["layerType"])
            assert isinstance(data, dict), f"Layer {c['layerType']} data is not dict"

        # 应包含关键图层
        assert "boundary" in layer_types or "function_zone" in layer_types, \
            f"Missing boundary/function_zone layer, got: {layer_types}"

    def test_generate_layout_includes_planning_zone(
        self, landuse_geojson, boundary_geojson, protection_zones, l3_reports_for_kg
    ):
        """generate_layout 应包含 planning_zone 图层（KG 驱动的 4 分区）。"""
        engine = SpatialLayoutEngine()
        engine.build_kg(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)

        intent = _dict_to_intent(make_real_intent())

        configs = engine.generate_layout(
            intent=intent,
            boundary_geojson=boundary_geojson,
            landuse_current_geojson=landuse_geojson,
            protection_zones=protection_zones,
        )

        layer_types = {c["layerType"] for c in configs}
        assert "planning_zone" in layer_types, \
            f"Missing planning_zone layer, got: {layer_types}"


# ============================================
# 测试 5：LayoutValidator 在真实布局上
# ============================================

class TestValidateLayoutRealOutput:
    """验证 LayoutValidator 在真实生成的布局上工作。"""

    @pytest.fixture(scope="class")
    def real_layout_and_constraints(
        self, landuse_geojson, boundary_geojson, protection_zones,
        road_geojson, hazard_points_geojson, l3_reports_for_kg
    ):
        """生成真实布局和约束供测试共享。"""
        engine = SpatialLayoutEngine()
        engine.build_kg(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        constraints = engine._kg_constraints

        intent = _dict_to_intent(make_real_intent())
        configs = engine.generate_layout(
            intent=intent,
            boundary_geojson=boundary_geojson,
            landuse_current_geojson=landuse_geojson,
            protection_zones=protection_zones,
            road_geojson=road_geojson,
            hazard_points_geojson=hazard_points_geojson,
        )
        return configs, constraints

    def test_validator_returns_report(self, real_layout_and_constraints):
        """LayoutValidator 应返回 ValidationReport 对象。"""
        configs, constraints = real_layout_and_constraints
        validator = LayoutValidator()
        report = validator.validate(configs, constraints)

        assert report.status in ("pass", "fail", "warning"), \
            f"Invalid status: {report.status}"
        assert len(report.checks) == 5, f"Expected 5 checks, got {len(report.checks)}"

    def test_validator_area_constraints_check_runs(self, real_layout_and_constraints):
        """area_constraints 检查应运行（无论 pass/fail）。"""
        configs, constraints = real_layout_and_constraints
        validator = LayoutValidator()
        report = validator.validate(configs, constraints)

        area_check = next(
            (c for c in report.checks if c.check_name == "area_constraints"), None
        )
        assert area_check is not None, "Missing area_constraints check"

    def test_validator_zone_completeness_with_real_layout(self, real_layout_and_constraints):
        """zone_completeness 检查应运行。"""
        configs, constraints = real_layout_and_constraints
        validator = LayoutValidator()
        report = validator.validate(configs, constraints)

        completeness_check = next(
            (c for c in report.checks if c.check_name == "zone_completeness"), None
        )
        assert completeness_check is not None, "Missing zone_completeness check"


# ============================================
# 测试 6：工具层端到端（build_knowledge_graph → query_knowledge_graph）
# ============================================

class TestToolLayerEndToEnd:
    """验证 @tool 注解的工具在真实数据上工作。

    注：InjectedState 参数不能通过 tool.invoke() 直接传入（pydantic 验证报错）。
    测试通过调用底层 .func 函数验证工具逻辑正确性。
    LangGraph 在实际运行时通过 ToolNode 注入 state。
    """

    def test_build_and_query_via_tools(self, l3_reports_for_kg, gis_data):
        """build_knowledge_graph 工具应写入 kg_turtle，query_knowledge_graph 应能查询。"""
        # Step 1: build_knowledge_graph（调用底层 .func）
        cmd = build_knowledge_graph.func(
            reports=l3_reports_for_kg,
            gis_data=gis_data,
            village_name="金田村",
            tool_call_id="call-build-1",
        )

        # 验证 Command 写入 kg_turtle 和 kg_constraints
        assert isinstance(cmd, Command)
        assert "kg_turtle" in cmd.update, "build_knowledge_graph did not write kg_turtle"
        assert "kg_constraints" in cmd.update, "build_knowledge_graph did not write kg_constraints"
        assert len(cmd.update["kg_turtle"]) > 1000, "kg_turtle too short"
        assert len(cmd.update["kg_constraints"]) >= 3, "kg_constraints too short"

        # 验证 LLM 可见的结果
        result = _extract_result(cmd)
        assert result["success"] is True
        assert result["data"]["triple_count"] >= 600

        # Step 2: query_knowledge_graph（用 step 1 写入的 kg_turtle）
        cmd2 = query_knowledge_graph.func(
            template_name="get_constraints",
            field_name="",
            dlbm="",
            zone_type="",
            kg_turtle=cmd.update["kg_turtle"],
            tool_call_id="call-query-1",
        )

        result2 = _extract_result(cmd2)
        assert result2["success"] is True
        assert result2["data"]["result_count"] >= 3, \
            f"Expected ≥3 constraints, got {result2['data']['result_count']}"

    def test_allocate_zones_via_tool(self, gis_data, l3_reports_for_kg):
        """allocate_zones 工具应在真实数据上工作。"""
        targets = {
            "永久基本农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农地区": 1881.54,
        }
        # 先构建 KG 获取约束
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=gis_data["landuse_current_geojson"])
        constraints = kg.get_constraints()

        cmd = allocate_zones.func(
            targets=targets,
            constraints=constraints,
            mode="greedy",
            gis_data=gis_data,
            kg_constraints=constraints,
            tool_call_id="call-alloc-1",
        )

        result = _extract_result(cmd)
        assert result["success"] is True
        assert result["data"]["total_features"] > 0, "allocate_zones returned 0 features"
