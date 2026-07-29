# 三阶段有机集成设计

## —— 现状分析(28维) ⇄ 规划定位 ⇄ 规划细化,与 KG/grounding/EXECUTE/L4 闭环

> 状态:提案(待评审) | 日期:2026-07-29
> 关联:v3 重构、ZONING、PARSE_SPATIAL_GROUNDING、EXECUTE_KG_UTILIZATION 四提案的集成总成
> 触发:用户指出"28个维度分析、规划定位、规划细化的实现没有充分利用、没有有机结合"

---

## 0. 诊断:三阶段是"文本生成+DB中转"流水线,与空间能力全链路脱节

调查确认 11 个断点,归为五类:

| 类                     | 断点                                                                                             | 证据                                                           |
| ---------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| **A 信息流断裂** | ① L1 问题未结构化喂 L2,全文本经 DB 中转                                                         | node.py L399-403;concept.py L36`{analysis_report}` 塞全文    |
|                        | ⑪ L3 的`planning_concept` 与 `analysis_report` 同源(同一 deps)                              | node.py L962-963                                               |
|                        | ④ intent_targets 是文本占位非 grounding                                                         | detailed.py L840-845,"N/A"兜底                                 |
| **B KG 未用**    | ② L2/L3 完全不查 KG                                                                             | node.py L667`if dim_layer != 1: return ""`                   |
|                        | ⑨ KG 实例不一致(L1 用`get_any_kg`,GIS 用 `get_session_kg`)                                  | node.py L691 vs layout_pipeline.py L232                        |
| **C L4 断链**    | ⑤ EXECUTE 后无`write_kg_l4` 节点;layer4.py 定义了却从未调用                                   | layout_pipeline.py L417-422 无 L4 写回                         |
|                        | ⑥ L3 细化无机制读 L4 PlannedState 做一致性校核                                                  | detailed.py 全文无 L4 读取                                     |
| **D 触发脱节**   | ③ 空间定位职责错位:ZoneTarget 应由 PARSE 子agent 产(消费 L1/L2/L3+grounding),现状从 L3 文本反推 | layout_pipeline.py L123`_parse_intent_node` 读 state.reports |
|                        | ⑦ gis_agent 仅手动触发,L3 完成后`after_analysis` 不路由到它                                   | routing.py L129-300 无 gis_agent 分支                          |
|                        | ⑧ PARSE 双重执行(gis_agent 调一次,pipeline 内再 parse),且 reports 未传入                        | graph.py L97/L117 vs layout_pipeline.py L123                   |
| **E 死代码**     | ⑩ detailed.py L874-910 在 return 之后,professional_data 永不执行                                | detailed.py L871/874                                           |

**三阶段本该是闭环,现状是开环甚至断环:**

```
L1现状(28维) ──文本DB──> L2定位 ──文本DB──> L3细化 ────> GIS(EXECUTE) ──✗L4断链──> 无校核回环
     │KG浅查                  │不查KG         │不查KG            │独立KG实例
```

---

## 1. 目标:闭环有机集成

```
L1现状(28维) ──结构化问题清单──> L2规划定位(策略性) ──strategic context──> L3细化(轮1生成)
     │analysis_queries               │analysis_queries+shared_queries        │execute_queries
     │KG认知摘要                      │村庄分类/发展方向/口号(文本,本就正确)  │↓ L1+L2+L3 上下文喂入
                                                                              ┌─────────────────────┐
                                                                              │ PARSE 子agent        │ ← 空间定位唯一生产者
                                                                              │  消费 L1+L2+L3+用户NL │
                                                                              │  + KG认知 + grounding │
                                                                              │  → ZoneTarget+Spec   │
                                                                              │  → grounded BSM      │
                                                                              └──────────┬──────────┘
                                                                                         │ 写 KG L3 intent
                                                                                         ▼
                                                    EXECUTE生成 → write_kg_l4(derived_from) → L3校核轮(读L4对账) → 规划文本
```

