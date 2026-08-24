# Evidence and Grounding

> Status: TARGET
> Authority: Normative behavior for evidence retrieval, semantic location resolution, spatial query and GROUND; current implementation is documented in `../architecture/CURRENT_RUNTIME.md`.

## 1. Evidence requirements, not raw queries

检索入口不是一条随意的自然语言 query，而是一组从 L1/L2/L3、TARGET_PROJECTION 或 GROUND 编译出的 `EvidenceRequirement`。每项要求至少说明：待支持的 claim/decision、必需或可选、适用范围、来源族、时效、空间粒度、允许的推断等级和成功条件。

原始问题“学校应该放在哪里”至少要拆成：人口与居民点、现状学校、服务半径规范、禁建范围、可建设地块、道路可达性、成本或容量等独立要求。一个 top-k 文本集合不能同时证明这些要求。

## 2. Source families and authority

| 来源族 | 主要用途 | 可提供定位 | 权威边界 |
|---|---|---|---|
| session reports | 现状、策略、规划文本 | report/page/section/span/table cell | 文字证据；不能直接成为几何 |
| bundle/structured data | 当前空间要素、属性、canonical membership | dataset/snapshot/layer/feature ID | 项目内空间身份和几何的首要来源 |
| KG/entity graph | 别名、实体关系、行政与拓扑语义 | entity/edge ID | 用于消歧和关系发现；不能替代 authoritative geometry |
| artifact store | L1/L2/L3、历史决定、阶段产物 | artifact ref/revision/digest | 只代表相应阶段和快照 |
| professional RAG | 规范、政策、方法、案例 | source/chunk/page/span | 外部专业背景；不能证明村内对象存在 |
| external web | 最新公共事实和缺失资料 | URL/date/quoted span | 必须经过外部证据策略；不得直接生成 BSM/坐标 |

每个 EvidenceClaim 必须保留 `source_kind`、`evidence_role`、authority、locator、version/digest 和检索路径。来源融合不能抹平权威差异。

## 3. Query decomposition and routing

控制器按 requirement、来源族和证据作用生成子查询，而不是对所有来源广播同一句话：

```text
compile requirements
→ retrieve per requirement/source family
→ fuse and rerank
→ bind claims and spatial identities
→ judge supported/contradicted/ambiguous/unavailable
→ generate only missing subqueries
→ stop at sufficient, source-exhausted, human-required, or budget-exhausted
```

查询计划必须记录：query ID、requirement ID、retriever、filters、top-k/budget、开始时间、结果数量、失败原因和重试关系。下一轮只针对缺口生成子查询，禁止把已满足的全部问题反复检索。

## 4. Hybrid retrieval and embedding degradation

目标检索至少包含四类独立通道：

- 结构化：artifact metadata、bundle、数据库字段和显式 ID；
- 词法：BM25/FTS、短语、别名、编号、章节和表格字段；
- dense：embedding 相似度，用于同义表达和语义召回；
- graph/spatial：KG 邻接、实体解析、拓扑、范围、距离和网络查询。

融合按 requirement 进行，可使用 reciprocal-rank fusion、来源配额和字段权重；reranker 只能调整已召回证据顺序，不能生成证据。必须保留每个候选来自哪些通道。

嵌入服务失效时：

1. 标记 dense channel 为 unavailable，并记录 provider/model/error；
2. 继续结构化、词法、本地报告、KG 和空间检索；
3. 扩展别名、领域词表和确定性 query variants；
4. 降低 `bounded completeness` 置信度，指出可能漏掉的语义改写；
5. 不把“向量不可用”写成“检索系统不可用”，也不把低召回静默写成 sufficient。

professional vector RAG 与 session-owned local text 是两个 retriever。前者不可用时不得阻断后者，后者也不能假装已经覆盖外部规范库。

## 5. Claim-evidence graph and contradiction handling

检索结果必须先转成 claim-evidence graph：

```text
EvidenceRequirement
  → EvidenceClaim
      → source locator
      → supports / contradicts / qualifies
      → spatial entity candidate
```

同一主张可以有多个来源，来源之间可以支持、限制或冲突。冲突处理顺序：检查是否不同时间、范围、口径或实体；按配置的权威规则判断；仍无法消解则标记 `contradicted` 或 `ambiguous` 并进入人工裁决。不得仅以相似度、来源数量或 LLM 偏好消除冲突。

规划阶段引用 claim ID；claim 反向引用证据 locator。摘要文本只是视图，不能成为新的无来源事实。

