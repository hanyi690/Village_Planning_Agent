# 错误处理架构

本文档说明错误分类和处理层次。

## 错误分类

| 类型 | 来源 | 处理方式 |
|------|------|----------|
| LLMError | LLM调用失败 | 重试+降级 |
| ToolError | 工具执行失败 | 记录+跳过 |
| ValidationError | 参数验证失败 | 返回错误消息 |
| SSEError | SSE连接断开 | 自动重连 |

## 处理层次

```
API层 -> 捕获异常 -> 返回HTTP错误码
Agent层 -> 状态标记 -> 继续或暂停
工具层 -> try-catch -> 返回错误信息
```

---

## 相关文档

- [04-backend-api](./04-backend-api.md) - SSE错误处理