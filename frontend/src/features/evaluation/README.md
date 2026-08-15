# evaluation feature（质量评估）

> 本 README 以 `frontend/src/features/evaluation/` 实际代码为准（核验日期 2026-08-15）。

## 定位

质量评估：对会话的维度报告做忠实度/引用/深度评分，展示评估结果与诊断。旧独立路由
`src/app/evaluation/page.tsx` 现在重定向到主工作台概览面板（`/?view=overview&panel=evaluation`）。

## 文件职责

| 文件 | 职责 |
|---|---|
| `api.ts` | 评估 API：`run` → `POST /api/evaluation/sessions/{id}/run`、`getResults` → `GET /api/evaluation/sessions/{id}/results`、`getStatus` → `GET /api/evaluation/sessions/{id}/status`、`getCascade` → `/cascade`、`exportMarkdown` → `/export/markdown`；类型 `DimensionEvaluation`/`EvaluationDiagnostics`/`CitationDetail` 等 |
| `components/QualityEvaluationPanel.tsx` | 评估结果面板（约 25KB：评分表、引用明细、诊断） |
| `hooks/useQualityEvaluation.ts` | 评估状态 hook |
| `utils/score.ts` | 评分计算工具 |

## 边界

- 评分逻辑以后端返回为准，前端只做展示与格式化。
- 该 feature 属于评估类辅助视图；正式规划主链在 `planning/`。