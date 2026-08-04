# KG 空间认知补充

> 本文档已收敛为 [03_KG_SEMANTIC_BRIDGE.md](03_KG_SEMANTIC_BRIDGE.md) 的补充索引。旧版“四层 KG + Agent 直接候选绑定”的方案不再作为独立设计源。

## 1. 空间认知的两部分

空间认知由两个可组合服务组成：

1. **Semantic Cognition**：KG 提供实体、关系、约束、来源和摘要。
2. **Geometric Cognition**：Spatial Query Service 提供几何、索引、距离和拓扑计算。

二者通过 `SemanticQueryPort` 和 `SpatialQueryPort` 组合，不由 EXPLORE 或 PARSE 直接持有 KG 实例。

## 2. 术语映射

| 旧术语 | 新术语 |
|---|---|
| KG L1 静态 | `BaseFacts` |
| KG L2 语义 | `DerivedRelations` |
| KG L3 Intent | `IntentGraph` |
| KG L4 PlannedState | `PlannedState` |
| candidate BSM | `GroundedCandidate`，只由 GROUND 产生 |
| LLM 直接选址 | `Selection Agent` 的受约束排序输出 |

## 3. 参考

- [03_KG_SEMANTIC_BRIDGE.md](03_KG_SEMANTIC_BRIDGE.md)
- [05_EXPLORE_BRIDGE.md](05_EXPLORE_BRIDGE.md)
- [06_PARSE_EXECUTE.md](06_PARSE_EXECUTE.md)
