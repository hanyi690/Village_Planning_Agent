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

## 6. 集中实现边界

检索不是由 L1、L2、L3、GROUND 或 SELECT 各自实现，而是由统一 Evidence runtime 集中实现：

```text
业务阶段声明 EvidenceRequirement
        ↓
EvidenceFacade
        ↓
QueryPlanner / RetrieverRouter
        ↓
Bundle / KG / Report / GIS / RAG / External adapters
        ↓
Normalizer / Provenance / Coverage / Sufficiency
        ↓
EvidencePacket
```

阶段只能决定：需要什么证据、允许哪些 scope、证据用于什么判断、缺口是否阻塞当前阶段。普通 evidence gap 应以 partial/unresolved/deferred 继续向后传递；只有缺失会破坏当前 artifact 不变量的硬输入才阻塞阶段。阶段不能决定 retriever 如何实现，也不能直接调用某个 provider。

目标集中实现位置为 `backend/app/infrastructure/evidence_runtime/`；`modules/evidence/` 只保留证据领域契约、需求语义和 facade，不复制检索实现。

## Evidence 目标目录与迁移出口

```text
backend/app/modules/evidence/
├── application.py
├── requirements.py
├── ports.py
├── projections.py
├── coverage.py
└── sufficiency.py
```

`backend/app/infrastructure/evidence_runtime/` 下集中放置 `facade.py`、
`query_planner.py`、`retriever_router.py`、各 provider retriever、`fusion.py`、
`provenance.py`、`coverage.py` 和 `sufficiency.py`。它是唯一的检索执行平台；
RAG、KG、search 只作为该 runtime 的基础设施适配器，不能被业务阶段直接调用。
迁移出口是：所有业务阶段通过统一 Evidence facade，且当前阶段可解决的 gap
会触发后续检索或推理。

当前输入检索执行还必须满足一个边界：`dimension_key` 和
`entity_scope` 是业务 owner / 检索提示，不是原始资料的硬分区。Evidence Runtime
在冷启动时从当前 session 装载 canonical `PlanningContext`，通过有界的
grep-like 文本候选检索访问完整当前输入；`gap_resolution` 可以跨维度查找匹配
的原文和 L1 typed fact。词法检索只返回带 locator 的 `needs_review` source span，
不使用正则抽取数值、不填造缺失字段；业务模块再用受限 LLM 从这些原文中抽取小批量
结构化项，并对 provenance 做逐项校验。

只有 `spatial_lookup` 或显式 typed spatial requirement 才会选择 KG/Bundle 的
空间执行器和 geometry sufficiency。单独携带 `facilities`、`roads` 等 scope 不会
把人口、产业或政策缺口错误升级为空间缺口。
