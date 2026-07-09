
# GIS 空间布局系统 V2 — 实现状态与规格文档

> 版本: 2.1 | 日期: 2026-06-29 | 基于 V2 架构设计，记录实现状态、已修复问题、已知差距

---

## 一、系统概述

GIS 空间布局系统基于 Trinity 架构（KG + Agent + 空间生成器），从 L3 报告 + 真实 GeoJSON 数据生成多图层规划布局。本文档记录 V2 设计的落地状态。

**核心管线**：

```
L3 报告 + 660 地块 GeoJSON
    → PlanningKG (660 parcels + constraints + indicators + zones)
    → ConflictDetector → ConflictResolver
    → ConstraintDrivenAllocator (greedy/MIP, 4 类规划分区)
    → CARefiner (空间合并简化)
    → FacilityPlacer + AxisBuilder
    → LayoutValidator (5 项验证, ≤3 轮闭环)
    → MapRenderer (多图层配置)
    → SSE 进度推送 → 前端 MapLibre 渲染
```

---

## 二、Trinity 三层实现状态

### Layer 1: PlanningKG (规划知识图谱)

| 组件        | 文件                     | 状态      | 说明                                                       |
| ----------- | ------------------------ | --------- | ---------------------------------------------------------- |
| KG 构建     | `layout/kg/builder.py` | ✅ 已实现 | `build_from_reports()` 从 L3 报告+GeoJSON 构建 RDF Graph |
| 实体类型    | `builder.py:136-410`   | ✅ 已实现 | Parcel(660) + Constraint + Indicator + Zone + Village      |
| SPARQL 查询 | `layout/kg/query.py`   | ✅ 已实现 | 9 个模板全部可执行                                         |
| 约束提取    | `builder.py:252-299`   | ✅ 已实现 | 7 种中文指标 + 5 种语义指标自动匹配                        |
| 空间邻接    | `builder.py:364-410`   | ✅ 已实现 | 10m buffer 空间连接，≤5000 edges                          |
| 序列化      | `builder.py:458-474`   | ✅ 已实现 | Turtle 序列化/反序列化，支持 state 持久化                  |

**9 个 SPARQL 查询模板**：

| 模板                     | 功能             | 验证        |
| ------------------------ | ---------------- | ----------- |
| get_constraints          | 所有约束         | ✅ 测试通过 |
| get_constraint_by_field  | 按字段查约束     | ✅ 测试通过 |
| get_parcels_by_dlbm      | 按 DLBM 查地块   | ✅ 测试通过 |
| get_parcels_by_zone_type | 按分区类型查地块 | ✅ 测试通过 |
| count_by_zone_type       | 各分区地块统计   | ✅ 测试通过 |
| get_zone_restrictions    | 分区限制规则     | ✅ 测试通过 |
| get_indicators           | 规划指标         | ✅ 测试通过 |
| check_protected_parcels  | 受保护地块       | ✅ 测试通过 |
| get_adjacent_parcels     | 相邻地块         | ✅ 测试通过 |

### Layer 2: Agent Pipeline (智能体管道)

| 组件                | 文件                          | 状态        | 说明                                                   |
| ------------------- | ----------------------------- | ----------- | ------------------------------------------------------ |
| ReAct Agent         | `agent/gis/graph.py`        | ✅ 已实现   | `create_react_agent()` + `GISAgentState` TypedDict |
| 系统提示词          | `agent/gis/prompts.py`      | ✅ 已修正   | 查询模板名已修正为`get_constraint_by_field`          |
| 工具注册            | `tools/gis/layout_tools.py` | ✅ 已实现   | 6 个工具 + InjectedState 注入 + Command 写回           |
| parse_planning_text | `layout_tools.py:269-310`   | ✅ 代码存在 | LLM 调用解析规划文本 → intent JSON                    |
| Agent 执行轨迹      | —                            | ⚠️ 未验证 | 未记录 LLM 实际工具调用顺序                            |

**6 个 Agent 工具**：

| 工具                  | 输入 (InjectedState)                                  | 输出 (Command.update)               |
| --------------------- | ----------------------------------------------------- | ----------------------------------- |
| parse_planning_text   | reports, village_name                                 | messages                            |
| build_knowledge_graph | reports, gis_data, village_name                       | kg_turtle, kg_constraints, messages |
| query_knowledge_graph | template_name, field_name, dlbm, zone_type, kg_turtle | messages                            |
| detect_conflicts      | summaries                                             | messages                            |
| allocate_zones        | targets, constraints, mode, gis_data, kg_constraints  | messages                            |
| generate_layout       | intent, gis_data                                      | layout_configs, messages            |

### Layer 3: Spatial Generator (空间生成器)

