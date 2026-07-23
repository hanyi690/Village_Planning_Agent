# GIS 系统架构重构提案：Tool-First，Agent-Orchestrated

> **Status: [IMPLEMENTING]** | **Type: Architecture Refactor Proposal** | **Version: 1.1** | **Updated: 2026-07-23**
> **Phase A/B/C 已完成** (commits 415dbf5, 2006d30, c8a76d4)。Phase D/E 待执行。
> - ✅ A: helpers 提升、KG 独立、utils 迁移
> - ✅ B: generation/analysis/rendering → tools/gis/_*
> - ✅ C: parse_tools 拆分、gis_data/ 创建、Schema 统一、空壳预留
> - ⬜ D: API + Agent 适配、测试运行
> - ⬜ E: 验证与文档
> **Relationship to DESIGN_GOALS**: 本提案重构 01_DESIGN_GOALS.md §3.7 代码位置，对齐 Phase 2/2.5/3 的实现基础。
> **References**: BIBLIOGRAPHY.md §F1-11, §G1-5
> **Related**: 01_DESIGN_GOALS.md §3, §5, §8, 02_OUTPUT_ARCHITECTURE.md §4

---

## 一、问题：当前架构的 5 个缺陷

### 1.1 modules/gis/ 过重

`modules/gis/` 下包含 6 个子模块（data/schema/analysis/generation/rendering/kg）+ 2 个独立文件 + utils，违反单一职责。

**影响**：
- 新人无法快速理解模块边界
- generation/ 和 analysis/ 的消费者只有 tool 层和 API 路由，却作为独立服务模块存在
- KG 建立的约束不止用于 GIS（conflict detector、parsing semantics 均引用），却困在 gis 子包内

### 1.2 Tool 层混乱

| 问题 | 具体表现 |
|------|---------|
| 功能重叠 | `parse.py` 和 `parse_tools.py` 各有一个 `parse_planning_text` |
| 无 Schema 约束 | `data.py`、`analytics.py` 返回裸 `json.dumps(dict)` 字符串 |
| 业务逻辑混入 | `generate.py` 含 6 个私有生成函数（200+ 行） |
| helpers 层级错 | `_helpers.py` 是所有 tool 共用的基础函数，却局限在 gis 子包内 |

### 1.3 Utils 未通用化

`modules/gis/utils/` 下的坐标转换、GeoJSON 工具是通用能力，应提升到 `app/utils/`。

### 1.4 KG 应独立

`modules/gis/kg/` 的 PlanningKG 被以下非 GIS 模块引用：
- `modules/gis/analysis/conflict/detector.py` — semantics 引用
- `agent/gis/parse/agent.py` — PARSE Agent 查询 KG
- Phase 2.5 的 EXECUTE_OPERATIONS Agent 也将查询 KG

### 1.5 不支持未来扩展

| 未来需求 | 当前架构障碍 |
|----------|-------------|
| Phase 2.5 EXECUTE_OPS Agent (ReAct 子图, 5 tools) | 无 `agent/gis/execute/` 子包，无 `tools/gis_execute/` |
| Proposal 02 规划 Agent 查询工具 (6 tools) | 无 `tools/gis_query/` |
| OperationEngine 原子操作几何实现 | 无 `spatial/operations/` 或 tool 内部实现 |

---

## 二、设计决策：Tool-First

### 2.1 核心原则

**Tool-First**：业务逻辑以 `@tool` 形式暴露，Agent 通过 tool 编排一切。tool 既是 Agent 的操作接口，也是业务逻辑的实现载体。

**LangGraph 最佳实践**（Context7 验证）：
- Agent = LLM + tools，每个 tool 做一件事
- 混合架构：确定性节点 + ReAct 子图共存于 StateGraph
- 工具粒度要小且原子化
- ToolNode 作为确定性节点执行 tool 调用

### 2.2 为什么不需要独立的 Engine 层？

| 传统思维 | Tool-First 思维 |
|----------|----------------|
| ConflictDetector 是"引擎"，tool 是"薄壳" | `detect_conflicts` tool 内含 ConflictDetector，tool 就是业务逻辑 |
| 需要独立的 `spatial/` 模块存放引擎 | tool 文件本身包含实现，内部类不导出 |
| OperationEngine import 引擎组件 | EXECUTE_OPS Agent 的 `check_compliance` tool 复用 conflict.py 内部逻辑 |
| API 路由直接 import 引擎类 | API 路由 import tool 文件中的内部类 |

