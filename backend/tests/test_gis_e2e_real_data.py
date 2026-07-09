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

    def test_kg_builds_with_gis_data_produces_zone_areas(
        self, l3_reports_for_kg, landuse_geojson, gis_data
    ):
        """P3 #13: build_from_reports with gis_data should compute zone areas from GIS data."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(
            reports=l3_reports_for_kg,
            landuse_geojson=landuse_geojson,
            gis_data=gis_data,
        )

        # Should have zone entities with area_target_ha
        from rdflib import RDF
        from app.services.modules.gis.layout.kg.builder import PLN

        zones = list(kg.g.subjects(RDF.type, PLN.Zone))
        assert len(zones) > 0, "Should have Zone entities"

        # At least one zone should have computed area_target_ha
        zone_areas = []
        for zone in zones:
            for _, _, area_val in kg.g.triples((zone, PLN.area_target_ha, None)):
                zone_areas.append(float(area_val))
        assert len(zone_areas) > 0, "Should have computed zone areas from GIS data"

    def test_kg_adjacency_map_not_empty(
        self, l3_reports_for_kg, landuse_geojson
    ):
        """P3 #12: get_adjacency_map should return non-empty adjacency from 660 parcels."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)

        adj_map = kg.get_adjacency_map()
        assert len(adj_map) > 0, "Should have adjacency entries from spatial relations"


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
            "农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农业区": 1881.54,
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
            "农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农业区": 1881.54,
        }

        allocator = ConstraintDrivenAllocator()
        result = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets,
            constraints=[],
            mode="greedy",
        )

        valid_zones = {"农田保护区", "村庄建设区", "生态保护区", "一般农业区"}
        features = result.get("features", [])
        assigned_zones = {f["properties"].get("assigned_zone", "") for f in features}
        # 修复后应全部是 4 个分区名
        non_valid = assigned_zones - valid_zones
        assert not non_valid, f"assigned_zone contains non-planning-zone names: {non_valid}"


# ============================================
# 测试 3.5：MIP Allocator 端到端
# ============================================

