# GIS 系统全面落地设计文档

## Context

GIS_LAYOUT_ARCHITECTURE_V2.md 描述了 Trinity 架构（KG + Agent + 空间生成器），代码层面三层均已实现，但存在5个关键的"存量未激活"问题：CA Refiner 未集成、验证闭环缺失、Agent prompt 模板名错误、SSE 进度推送缺失、MIP solver 约束执行 bug。本文档修复这些差距，使系统达到 V2 文档的设计目标。

## 修改范围

| 差距 | 文件 | 操作 | Sprint |
|------|------|------|--------|
| CA Refiner 未集成 | `layout/engine.py` | 新增 CA 调用 | 1 |
| _enforce_constraints bug | `layout/optimizer/mip_solver.py` | 修复 zone_areas 更新 | 1 |
| 验证闭环缺失 | `layout/engine.py` | 新增 validate→adjust 循环 | 2 |
| Agent prompt 模板名错误 | `agent/gis/prompts.py` | 修正查询示例 | 2 |
| Agent tool docstring | `tools/gis/layout_tools.py` | 补充模板列表 | 2 |
| SSE 进度推送缺失 | `layout/engine.py`, `utils/sse_publisher.py` | 注入事件 | 3 |

---

## Sprint 1: 内部逻辑修复

### 1.1 CA Refiner 集成

**文件**: `backend/app/services/modules/gis/layout/engine.py`

**修改**: 在 `generate_layout()` 方法中，planning_zone 生成后加入 CA 精细化。

```python
# 在 _generate_planning_zones() 返回结果后：
if planning_zone_geojson and planning_zone_geojson.get("features"):
    # CA refinement for spatial coherence
    planning_zone_geojson = self._refine_planning_zones(planning_zone_geojson)
    layers["planning_zone"] = planning_zone_geojson
```

**新增方法**: `_refine_planning_zones(geojson)`

```python
def _refine_planning_zones(self, geojson: Dict[str, Any]) -> Dict[str, Any]:
    """Apply CA refinement to planning zone features.

    Closes gaps < 30m between same-type features and simplifies boundaries.
    Falls back to original if area conservation fails (>1% loss).
    """
    try:
        from .optimizer.ca_refiner import ZoneCARefiner
        refiner = ZoneCARefiner(
            merge_distance_m=30.0,
            simplify_tolerance_m=10.0,
            iterations=3,
            min_area_ha=0.5,
        )
        original_area = refiner._total_area_ha(geojson["features"])
        refined = refiner.refine(geojson["features"])
        refined_area = refiner._total_area_ha(refined)

        if abs(original_area - refined_area) / max(original_area, 1) > 0.01:
            logger.warning("[Engine] CA area loss >1%%, reverting (%.1f → %.1f ha)",
                         original_area, refined_area)
            return geojson

        return {"type": "FeatureCollection", "features": refined}
    except Exception as e:
        logger.warning("[Engine] CA refinement failed, using original: %s", e)
        return geojson
```

### 1.2 MIP Solver _enforce_constraints bug fix

**文件**: `backend/app/services/modules/gis/layout/optimizer/mip_solver.py`

**问题**: 第 288-298 行，重新赋值 `self.assignments[bsm]` 后用 `self.assignments.get(bsm)` 读出的是新值，导致 `zone_areas[old_zone]` 减去的是新 zone 的面积。

**修复**:

```python
# Before (buggy):
if current_zone not in constrained_zones:
    self.assignments[bsm] = current_zone
else:
    self.assignments[bsm] = "农业用地"
old_zone = self.assignments.get(bsm, current_zone)  # BUG: reads new value
self.zone_areas[old_zone] = self.zone_areas.get(old_zone, 0) - area
self.zone_areas[self.assignments[bsm]] = self.zone_areas.get(self.assignments[bsm], 0) + area

# After (fixed):
old_zone = self.assignments.get(bsm, current_zone)  # Save BEFORE reassignment
if current_zone not in constrained_zones:
    new_zone = current_zone
else:
    new_zone = "农业用地"
self.assignments[bsm] = new_zone
self.zone_areas[old_zone] = self.zone_areas.get(old_zone, 0) - area
self.zone_areas[new_zone] = self.zone_areas.get(new_zone, 0) + area
```