**六处改造闭合五个断点类**,严格复用四提案已设计的能力,不新增范式。

---

## 2. 改造 I1:L1→L2 结构化问题清单(治断点①⑪)

现状 L1 报告全文本喂 L2,L3 的 planning_concept 与 analysis_report 同源。改造:

- L1 每个 dimension 的 `summary`(已结构化 JSON,node.py L575)扩展产出**问题/资源条目**:`{dimension_key, issues:[{topic, severity, spatial_hint}], resources:[{type, scale, location_hint}]}`;
- `concept.py` 的 `{analysis_report}` 占位拆为两部分:`{analysis_findings_structured}`(问题/资源清单 JSON)+ `{analysis_report_text}`(全文,降级兼容);
- L3 的 `planning_concept` 改为**独立读 L2 报告**(node.py L962-963 修复:从 DB 取 layer=2 报告,不复用 deps)。

**收益**:L2 定位基于结构化问题清单(如"耕地破碎化严重+林地占90%")而非全文扫描;L3 拿到的是 L2 真实结论不是 L1 复读。

---

## 3. 改造 I2:L2/L3 开放 KG 查询(治断点②⑨)

现状 `node.py L667 if dim_layer != 1: return ""` 一刀切禁了 L2/L3 的 KG 查询。改造:

- 拆闸门为**按命名空间分派**(对应 KG_SPATIAL_COGNITION §十):
  - L1 → `analysis_queries`(粗,semantic)——现状已用,保留
  - L2 → `analysis_queries` + `shared_queries`(定位需认知摘要做约束校核:村庄分类、三区三线覆盖、资源禀赋)
  - L3 → `execute_queries`(本提案激活的 6 模式)+ `shared_queries`(细化需 get_area_by_type 算现状结构、get_parcel_context 校布局)
- KG 实例统一(治⑨):`_optimize_semantics` 改用 `manager.get_session_kg(session_id)`,与 GIS pipeline 同一实例,L1 查的 KG 就是 session KG;
- L2/L3 的 `phases.yaml` 增加 `kg_query` 字段(类比现有 `rag_query`),声明该维度需查的 KG 模式;空则跳过(与 RAG 同机制)。

**收益**:L2 定位能"基于 KG 认知校核"(如定位为集聚提升类时,KG 确认生态红线覆盖率是否支持);L3 细化能"基于 KG 现状结构校核"(如用地布局调整不超三区指标)。

---

## 4. 改造 I3:PARSE 子agent 作为空间定位唯一生产者(治断点③④⑧)

> **纠正(2026-07-29)**:前版误将"规划定位"当作空间定位,让 L2 产 ZoneTarget。实则 L2 的"规划定位"是**策略性定位**(村庄分类、发展方向、形象口号、规划策略),本就是文本且正确,不应空间化。**空间定位(ZoneTarget/grounding)是 PARSE 子agent 的职责**,消费 L1/L2/L3 上下文产出。L2 不动。

**现状问题**:PARSE 不是正经子agent,而是 layout_pipeline 内的 `_parse_intent_node`(L123)从 `state.reports`(L3 文本)反推 ZoneTarget;加上 graph.py L97 gis_agent_node 又独立调 `create_parse_agent_graph`,**双重 parse 且 reports 未传入**(⑧)。空间定位既不消费 L1/L2 策略上下文,也不做 grounding,纯文本反推。

**改造(L2 不动,集中在 PARSE)**:

- PARSE 升级为**正经子agent**,消费三路上下文:① L1 结构化问题/资源清单(I1);② L2 策略定位(村庄分类决定分区方向、发展方向决定产业用地、形象口号无空间语义);③ L3 细化文本(具体布局意图);外加 ④ 用户 NL(显式空间请求);
- PARSE 经 instructor 产出 **ZoneTarget/FacilityTarget/AxisTarget/RoadTarget**(结构化),每个 target 的 `spatial_preference_desc`(NL)→ **SpatialReferenceSpec** → KG 候选 BSM → spatial_ops 精化 → ResolvedSpatialRef(PARSE_SPATIAL_GROUNDING 提案闭环);
- **消除双重 parse(⑧)**:graph.py gis_agent_node 不再独立 `create_parse_agent_graph`,统一由 layout_pipeline 的 PARSE 节点做;`reports`(L1/L2/L3)显式传入 pipeline input(graph.py L117-133 修复);
- 接地结果写 KG L3(`kg.build_intent_layer`,layout_pipeline.py L237 现成);
- L3 细化的 `intent_targets` 占位改为读**已接地的 ResolvedSpatialRef**(geometry+BSM),非"N/A"标量(治④)。

**收益**:空间定位职责归位——L2 保持策略性文本不动,PARSE 子agent 消费全量上下文+grounding 产出 ZoneTarget,消除"L3 文本反推"和"双重 parse"两个问题。L2 策略(如"集聚提升类+杉木家具产业")作为 PARSE 的**引导信号**(决定要规划什么类型的 zone),而非直接产 zone。

---

## 5. 改造 I4:EXECUTE 后 write_kg_l4 + derived_from(治断点⑤)

**最致命断点**:layer4.py 定义了 PlannedParcel/PlannedZone/PlannedFacility 却从未被调用。改造:

- layout_pipeline 边 `execute → write_kg_l4 → detect_conflicts → export_gdb → render_map → END`(在 execute 后插 `write_kg_l4` 节点);
- `write_kg_l4` 调 `kg/builder/layer4.py`(激活),写 L4 实体带 provenance:`pln:derived_from → L1 BSM`、`pln:source_spec → L2 spec`、`pln:decided_by`、`pln:operation`(EXECUTE_KG_UTILIZATION §3);
- `detect_conflicts` 改用 `execute_queries.get_conflict_set`(L2 关系粗筛)+ spatial_ops 精算,替现状启发式。

**收益**:规划成果进 KG,可被查询/校核/版本对比;derived_from 链使"规划可回溯到现状图斑 + 定位 spec"落到数据层。

---

## 6. 改造 I5:L3 细化读 L4 回写校核(治断点⑥)

现状 L3 完全无机制读 L4。改造为**两轮 L3**:

- **L3-轮1(生成)**:L3 各维度基于 L2 intent + KG 认知生成细化文本(现状流程);
- **EXECUTE 触发**:L3-轮1 完成后触发 GIS pipeline(grounding→EXECUTE→write_kg_l4);
- **L3-轮2(校核)**:L3 读 L4 PlannedState,对每个维度做一致性校核:
  - `land_use_planning` 维度:`execute_queries.get_area_by_type` 算 L4 规划后面积 vs L3 文本表述的面积,不一致则修正文本;
  - `spatial_structure` 维度:读 L4 PlannedZone 的 derived_from 链,校核"二心二轴四区"结构是否与文本一致;
  - `project_bank` 维度:读 L4 PlannedFacility 的 operation/area,校核项目表;
- 校核结果写回 DB(version+1),触发条件:`after_analysis` 在 L3-轮1 完成且 L4 已回写时分派 L3-轮2。

**收益**:规划文本与规划几何双向一致(文本说"耕地127.18公顷",L4 算出来也是 127.18);消除"文本与图不符"的村庄规划通病。

---

## 7. 改造 I6:触发编排 + 死代码(治断点⑦⑧⑩)

- ⑦ `after_analysis` 增加 L3→GIS 自动路由:L3-轮1 完成→grounding(I3)→EXECUTE→write_kg_l4(I4)→L3-轮2(I5),不再手动调 gis_analysis;
- ⑧ PARSE 单一化:graph.py L97 的 gis_agent_node 不再独立 create_parse_agent_graph,L2 结构化 intent(I3)直接喂 layout_pipeline,消除 pipeline 内重复 parse;`reports` 显式传入 pipeline input;
- ⑩ 删 detailed.py L874-910 死代码,professional_data 格式化逻辑移到 return 之前(或确认废弃移除)。