**关键洞察**：LangGraph Agent 只通过 tool 与世界交互。把业务逻辑放在独立模块中，然后 tool 薄壳调用它，增加了不必要的间接层——Agent 永远不会直接 import 那个模块。

### 2.3 三层架构

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 1: SCHEMA (单一真相源)                                  │
│   modules/gis/schema/   — 编码/类型/契约/字典/颜色/GDB        │
│   modules/kg/           — KG 本体+构建+查询                   │
│   modules/gis/data/     — 数据获取/加载/Provider 适配          │
│   modules/parsing/      — 文本解析工具                        │
│   utils/ (app/utils/)   — 坐标/GeoJSON/面积 通用工具          │
│   spatial_context.py    — SpatialContext 计算                 │
├──────────────────────────────────────────────────────────────┤
│ Layer 2: TOOL (业务逻辑的原子化暴露)                           │
│   tools/gis/            — GIS 管线 tools (11 tools)           │
│   tools/gis_execute/    — EXECUTE_OPS Agent tools (5 tools)  │
│   tools/gis_data/       — 数据获取 tools (4 tools)            │
│   tools/gis_query/      — 规划 Agent 查询 tools (6 tools)    │
│   tools/helpers.py      — make_result / to_tool_message       │
├──────────────────────────────────────────────────────────────┤
│ Layer 3: AGENT (LLM 编排决策)                                 │
│   agent/gis/parse/      — PARSE Agent (半结构化 ReAct)         │
│   agent/gis/execute/    — EXECUTE_OPS Agent (ReAct, 未来)     │
│   agent/gis/            — LAYOUT Pipeline (StateGraph)         │
│   agent/ (graph.py)     — Router Agent (未来集成 GIS query)    │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、目标目录结构

### 3.1 `backend/app/tools/` — Tool 层

```
backend/app/tools/
├── helpers.py                     # make_result / to_tool_message（从 gis/_helpers.py 提升）
├── protocol.py, types.py, constants.py, registry.py  # 已有
│
├── gis/                           # GIS 管线 tools
│   ├── __init__.py                # GIS_PIPELINE_TOOLS
│   ├── parse.py                   # parse_planning_text
│   ├── extract.py                 # extract_structured_text
│   ├── lookup.py                  # lookup_land_use_code
│   ├── kg.py                      # build_knowledge_graph / query_knowledge_graph
│   ├── conflict.py                # detect_conflicts (内含 ConflictDetector)
│   ├── allocate.py                # allocate_zones (内含 MIPAllocator)
│   ├── generate.py                # generate_layout (内含各 Generator)
│   ├── validate.py                # validate_layout (内含 LayoutValidator)
│   ├── export.py                  # export_gdb
│   └── render.py                  # render_map (内含 MapRenderer)
│
├── gis_execute/                   # ★ 预留：EXECUTE_OPS Agent tools
│   └── __init__.py                # 空壳
│
├── gis_data/                      # GIS 数据获取 tools
│   ├── __init__.py                # GIS_DATA_TOOLS
│   ├── fetch.py                   # fetch_gis_data
│   ├── search_poi.py              # search_poi
│   └── analytics.py               # calculate_gis_coverage / analyze_accessibility
│
└── gis_query/                     # ★ 预留：规划 Agent 查询 tools
    └── __init__.py                # 空壳
```

### 3.2 `backend/app/modules/gis/` — 精简为 schema + data + context

```
backend/app/modules/gis/
├── __init__.py                    # 精简导出
├── schema/                        # ✅ 不变
├── data/                          # ✅ 不变
└── spatial_context.py             # ✅ 不变
```

**删除**：generation/、analysis/、rendering/（迁入 tools/）、utils/（迁入 app/utils/）、kg/（迁入 modules/kg/）

### 3.3 `backend/app/modules/kg/` — KG 独立

```
modules/kg/
├── __init__.py
├── builder.py                     # PlanningKG
├── query.py                       # SPARQL 查询
└── ontology.py                    # PLN, GEO, EntityTypes, Relations
```

### 3.4 `backend/app/utils/` — 通用 Utils