---

## Sprint 2: Agent 闭环

### 2.1 Engine 验证→调整循环

**文件**: `backend/app/services/modules/gis/layout/engine.py`

**修改**: `full_pipeline()` 方法中，在 Phase 1 生成后添加最多 3 轮验证循环。

```python
def full_pipeline(self, ..., max_validation_rounds: int = 3):
    # ... Phase 0 (existing) ...

    # Phase 1: Generate layout
    configs = self.generate_layout(...)

    # Phase 1.5: Validate and re-optimize loop (NEW)
    from .validator import LayoutValidator
    validator = LayoutValidator()

    for round_num in range(max_validation_rounds):
        report = validator.validate(configs, self._kg_constraints)
        if report.status == "pass":
            logger.info("[Engine] Validation passed on round %d", round_num + 1)
            break

        # Extract adjustments from violations
        adjustments = self._violations_to_adjustments(report.violations)
        if not adjustments:
            break

        # Adjust targets and regenerate planning_zone only
        logger.info("[Engine] Validation round %d: %d violations, adjusting targets",
                    round_num + 1, report.total_violations)
        adjusted_targets = self._apply_adjustments(
            self._last_planning_targets, adjustments, damping=0.2 / (round_num + 1)
        )

        # Re-generate planning zone only (not the full layout)
        if landuse_current_geojson and self.has_kg():
            new_planning = self._generate_planning_zones_with_targets(
                intent, landuse_current_geojson, adjusted_targets
            )
            if new_planning:
                # Replace planning_zone layer in configs
                configs = self._replace_planning_zone_layer(configs, new_planning)

    return conflict_report, resolution_report, configs
```

**新增辅助方法**:

```python
def _violations_to_adjustments(self, violations):
    """Convert ValidationReport violations to target adjustments."""
    adjustments = {}
    for v in violations:
        if v.check == "area_constraint" and v.details:
            zone = v.details.get("zone", "")
            if "超过上限" in v.message:
                adjustments[zone] = {"action": "reduce", "excess": v.details.get("actual", 0) - v.details.get("limit", 0)}
            elif "低于下限" in v.message:
                adjustments[zone] = {"action": "increase", "shortfall": v.details.get("limit", 0) - v.details.get("actual", 0)}
    return adjustments

def _apply_adjustments(self, targets, adjustments, damping=0.2):
    """Adjust zone area targets based on violations."""
    adjusted = dict(targets)
    for zone, adj in adjustments.items():
        if zone not in adjusted:
            continue
        if adj["action"] == "reduce":
            adjusted[zone] -= adj.get("excess", 0) * damping
        elif adj["action"] == "increase":
            adjusted[zone] += adj.get("shortfall", 0) * damping
    return adjusted
```

### 2.2 Agent Prompt 修正

**文件**: `backend/app/agent/gis/prompts.py`

**修改**: `GIS_AGENT_SYSTEM_PROMPT` 中的查询示例。

```python
# Before (incorrect template names):
#   query_knowledge_graph("construction_cap")
#   query_knowledge_graph("farmland_min")
#   query_knowledge_graph("ecological_redline")

# After (correct template names):
#   query_knowledge_graph("get_constraint_by_field", field_name="construction")
#   query_knowledge_graph("get_constraint_by_field", field_name="farmland")
#   query_knowledge_graph("get_constraint_by_field", field_name="ecological")
```

同时增加可用模板说明：

```python
# 新增到 prompt 中：
# 可用查询模板:
# - get_constraints: 所有约束
# - get_constraint_by_field(field_name): 按字段查约束 (construction/farmland/ecological)
# - get_parcels_by_dlbm(dlbm): 按DLBM查地块
# - get_parcels_by_zone_type(zone_type): 按分区类型查地块
# - count_by_zone_type: 各分区地块统计
# - get_zone_restrictions: 分区限制规则
# - get_indicators: 规划指标
# - check_protected_parcels: 受保护地块
# - get_adjacent_parcels: 相邻地块
```

