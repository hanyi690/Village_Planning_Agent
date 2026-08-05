# agent/common 子包（共享维度运行时）

> 从 `l1_observe/analysis_node.analyze_dimension` 抽取的共享运行时基础设施，供 L1/L2/L3 三个维度 worker 复用（Wave D/E）。
> 单一文件：`dimension_runtime.py`。

---

## 职责边界

**做**：为维度分析提供**纯包装**辅助（I/O 委托给 `RagService` / `PlanningRuntimeService` / `sse_manager` / `ReportStore` / `step_report` / 摘要生成器，均非致命容错）：`run_rag`（RAG 检索，返回 `(context_str, RAGRetrievalLog|None)`）、`load_dependency_reports` / `load_layered_dependency_reports`（依赖报告加载）、`generate_summary`（结构化摘要）、`publish_dimension_start/delta/complete`（SSE）、`save_report_immediate` / `save_step_report`（落库）。导出 `RetrievedChunk` / `RAGRetrievalLog` / `DependencyError`。

**不做**：不包含任何 LLM 提示词 / 维度特定逻辑 / 报告内容解析（那在各 stage 的 worker 与 `modules/prompts`）；不实现 LangGraph 节点。

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 检索日志 | `app/agent/common/dimension_runtime.py` | `RetrievedChunk`、`RAGRetrievalLog`（dataclass） |
| 异常 | 同上 | `DependencyError` |
| 证据契约 | `app/modules/schema/contracts/evidence_contracts.py` | `ExplorationRequest`（由调用方构造，传给 `retrieve_evidence`） |

**消费方**：`app/agent/l1_observe/analysis_node.py`、`app/agent/l2_strategize/worker.py`、`app/agent/l3_plan/worker.py`（均 import `app.agent.common.dimension_runtime` 的辅助函数）。

## 依赖方向

**可导入**：`app/services/runtime`（`PlanningRuntimeService`）、`app/services/report_store`、`app/services/step_report`、`app/core/events`（`SSEEventType`）、`app/config`（`get_dimension_layer`）、`app/utils/logger`。

**禁止导入**：`app/agent/l1_observe` / `l2_strategize` / `l3_plan`（公共运行时不得反向依赖具体 stage）；任何维度提示词 / LLM 构造逻辑。

## 禁止行为

- 不得在 `dimension_runtime` 内调用 LLM 或构造维度 Prompt（那是 worker 的职责）。
- 不得把运行时辅助做成"会抛错中断分析"（必须与原始 L1 一致保持非致命容错）。
- 不得在此引入 stage 特定常量（维度列表 / 层名在 `bootstrap/phase_machine.py` 与 `modules/schema/layers`）。

---

## 相关文档

- `../l1_observe/README.md` / `../l2_strategize/README.md` / `../l3_plan/README.md` — 三个消费方
- `app/services/runtime.py` — `PlanningRuntimeService`
- `app/services/report_store.py` — 报告落库
