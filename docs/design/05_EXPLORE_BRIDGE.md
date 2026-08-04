# EXPLORE：横向事实与证据探索能力

## 1. 定位

EXPLORE 回答：

> “系统还需要知道什么，才能让当前阶段继续并且可解释？”

EXPLORE 不是空间接地器，不是 PARSE 的前置候选生成器，也不是 GIS 的桥接格式转换器。它只生产 `EvidenceBundle`、`ExplorationResult` 和 `ExplorationRequest` 的闭环记录。

## 2. 输入与输出

```python
class ExplorationRequest(BaseModel):
    request_id: str
    requested_by: Literal['l1', 'l2', 'l3', 'ground', 'validate']
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

| 调用者 | 目的 | 例子 |
|---|---|---|
| L1 Gate | 补齐现状和数据来源 | 缺少自然村人口、道路等级或水体范围 |
| L2 Gate | 验证策略依据 | 生态策略与现状约束是否冲突 |
| L3 Gate | 补齐规划目标依据 | 设施服务需求、项目规模、村民诉求 |
| GROUND Gate | 处理实体歧义 | 同名自然村或多个 KG 实体匹配 |
| VALIDATE Gate | 解释成果与文本不一致 | 规划设施缺少对应需求或来源 |

## 4. Agent 行为边界

EXPLORE Agent 可以：

- 选择 KG、RAG、报告、外部数据等工具。
- 组合多次查询并总结证据。
- 标记冲突、时效性和不确定性。
- 产生新的 `ExplorationRequest`。

EXPLORE Agent 不可以：

- 写 `L3PlanningIntent`。
- 写 `IntentGraph` 或 `PlannedState`。
- 生成 `candidate_bsm_list` 作为规划候选。
- 修改 `SpatialReferenceSpec`。
- 绕过 Gate 直接触发 EXECUTE。

## 5. 与 PARSE 的关系

推荐流程：

```text
L1/L2/L3 产生 InformationNeed
  → EXPLORE 返回 EvidenceBundle
  → L3 IntentCompiler 消费 EvidenceBundle
  → 生成 SpatialReferenceSpec 和 L3PlanningIntent
```

EXPLORE 与 PARSE 的共享契约是证据引用和实体引用，而不是共同生成一份“半解析、半接地”的空间结果。

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
