> [!WARNING] **DEPRECATED — 历史参考**
> 性能参数以实际代码配置为准。当前架构以 [README.md](../README.md) 为准。

# 性能架构

本文档说明 LLM 并发控制、缓存机制和批量写入优化。

## LLM 并发控制

```python
LLM_MAX_CONCURRENT = 50  # 最大并发数（默认值）
LLM_STREAM_TIMEOUT = 300  # 流式超时（秒）
GRAPH_MAX_CONCURRENCY = 8  # LangGraph 图并发上限
```

### Semaphore 控制

```python
# backend/app/core/llm.py
semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENT)
async with semaphore:
    result = await llm.ainvoke(...)
```

## 缓存机制

| 缓存 | 内容 | 位置 |
|------|------|------|
| KnowledgeCache | RAG 预加载结果 | state.config.knowledge_cache |
| CheckpointCache | 状态快照 | LangGraph Checkpointer |
| layer_char_counts | 字符数缓存（避免 DB 查询） | AgentState.layer_char_counts |
| _query_cache | RAG 查询结果缓存（TTL） | RagService._query_cache |

## 批量写入优化

```python
# AgentState 性能优化字段
pending_reports: List[Dict]  # 批量写入缓冲，accumulate 后一次性 bulk_save
layer_char_counts: Dict[int, Dict[str, int]]  # 字符数缓存
```

- `pending_reports`: 维度分析完成时先追加到缓冲，`layer_completion_check` 节点触发 `bulk_save()` 批量写入数据库
- `layer_char_counts`: 缓存每个维度的字符计数，避免重复 DB 查询

## SSE 队列配置

```python
SSE_QUEUE_SIZE = 2000  # 每个 SSE 连接的事件队列大小
SSE_QUEUE_WAIT_TIMEOUT = 5.0  # 队列写入超时（秒）
```

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - 状态定义与并行合并
- [08-rag-system](./08-rag-system.md) - 向量缓存
- [09-database-schema](./09-database-schema.md) - 数据库写入