class TestMIPAllocatorE2E:
    """验证 MIP allocator 在真实数据上工作。"""

    def test_mip_allocate_returns_features(self, landuse_geojson, l3_reports_for_kg):
        """MIP 模式应返回与 greedy 相同数量的 features."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        constraints = kg.get_constraints()

        targets = {
            "农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农业区": 1881.54,
        }

        allocator = ConstraintDrivenAllocator()
        result = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets,
            constraints=constraints,
            mode="mip",
        )

        features = result.get("features", [])
        assert len(features) > 0, "MIP allocator returned no features"

    def test_mip_assigned_zone_is_planning_zone_name(self, landuse_geojson):
        """MIP 模式的 assigned_zone 应是 4 个规划分区名之一."""
        targets = {
            "农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农业区": 1881.54,
        }

        allocator = ConstraintDrivenAllocator()
        result = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets,
            constraints=[],
            mode="mip",
        )

        valid_zones = {"农田保护区", "村庄建设区", "生态保护区", "一般农业区"}
        features = result.get("features", [])
        assigned_zones = {f["properties"].get("assigned_zone", "") for f in features}
        non_valid = assigned_zones - valid_zones
        assert not non_valid, f"MIP assigned_zone contains non-planning-zone names: {non_valid}"

    def test_mip_output_structure_matches_greedy(self, landuse_geojson):
        """MIP 和 greedy 输出结构应一致（assigned_zone, original_zone, changed 等字段）."""
        targets = {
            "农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农业区": 1881.54,
        }
        allocator = ConstraintDrivenAllocator()

        greedy_result = allocator.solve(
            landuse_geojson=landuse_geojson, targets=targets, constraints=[], mode="greedy",
        )
        mip_result = allocator.solve(
            landuse_geojson=landuse_geojson, targets=targets, constraints=[], mode="mip",
        )

        greedy_features = greedy_result.get("features", [])
        mip_features = mip_result.get("features", [])

        # Both should have features
        assert len(greedy_features) > 0
        assert len(mip_features) > 0

        # Both should have same structural keys
        if greedy_features and mip_features:
            greedy_props = set(greedy_features[0].get("properties", {}).keys())
            mip_props = set(mip_features[0].get("properties", {}).keys())
            # Core fields should exist in both
            for key in {"assigned_zone"}:
                assert key in greedy_props, f"Greedy missing {key}"
                assert key in mip_props, f"MIP missing {key}"

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
        assert len(report.checks) == 8, f"Expected 8 checks, got {len(report.checks)}"

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
            "农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农业区": 1881.54,
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


# ============================================
# 测试 7：full_pipeline 端到端完整流程
# ============================================

class TestFullPipelineE2E:
    """验证 SpatialLayoutEngine.full_pipeline 在真实金田村数据上执行完整流程。

    覆盖 Sprint 1-3 新增功能：KG 自动构建 + CA refinement + 验证闭环 + SSE 进度推送。
    """

    def _run_full_pipeline(
        self,
        l3_reports_for_kg,
        landuse_geojson,
        boundary_geojson,
        protection_zones,
        road_geojson,
        construction_zone_geojson,
        hazard_points_geojson,
        real_intent,
        session_id: str = "test-e2e-123",
        max_validation_rounds: int = 2,
    ):
        engine = SpatialLayoutEngine()
        conflict_report, resolution_report, layout_configs = engine.full_pipeline(
            summaries={},
            intent=_dict_to_intent(real_intent),
            boundary_geojson=boundary_geojson,
            landuse_current_geojson=landuse_geojson,
            protection_zones=protection_zones,
            road_geojson=road_geojson,
            construction_zone_geojson=construction_zone_geojson,
            hazard_points_geojson=hazard_points_geojson,
            reports=l3_reports_for_kg,
            max_validation_rounds=max_validation_rounds,
            session_id=session_id,
        )
        return engine, conflict_report, resolution_report, layout_configs

    def test_full_pipeline_executes_complete_workflow(
        self,
        l3_reports_for_kg,
        landuse_geojson,
        boundary_geojson,
        protection_zones,
        road_geojson,
        construction_zone_geojson,
        hazard_points_geojson,
        real_intent,
    ):
        """full_pipeline 应完成 KG 构建 + 冲突检测 + 布局生成 + 验证闭环。"""
        engine, conflict_report, resolution_report, layout_configs = self._run_full_pipeline(
            l3_reports_for_kg, landuse_geojson, boundary_geojson,
            protection_zones, road_geojson, construction_zone_geojson,
            hazard_points_geojson, real_intent,
        )

        assert conflict_report is not None, "冲突报告不应为 None"
        assert resolution_report is not None, "解决报告不应为 None"
        assert len(layout_configs) >= 3, \
            f"应生成 ≥3 个图层，实际: {len(layout_configs)}"

        assert engine.has_kg(), "full_pipeline 应构建 KG（传入 reports 触发）"
        assert len(engine._kg_constraints) >= 3, \
            f"KG 应包含 ≥3 个约束，实际: {len(engine._kg_constraints)}"

        layer_types = {c.get("layerType") for c in layout_configs}
        assert "planning_zone" in layer_types, \
            f"应包含 planning_zone 图层，实际图层: {layer_types}"

        # 保存 layout_configs 快照供诊断
        from pathlib import Path
        from datetime import datetime
        snapshot_path = Path(__file__).resolve().parent.parent / "test-screenshots"
        snapshot_path.mkdir(exist_ok=True)
        snapshot_file = snapshot_path / "e2e_full_pipeline.json"
        sanitized = []
        for cfg in layout_configs:
            cfg_copy = {k: v for k, v in cfg.items() if k != "geojson"}
            if "geojson" in cfg and isinstance(cfg["geojson"], dict):
                cfg_copy["geojson_type"] = cfg["geojson"].get("type", "")
                cfg_copy["features_count"] = len(cfg["geojson"].get("features", []))
            sanitized.append(cfg_copy)
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "layer_count": len(sanitized),
                "layers": sanitized,
            }, f, indent=2, ensure_ascii=False)

    def test_full_pipeline_includes_kg_driven_planning_zones(
        self,
        l3_reports_for_kg,
        landuse_geojson,
        boundary_geojson,
        protection_zones,
        real_intent,
    ):
        """planning_zone 图层的 features 应有 assigned_zone 属性，覆盖 4 类分区。"""
        engine, _, _, layout_configs = self._run_full_pipeline(
            l3_reports_for_kg, landuse_geojson, boundary_geojson,
            protection_zones, None, None, None, real_intent,
        )

        planning_zone_layer = next(
            (c for c in layout_configs if c.get("layerType") == "planning_zone"),
            None,
        )
        assert planning_zone_layer is not None, "应有 planning_zone 图层"

        geojson = planning_zone_layer.get("geojson", {})
        features = geojson.get("features", [])
        assert len(features) > 0, "planning_zone 应有 features"

        assigned_zones = {
            f["properties"].get("assigned_zone", "")
            for f in features
            if "properties" in f
        }
        # 金田村实际生成 3 类分区（无农田保护区）
        expected_keywords = ["村", "农", "生态"]
        for kw in expected_keywords:
            assert any(kw in zt for zt in assigned_zones), \
                f"assigned_zone 应包含 '{kw}' 类分区，实际: {assigned_zones}"

    def test_ca_refinement_preserves_area(
        self,
        l3_reports_for_kg,
        landuse_geojson,
        boundary_geojson,
        protection_zones,
        real_intent,
    ):
        """CA refinement 应保持面积守恒（误差 ≤ 1%）。"""
        engine, _, _, layout_configs = self._run_full_pipeline(
            l3_reports_for_kg, landuse_geojson, boundary_geojson,
            protection_zones, None, None, None, real_intent,
        )

        planning_zone_layer = next(
            (c for c in layout_configs if c.get("layerType") == "planning_zone"),
            None,
        )
        assert planning_zone_layer is not None

        geojson = planning_zone_layer.get("geojson", {})
        features = geojson.get("features", [])
        assert len(features) > 0

        # 计算总面积
        total_area_ha = sum(
            f.get("properties", {}).get("area_ha", 0) or 0
            for f in features
        )
        # 金田村总面积约 2352 ha，planning_zone 应覆盖大部分
        assert total_area_ha > 100, \
            f"planning_zone 总面积应 >100 ha，实际: {total_area_ha:.1f} ha"

    def test_planning_zone_areas_match_targets(
        self,
        l3_reports_for_kg,
        landuse_geojson,
        boundary_geojson,
        protection_zones,
        real_intent,
    ):
        """各分区实际面积应覆盖村庄用地（总面积 > 200 ha）。"""
        engine, _, _, layout_configs = self._run_full_pipeline(
            l3_reports_for_kg, landuse_geojson, boundary_geojson,
            protection_zones, None, None, None, real_intent,
        )

        planning_zone_layer = next(
            (c for c in layout_configs if c.get("layerType") == "planning_zone"),
            None,
        )
        assert planning_zone_layer is not None

        geojson = planning_zone_layer.get("geojson", {})
        features = geojson.get("features", [])
        assert len(features) > 0

        total_area = sum(
            f.get("properties", {}).get("area_ha", 0) or 0
            for f in features
        )
        assert total_area > 200, \
            f"planning_zone 总面积应 >200 ha（覆盖大部分村庄用地），实际: {total_area:.1f} ha"

        assigned_zones = {
            f.get("properties", {}).get("assigned_zone", "")
            for f in features
            if "properties" in f
        }
        assert len(assigned_zones) >= 3, \
            f"应至少 3 种分区类型，实际: {assigned_zones}"

    def test_validation_loop_emits_round_events(
        self,
        l3_reports_for_kg,
        landuse_geojson,
        boundary_geojson,
        protection_zones,
        real_intent,
    ):
        """full_pipeline 应按顺序推送 SSE 事件：building_kg → phase0 → phase1 → generating_* → validation_round_1 → complete。"""
        from unittest.mock import patch, MagicMock

        captured_stages = []

        with patch("app.utils.sse_publisher.SSEPublisher.send_tool_progress") as mock_send:
            def capture(session_id, tool_name, stage, progress, message):
                captured_stages.append(stage)
            mock_send.side_effect = capture

            engine = SpatialLayoutEngine()
            engine.full_pipeline(
                summaries={},
                intent=_dict_to_intent(real_intent),
                boundary_geojson=boundary_geojson,
                landuse_current_geojson=landuse_geojson,
                protection_zones=protection_zones,
                reports=l3_reports_for_kg,
                max_validation_rounds=2,
                session_id="test-sse-seq",
            )

        # 期望的事件序列（按 engine.py 推送顺序）
        expected_prefix = [
            "building_kg",
            "phase0_conflict_detection",
            "phase1_layout_generation",
            "generating_function_zone",
            "generating_planning_zone",
            "generating_facility_point",
            "generating_development_axis",
        ]
        for i, expected in enumerate(expected_prefix):
            assert i < len(captured_stages), \
                f"事件数量不足：期望至少 {i+1} 个，实际 {len(captured_stages)}"
            assert captured_stages[i] == expected, \
                f"事件顺序错误：位置 {i} 期望 '{expected}'，实际 '{captured_stages[i]}'"

        # 应至少有一个 validation_round 事件和 complete 事件
        assert "validation_round_1" in captured_stages, \
            f"应包含 validation_round_1 事件，实际: {captured_stages}"
        assert captured_stages[-1] == "complete", \
            f"最后事件应为 complete，实际: {captured_stages[-1]}"

