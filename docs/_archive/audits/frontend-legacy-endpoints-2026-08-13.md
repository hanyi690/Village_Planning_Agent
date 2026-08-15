# 前端遗留端点退役清单（2026-08-13）

> 背景：后端已完成 v1 蓝图收敛，仅暴露 9 条 `/api/v1` 稳定路由。以下遗留端点已从后端删除，
> 前端于 2026-08-13 全部停止调用（运行时不再发起网络请求）。
> 本清单是"待后端 v1/v2 迁移后恢复"的显式登记，恢复前禁止重新启用这些调用。

图例：已停止（stub 抛错） / 本地化（仅本地生效） / UI 禁用

## 一、planningApi 遗留方法（stub 抛错，保留签名仅类型兼容）

| 方法 | 原端点 | 主要消费方 | 处理 | 恢复条件（后端 v1/v2 提供后） |
|---|---|---|---|---|
| submitFeedback | POST /api/sessions/{id}/feedback | ReportViewer(handleRejectWithFeedback) | 已停止（抛错显示"已下线"）；人工审核已走 POST /api/v1/sessions/{id}/human-review | v1 反馈/修订命令 |
| sendChatMessage | POST /api/sessions/{id}/feedback | planning-context(sendChatMessage) | 本地回显"对话功能暂不可用" | v1 对话端点 |
| getLayerReports | GET /api/sessions/{id}/layer/{layer}/reports | useHandlers(fetchLayerReportsFromBackend) | 改为读 store（SSE dimension_complete 累积/事件重放） | 无需恢复 |
| getDimensionReport | GET /api/sessions/{id}/reports/{dim_key} | 无直接消费方 | 已停止 | v1 报告资源 |
| deleteSession | DELETE /api/sessions/{id} | planning-context(deleteSession/clearAllHistory) | 本地删除（markSessionsDeleted + 移除本地历史） | v1 会话删除 |
| getCheckpoints | GET /api/sessions/{id}/checkpoints | session-hydrate（已移除调用） | 已停止；恢复改走事件重放 | v1 检查点资源 |
| exportLayerFormat/Docx/Json/Md | POST /api/sessions/{id}/export | ExportDialog | 已停止；ExportDialog 显示"导出暂不可用"横幅 | /delivery.downloads 下载端点 |
| exportPlanningTextDocx | POST /api/sessions/{id}/export?planning_text=true | ExportDialog、PlanningTextViewer | 已停止 | v1 导出/下载 |
| getPlanningText / getPlanningTextVersions / generatePlanningText | /api/sessions/{id}/planning-text* | PlanningTextViewer | 已停止（组件显示错误） | v1 规划文本资源 |
| updateRagConfig | PATCH /api/sessions/{id}/rag-config | SettingsPanel（未渲染，死代码） | 已停止 | v1 配置资源 |
| updateStepMode | PATCH /api/sessions/{id}/step-mode | SettingsPanel、Workbench | 已停止 | v1 配置资源 |
| geocodeVillage | GET /api/sessions/{id}/geocode | planning-context(startPlanning) | 已移除调用 | v1 地理编码 |
| uploadGisData | POST /api/sessions/{id}/gis-data | 无直接消费方 | 已停止 | v1 GIS 上传 |

## 二、dataApi 遗留方法（stub 抛错）

| 方法 | 原端点 | 主要消费方 | 处理 | 恢复条件 |
|---|---|---|---|---|
| listVillages | GET /api/projects | planning-context(loadVillagesHistory) | 本地历史替代（不再拉远程） | v1 项目列表 |
| getVillageSessions | GET /api/projects/{name}/sessions | planning-context、evaluation/api | 本地历史替代 | v1 项目会话 |
| getCrossSessionReport | GET /api/projects/{name}/reports/{dim_key} | ReportViewer(compare 模式) | compare 降级为空 | v1 跨会话报告 |
| getDimensionVersions | GET /api/sessions/{id}/reports/{dim_key}/versions | ReportViewer(compare 模式) | compare 降级为空 | v1 版本历史 |

## 三、其他前端遗留调用

| 位置 | 原端点 | 处理 |
|---|---|---|
| evaluation/api.ts（listProjects/listSessions/run/getResults/getStatus/runCascade/exportMarkdown） | /api/projects、/api/evaluation/* | QA 页遗留；后端未提供，待迁移或下线页面 |
| useMessagePersistence | 曾 POST 消息到后端 | 已无网络调用（仅本地去重） |

## 四、恢复流程约束

1. 恢复某个功能前，必须先确认对应 `/api/v1`（或 v2）端点已在 `docs/contracts/openapi-v1.json` 登记，
   前端类型从 openapi 重新生成。
2. 禁止以"重新调用已删端点"的方式恢复功能；缺失能力一律显示明确"暂不可用"状态。
3. 每个恢复项更新本清单状态与 `docs/architecture/frontend-v1-alignment.md`。