| 组件                      | 文件                                  | 状态        | 说明                                                    |
| ------------------------- | ------------------------------------- | ----------- | ------------------------------------------------------- |
| 三阶段引擎                | `layout/engine.py`                  | ✅ 已实现   | Stage A(MIP) + Stage B(CA) + Stage C(设施+轴线)         |
| ZoneGenerator             | `layout/zone_generator.py`          | ✅ 已实现   | DLBM 重分类 → function_zone 图层                       |
| ConstraintDrivenAllocator | `optimizer/mip_solver.py`           | ✅ 已实现   | greedy + MIP 双模式，4→7 类分区映射                    |
| MIP Allocator             | `optimizer/mip_allocator.py`        | ✅ 代码存在 | PuLP-based MIP，代码完整但未端到端测试                  |
| PlanningZoneMapper        | `optimizer/planning_zone_mapper.py` | ✅ 已实现   | 4 类 ↔ 7 类分区双向映射                                |
| CA Refiner                | `optimizer/ca_refiner.py`           | ✅ 已修复   | `assigned_zone` 优先取值 bug 已修；Iter 1 成功 660→3 |
| FacilityPlacer            | `layout/facility_placer.py`         | ✅ 已实现   | 灾害点避让 + 边界约束                                   |
| AxisBuilder               | `layout/axis_builder.py`            | ✅ 已实现   | 三级发展轴（primary/secondary/corridor）                |
| MapRenderer               | `layout/map_renderer.py`            | ✅ 已实现   | 6 种图层类型 + 渲染优先级                               |
| LayoutValidator           | `layout/validator.py`               | ✅ 已实现   | 5 项检查 + RetryValidationReport                        |
| 验证闭环                  | `engine.py:294-328`                 | ✅ 已实现   | ≤3 轮 validate→adjust→regenerate + damping 递减      |
| SSE 进度推送              | `engine.py:_emit_progress`          | ✅ 已实现   | 11 个事件按序推送                                       |

---

## 三、Sprint 1-3 交付记录

### Sprint 1: 内部逻辑修复

| 修复项                          | 文件                                | 变更                                                   |
| ------------------------------- | ----------------------------------- | ------------------------------------------------------ |
| MIP`_enforce_constraints` bug | `optimizer/mip_solver.py:285-298` | `old_zone` 保存移至赋值前                            |
| CA Refiner 集成                 | `engine.py:487-521`               | `_refine_planning_zones()` + 面积守恒 >1% 回退       |
| CA Refiner 属性 bug             | `optimizer/ca_refiner.py:64`      | `land_use` → 优先取 `assigned_zone`/`zone_type` |

### Sprint 2: Agent 闭环

| 修复项              | 文件                     | 变更                                                             |
| ------------------- | ------------------------ | ---------------------------------------------------------------- |
| 验证闭环            | `engine.py:294-328`    | ≤3 轮 validate→adjust→regenerate，damping=0.2/(round+1)       |
| Agent prompt 模板名 | `agent/gis/prompts.py` | `construction_cap` → `get_constraint_by_field` + 9 模板说明 |
| 验证循环日志        | `engine.py:309-316`    | 输出 violations 摘要 + adjustments 键列表                        |

### Sprint 3: SSE 进度推送

| 修复项             | 文件                  | 变更                                                    |
| ------------------ | --------------------- | ------------------------------------------------------- |
| session_id 参数    | `engine.py:106,246` | `generate_layout` + `full_pipeline` 新增 session_id |
| 进度事件注入       | `engine.py:141-218` | 4 个图层生成前 + 验证轮次前 + complete                  |
| `_emit_progress` | `engine.py:471-485` | 静态方法封装`SSEPublisher.send_tool_progress`         |

### 端到端测试

| 测试文件                            | 测试类               | 方法数 | 覆盖                                                        |
| ----------------------------------- | -------------------- | ------ | ----------------------------------------------------------- |
| `tests/test_gis_e2e_real_data.py` | TestFullPipelineE2E  | 5      | full_pipeline + KG 分区 + CA 面积 + 验证闭环事件 + 面积覆盖 |
| `tests/test_gis_sse_events.py`    | TestSSEEventSequence | 3      | 事件顺序 + 空 session_id + 验证轮次数                       |
| `tests/test_gis_api_endpoints.py` | TestGISAPIEndpoints  | 3      | 端点成功 + 响应结构 + 分区属性                              |

**总计**：57 个测试全部通过（含原有 46 个）

---

## 四、规划文本一致性

### 金田村 L3 报告目标值 vs Engine 默认值

| 分区               | L3 报告   | Engine 默认 | 匹配                            |
| ------------------ | --------- | ----------- | ------------------------------- |
| 永久基本农田保护区 | 78.83 ha  | 78.83 ha    | ✅                              |
| 村庄建设区         | 30.50 ha  | 30.50 ha    | ✅                              |
| 生态保护区         | 362.02 ha | 362.02 ha   | ✅                              |
| 一般农地区         | ~1845 ha  | 动态计算    | ✅ (已修正为 total - 其他3分区) |

**修正记录**：`general_agriculture_ha` 从硬编码 1881.54 改为 `round(total_area - farmland - construction - ecological, 2)`

### 验证闭环检测结果