## 6. Structured sufficiency and gap loop

`EvidenceCoverage` 对每项 requirement 给出：状态、已采用 claim、来源族覆盖、定位完整性、冲突、剩余缺口和停止原因。总体 sufficient 只能由必需要求聚合产生，不能由“返回了 N 条内容”或平均相关分判定。

需要继续检索的缺口必须类型化：缺来源族、缺时间有效性、缺空间身份、缺精确定位、存在冲突、证据只支持弱推断或来源不可用。预算耗尽不是 sufficient；它是带剩余缺口的可诊断终止。

## 7. Natural-language spatial query AST

自然语言空间请求先解析为受限 `SpatialQuery` AST，再由确定性 adapter 执行。建议节点包括：

```text
EntityRef(name, type, aliases, scope)
DatasetRef(dataset_id, snapshot_id, layer_id)
AttributeFilter(field, operator, value, unit)
SpatialPredicate(within, intersects, contains, touches, nearest)
DistancePredicate(metric, threshold, unit, network_mode)
TopologyPredicate(connected_to, upstream_of, adjacent_to)
Aggregate(count, area, length, min, max, sum)
Sort(metric, direction)
Limit(k)
```

示例“找金田村北部、距主干路 500 米内且不在生态红线内的建设用地”应编译为有 scope、dataset snapshot、方向分区定义、距离 metric 和排除谓词的 AST。任何未解析实体、单位、CRS 或时间快照都必须留在 unresolved，不能交给 LLM 补坐标。

AST 必须白名单化谓词和字段，参数化执行，不暴露自由 SQL。结果返回 feature refs、几何 refs、解释路径、查询 fingerprint 和排除统计。

## 8. Feature identity, geometry, CRS, scale, and uncertainty

“语义地点落地”按以下顺序进行：

```text
文本 mention
→ entity candidates / aliases
→ scope and temporal disambiguation
→ authoritative dataset and snapshot
→ feature identity
→ geometry reference
→ topology/network verification
→ GroundedCandidateDomain
```

位置必须区分：exact authoritative geometry、derived geometry、inferred extent 和 text-only mention。后两者只有在策略明确允许且风险被批准时才能成为可执行输入。

每个空间引用必须记录原 CRS、计算 CRS、转换版本、精度/scale、有效时间、geometry digest 和 uncertainty。距离、面积、缓冲区和网络时间必须声明计算方法。用村中心、行政面质心或同类任意 feature 作为 fallback 时，必须标记为 degraded；不能把 fallback 表述为精确定位。

候选域要保留所有纳入/排除成员及原因，并区分 `all_members`、`choose_one`、`choose_subset`。数量相等不代表身份相同；报告数量、GIS feature 数、KG entity 数和规划输出数不能直接互证。

## 9. External evidence policy

只有 requirement 明确需要最新、项目外或本地缺失的事实时才启用 external source。外部证据必须记录 URL、访问时间、发布日期、publisher、locator 和内容 digest，并按来源权威性分类。

外部搜索可以支持规范阈值、政策背景、案例和方法，不得直接声称某个项目内地块、道路或设施存在。外部文本若提到项目内地点，仍需通过 bundle/KG/authoritative dataset 完成身份和几何绑定。外部证据变化只使相关 claim 和下游 fingerprints 失效，不允许静默更新已批准执行输入。

## 10. Output contract and stop conditions

Evidence plane 的规范输出是 EvidenceClaim、EvidenceCoverage、query trace 和可选的 entity candidates；GROUND 的规范输出是 `GroundedPlanningProblem`。后者必须包含完整候选域、候选几何引用、约束因子、关系测量、网络/共享资源引用、source artifacts、baseline、unresolved/deferred 和 fingerprint。

GROUND 的停止状态：

- `candidate_complete`：所有可执行目标都有足够的闭合输入；
- `evidence_required`：缺失证据可通过 EXPLORE 继续补齐；
- `human_required`：歧义或降级风险需要批准；
- `not_groundable`：在当前来源范围内无法建立空间身份；
- `source_exhausted` 或 `budget_exhausted`：保留缺口后停止。

GROUND explicitly forbids final location selection. 它不得写入 recommended scenario，不得按评分删除合法备选，也不得为求解方便创造 coordinates。只有达到 grounding gate 的 `GroundedPlanningProblem` 才能产生可行/推荐 ScenarioSet；不完整问题允许进入 ScenarioOptimizer 生成带 finding 的 provisional rows 供诊断和部分交付，但不得进入 feasible、approval 或正式执行。
