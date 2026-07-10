# Approve Continue Fix

本版本专门修复：点击“批准并进入下一阶段”后没有反应。

## 修复内容

1. 后端 `submit_feedback(approve=True)` 不再只依赖 LangGraph interrupt resume。
   - 如果当前 checkpoint 正好在 interrupt，会走官方 `resume_from_interrupt`。
   - 如果前端是通过兜底逻辑显示的审查栏，而后端不在 interrupt 状态，会直接判断当前 Layer 是否完成。
   - 如果当前 Layer 已完成，会显式推进到下一 Layer，并注入 `advance_planning_intent`，触发下一层维度生成。

2. 前端批准按钮提交成功后会：
   - 清空 pending review layer；
   - 退出暂停状态；
   - 主动触发 SSE 重连/同步，避免漏掉 `layer_start` 和后续维度事件。

3. 如果批准失败，右侧消息栏会显示错误信息，不再只在控制台报错。

## 覆盖说明

该压缩包不包含 `.env` 和 `frontend/.env.local`，不会覆盖你的本地 API Key。

覆盖后请重启后端和前端。
