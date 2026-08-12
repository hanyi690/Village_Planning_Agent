# EXPLORE：横向事实与证据探索能力

## 1. 定位

EXPLORE 回答：

> “系统还需要知道什么，才能让当前阶段继续并且可解释？”

EXPLORE 不是空间接地器，不是 TARGET_PROJECTION 的前置候选生成器，也不是 GIS 的桥接格式转换器。它是
session-wide evidence service：统一搜索 KG、VillageBundle、各层报告、`【INSTRUCTION】`、typed
artifacts、已有证据、用户修订记录和允许的外部来源，生产 `EvidenceBundle`、`ExplorationResult`
和 `ExplorationRequest` 的闭环记录。

当前实现边界：`retrieve_evidence()` 已接入 KG、Bundle、报告和 instruction retrievers；typed artifact、
历史证据、用户修订和外部来源的 session-wide 索引仍不完整。L1/L2/L3 worker 目前多以维度名发起
`context_injection` 查询，尚未普遍使用 intervention-specific、evidence-gap-specific 查询计划。
因此 EXPLORE 当前是多源证据补充服务，不应描述为已经完成的规划空间认知 Agent。

地名解析的目标方案见 [12_PLACE_NAME_RESOLUTION.md](12_PLACE_NAME_RESOLUTION.md)：EXPLORE 应将 KG
候选、L1 typed location facts、实体关系和 Bundle 几何组织为 `PlaceEvidenceIndex`，但不直接选择最终
地块。当前 `PlaceNameResolver`/Gazetteer 仍以 KG 聚类、外部锚点和模糊匹配为主，L1 facts 尚未成为
统一的候选评分输入。

## 2. 输入与输出

### EXPLORE

检索能力存在，但必须从：

```
dimension_name → generic evidence
```

升级为：

```
intervention_id + spatial question + evidence gap
→ targeted KG/bundle/report evidence
```


```python
class ExplorationRequest(BaseModel):
    request_id: str
    requested_by: Literal['l1', 'l2', 'l3', 'ground', 'validate']
    dimension_key: str | None = None
    query_purpose: str
    questions: list[str]
    required_facts: list[str]
    entity_scope: list[str] = []
    source_preferences: list[str] = []
    parent_artifact_ref: str


class EvidenceItem(BaseModel):
    evidence_id: str
    request_id: str
    claim: str
    entity_refs: list[str] = []
    source_type: str
    source_ref: str
    confidence: float
    limitations: list[str] = []


class ExplorationResult(BaseModel):
    request_id: str
    evidence: list[EvidenceItem]
    unresolved_requests: list[ExplorationRequest]
    contradictions: list[dict]
    implications: list[str]
    provenance: dict
```

允许 `entity_refs` 包含 BSM、道路、水体等事实实体，但它们只是证据引用，不是规划候选集。

## 3. 调用模式

| 调用者        | 目的                 | 例子                               |
| ------------- | -------------------- | ---------------------------------- |
| L1 Gate       | 补齐现状和数据来源   | 缺少自然村人口、道路等级或水体范围 |
| L2 Gate       | 验证策略依据         | 生态策略与现状约束是否冲突         |
| L3 Gate       | 补齐规划目标依据     | 设施服务需求、项目规模、村民诉求   |
| GROUND Gate   | 处理实体歧义         | 同名自然村或多个 KG 实体匹配       |
| VALIDATE Gate | 解释成果与文本不一致 | 规划设施缺少对应需求或来源         |

EXPLORE 分为两个不同动作：

```text
Bootstrap evidence index preparation
  → 建立 Bundle / KG / session artifact 可检索索引
  → 不判断证据是否充分

Stage worker or Gate request
  → stage + dimension + query purpose + questions + evidence gaps
  → progressive retrieval
  → EvidenceBundle / SpatialCognitionEvidence
  → Gate 判断通过、重查、返工或人工审查
```

索引准备可以发生在 L1 之前，但不能替代 L1/L2/L3/GROUND/VALIDATE 的按需探索。预置查询只能提供
低成本基础上下文；当前阶段真正关心的问题必须由 worker 或 Gate 显式提交。

## 4. Agent 行为边界

EXPLORE Agent 可以：

- 根据阶段、维度和查询目的选择 KG、Bundle、报告、instruction、typed artifact、RAG 和外部数据工具。
- 组合多次查询并总结证据。
- 标记冲突、时效性和不确定性。
- 产生新的 `ExplorationRequest`。

EXPLORE Agent 不可以：

- 写 `PlanningProgram` 或 `IntentCompilationResult`。
- 写 `IntentGraph` 或 `PlannedState`。
- 生成 `candidate_bsm_list` 作为规划候选。
- 修改 `SpatialReferenceSpec`。
- 绕过 Gate 直接触发 EXECUTE。

EXPLORE 的 session 检索必须采用 progressive disclosure：先读取索引和相关 artifact 引用，再按
查询目的加载证据片段；不得默认把整个 session 原文塞入单次 prompt。KG 查询、报告读取和外部
来源都必须记录 source、context version、KG snapshot version 和 query purpose。

L1 并行启动时，同层其他报告通常尚未存在。此时 EXPLORE 必须诚实返回 Bundle/KG 等已有证据及
未解决问题，不得把“已扫描当前 session”解释为“已经获得完整 L1 认知”。跨维度报告证据在报告
产生后通过 Gate 请求增量补充。

## 5. 与 TARGET_PROJECTION 的关系

推荐流程：

```text
L1/L2/L3 产生带 stage/dimension/purpose 的 ExplorationRequest
  → EXPLORE 搜索整个 session（KG + Bundle + reports + artifacts + prior evidence）
  → 返回 EvidenceBundle / SpatialCognitionEvidence
  → L3 生成 PlanningProgram
  → TARGET_PROJECTION / IntentCompiler 消费 PlanningProgram + EvidenceBundle
  → 生成 IntentCompilationResult + SpatialReferenceSpec
```

EXPLORE 与 L1/L2/L3/TARGET_PROJECTION 的共享契约是证据引用、空间认知证据和实体引用，而不是共同生成一份
“半解析、半接地”的空间结果。

## 6. 与 GROUND 的关系

GROUND 可以在实体歧义、缺少几何或快照过期时发起新的 `ExplorationRequest`。EXPLORE 返回事实后，GROUND 从原始 `SpatialReferenceSpec` 重新解析，不直接消费 EXPLORE 拼出的 BSM 列表。

## 7. 可观测性

每次探索必须记录：

- request 和 parent artifact
- 使用的工具及参数摘要
- 返回事实和来源
- 未解决问题
- 结论置信度
- 是否导致某个阶段重跑

这样可以区分“没有查到事实”和“查询本身失败”。
