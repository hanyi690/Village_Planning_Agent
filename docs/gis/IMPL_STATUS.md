# GIS 系统 — 实现状态与差距分析

> 审计日期: 2026-07-15 | 对比基线: `docs/gis/DESIGN_GOALS.md` | 分支: `feature/gis-layout-engine`

## 1. 总览

| 状态          | 数量 | 说明 |
| ------------- | ---- | ---- |
| ✅ 已实现     | 21   | 核心流水线 + 统一 Schema + 双路径 + 三路对比 |
| ⚠️ 部分实现 | 2    | Export 字段对齐 + CA 精化 |
| ❌ 未实现     | 3    | Phase 2/3 规划中 |

**测试**: 56 单元+集成 / 20 E2E（已精简重构，先前 164 测试包含大量弃用逻辑已剔除）

---

## 2. 逐模块评估

### 2.1 数据获取 ✅

| 功能                  | 状态 | 文件 |
| --------------------- | :--: | ---- |
| 天地图 WFS 自动获取   |  ✅  | `data/fetcher.py` |
| OSM 村级道路补充      |  ✅  | `providers/osm/provider.py` |
| 高德 POI 搜索         |  ✅  | `providers/amap/provider.py` |
| 高德优先 + 天地图回退 |  ✅  | `providers/poi.py` |
| GDB 12 层字段标准定义 |  ✅  | `data/gdb_schema.py` |
| 金田村测试数据加载    |  ✅  | `tests/fixtures/gis_e2e.py` |

### 2.2 编码系统 ✅

| 功能                                     | 文件 |
| ---------------------------------------- | ---- |
| **统一分类 Schema** (83条 LandUseClass)    | `zone_schema/schema.py` ★ |
| DLBM/GHYTBM → 8 功能分区 (从 schema 派生) | `zone_schema/encodings.py` |
| DLBM → 6 规划分区 (从 schema 派生)        | `zone_schema/encodings.py` |
| ECOLOGICAL/FORESTRY 等 7 组代码集 (从 schema 派生) | `zone_schema/code_sets.py` |
| GB/T 21010 标准配色 (8功能+6规划+3三区)    | `zone_schema/colors.py` |
| GHFLBM/GHYTBM/VNE 编码互转               | `zone_schema/encodings.py` |
| LLM prompt 结构化分类表格 (自动注入)       | `schema.to_prompt_table()` |
| GB/T 21010 合规: 商品林(1340)→农业用地     | 三大类对照表，已修正 |

**架构变更**: 2026-07-15 从 20 个散落 dict/set → 1 个 `schema.py` 单一真相源。LLM prompt 不再手写 DLBM 示例，改为 `SCHEMA.to_prompt_table()` 自动注入结构化分类表格。

### 2.3 PARSE（意图解析） ✅

| 功能                                          | 状态 | 位置 |
| --------------------------------------------- | :--: | ---- |
| Gen 路径: 人工规划 markdown → LLM → intent    |  ✅  | `tools/gis/parse.py::parse_text_via_llm()` |
| Plan 路径: L3 reports → LLM → intent          |  ✅  | `tools/gis/parse.py::_parse_reports_to_intent()` |
| GIS 实测约束注入 LLM prompt                    |  ✅  | `_build_gis_constraints_for_llm()` (365ha生态, 1966ha农用) |
| 结构化分类表格注入 prompt                      |  ✅  | `SCHEMA.to_prompt_table()` 替代手写 DLBM 示例 |
| Intent 缓存（解析因子感知）                    |  ✅  | `layout/intent_cache.py` (PARSE_VERSION + LLM_MODEL + 内容hash) |
| 默认意图兜底（无 LLM 时）                      |  ✅  | `_build_default_intent()` |
| 土地利用提示注入（top 10 DLBM ← 从 schema 派生）|  ✅  | `_build_landuse_hint()` |

### 2.4 KG（知识图谱） ✅

| 功能                              | 状态 | 位置 |
| --------------------------------- | :--: | ---- |
| RDF 图谱构建 (PlanningKG)         |  ✅  | `kg/builder.py` |
| 从报告构建 + 从 Intent 构建       |  ✅  | `build_from_reports()` / `build_from_intent()` |
| GIS 实测约束注入 KG 三元组         |  ✅  | `_add_gis_constraint_triples()` (construction≤21.66, farmland≥98.54, ecological≥365.28) |
| 9 个 SPARQL 查询模板              |  ✅  | `kg/query.py` |
| Turtle 序列化/反序列化            |  ✅  | `to_turtle()` / `from_turtle()` |
| 邻接图构建                        |  ✅  | `get_adjacency_map()` |

**金田村实测**: 8462 triples, 4 constraints, 660 parcels, 2607 adjacency edges.

### 2.5 CONFLICT（冲突检测） ✅

| 功能                                     | 状态 | 位置 |
| ---------------------------------------- | :--: | ---- |
| 三类冲突检测 (metric/constraint/spatial) |  ✅  | `conflict/detector.py` |
| 自动消解 (dimension priority-based)      |  ✅  | `conflict/resolver.py` |
| 5% 相对差异阈值                          |  ✅  | 可配置 |

