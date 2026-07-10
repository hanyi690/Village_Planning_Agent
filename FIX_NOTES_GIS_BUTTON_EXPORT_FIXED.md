# GIS Button and Planning Text Export Fix

本版本针对两个回归问题做修复：

1. 空间布局生成按钮消失
   - 之前按钮条件为 `completedLayers[3] && !hasGisLayers && !isPaused`，在步骤模式暂停审查时会被隐藏。
   - 现在改为只要 Layer 3 已完成或根据报告数量推断已完成，就显示 GIS 生成入口。
   - 即使系统处于 Layer 3 审查暂停状态，也可以点击“确认生成”生成空间布局。

2. 规划文本导出失败
   - 原导出依赖 `scripts/md_to_docx.py`，但该文件在当前包中不存在，会导致导出 500。
   - 现在导出逻辑会优先尝试 `md_to_docx`，失败后自动使用 `python-docx` 兜底生成 DOCX。
   - 同时支持 GET/POST 两种 export 请求，减少前端和浏览器调用不一致导致的失败。

其他修复：
- GIS 结果事件在写入图层前判断是否为首次 GIS 数据，确保地图面板能自动切换到“地图”。
- 不包含 `.env` 和 `frontend/.env.local`，不会覆盖本地 API Key。
