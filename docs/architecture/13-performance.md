# 性能架构

本文档说明LLM并发控制和缓存机制。

## LLM并发控制

```python
LLM_MAX_CONCURRENT = 4  # 最大并发数
LLM_STREAM_TIMEOUT = 300  # 流式超时（秒）
```

### Semaphore控制

```python
semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENT)
async with semaphore:
    result = await llm.ainvoke(...)
```

## 缓存机制

| 缓存 | 内容 | 位置 |
|------|------|------|
| KnowledgeCache | RAG预加载结果 | state.config.knowledge_cache |
| VectorCache | 向量检索结果 | backend/app/modules/rag/cache.py |
| CheckpointCache | 状态快照 | LangGraph Checkpointer |

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - 知识预加载
- [08-rag-system](./08-rag-system.md) - 向量缓存