### 2.6 ALLOCATE（MIP 分区分配） ⚠️

| 功能                       | 状态 | 位置 |
| -------------------------- | :--: | ---- |
| PuLP MILP 求解器           |  ✅  | `optimizer/mip_allocator.py` |
| 保护地块硬约束（变量锁定） |  ✅  | KG-driven 模式 |
| 约束松弛变量（slack）      |  ✅  | 非保护地块面积偏差最小化 |
| Greedy 回退模式            |  ✅  | PuLP 不可用时自动切换 |
| 邻接图构建                 |  ✅  | `optimizer/adjacency_graph.py` |
| CA 细化器                  | ✅ | 导入路径已修复 (`app.services.modules.gis.optimizer.ca_refiner`) |
| **Voronoi 几何细化** |  ❌  | Phase 2 |

### 2.7 GENERATE（布局生成） ✅

| 功能                                      | 状态 | 位置 |
| ----------------------------------------- | :--: | ---- |
| DLBM 重分类 → function_zone 图层         |  ✅  | `layout/zone_generator.py` |
| DLBM → planning_zone 图层 (per-parcel)   |  ✅  | `tools/gis/generate.py::_make_planning_zone_layer()` |
| 设施选址（4 策略：保留/新建/改扩建/迁建） |  ✅  | `layout/facility_placer.py` |
| 轴生成（一核一带三区）                    |  ✅  | `layout/axis_builder.py` |
| **道路网络生成**                    |  ❌  | Phase 2 |

### 2.8 VALIDATE（布局验证） ✅

| 功能                                        | 状态 | 位置 |
| ------------------------------------------- | :--: | ---- |
| 8 项空间检查                                |  ✅  | `validation/layout_validator.py` |
| 设施选址验证                                |  ✅  | `validation/facility_validator.py` |
| 最多 3 轮验证-重试                         |  ✅  | LAYOUT Agent ReAct 内循环 |

### 2.9 EXPORT + RENDER ✅

| 功能                              | 状态 | 位置 |
| --------------------------------- | :--: | ---- |
| 12 层 GeoJSON 输出                |  ✅  | `tools/gis/export.py` |
| 用地平衡表 JSON                   |  ✅  | `_compute_land_balance()` |
| 三路并排 PNG 对比图               |  ✅  | `scripts/render_comparison.py` |
| Python/matplotlib 渲染            |  ✅  | 从 PLANNING_ZONE_COLORS 导入颜色 |
| **Excel 用地平衡表**        |  ❌  | Phase 2 |

## 3. 测试覆盖

| 测试集                     | 状态 | 文件 |
| -------------------------- | :--: | ---- |
| 单元测试                   | ✅ 30 passed | `test_gis_unit.py` |
| 集成测试                   | ✅ 24 passed | `test_gis_integration.py` |
| E2E 测试                   | ✅ 25/25 passed | `test_gis_e2e.py` |
| 三路对比 E2E               | ✅ 3 passed | `TestThreeWayComparison` |

### 3.1 最近修复 (2026-07-15)

| 修复 | 文件 | 说明 |
|------|------|------|
| `facility_id` KeyError | `tools/gis/generate.py:49` | `f["facility_id"]` → `f.get("facility_id", f.get("name", ""))` |
| `axis_id` KeyError | `tools/gis/generate.py:59` | `a["axis_id"]` → `a.get("axis_id", "")` |
| CA 导入路径错误 | `layout/zone_generator.py:140` | `.optimizer.ca_refiner` → `app.services.modules.gis.optimizer.ca_refiner` |

## 4. 已知问题

| 问题 | 影响 | 位置 |
|------|------|------|
| `layout_tools` 模块缺失 | render_planning_layout.py LLM 解析链路断裂，渲染仅产出 boundary + 空 function_zone | `scripts/render_planning_layout.py:552` 引用不存在的 `app.tools.gis.layout_tools` |

## 5. 优先级路线图

核心目标：**规划文本 → GIS 图层** 的端到端转换管线。

### P0 — 本迭代（恢复主链路）
- [ ] 修复 render_planning_layout.py 的 LLM 解析路径（改用 `resolve_plan_intent_cached()`）
- [ ] 验证完整 4 层输出（function_zone + planning_zone + facility_point + infrastructure）
- [ ] 面积验证修复（当前 0.0 ha vs 2868.5 ha，误差 100%）

### P1 — 下一迭代（功能完整性）
- [ ] 设施布点层：LLM 解析 intent 中 facilities 字段完整性保障
- [ ] 轴线层：LLM 不可用时的启发式路网主轴提取兜底
- [ ] Excel 用地平衡表
- [ ] PuLP → COIN_CMD 迁移

### P2 — 远期（质量提升）
- [ ] CA 多轮退火精化（当前 3 轮 → 5-10 轮，参考 MOP-FLUS 框架）
- [ ] Voronoi 几何细化
- [ ] 道路网络规划生成