---

## 8. 改动清单与验收

### 8.1 改动(6 改造,按优先级)

| 改造                      | 文件                                                                                                                  | 估算   | 优先级         |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------ | -------------- |
| I4 write_kg_l4            | layout_pipeline.py(插节点)、kg/builder/layer4.py(激活)                                                                | ~150行 | P0(最致命断链) |
| I3 PARSE 子agent 空间定位 | graph.py(去双重parse)、layout_pipeline.py(parse 读 L1/L2/L3+grounding)、node.py(intent_targets 读 ResolvedSpatialRef) | ~200行 | P0             |
| I2 L2/L3 开放 KG          | node.py(拆闸门)、phases.yaml(kg_query 字段)                                                                           | ~120行 | P1             |
| I5 L3 校核轮              | node.py(L3-轮2)、detailed.py(读 L4)、routing.py(分派)                                                                 | ~180行 | P1             |
| I1 结构化问题清单         | node.py(L1 summary 扩展)、concept.py                                                                                  | ~100行 | P2             |
| I6 触发编排+死代码        | graph.py、routing.py、detailed.py                                                                                     | ~80行  | P2             |

### 8.2 验收(金田村端到端)

| 用例              | 期望                                                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| L1→L2 结构化传递 | L2 positioning prompt 含结构化问题清单 JSON,非全文                                                                              |
| L2 查 KG          | planning_positioning 查 analysis_queries,定位"集聚提升类"时 KG 确认生态红线覆盖率(策略性定位,仍为文本)                          |
| PARSE 空间定位    | PARSE 子agent 消费 L1+L2+L3+NL,产 ZoneTarget;spatial_preference_desc 经 SpatialReferenceSpec 接地为 ResolvedSpatialRef,写 KG L3 |
| L4 回写           | EXECUTE 后 KG 含 PlannedParcel×N,derived_from 链可 SPARQL 查回 L1 BSM + PARSE spec                                             |
| L3 校核轮         | L3-轮2 读 L4,land_use_planning 文本面积 = get_area_by_type 算的 L4 面积                                                         |
| 闭环              | NL→L1问题→L2策略(文本)→PARSE(spec+grounding→BSM)→EXECUTE(L4)→L3校核→文本,全链 provenance 可查                            |
| KG 实例统一       | L1/L2/L3/GIS 同一 session KG,get_any_kg 调用清零                                                                                |

### 8.3 与四提案衔接矩阵

| 提案                    | 在本集成中的角色                                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------ |
| v3 重构(编码中心)       | L3 校核轮的 get_area_by_type 用统一编码映射算面积;L4 derived_from 带编码 provenance        |
| ZONING(自定义分区)      | L3 industry 维度触发的 EXECUTE 生成类型之一;L4 FunctionalZone 进 KG                        |
| PARSE_SPATIAL_GROUNDING | I3 的 SpatialReferenceSpec 闭环由 PARSE 子agent 驱动;L2 策略定位作引导信号(非 spec 生产者) |
| EXECUTE_KG_UTILIZATION  | I4/I5 激活的 execute_queries 命名空间;L4 回写+校核的总线                                   |

## 9. 一句话总结

三阶段没有机结合的根因是"文本生成+DB中转"开环——L2/L3 不查 KG、空间定位(ZoneTarget)错位地由 L3 文本反推而非 PARSE 子agent 正经产出、EXECUTE 的 L4 完全断链。六个改造闭合为闭环:**L1 产结构化问题清单→L2 产策略性定位(文本,不改)→PARSE 子agent 消费 L1/L2/L3+NL 经 grounding 产出 ZoneTarget+grounded BSM→EXECUTE 生成 L4 带 derived_from→L3 校核轮读 L4 做文本/几何一致性校核**,全程同一 session KG,provenance 从 NL 贯通到 L4。这正是四提案(v3/ZONING/PARSE/EXECUTE)的集成总成——每条改造都复用已设计能力,不新增范式。
