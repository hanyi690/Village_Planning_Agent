# Tools Access — EXPLORE 会话统一读路径

> **定位**：EXPLORE 阶段的**bundle 统一读路径工具集**——semantic-first、bundle-first、token-budgeted。任何 agent 声明相同 scope 即可采用。
> **Updated: 2026-08-19**

---

## 职责边界

**负责**：先从 bundle 快照 / EvidenceGraph 取得空间事实和来源引用，再按引用展开报告/RAG 文本，向 LLM 提供紧凑语义化读取，**绝不给原始坐标转储 / 原始 SPARQL / 全量报告文本**。

**不负责**：
- 不写数据 / 不触发构建（只读路径）
- 不做几何计算 / 规划决策
- 不 import agent 状态作为业务依赖（仅经 `InjectedState` 取会话标识）

---

## 输入/输出契约

**导出**（`access/__init__.py`）：`ACCESS_TOOLS` = `bundle_overview` / `spatial_context` / `spatial_features` / `layer_reports` / `knowledge_graph` / `rag_search`（另有 `index_bundle_texts`）。

| 文件 | 工具 | 说明 |
|---|---|---|
| `bundle.py` | `bundle_overview` / `spatial_context` / `spatial_features` | 会话数据统计 / 标签分布 / 紧凑结构化负载；`include_geometry` 是 EXECUTE / 渲染的显式逃生门 |
| `knowledge.py` | `knowledge_graph` | 会话 KG 语义查询（包装 `kg/queries/semantic.py` + `cognition.py`），token 预算 |
| `rag.py` | `rag_search` / `index_bundle_texts` | 文本清单检索（`documents.document_refs` 为权威范围，正文按 ref 读取，无全库漂移）；全部结果经 `TokenBudget` 标注 |
| `reports.py` | `layer_reports` | bundle `report_refs` progressive disclosure：先 manifest/summary，仅显式 `include_content` 才按 report_id 物化全文 |
| `evidence.py` | `evidence_query` / geometry bridge | EvidenceGraph 候选、L1/KG topology 和 bundle feature ref；几何只按 opaque ref 回到 bundle |
| `shared.py` | 共享助手 | bundle 解析（内存缓存 → 版本化快照 → 实时构建）+ `budget_check` 预算 |

**读路径优先级**（shared.py）：① 内存缓存 session bundle（最快）→ ② 持久化版本化快照（`BundleStore`，确定性/不可变）→ ③ 实时构建（`DataCatalog` 兜底）。

---

## 依赖方向

```
access/ → app/application/sessions（session_bundle / BundleStore）、app/infrastructure/kg.queries、app/infrastructure/rag、app/contracts、app.utils
   ▲ 被 ToolRegistry.for_agent("explore") 绑定
```

- 允许：`app/application`（读）、`app/infrastructure/*`（读）、`app/contracts`、`app.utils`、LangChain
- 禁止：写路径 / 几何计算 / 算法实现

---

## 禁止行为

- 默认返回原始坐标 / 全量报告 / 原始 RDF（破坏 semantic-first 与 token 预算约定）
- 绕过 snapshot-first 读路径直接触发实时构建（性能与确定性退化）
- 让工具拥有会话状态（只读适配器）
- 未经 `budget_check` 返回超长负载
