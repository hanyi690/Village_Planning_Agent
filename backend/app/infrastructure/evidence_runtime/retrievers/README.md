# evidence/retrieval/retrievers 子包（确定性证据检索器）

> 本 README 以 `backend/app/infrastructure/evidence_runtime/retrieval/retrievers/` 实际代码为准（核验日期 2026-08-15）。
> EXPLORE 证据服务的**确定性检索器集合**：从报告 / KG / VillageBundle 抽取证据。

## 职责边界

**做**：为维度分析与 GROUND 提供**确定性证据注入**（无 LLM）：

- `report_retriever.retrieve_from_reports`：检索 L1/L2/L3 报告中的空间发现和规划语义句段；
- `local_text_retriever.retrieve_from_local_text`：检索会话 bundle 输入文档、L1 source span；
  报告正文由 bundle manifest 驱动的 `report_retriever` 按需打开；不依赖向量服务，也不返回几何；
- `kg_retriever.retrieve_from_kg`：session KG 认知与 L2/L3 拓扑事实（`get_village_cognition`），返回 `SpatialCognitionEvidence`；
- `bundle_retriever.retrieve_from_bundle`：`VillageBundle` 空间分组统计；指定 `entity_scope` 时按
  分组读取，未指定时在 points/lines/polygons 全部集合上做有界标签命中，返回 BSM/ref 而不返回几何。
- `rag_retriever.retrieve_from_rag`：仅检索专业外部向量语料；向量服务不可用时返回空事实和 typed unavailable 日志，绝不代替本地来源。

**不做**：不调用 LLM（确定性）；不写 KG / 不改 bundle；不产出任何空间几何或决策（只产证据）。

## 目录文件

| 文件 | 检索器 | 数据源 |
|---|---|---|
| `report_retriever.py` | `retrieve_from_reports` | bundle `documents.report_refs` 选引用，再从 `ReportStore` 批量打开正文 |
| `kg_retriever.py` | `retrieve_from_kg` | session KG（`app/infrastructure/kg/queries/`） |
| `bundle_retriever.py` | `retrieve_from_bundle` | `VillageBundle` 快照（`app/data/model/`） |
| `local_text_retriever.py` | `retrieve_from_local_text` | 当前 session 的 bundle 输入文本、L1 source span |
| `rag_retriever.py` | `retrieve_from_rag` | 专业外部向量库（可用性受 provider/embedding 服务影响） |

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 证据 | `app/contracts/evidence/evidence_contracts.py` | `EvidenceFact`、`EvidenceSource`、`SpatialCognitionEvidence` |
| 访问辅助 | `app/infrastructure/llm/tools/access/shared.py` | `session_kg` / `resolve_bundle` / `group_stats` |
| 报告 | `app/infrastructure/reports/report_store.py` | `ReportStore` |
| KG 查询 | `app/infrastructure/kg/queries/cognition.py` / `sparql.py` | `get_village_cognition` / `query_kg` |

统一返回约定：报告/束检索器返回 `(list[EvidenceFact], list[EvidenceSource])`；KG 检索器返回
`(list[EvidenceFact], SpatialCognitionEvidence)`；失败一律返回空（不抛异常）。

## 依赖方向

**可导入**：`app/infrastructure/reports`、`app/infrastructure/llm/tools/access`、
`app/infrastructure/kg/queries/*`、`app/contracts/evidence/evidence_contracts`。

**禁止导入**：各 stage worker 实现；不得反向依赖 `retrievers` 的上层调用方。

## 禁止行为

- 不得在检索器内调用 LLM；来源语义判定由统一检索入口显式编排，并在 provider 不可用时返回明确状态。
- 不得抛异常打断调用链（基础设施缺失必须返回空并记日志）。
- 不得跨 session 回退查询 KG（`session_kg` 只查当前 session）。
- 不得在 `kg_retriever` 里虚构 BSM / 实体（只读 KG 实际结果）。
