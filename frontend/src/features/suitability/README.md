# suitability feature（适宜性评估）

> 本 README 以 `frontend/src/features/suitability/` 实际代码为准（核验日期 2026-08-15）。

## 定位

适宜性评估：展示分区尺度的生态/农业/建设适宜性汇总（`SuitabilityResult`），作为工作台
评估类视图之一。

## 文件职责

| 文件 | 职责 |
|---|---|
| `api.ts` | 适宜性 API：`run` → `POST /api/suitability/sessions/{id}/run`、`getResults` → `GET /api/suitability/sessions/{id}/results`、`getStatus` → `GET /api/suitability/sessions/{id}/status`；类型 `SuitabilityZoneSummary`/`SuitabilityResult` |
| `components/SuitabilityPanel.tsx` | 适宜性结果面板 UI |

## 边界

- 适宜性计算由后端完成，前端只展示汇总与样本地块。
- 属于评估类辅助视图，非规划主链。