# 金田村 L1 → GROUND 定位审计

日期：2026-08-28  
数据范围：当前新建的金田村 `VillageBundle`、当前会话内重建的 KG、v5 L1 快照中的地点 mention 与事实。  
会话边界：不读取历史会话作为业务输入；本审计不运行测试。

## 结论

当前数据可以让 GROUND 为每个 L1 地点工作项产出一个“定位状态”，但不能让每个工作项都产出唯一坐标或唯一几何。现状中同时存在三类情况：

1. 当前 bundle 有唯一源特征，应该形成 `exact_feature`。
2. 当前 bundle 有同语义的多个源特征，应该形成带 BSM 的 `feature_set`，再由 GROUND 的闭集推理决定是否能收窄。
3. 报告/KG 有语义和关系，但当前 bundle 没有同名空间源，只能形成 `inferred_scope` 或明确 `source_gap`，不能生成虚拟身份、坐标或几何。

因此，“正常来说每个地点都能解析”在系统契约中应解释为：每个地点都必须有可审计的终态，而不是每个地点都必须被强行选成一个空间对象。

## 原始源事实

本次从 `DataCatalog.load_village_bundle('金田村')` 读取到：

| 源层 | 数量 | 关键属性情况 |
| --- | ---: | --- |
| `annotations_current` | 34 | 有 BSM；当前标签主要是 `停/站/广/祠/电/水/小` 等短标注 |
| `hazard_points` | 40 | 有 BSM；实际灾害名称主要位于原始属性字段 |
| `roads_current` | 131 | 有 BSM 和线几何，但道路名称字段为空 |
| `water_bodies` | 48 | 有水体面和 BSM，但没有 `金田河/石窟河` 命名几何 |
| `admin_areas` | 1 | 有行政范围源，但名称字段为空，原始属性只有编码类字段 |
| `landuse_current` | 660 | 可用于范围和邻近地块，不可直接当成河流、道路或设施身份 |

当前 KG 重建约 29,084 条三元组、347 个 EvidenceGraph 索引条目。KG 能生成当前水体实体，但名称是 `水体_<BSM>`；它没有把“金田河”自动变成某一个水面几何。

## 逐类推理记录

### 设施点

推理链统一为：

```text
L1 mention + source_span/source_refs
  → 当前事实中的数量、范围和用途
  → GIS 短标注候选
  → BSM/来源特征校验
  → exact_feature 或 feature_set
```

| L1 地点 | L1 约束 | 当前 GIS 候选 | 合法结论 |
| --- | --- | --- | --- |
| 停车场 | 1 处；位于村委会 | `停` 1 点，BSM `00000000000000000160` | 可精确绑定；仍需保留 L1 来源和村委会范围证据 |
| 公交站点 | 3 处；村庄西南部 | `站` 3 点，BSM `...141`、`...158`、`...159` | 三点 `feature_set`；不能任选一个代表全部站点 |
| 文化广场 | 2 个 | `广` 2 点，BSM `...154`、`...155` | 两点 `feature_set`；数量与源点数一致 |
| 祠堂 | 报告说社前、黄竹、田坑共 3 座 | `祠` 原始点有 13 个 | 先保留 13 点集合并记录数量冲突；不能从 13 个点随机挑 3 个 |
| 水电站 | 3 个；沿石窟河 | `水/电/站` 短标注形成多个候选，但没有明确三站的源语义闭集 | 至少是有界候选集合；需结合河流关系和源字段继续判断，无法证明时明确缺口 |

这里的 `停/站/广/祠` 不是系统内置的事实。它们是当前 GIS 原始属性，只有在 L1 事实和本次源语义分类共同支持后，才可以成为候选的语义别名；LLM 不能创造 BSM 或坐标。

### 道路

L1 给出“122乡道是村中唯一的东西方向道路”，但当前 `roads_current` 只有 131 条线几何，没有道路名称。当前 runtime 对真实线几何做 15° 容差方向过滤后得到 26 条东西向候选，所以当前源仍不能证明哪一条是 `122乡道`。

合法的推理结果是：

```text
122乡道
  → L1 关系：is_sole + east_west
  → 当前 131 条道路线
  → 几何方向过滤得到有界候选集
  → 若仍多条：feature_set/corridor + source_gap
```

不能把最长线、第一条线或某条空间上看似居中的线命名为 122 乡道。`村道` 同样只能在当前道路源字段和 L1 关系足够时形成集合，不能用“没有名称”当成唯一身份。

### 水体

L1 原文明确给出：金田河由西南至东北贯穿金田村并汇入石窟河；另一事实给出水电站主要沿石窟河布置。这些是有效的关系和方向证据，但当前 bundle 只有未命名水体面，KG 也只有 `水体_<BSM>`。

因此：

* `金田河` 可以解析为带来源的水体检索任务，附带 `SW→NE`、`traverses(金田村)` 和 `confluence(石窟河)` 关系。
* `石窟河` 可以作为接收水体/空间锚点参与 GROUND 迭代。
* 不能把 48 个水面中的任意一个提升成金田河，也不能把 landuse parcel 集合当作河流几何。
* 若没有新的命名水系线或可验证的水体关系，终态应为有界水体集合或 `source_gap`。

### 自然村、建筑集中区和历史地点

报告和 L1 已经提供了 `园寨、马头段、社前、炉池` 等名称以及它们之间的业务关系；当前 GIS bundle 没有同名自然村面，也没有古驿道、古茶亭、千年古檀、蕈树的权威空间特征。

这些地点应保留：

