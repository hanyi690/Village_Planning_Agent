# compliance feature（合规/土地平衡）

> 本 README 以 `frontend/src/features/compliance/` 实际代码为准（核验日期 2026-08-15）。

## 定位

合规面板：展示会话的土地平衡与合规检查结果（`LandBalanceTable`：各地类现状/规划面积、
变化、闭合度、三区汇总）。是工作台的数据中心/合规视图的一部分，不作为独立页面。

## 文件职责

| 文件 | 职责 |
|---|---|
| `api.ts` | 合规 API：`run(sessionId)` → `POST /api/compliance/sessions/{id}/run`、`getResults` → `GET /api/compliance/sessions/{id}/results`、`getStatus` → `GET /api/compliance/sessions/{id}/status`；类型 `LandBalanceRow`/`LandBalanceTable`/`ComplianceResult` |
| `components/CompliancePanel.tsx` | 合规结果面板 UI |
| `components/LayerCompletenessCard.tsx` | 图层完整性卡片 |

## 边界

- 合规结果来自后端评估，前端只渲染；不在此计算土地平衡。
- 该 feature 与 `evaluation`/`suitability` 类似，属于评估类辅助视图，非规划主链。