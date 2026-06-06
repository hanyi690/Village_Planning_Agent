# 错误处理架构

> **更新日期**: 2026-06-05
> **版本**: v3.0

本文档说明错误分类和处理层次。

## 错误分类

| 类型 | 来源 | 处理方式 | 实现位置 |
|------|------|----------|----------|
| LLMError | LLM 调用失败 | 重试 + 降级 | `core/llm.py` |
| ToolError | 工具执行失败 | 记录 + 跳过 | `tools/registry.py` |
| ValidationError | 参数验证失败 | 返回错误消息 | `api/schemas.py` |
| SSEError | SSE 连接断开 | 自动重连 + 序列号同步 | `services/sse.py` |
| AgentError | Agent 路由异常 | 状态标记 + 暂停 | `agent/routing.py` |

## 处理层次

```
API层 -> HTTPException -> 返回 HTTP 错误码
Agent层 -> AgentState 标记 -> 继续或暂停
工具层 -> try-catch -> 返回错误信息给 LLM
SSE层 -> 序列号同步 -> 自动重连恢复
```

### API 层错误处理

```python
# backend/app/api/session_routes.py
raise HTTPException(status_code=404, detail="Session not found")
raise HTTPException(status_code=500, detail="Internal server error")
```

### SSE 重连机制

```python
# backend/app/services/sse.py
# 1. 每个事件附带序列号 (seq_no)
# 2. 客户端通过 Last-Event-ID 请求缺失事件
# 3. pending_events 缓存关键事件（7种类型）
# 4. sync_events 端点补发缺失序列号之后的所有事件
```

### LLM 重试策略

```python
# backend/app/utils/retry.py
# 指数退避重试：max_retries=3, base_delay=1s
# 超时处理：LLM_STREAM_TIMEOUT=300s
```

### 工具层错误处理

```python
# backend/app/tools/registry.py
# try-catch 包裹每个工具调用
# 错误信息返回给 LLM 作为 ToolMessage
```

---

## 相关文档

- [04-backend-api](./04-backend-api.md) - SSE 重连协议
- [13-performance](./13-performance.md) - SSE 队列与超时