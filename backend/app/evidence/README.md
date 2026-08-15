# Evidence 证据层

> 本 README 以 `backend/app/evidence/` 实际代码为准（核验日期 2026-08-15）。

## 定位

证据模型与检索：把 KG、Bundle、报告、外部搜索等来源统一成带来源与 provenance 的
evidence，供分析/接地/校验阶段消费。`evidence/` 定义证据**怎么组织、怎么评分、怎么检索**；
具体外部实现（KG/RAG/gazetteer）位于 `infrastructure/`。

## 目录职责

| 目录/文件 | 职责 |
|---|---|
| `model/` | 证据 Pydantic 契约：`place_resolution`（PlaceResolutionStatus）、`l1_location_fact`（L1LocationFact）、`planning`（ScenarioSnapshot）、`relation_evidence`（RelationEvidence/DirectionalRelation）、`external_search`（ExternalSearchEvidence/ExternalClaimDraft）、`media`（ImageEvidence/VisualFact/VisualReview） |
| `index/` | 地点证据索引与评分：`place_evidence_index.PlaceEvidenceIndex`、`evidence_scorer.score_candidate`（拓扑/名称/空间评分）、`resolution_coverage`（ResolutionCoverage） |
| `kg/` | KG-facing 证据模型：`base_facts`（BaseFacts）、`derived_relations`（DerivedRelations） |
| `retrieval/` | 检索服务：`evidence_service.retrieve_evidence`（聚合多来源）、`explore_service.ExploreService`（EXPLORE 横向探索）、`agent.ExploreFlashAgent`（flash LLM 提取规划文本实体）、`verification`（intent↔layout 一致性）、`retrievers/`（`kg_retriever`、`bundle_retriever`、`report_retriever`）、`contracts.py`（ExplorationInstruction） |

## 关键入口

- `retrieval/evidence_service.py::retrieve_evidence`：L1/L2/L3 维度运行时获取证据的统一入口，
  返回 `EvidenceBundle`；`render_evidence_prompt_section` 把证据渲染进 prompt。
- `retrieval/explore_service.py::ExploreService`：EXPLORE 阶段水平检索（bundle/KG/report），
  `outcome_of` 判定探索结果是否可接受。
- `index/place_evidence_index.py`：地点证据索引（名称→候选），被 grounding/解析复用。
- `retrieval/verification.py::compare_intent_to_layout`：意图与 layout configs 的一致性校验。

## 边界规则

- 证据必须带 source/provenance；不能把“检索到”当成“规划决定”。
- `evidence/` 不拥有 KG/RAG 存储，只定义模型与检索编排；存储适配在 `infrastructure/`。
- 空结果/来源冲突必须显式报告，不允许用空证据冒充“没有证据”。