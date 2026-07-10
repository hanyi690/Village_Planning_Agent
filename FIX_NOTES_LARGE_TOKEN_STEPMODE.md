# Large Token + Step Mode Fix Notes

本版在上一版 all-issues-fixed 基础上继续修复：

1. 不再把 MAX_TOKENS 改小。
   - `.env` 和 `.env.example` 已恢复为 `MAX_TOKENS=65536`。
   - `backend/app/core/settings.py` 默认值也改为 65536。

2. 缓解“文字生成到一半像被截断”的问题。
   - `LLM_REQUEST_TIMEOUT=900`
   - `LLM_STREAM_TIMEOUT=1200`
   - `dimension_complete` SSE 事件现在会额外发送 `full_content`，前端完成时会用最终全文覆盖流式累积内容，避免最后几个流式片段丢失导致文本不完整。

3. 步骤模式默认开启，并保留设置面板开关。
   - `.env` / `.env.example` 新增 `DEFAULT_STEP_MODE=true`。
   - 后端 `SessionCreateRequest`、multipart 创建接口和 `PlanningRuntimeService` 默认 `step_mode=True`。
   - 当前层完成后会暂停，等待用户点击“批准并进入下一阶段”。如果用户在设置面板关闭步骤模式，则后端会自动继续下一层。

4. 仍保留上一版修复：
   - 提交修订时没有维度会返回 `need_dimension`，不会假卡住。
   - 后台修订任务异常会通过 SSE error 显示。
   - Layer 2/3 暂停后修订栏按钮消失的问题已有前端兜底。
   - GIS 生成使用独立接口。

注意：本包包含本地 `.env` 配置，请不要上传到 GitHub。