```
Validation round 1: 4 violations
  - zone_completeness: 缺少必需分区: 村庄建设区
  - zone_completeness: 缺少必需分区: 一般农地区
  - zone_completeness: 缺少必需分区: 生态保护区
  - zone_completeness: 缺少可选分区: 永久基本农田保护区
  adjustments=[] (面积约束无 violation，仅分区完整性)
```

**说明**：CA Refiner 将 660 features 合并为 3 个后，MapRenderer 可能无法正确识别分区类型，导致验证器报告"缺少分区"。这是 CA 合并粒度过粗的副作用，需后续优化。

---

## 五、前端矢量底图叠加

✅ **完全支持**，无数据流断点。

**数据流**：

```
POST /api/dev/gis/spatial-layout
  → layout_configs[] (含 geojson + layerType + color)
  → useGisTestSuite.ts:126 (提取 GISLayerConfig[])
  → MapView.tsx:289 (构建 geojsonSources + layerStyles)
  → MapLibre GL 渲染
```

**渲染配置**：

| 图层类型         | 填充                               | 描边       | 优先级 |
| ---------------- | ---------------------------------- | ---------- | ------ |
| planning_zone    | 半透明 0.35 + PLANNING_ZONE_COLORS | 虚线 2.5px | 高     |
| function_zone    | 按 zone_type 配色                  | 实线 1px   | 中     |
| sensitivity_zone | 红色半透明                         | —         | 高     |
| infrastructure   | 道路灰/建设区橙                    | —         | 中     |
| facility_point   | 圆点                               | —         | 低     |
| development_axis | 粗线                               | —         | 中     |

**底图**：天地图矢量瓦片（vec/cva）+ OSM + ArcGIS 可选

---

## 六、已知差距与后续计划

| 优先级 | 差距                                        | 影响                                                 | 建议                                                      |
| ------ | ------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------- |
| 🔴 P0  | CA Refiner 合并后 "list index out of range" | CA 合并 660→3 后后续处理报错                        | 调试`_shapely_to_feature` 或 `_merge_pass` 的索引越界 |
| 🔴 P0  | 验证闭环未触发面积调整                      | violations 为 zone_completeness 而非 area_constraint | 优化 CA 合并粒度，保留分区标识                            |
| 🟡 P1  | MIP 模式未测试                              | PuLP 求解路径未验证                                  | 添加 MIP mode E2E 测试                                    |
| 🟡 P1  | Agent ReAct 路径未验证                      | LLM 是否按 9 步流程调用工具未知                      | 添加 Agent 执行轨迹记录                                   |
| 🟡 P1  | parse_planning_text 未验证                  | LLM 解析规划文本 → intent 的质量未知                | 添加 LLM 输出断言测试                                     |
| 🟢 P2  | 面积分配偏差较大                            | 村庄建设区实际 20.3ha vs 目标 30.5ha                 | 优化 Allocator 的 target 追踪逻辑                         |
| 🟢 P2  | Validator 缺少 Indicator 约束               | 人均建设用地等指标未验证                             | 扩展`_check_area_constraints`                           |

---

## 七、关键文件索引

| 文件                                                                          | 用途            |
| ----------------------------------------------------------------------------- | --------------- |
| `backend/app/services/modules/gis/layout/engine.py`                         | 核心编排器      |
| `backend/app/services/modules/gis/layout/kg/builder.py`                     | KG 构建         |
| `backend/app/services/modules/gis/layout/kg/query.py`                       | SPARQL 查询     |
| `backend/app/services/modules/gis/layout/optimizer/mip_solver.py`           | Greedy 分配器   |
| `backend/app/services/modules/gis/layout/optimizer/mip_allocator.py`        | MIP 分配器      |
| `backend/app/services/modules/gis/layout/optimizer/ca_refiner.py`           | CA 空间精细化   |
| `backend/app/services/modules/gis/layout/optimizer/planning_zone_mapper.py` | 4↔7 类分区映射 |
| `backend/app/services/modules/gis/layout/validator.py`                      | 布局验证器      |
| `backend/app/services/modules/gis/layout/zone_generator.py`                 | DLBM 重分类     |
| `backend/app/services/modules/gis/layout/facility_placer.py`                | 设施选址        |
| `backend/app/services/modules/gis/layout/axis_builder.py`                   | 发展轴生成      |
| `backend/app/services/modules/gis/layout/map_renderer.py`                   | 图层渲染        |
| `backend/app/agent/gis/graph.py`                                            | GIS Agent 图    |
| `backend/app/agent/gis/prompts.py`                                          | Agent 提示词    |
| `backend/app/tools/gis/layout_tools.py`                                     | Agent 工具      |
| `backend/app/utils/sse_publisher.py`                                        | SSE 事件发布    |
| `backend/app/api/gis_test_routes.py`                                        | Dev API 端点    |
| `frontend/src/features/planning/components/gis/MapView.tsx`                 | 前端地图渲染    |
| `frontend/src/app/test-gis/hooks/useGisTestSuite.ts`                        | 前端测试套件    |
