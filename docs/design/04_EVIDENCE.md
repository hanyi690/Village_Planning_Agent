# 04 Evidence：检索、融合与推理

## 1. 业务问题

Evidence 回答“结论依据是什么、是否足够、缺口能否现在解决”。它服务所有阶段，不是主链中的串行步骤。

## 2. 子图

```text
EvidenceRequirement → query plan
→ report/Bundle/KG/GIS/RAG/external retrieval
→ normalize/provenance → coverage/sufficiency
→ gap classification
→ resolvable: follow-up retrieval/inference
→ not resolvable: unresolved requirement
```

## 3. 输出

`EvidencePacket` 包含 requirements、items、source_refs、provenance、coverage、sufficiency、unresolved_requirements 和 diagnostics。

Evidence 可以输出给 L1 的 `FactCandidateEvidence`、给 GROUND 的 `SpatialBindingEvidence`、给 SELECT 的 `CandidateEvidenceSummary`，但不直接生成规划目标、scenario 或执行计划。

## 4. 统一入口和上下文

上层只能调用 `EvidenceFacade`，不得直接调用 retriever、RAG、KG 或 external provider 内部函数。所有检索结果先归一化，再由业务阶段决定是否形成 fact 或 binding。

## 5. 验收

真实查询必须返回带 provenance 的 EvidencePacket；覆盖率和充分性可计算；provider 不可用时有 degraded 状态；L1/L2/L3/GROUND/SELECT 都能使用同一入口。