```
app/utils/
├── ... (已有)
├── coord_transform.py, coord_utils.py, crs_engine.py
├── geojson_utils.py, geo_utils.py, area_engine.py
```

### 3.5 `backend/app/agent/gis/` — 扩展

```
agent/gis/
├── agent.py, layout_pipeline.py, prompts.py, state.py  # 不变
├── parse/                         # 不变
└── execute/                       # ★ 预留：EXECUTE_OPS Agent 子图
    └── __init__.py                # 空壳
```

---

## 四、面向最终系统的 Agent 架构

```
                    ┌──────────────────────────────────────────────┐
                    │              Router Agent                    │
                    │  当前: RAG only → 纯文本报告                 │
                    │  未来: RAG + gis_query/ tools → 结构化输出   │
                    └───────────┬──────────────────────────────────┘
                                │ OperationSequence + ConstraintSet
                    ┌───────────▼──────────────────────────────────┐
                    │           PARSE Agent (半结构化 ReAct)        │
                    │  Tools: gis/parse, extract, lookup           │
                    └───────────┬──────────────────────────────────┘
                                │
            ┌───────────────────▼───────────────────────┐
            │        LAYOUT Pipeline (StateGraph)         │
            │                                           │
            │  build_kg → conflicts → ┌──────────────┐  │
            │    (gis/kg)  (gis/conflict)│ EXECUTE_OPS  │  │
            │                          │ Agent (ReAct) │  │
            │                          │               │  │
            │                          │ Tools:        │  │
            │                          │ gis_execute/  │  │
            │                          │ (5 tools)     │  │
            │                          └───────┬───────┘  │
            │                                  │           │
            │  validate_layout (gis/validate)  │           │
            │  export_gdb (gis/export)         │           │
            │  render_map (gis/render)         │           │
            └──────────────────────────────────────────────┘
```

### EXECUTE_OPERATIONS Agent (Phase 2.5)

设计文档明确：**EXECUTE_OPERATIONS 是 ReAct 子图**，不是固定执行流程。LLM 自适应决策。

| Tool | 功能 | 复用 |
|------|------|------|
| `resolve_place_name` | 地名解析 → 候选图斑 | SpatialContext + Gazetteer |
| `check_compliance` | 合规预检 | conflict.py 内部 ConflictDetector |
| `edit_parcel` | 执行 create/split/merge/modify/reclassify | 新实现（原子操作几何逻辑） |
| `lookup_land_use_code` | 用途查表 | 已有（从 gis/lookup.py 复用） |
| `optimize_allocation` | MIP 辅助 | allocate.py 内部 MIPAllocator |

### 规划 Agent 查询工具 (Proposal 02)

| Tool | 功能 | 复用 |
|------|------|------|
| `query_spatial_context` | 村庄空间概况 | spatial_context.py |
| `query_parcel_info` | 地块信息 | data/loader.py |
| `check_planning_compliance` | 合规预检 | conflict.py 内部 |
| `lookup_land_use_code` | 编码查表 | 已有 |
| `resolve_place_name` | 地名解析 | 已有 |
| `add_construction_project` | 建设项目→操作队列 | 新实现 |

---

## 五、迁移映射

### 5.1 generation/ → tools/gis/

| 当前位置 | 迁入目标 |
|----------|---------|
| `modules/gis/generation/zone_generator.py` | `tools/gis/generate.py` 内部类 |
| `modules/gis/generation/facility_placer.py` | `tools/gis/generate.py` 内部类 |
| `modules/gis/generation/axis_builder.py` | `tools/gis/generate.py` 内部类 |
| `modules/gis/generation/space_control_generator.py` | `tools/gis/generate.py` 内部类 |
| `modules/gis/generation/land_use_zone_generator.py` | `tools/gis/generate.py` 内部类 |
| `modules/gis/generation/pipeline.py` | `tools/gis/generate.py` 内部函数 |
| `modules/gis/generation/optimizer/mip_allocator.py` | `tools/gis/allocate.py` 内部类 |
| `modules/gis/generation/optimizer/mip_solver.py` | `tools/gis/allocate.py` 内部类 |
| `modules/gis/generation/optimizer/adjacency_graph.py` | `tools/gis/allocate.py` 内部类 |
| `modules/gis/generation/optimizer/planning_zone_mapper.py` | `tools/gis/allocate.py` 内部类 |
| `modules/gis/generation/optimizer/ca_refiner.py` | `tools/gis/generate.py` 内部类 |
| `modules/gis/generation/optimizer/procedural.py` | `tools/gis/generate.py` 内部函数 |

