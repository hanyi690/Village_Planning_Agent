# agent/explore/retrievers 子包（确定性证据检索器）

> EXPLORE 证据服务的**确定性检索器集合**：从报告 / KG / VillageBundle 抽取 `EvidenceFact` 与 `EvidenceSource`。
> 父目录 `agent/explore/README.md` 已存在（勿覆盖）；本 README 只描述 `retrievers/` 子目录。

---

## 职责边界

**做**：为维度分析与 GROUND 提供**确定性证据注入**（无 LLM）：`report_retriever.retrieve_from_reports`（按空间关键词 + 数字过滤 L1/L2/L3 报告句子级空间发现）；`kg_retriever.retrieve_from_kg`（session KG 三层认知 `get_village_cognition` + L2/L3 拓扑事实，如现状道路/水系，返回 `SpatialCognitionEvidence`）；`bundle_retriever.retrieve_from_bundle`（`VillageBundle` 空间分组统计，按 `entity_scope` 映射到分组）。

**不做**：不调用 LLM（确定性）；不写 KG / 不改 bundle；不产出任何空间几何或决策（只产证据）。

### 目录文件

| 文件 | 检索器 | 数据源 |
|---|---|---|
| `report_retriever.py` | `retrieve_from_reports` | `ReportStore` L1/L2/L3 报告 |
| `kg_retriever.py` | `retrieve_from_kg` | session KG（cognition / sparql） |
| `bundle_retriever.py` | `retrieve_from_bundle` | `VillageBundle` 快照 |

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 证据 | `app/modules/schema/contracts/evidence_contracts.py` | `EvidenceFact`、`EvidenceSource`、`SpatialCognitionEvidence` |
| 访问辅助 | `app/tools/access/shared.py` | `session_kg` / `resolve_bundle` / `group_stats` |
| 报告 | `app/services/report_store.py` | `ReportStore` |
| KG 查询 | `app/modules/kg/queries/cognition.py` / `sparql.py` | `get_village_cognition` / `query_kg` |

统一返回约定：报告/束检索器返回 `(list[EvidenceFact], list[EvidenceSource])`；KG 检索器返回 `(list[EvidenceFact], SpatialCognitionEvidence)`；失败一律返回空（不抛异常）。

## 依赖方向

**可导入**：`app/services/report_store`、`app/tools/access/shared`、`app/modules/kg/queries/*`、`app/modules/schema/contracts/evidence_contracts`。

**禁止导入**：`app/agent/explore/agent.py`（桥接 agent，`ExploreFlashAgent` 是 LLM 侧，与确定性检索器分离）、各 stage worker 实现；不得反向依赖 `retrievers` 的上层调用方。

## 禁止行为

- 不得在检索器内调用 LLM（确定性基线，LLM 桥接在 `agent/explore/agent.py`）。
- 不得抛异常打断调用链（基础设施缺失必须返回空并记日志）。
- 不得跨 session 回退查询 KG（`session_kg` 只查当前 session，见 `explore/agent.py` 的 `require_session_kg` 约束）。
- 不得在 `kg_retriever` 里虚构 BSM / 实体（只读 KG 实际结果）。

---

## 相关文档

- `../README.md` — EXPLORE 能力引擎（父目录，勿覆盖）
- `app/tools/access/shared.py` — `session_kg` / `resolve_bundle` / `group_stats`
- `app/modules/kg/queries/cognition.py` — 村域认知查询
- `app/modules/schema/contracts/evidence_contracts.py` — 证据契约
