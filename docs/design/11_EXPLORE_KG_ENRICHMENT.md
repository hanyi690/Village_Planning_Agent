# EXPLORE 与 KG 的证据富化

## 1. 目标

EXPLORE 使用 KG 提高规划分析的事实密度，但不把 KG 查询结果直接变成规划候选或执行命令。

## 2. 查询链

```text
ExplorationRequest
  → query plan
  → SemanticQueryPort / RAG / Data Provider
  → EvidenceItem
  → EvidenceBundle
  → requesting stage
```

## 3. KG 查询类别

| 查询 | 返回 | 典型用途 |
|---|---|---|
| entity lookup | 实体和来源 | 同名村、设施、道路识别 |
| relation lookup | 邻接、包含、连通关系 | 现状认知、策略校核 |
| constraint lookup | 管制和冲突 | L1/L2 证据、Validation |
| cognition summary | 汇总事实 | 维度分析 Prompt |
| provenance lookup | 来源和时效 | 置信度和人工审查 |

## 4. 与空间决策的边界

EXPLORE 可以发现“园寨实体对应 BSM-001 和 BSM-017”，但返回的是两个 `entity_refs` 及其来源。它不把二者写入 `candidate_bsm_list`，也不判断哪个适合建设养老设施。

GROUND 再根据 PARSE 生成的 `SpatialReferenceSpec` 查询候选；SELECT 再根据目标指标和约束进行选址。

## 5. 缓存与失效

- EvidenceBundle 的缓存键必须包含 request、context version、KG snapshot version 和 query purpose。
- BaseFacts 更新时，相关 EvidenceBundle 标记 stale。
- stale 证据不能直接进入 L3 Gate 或 PlacementDecision。
- 任何外部查询结果都记录 provider、时间、坐标系和原始引用。

## 6. 审计字段

```text
EvidenceItem
├── evidence_id
├── request_id
├── source_type / source_ref
├── kg_snapshot_version
├── claim
├── entity_refs
├── confidence
├── limitations
└── created_at
```