* mention、原文片段、报告引用和关系；
* `search_scope` 或 `inferred_scope`；
* 当前源没有对应几何的明确诊断。

它们不能因为 LLM 理解了报告就变成虚拟 KG entity、虚拟 BSM 或虚拟坐标。

### 非空间工作项

`农业`、`杉木家具制造业` 属于产业语义，不应被强行塞入地点解析队列。它们可以保留在 L1 事实和后续业务维度，但 GROUND 应给出 `not_spatial_work_item`，而不是把“未找到地点”记成检索故障。

## 实现反查结果

本次发现的实现问题有四类：

1. L1 的 `parent_area/building_concentration_area/new_building_location/facility_location/...` 曾直接进入源角色过滤，导致已存在的 scope 证据被过滤掉。现在统一转换为 GROUND 的 `scope`，道路、设施等工作项再转换为对应源角色。
2. `semantic_type=unknown` 时，运行时没有读取 `attributes.entity_type` 和 `instance_label`，导致停车场、公交站点、祠堂、水电站等候选词未进入闭集。现在 L1 mention 本身可以动态生成候选，已知类型只用于可选的图层/几何收紧，不再作为新实体的准入白名单。
3. GIS 属性投影曾只读取少量固定字段。现在源语义描述同时读取当前 feature 的 `_raw`、`properties`、模型字段中的标量元数据，并隔离 geometry、坐标和身份字段；字段名称不同不会让语义证据静默丢失。
4. KG 查询实体现在保留 RDF literal 属性对，便于 KG 的 canonical name、alias、type 和其他属性与 GIS 描述一起进入语义判断。身份仍由 KG/bundle 提供，LLM 只做闭集选择。
5. 源语义、GROUND 候选选择、L1→GROUND 批量选择和 GROUND 目标优先级的模型输入现在统一经过 `Context Runtime.build_bounded_table()`；模型看到的是有界结构化表格，JSON 仅用于内部 digest 和持久化。没有业务语义的匿名道路行不会消耗 provider 调用，但仍保留 unresolved 终态。

属性抽取没有依赖正则或某个村庄的实体枚举：字段名只用于安全隔离身份/几何字段，其他标量属性原样作为本次快照的语义输入；语义归类交给 LLM，候选引用和空间合法性由运行时校验。

## 仍需继续收敛的实现点

* GROUND 的 `evidence_graph_join` 必须把 `candidate_count=0` 区分为“角色过滤错误”“名称缺失”“当前源没有该几何”“provider 超时”，不能统一记成 unresolved；当前已补充道路/水体的按角色源候选召回，仍需把这些原因完整收进最终阶段状态。
* 道路方向关系应产出可审计的候选集合和几何摘要，并通过闭集选择；不能借助首项或最长项兜底。
* 水体查询只能返回水体层候选或水体范围，不能回退到 landuse parcel 来假装河流。
* 真实源语义分类必须按当前快照持久化输入 digest、候选词表、provider 状态和每个 source feature 的 accepted/ambiguous/unresolved 结果；provider 超时要形成诊断，不得改变身份状态。
* 每轮新增证据后，GROUND 要重新评估仍未解析的地点，并在 trace 中记录“哪些新证据使哪些候选可解析”；已经达到终态的地点不可被后续弱证据覆盖。

## 本轮验证

已完成：

* 当前金田村 bundle 的真实层数量与字段检查；
* 当前 KG 的重新构建；
* L1 35 个地点工作项的 EvidenceGraph 逐项查询；
* GIS 原始属性泛化投影与 BSM fallback 的编译检查；
* 真实道路角色召回读取 131 条源候选，东西向过滤得到 26 条候选；真实水体角色召回返回 44 条源候选；两者均保持 `ambiguous`，没有自动选首项；
* 源语义和 GROUND 的模型上下文表格化、统一字符/行预算的编译与金田村字段投影检查；
* `backend/app/infrastructure/evidence_runtime`、`backend/app/infrastructure/kg`、`backend/app/contracts` 的 `compileall`。

未完成：

* 之前针对 34 个设施点和 131 条道路的 MiniMax 源语义分类发生 `TimeoutError`，165 个 decision 中 accepted=0。系统保留为 unresolved，没有把超时结果写成语义映射；本轮已将批次降至 16、改用统一表格上下文，并在 provider 前过滤只有来源元数据/纯数值的匿名道路行，尚未重新消耗一轮真实 provider 配额。

## 当前上下文与历史隔离补充

本轮进一步移除了生产输入面上的历史回流：L1 不再从 session step reports 恢复旧
observe payload，L1 aggregate 不再从 step reports 补写 `kg_evidence_consumed`，
context bootstrap 和 PlanningContext 也不再自动加载 `kg_memory/*_round_*.json`；
gazetteer 不再读取 `data/gazetteer/*.json`。这些文件若存在，只能作为审计或清理对象，
不能改变当前冻结 bundle/KG、当前 artifact/CAS checkpoint 或本轮 Evidence Runtime 的
结果。当前 L1 重新执行会从当前 source digest 开始，无法恢复时保留诊断而不借旧结论补齐。

直接给 LLM 的阶段输入统一经过 Context Runtime 的 `build_bounded_table()`：source
page、Evidence facts/coverage/gap、依赖 decision/claim、source semantic rows、GROUND
候选/目标和 SELECT 场景均受同一行数与字符预算约束。表格单元格内部允许有限的结构化
列表/映射，但不再把 Python 对象通过 `str()` 作为无结构业务上下文发送；JSON 仅保留在
digest、artifact、checkpoint 和审计存储面。
