# 集成断点诊断与修复路线

> **来源**：`THREE_STAGE_INTEGRATION_DESIGN` 提案提升为设计文档
> **状态**：11 断点 + 6 改造（I1-I6），部分已实现

---

## 1. 诊断：三阶段是开环

三阶段（L1现状/L2定位/L3细化）本应是闭环，现状是开环甚至断环。调查确认 11 个断点，归为五类：

### 1.1 断点清单

| 类 | 断点 | 描述 | 证据 |
|----|------|------|------|
| **A 信息流断裂** | ① | L1 问题未结构化喂 L2，全文本经 DB 中转 | node.py L399-403 |
| | ⑪ | L3 的 planning_concept 与 analysis_report 同源 | node.py L962-963 |
| | ④ | intent_targets 是文本占位非 grounding | detailed.py L840-845, "N/A"兜底 |
| **B KG 未用** | ② | L2/L3 完全不查 KG | node.py:667 `if dim_layer != 1: return ""` |
| | ⑨ | KG 实例不一致（L1用get_any_kg，GIS用get_session_kg） | node.py:691 vs layout_pipeline.py:232 |
| **C L4 断链** | ⑤ | ~~EXECUTE 后无 write_kg_l4 节点~~ **[已修复]** | execute/agent.py:374 `_write_l4_node` `[IMPLEMENTED]` |
| | ⑥ | L3 细化无机制读 L4 PlannedState 做一致性校核 | detailed.py 全文无 L4 读取 |
| **D 触发脱节** | ③ | 空间定位职责错位：ZoneTarget 应由 EXPLORE+PARSE 产 | layout_pipeline.py:123 `_parse_intent_node` 读 state.reports |
| | ⑦ | gis_agent 仅手动触发，L3 完成后 after_analysis 不路由到它 | routing.py:239 `if phase == "completed": return END` |
| | ⑧ | PARSE 双重执行（graph.py + layout_pipeline.py） | graph.py:97 vs layout_pipeline.py:123 |
| **E 死代码** | ⑩ | detailed.py L874-910 在 return 之后，永不执行 | detailed.py L871/874 |

### 1.2 开环图

```
L1现状(28维) ──文本DB──> L2定位 ──文本DB──> L3细化 ────> GIS(EXECUTE) ──L4回写[✓]──> 无校核回环[⑥]
     │KG浅查                  │不查KG[②]         │不查KG[②]        │独立KG实例[⑨]
```

---

## 2. 目标：闭环有机集成

```
L1现状(28维) ──结构化问题清单──> L2规划定位(策略性) ──strategic context──> L3细化(轮1生成)
     │analysis_queries               │analysis_queries+shared_queries        │execute_queries
     │KG认知摘要                      │村庄分类/发展方向/口号(文本,本就正确)  │↓ L1+L2+L3 上下文喂入
                                                                               ┌─────────────────────┐
                                                                               │ EXPLORE 桥接节点     │ ← 空间定位唯一入口
                                                                               │  按需读L1+L2+L3+NL   │
                                                                               │  + KG认知 + grounding │
                                                                               │  -> ExplorationInstr │
                                                                               │  -> ReportSummaryIndex│
                                                                               └──────────┬──────────┘
                                                                                          │ -> gis_agent
                                                                                          ▼
                                                     PARSE(消费概要) -> EXECUTE生成 -> write_kg_l4[✓] -> L3校核轮(读L4对账) -> 规划文本
```

---

## 3. 六处改造（I1-I6）

### I1: L1->L2 结构化问题清单（治断点①⑪）

`[PLANNED]`

- L1 每个 dimension 的 `summary` 扩展产出**问题/资源条目**：`{dimension_key, issues:[{topic, severity, spatial_hint}], resources:[{type, scale, location_hint}]}`
- `concept.py` 的 `{analysis_report}` 占位拆为 `{analysis_findings_structured}` + `{analysis_report_text}`（降级兼容）
- L3 的 `planning_concept` 改为独立读 L2 报告

**收益**：L2 定位基于结构化问题清单而非全文扫描；L3 拿到的是 L2 真实结论不是 L1 复读。

### I2: L2/L3 开放 KG 查询（治断点②⑨）

`[PLANNED]`

- 拆闸门为按命名空间分派（EXPLORE 维度认知模式统一提供）：
  - L1 -> `analysis_queries`（粗，semantic）-- 现状已用静态 DIM_KG_MAP，待升级为 EXPLORE 动态调用
  - L2 -> `analysis_queries` + `shared_queries`（定位需认知摘要做约束校核）
  - L3 -> `execute_queries` + `shared_queries`（细化需 get_area_by_type 算现状结构）
- KG 实例统一（治⑨）：`_optimize_semantics` 改用 `manager.get_session_kg(session_id)`（EXPLORE 统一用 session KG）
- `phases.yaml` 增加 `kg_query` 字段（类比 `rag_query`）

**收益**：L2 定位能基于 KG 认知校核；L3 细化能基于 KG 现状结构校核。

### I3: EXPLORE+PARSE 作为空间定位唯一生产者（治断点③④⑧）

`[PLANNED]`

- EXPLORE 提升为主图顶层节点，消费 L1/L2/L3 上下文 + 用户 NL，经 KG 接地产出 ExplorationInstruction
- PARSE 消费 ExplorationInstruction + 概要索引，产出 ZoneTarget/FacilityTarget/AxisTarget/RoadTarget
- 消除双重 parse（⑧）：graph.py 不再独立 `create_parse_agent_graph`
- 接地结果写 KG L3（`kg.build_intent_layer`）
- L3 细化的 `intent_targets` 占位改为读已接地的 ResolvedSpatialRef

