# PlanningTextGenerator 弃用说明（Wave O）

> **状态：DEPRECATED（Wave O）** · 本模块保留仅为兼容既有 API 路由，新功能禁止扩展此路径。

## 弃用状态

`backend/app/modules/planning_text/` 下的 `PlanningTextGenerator`（含 `SectionBuilder`、`LLMStyler`）在 **Wave O** 被标记为 **DEPRECATED**。运行时在 `PlanningTextGenerator.__init__` 触发 `DeprecationWarning`。

## 弃用原因

- 仅从 `ReportStore` 读原始报告文本（L1/L2/L3 markdown），直接拼接生成 22 条法定条文；
- 不消费 typed artifacts（L1Snapshot / L2Strategy / PlanningProgram / DeliveryManifest）；
- 不消费 bundle 表格（typed table 数据）；
- 不接 post-L3 链输出（DeliveryManifest）；
- 与 typed artifact 目标架构冲突：每个阶段应只生产一种权威产物，后续阶段通过类型化契约消费，而非回到文本级组装。

## 替代方案

最终规划输出改用：

1. **`build_stage_report_markdown(session_id)`**（`app/services/stage_report.py:51`）——全链每模块输入/输出/诊断审计 markdown；
2. **`FilesystemArtifactStore`**（`app/services/artifact_store.py:53`）下持久化的 typed artifacts：
   - `L1Snapshot`
   - `L2Strategy`
   - `PlanningProgram`
   - `IntentCompilationResult`
   - `GroundingResult`
   - `SiteSelectionDecision`
   - `ParcelChangeSet`
   - `PlannedState`
   - `ValidationReport`
   - `ReconciliationReport`
   - `DeliveryManifest`

## P0/P1 研究摘要

以下 9 个问题的解决方案概要，作为后续重构方向参考：

1. **图路由 / Gate 错位**：Gate（证据/一致性/程序）判定失败时应沿产生原因返回对应上游节点，避免回退到巨大的总路由器；路由决策与 Gate 判定解耦，保证失败语义可追踪。
2. **L1Snapshot-L2Strategy 权威输入**：明确 L2 以 L1Snapshot 为权威输入，L2Strategy 作为 L3 的权威输入，阶段间通过类型化契约传递，禁止跨层读取原始报告文本。
3. **干预-地块可追溯 ID**：每个干预（intervention）与其作用的地块（parcel）建立可追溯 ID 关联，支持从规划意图反查地块、从地块反查来源干预。
4. **地块足迹**：地块的空间足迹（footprint）以类型化几何数据持久化，避免在规划输出阶段从文本重新解析。
5. **后置分区**：分区决策后置到有完整空间上下文（L3 后）的阶段，避免早期文本阶段的模糊分区成为后续硬约束。
6. **设施 MCLP**：公共服务设施配置采用最大覆盖选址模型（MCLP）求解，设施选址与覆盖范围基于 typed 数据而非文本描述。
7. **评分扩展**：评分/打分体系设计为可扩展结构，支持按维度增减指标，避免硬编码评分逻辑限制后续维度扩展。
8. **证据重试**：Gate 因缺证据失败时，触发证据探索（EXPLORE）并带重试语义，证据回填后重新评估 Gate，而非直接丢弃阶段产物。
9. **验证强化**：ValidationReport 作为验证权威产物，校验规则与阶段解耦，支持增量/可组合验证，并在 ReconciliationReport 中登记不一致项。

## 保留原因

为兼容既有 `POST /api/sessions/{id}/planning-text` API 路由（`app/api/session_routes.py`），`PlanningTextGenerator` 暂不删除，仅做弃用标注。新功能一律走 stage_report + typed artifacts 路径。
