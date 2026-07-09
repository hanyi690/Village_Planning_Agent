# Agent / Review / Layer Pause / GIS 修复说明

本版本在 fixed-chat 基础上继续修复：

1. 右侧消息栏不再把普通聊天注入 LangGraph 主流程，避免“问一句话就推进规划”。
2. 增加 `pending_chat_action`：用户提出修订意见时，后端识别维度并生成 `draft_feedback`；前端自动填入审查修订栏，用户仍需点击“提交修订”才真正重跑。
3. 默认开启 `step_mode=True`，并关闭跨 Layer 提前调度，避免 L1 审查时 L2/L3 已经继续生成。
4. Layer 完成后发送 `layer_paused`，前端显示审批面板；批准后才进入下一层。
5. GIS 改为独立接口 `POST /api/sessions/{session_id}/gis/generate`，前端“确认生成”按钮调用该接口，不再复用聊天接口。
6. GIS Agent 使用统一 `create_llm()`，避免 DeepSeek/Qwen/OpenAI-compatible 配置不生效；修复报告摘要异步读取问题，并给 GIS ReAct Agent 明确任务消息。
7. 修复 `gis_layer_update` 第一次图层到达时不会自动切换地图的问题。

注意：我在当前环境做了静态修改和 Python 编译检查，但没有你的 API Key 和完整前端依赖，无法保证真实报告和 GIS 一次性完全成功。若 GIS 仍失败，优先查看后端日志中 `[gis_agent]`、`GIS Agent`、`layout_configs` 相关错误。