**收益**：空间定位职责归位，消除"L3 文本反推"和"双重 parse"。

### I4: EXECUTE 后 write_kg_l4 + derived_from（治断点⑤）

`[IMPLEMENTED]` ✅

- layout_pipeline 边 `execute -> write_kg_l4` 已接入
- `write_kg_l4` 调 `kg/builder/layer4.py:apply_planned_state`，写 L4 实体带 provenance：
  - `pln:derived_from -> L1 BSM`
  - `pln:source_spec -> L2 spec`
  - `pln:decided_by`
  - `pln:operation`
  - `pln:area_change_ha`
  - `pln:in_version`

**收益**：规划成果进 KG，可被查询/校核/版本对比；derived_from 链使规划可回溯到现状图斑。

### I5: L3 校核轮读 L4 回写校核（治断点⑥）

`[PLANNED]`

- L3-轮1（生成）：L3 各维度基于 L2 intent + KG 认知生成细化文本（现状流程）
- EXECUTE 触发：L3-轮1 完成后触发 EXPLORE -> GIS pipeline -> write_kg_l4
- L3-轮2（校核）：L3 读 L4 PlannedState，对每个维度做一致性校核：
  - `land_use_planning`：`get_area_by_type` 算 L4 规划后面积 vs L3 文本表述面积
  - `spatial_structure`：读 L4 PlannedZone 的 derived_from 链校核结构
  - `project_bank`：读 L4 PlannedFacility 的 operation/area 校核项目表
- 校核结果写回 DB（version+1）

**收益**：规划文本与规划几何双向一致，消除"文本与图不符"通病。

### I6: 触发编排 + 死代码（治断点⑦⑧⑩）

`[PLANNED]`

- ⑦ `after_analysis` 增加 L3->EXPLORE 自动路由：L3-轮1 完成 -> EXPLORE -> GIS -> L4 -> L3-轮2
- ⑧ PARSE 单一化：graph.py 不再独立 create_parse_agent_graph
- ⑩ 删 detailed.py L874-910 死代码

---

## 4. 改动清单与优先级

| 改造 | 文件 | 估算 | 优先级 | 状态 |
|------|------|------|--------|------|
| I4 write_kg_l4 | layout_pipeline.py, kg/builder/layer4.py | ~150行 | P0 | `[IMPLEMENTED]` ✅ |
| I3 EXPLORE+PARSE 空间定位 | graph.py, explore/, layout_pipeline.py, node.py | ~200行 | P0 | `[PLANNED]` |
| I2 L2/L3 开放 KG | node.py, phases.yaml | ~120行 | P1 | `[PLANNED]` |
| I5 L3 校核轮 | node.py, detailed.py, routing.py | ~180行 | P1 | `[PLANNED]` |
| I1 结构化问题清单 | node.py, concept.py | ~100行 | P2 | `[PLANNED]` |
| I6 触发编排+死代码 | graph.py, routing.py, detailed.py | ~80行 | P2 | `[PLANNED]` |

---

## 5. 验收用例（金田村端到端）

| 用例 | 期望 | 状态 |
|------|------|------|
| L1->L2 结构化传递 | L2 positioning prompt 含结构化问题清单 JSON，非全文 | `[PLANNED]` |
| L2 查 KG | planning_positioning 查 analysis_queries，定位"集聚提升类"时 KG 确认生态红线覆盖率 | `[PLANNED]` |
| EXPLORE 空间定位 | EXPLORE 消费 L1+L2+L3+NL，产 ExplorationInstruction + ReportSummaryIndex | `[PLANNED]` |
| PARSE 消费概要 | PARSE 通过 ReportSummaryIndex 按维度取 L3 原文，产 ZoneTarget | `[PLANNED]` |
| L4 回写 | EXECUTE 后 KG 含 PlannedParcel×N，derived_from 链可 SPARQL 查回 L1 BSM | `[IMPLEMENTED]` ✅ |
| L3 校核轮 | L3-轮2 读 L4，land_use_planning 文本面积 = get_area_by_type 算的 L4 面积 | `[PLANNED]` |
| 闭环 | NL->L1->L2->L3->EXPLORE->PARSE->EXECUTE(L4)->L3校核->文本，全链 provenance 可查 | `[PLANNED]` |
| KG 实例统一 | L1/L2/L3/GIS 同一 session KG，get_any_kg 调用清零 | `[PLANNED]` |

---

## 6. 与提案的衔接

| 提案 | 在本集成中的角色 | 提案状态 |
|------|------------------|----------|
| [three-stage-integration](../proposals/three-stage-integration.md) | 本文档的完整原版（含改动清单/验收矩阵） | `[PARTIAL]` I4已实现 |
| [parse-spatial-grounding](../proposals/parse-spatial-grounding.md) | I3 的 SpatialReferenceSpec 闭环 | `[PARTIAL]` ~2/5 |
| [execute-kg-utilization](../proposals/execute-kg-utilization.md) | I4/I5 激活的 execute_queries 命名空间 | `[PARTIAL]` L4已实现 |
| [analysis-kg-integration](../proposals/analysis-kg-integration.md) | I2 的 L1 KG 查询基础 | `[PARTIAL]` L1已实现 |
| [zoning-custom-functional](../proposals/zoning-custom-functional.md) | L3 industry 维度触发的 EXECUTE 生成类型 | `[PARTIAL]` ~3/7 |
