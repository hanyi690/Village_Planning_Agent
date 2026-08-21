# Evidence 证据层

> 本 README 以 `backend/app/evidence/` 实际代码为准（核验日期 2026-08-20）。

## 定位

证据模型与检索：把 KG、Bundle、报告、外部搜索等来源统一成带来源与 provenance 的
evidence，供分析/接地/校验阶段消费。`evidence/` 定义证据**怎么组织、怎么评分、怎么检索**；
具体外部实现（KG/RAG/gazetteer）位于 `infrastructure/`。

## 目录职责

| 目录/文件 | 职责 |
|---|---|
| `model/` | 证据 Pydantic 契约：`place_resolution`（PlaceResolutionStatus）、`l1_location_fact`（L1LocationFact）、`planning`（ScenarioSnapshot）、`relation_evidence`（RelationEvidence/DirectionalRelation）、`external_search`（ExternalSearchEvidence/ExternalClaimDraft）、`media`（ImageEvidence/VisualFact/VisualReview） |
| `index/` | 地点证据索引与评分：`place_evidence_index.PlaceEvidenceIndex` 仅是 EvidenceGraph 的私有候选生成实现；对外统一由 `retrieval/evidence_graph.py` 输出 typed result/packet。 |
| `kg/` | KG-facing 证据模型：`base_facts`（BaseFacts）、`derived_relations`（DerivedRelations） |
| `retrieval/` | 统一检索服务：`evidence_service.retrieve_evidence`（聚合多来源并编排可选外源检索）、`evidence_graph.EvidenceGraph`（空间候选与拓扑）、`verification`（intent↔layout 一致性）、`retrievers/`（`local_text_retriever`、`kg_retriever`、`bundle_retriever`、`report_retriever`、专业 `rag_retriever`） |

## 关键入口

- `retrieval/evidence_service.py::retrieve_evidence`：L1/L2/L3 维度运行时获取证据的统一入口，
  返回 `EvidenceBundle`；`render_evidence_prompt_section` 把证据渲染进 prompt。
- `retrieval/evidence_service.py::retrieve_evidence`：唯一的多源检索与外源策略入口；
  不再保留独立 EXPLORE 编排器，避免出现两套候选、状态和外源策略。
- `index/place_evidence_index.py`：地点证据索引（名称→候选），只由 EvidenceGraph 内部持有；GROUND、SELECT、LLM 不直接访问它。
- `retrieval/evidence_graph.py::EvidenceGraph`：对外唯一空间检索边界；除名称/范围候选外，
  `query_parcel_bsms_in_bbox` 也只返回 bundle parcel BSM 引用，调用方不得通过私有 index 取几何。
- 索引只保存语义标签、BSM 和 `bundle://feature/<BSM>` 不透明引用；不缓存点、线、面 WKT。只有 GROUND 的 bundle bridge 可以按引用回读权威几何。
- 同名对象的合并优先使用 `feature_bsm` / `source_bsm` / `source_feature_id` 身份；不同 source identity 即使 geometry ref 都是 opaque 也必须保留为独立候选，不能因名称相同而合并。
- 命名道路/水体在索引构建时可把自身 geometry 与 bundle 地块做一次 STRtree 拓扑连接，条目只保留 `related_parcel_bsms`；查询“甲村的道路/水体”时先用村庄 gazetteer BSM 集过滤，再用 KG 的 feature→village 关系补充验证。若没有任何范围证据则保留有界候选并标记范围未验证，不伪造定位。
- KG 中的 `AdministrativeBoundary`、`ContourLine` 虽然同样是带 BSM 的线状空间实体，但不属于 `Road`；道路检索按交通 source layer 和本体类型隔离，避免行政界线/等高线污染道路候选。
- 统一入口还消费方向型范围提示：`村西/村北/东侧/东北部` 会以 gazetteer 或 KG village anchor 为中心生成粗粒度 bbox，并通过 bundle parcel BSM 相交集合参与候选过滤；`东西向/南北向` 等线状走向不会误当作区域方向。L1 的 `spatial_hint`、`related_mentions`、`source_span` 会和用户查询一起作为 KG topology hints。
- `retrieval/verification.py::compare_intent_to_layout`：意图与 layout configs 的一致性校验。

## 边界规则

- 证据必须带 source/provenance；不能把“检索到”当成“规划决定”。
- `evidence/` 不拥有 KG/RAG 存储，只定义模型与检索编排；存储适配在 `infrastructure/`。
- 空结果/来源冲突必须显式报告，不允许用空证据冒充“没有证据”。
- L1/L2/L3 报告正文属于 `planning_background`，只辅助规划语义判断，不能凭报告中的词语、数字或叙述直接生成空间位置；空间定位必须使用 typed L1 spatial fact 与 bundle/KG EvidenceGraph。
- 发送给规划 LLM 的空间事实只携带 `bundle://feature/<BSM>` 等不透明引用，不携带 WKT/坐标；只有 bundle geometry bridge 可以按已返回的 ref 读取权威几何。
