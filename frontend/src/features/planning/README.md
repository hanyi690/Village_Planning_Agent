# planning feature

规划 feature 是前端的主业务边界：把会话 API/SSE 转换为工作台可消费的 UI 状态，并呈现文本规划、GIS 图层、报告、检查点和 HITL 审核。

## 目录职责

| 目录 | 职责 |
|---|---|
| `api/` | HTTP 请求、上传、报告和人工审核 API |
| `hooks/` | SSE、会话恢复、流式操作和持久化副作用 |
| `store/` | Zustand + Immer 状态与事件 reducer |
| `types/` | 消息、事件、报告和状态类型/guard |
| `components/` | 工作台、聊天、报告、地图、审核和设置 UI |
| `config/`、`constants/` | 阶段、维度、GIS 和 UI 配置 |
| `utils/` | 报告解析、下载、格式化和轻量纯函数 |

## 数据流

```text
API/SSE → hooks → message/event guards → planningStore → components
```

事件处理必须可重复执行；SSE 重连按 `seq` 同步，组件不能自行推断后端阶段状态。生产构建前运行 `npm run type-check` 和 `npm run lint`。
