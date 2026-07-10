# 修复说明：修订卡住 + Layer 2 修订按钮消失

本版本在上一版基础上继续修复：

1. 修订卡住问题
   - 后端 `submit_feedback` 在没有明确维度时返回 `need_dimension`，不会假装启动修订。
   - 如果前端未传 `dimensions`，后端会尝试从修订意见中推断维度。
   - 后台 `resume_from_interrupt` / GIS 任务统一通过 `_schedule_background_task` 执行，异常会推送 SSE `error`，避免界面无限卡住。
   - 修复 `final_tree` 字典推导变量错误。

2. 前端修订状态
   - `ReportViewer` 会检查后端返回状态：只有 `revision_started` 才进入 `revising`。
   - 返回 `need_dimension` 时会保持暂停状态，并自动展开维度选择器。

3. Layer 2/3 审查面板消失
   - 新增 `reviewLayerForPanel` 兜底逻辑：即使 `pendingReviewLayer` 丢失，只要状态是 `paused` 且已有报告，也会显示审查/提交修订区域。

4. 大模型参数
   - `.env` / `.env.example` 中 `MAX_TOKENS` 改为 4096，避免修订生成过慢或长期无响应。

注意：压缩包内 `.env` 含本地 API 配置，请不要上传 GitHub。

5. SSE 错误可见化
   - 前端 store 新增通用 `error` SSE 处理。后端后台任务失败时，会在消息栏显示错误，并从 `revising` 状态恢复到可操作状态，避免一直卡住。

6. `setStatus("paused")` 现在会重新派生 `isPaused` / `pendingReviewLayer`，保证前端手动恢复暂停状态时审查面板能出现。