### 2.3 Tool Docstring 补充

**文件**: `backend/app/tools/gis/layout_tools.py`

**修改**: `query_knowledge_graph` tool 的 docstring 已包含9个模板列表（第335-344行），无需修改。但需验证实际可用模板与 docstring 一致。

---

## Sprint 3: SSE 进度推送

### 3.1 Engine 阶段事件注入

**文件**: `backend/app/services/modules/gis/layout/engine.py`

**方案**: 在 `full_pipeline()` 和 `generate_layout()` 的关键阶段调用 `sse_publisher`。

```python
def full_pipeline(self, ..., session_id: str = ""):
    from app.utils.sse_publisher import publish_gis_progress

    publish_gis_progress(session_id, "phase0_conflict_detection", "检测维度间冲突")
    conflict_report, resolution_report = self.detect_and_resolve(summaries)

    publish_gis_progress(session_id, "phase1_layout_generation", "生成空间布局图层")
    configs = self.generate_layout(...)

    publish_gis_progress(session_id, "phase1_validation", "验证布局合规性")
    # ... validation loop ...

    publish_gis_progress(session_id, "complete", "布局生成完成")
    return conflict_report, resolution_report, configs
```

### 3.2 SSE Publisher 扩展

**文件**: `backend/app/utils/sse_publisher.py`

**新增函数**: `publish_gis_progress(session_id, stage, message)`

```python
def publish_gis_progress(session_id: str, stage: str, message: str):
    """Publish a GIS layout generation progress event via SSE."""
    from app.services.sse import sse_manager

    if not session_id:
        return

    event_data = {
        "type": "gis_layout_progress",
        "stage": stage,
        "message": message,
    }
    sse_manager.publish(session_id, event_data)
```

### 3.3 generate_layout 内部阶段事件

在 `engine.py:generate_layout()` 中为每个图层生成推送事件：

```python
publish_gis_progress(session_id, "generating_function_zone", "生成功能分区图层")
# ... generate function_zone ...

publish_gis_progress(session_id, "generating_planning_zone", "生成规划分区图层")
# ... generate planning_zone + CA refine ...

publish_gis_progress(session_id, "generating_facility_point", "生成设施点图层")
# ... generate facility_point ...

publish_gis_progress(session_id, "generating_development_axis", "生成发展轴线图层")
# ... generate development_axis ...
```

需要将 `session_id` 作为参数传递到 `generate_layout()` 和 `full_pipeline()`。

---

## 验证方案

### Sprint 1 验证
```bash
# CA Refiner 集成测试
cd backend && python scripts/render_planning_layout.py
# 检查日志：[CARefiner] Iteration 1/2/3

# MIP bug 修复测试
python -m pytest tests/ -v -k "test_constraint"
```

### Sprint 2 验证
```bash
# Agent prompt 验证：手动运行 Agent 对话，确认模板名正确
# 验证闭环：构造故意违规的 targets，确认引擎自动修正
python -c "
from app.services.modules.gis.layout.engine import SpatialLayoutEngine
engine = SpatialLayoutEngine()
# ... 验证闭环逻辑 ...
"
```

### Sprint 3 验证
```bash
# SSE 推送测试
curl -N http://localhost:8000/api/sse/{session_id}
# 在另一个终端触发 GIS 生成
# 观察是否收到 gis_layout_progress 事件
```

### 回归测试
```bash
cd backend && python -m pytest tests/ -v
# 期望：所有现有测试通过 + 新功能测试通过
```

## 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| CA Refiner 面积守恒失败 | 中 | 低 | 回退到原始结果 |
| 验证循环不收敛 | 低 | 中 | 3轮硬上限 + damping 递减 |
| SSE 推送阻塞主流程 | 低 | 中 | SSE publish 是非阻塞的（fire-and-forget） |
| _enforce_constraints 修复引入新 bug | 低 | 中 | 添加单元测试覆盖 |