### 5.2 analysis/ → tools/gis/ + tools/gis_data/

| 当前位置 | 迁入目标 |
|----------|---------|
| `modules/gis/analysis/conflict/detector.py` | `tools/gis/conflict.py` 内部类 |
| `modules/gis/analysis/conflict/resolver.py` | `tools/gis/conflict.py` 内部类 |
| `modules/gis/analysis/validation/layout_validator.py` | `tools/gis/validate.py` 内部类 |
| `modules/gis/analysis/validation/facility_validator.py` | `tools/gis/validate.py` 内部类 |
| `modules/gis/analysis/dynamic_zoning.py` | `tools/gis/generate.py` 内部类 |
| `modules/gis/analysis/metrics_calculator.py` | `tools/gis_data/analytics.py` 内部类 |
| `modules/gis/analysis/coverage.py` | `tools/gis_data/analytics.py` 内部函数 |
| `modules/gis/analysis/accessibility.py` | `tools/gis_data/analytics.py` 内部函数 |
| `modules/gis/analysis/isochrone.py` | `tools/gis_data/analytics.py` 内部函数 |

### 5.3 rendering/ → tools/gis/

| 当前位置 | 迁入目标 |
|----------|---------|
| `modules/gis/rendering/map_renderer.py` | `tools/gis/render.py` 内部类 |
| `modules/gis/rendering/compare_layouts.py` | `tools/gis/render.py` 内部函数 |

### 5.4 其他迁移

| 当前位置 | 迁入目标 |
|----------|---------|
| `modules/gis/kg/` | `modules/kg/` |
| `modules/gis/utils/*.py` (6个文件) | `app/utils/*.py` |
| `tools/gis/_helpers.py` | `tools/helpers.py` |
| `tools/gis/parse.py` 辅助函数 | `modules/gis/data/loader.py` |
| `tools/gis/parse_tools.py` | 拆分为 `gis/parse.py` + `gis/extract.py` + `gis/lookup.py` |
| `tools/gis/data.py` | 拆分为 `gis_data/fetch.py` + `gis_data/search_poi.py` |
| `tools/gis/analytics.py` | 移入 `gis_data/analytics.py` |

---

## 六、执行路线图

### Phase A：基础层迁移

1. 创建 `tools/helpers.py`
2. 创建 `modules/kg/`
3. 迁移 `gis/utils/` → `app/utils/`
4. 全量更新 import
5. 删除旧目录

### Phase B：generation/analysis/rendering 迁入 tools/

6. 迁移 `generation/` → `tools/gis/generate.py` 和 `allocate.py`
7. 迁移 `analysis/conflict/` → `tools/gis/conflict.py`
8. 迁移 `analysis/validation/` → `tools/gis/validate.py`
9. 迁移 `analysis/` 其余 → `tools/gis_data/analytics.py`
10. 迁移 `rendering/` → `tools/gis/render.py`
11. 全量更新 import
12. 删除旧目录

### Phase C：Tool 层重组

13. 迁移 parse.py 辅助函数 → `modules/gis/data/loader.py`
14. 删除旧 `tools/gis/parse.py`
15. 拆分 `parse_tools.py` → parse.py + extract.py + lookup.py
16. 创建 `tools/gis_data/`
17. 创建空壳：`gis_execute/`、`gis_query/`、`agent/gis/execute/`
18. 统一 Schema 约束（裸 json.dumps → Pydantic）

### Phase D：API + Agent 适配

19. 更新 `api/gis_test_routes.py`
20. 更新 Agent 注册
21. 更新 scripts/

### Phase E：验证与文档

22. pytest + E2E
23. 更新设计文档

---

## 七、风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Tool 文件过大（generate.py 内含 6 个类） | 高 | 低 | 可接受：内聚性高，内部类逻辑独立 |
| Import 路径断裂 | 高 | 高 | 每步全量 grep + pytest |
| API 路由 import 内部类 | 中 | 低 | `from app.tools.gis.conflict import ConflictDetector` 合法 |

回退：每 Phase 独立 commit。
