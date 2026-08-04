# Core 层

> 全局基础设施：LLM 工厂、SSE 事件类型常量、LangSmith 追踪。被 `agent/`、`services/`、`tools/`、`utils/` 各层共享的横向能力，无业务逻辑。

---

## 一、文件清单

| 模块 | 职责 | 关键导出 |
|------|------|----------|
| `llm.py` | 统一 LLM 工厂（OpenAI/DeepSeek + 智谱 GLM + DashScope Flash） | `create_llm` / `create_flash_llm` / `get_default_llm` |
| `events.py` | SSE 事件类型常量（全系统唯一来源） | `SSEEventType` |
| `tracing.py` | LangSmith 追踪管理（单例） | `get_langsmith_manager` / `create_run_metadata` |
| `settings.py` | 环境配置加载（.env → 模块级常量） | 全量配置常量（见 `app/config/README.md` 关联） |

> `core/settings.py` 是配置源头（`.env` 经 `load_dotenv(override=True)` 加载）；`app/config/` 是**领域配置**（YAML 维度/阶段定义）。两者分工见 `app/config/README.md`。

---

## 二、LLM 工厂（`llm.py`）

**Provider 决策**：`get_provider()` 依据 `LLM_PROVIDER`（默认 `deepseek`）映射：

| Provider 名 | 枚举 | 通道 |
|-------------|------|------|
| `deepseek` / `openai` | `LLMProvider.OPENAI` | `ChatOpenAI`（`OPENAI_API_BASE` 覆盖 base_url） |
| `zhipuai` | `LLMProvider.ZHIPUAI` | `ChatZhipuAI`（langchain-classic → langchain-community fallback） |

- **Flash 模型**：`create_flash_llm` 走 DashScope（`DASHSCOPE_API_KEY` + `DASHSCOPE_API_BASE`），轻量任务专用
- **全局并发闸门**：`get_llm_semaphore(max_concurrent=20)` 惰性单例 `asyncio.Semaphore`，维度并行分析限流用（与 `LLM_MAX_CONCURRENT` 是两套机制，前者为显式信号量）
- **限流观测**：`rate_limiter` 参数接入 `InMemoryRateLimiter`，配合 `_on_ratelimit_info` 记录响应头剩余额度（仅观测，不做动态调整——共享 `max_bucket_size` 并发调整不安全）
- **回调合并**：`_merge_callbacks` 将用户回调与 LangSmith 回调合并
- **超时**：`LLM_REQUEST_TIMEOUT`（默认 180s）写入 `request_timeout`

---

## 三、SSE 事件类型（`events.py`）

`SSEEventType` 是所有 SSE 事件字符串的唯一权威来源，按域分组：

- **连接**：`connected` / `heartbeat` / `completed` / `error` / `resumed` / `pause`
- **层级**：`layer_started` / `layer_completed` / `layer_paused` / `execution_resumed`
- **维度**：`dimension_start` / `dimension_complete` / `dimension_delta` / `dimension_error`
- **级联**：`cascade_impact` / `cascade_complete`
- **AI 响应**：`ai_response_delta` / `ai_response_complete`
- **检查点**：`checkpoint_saved` / `revision_completed`
- **工具**：`tool_started` / `tool_status`（简化版）；`tool_call` / `tool_progress` / `tool_result`（遗留，向后兼容）
- **GIS**：`gis_result` / `gis_layer_update`
- **RAG**：`rag_query` / `rag_result`
- **配置**：`rag_config_updated` / `step_mode_updated`

消费方：`services/sse.py` 的 `SSEManager`（`CACHE_CONFIG` 按事件类型做关键事件缓存）、`utils/sse_publisher.py`、`utils/event_factory.py`。

---

## 四、LangSmith 追踪（`tracing.py`）

单例 `LangSmithManager`：

- **启用条件**：`LANGCHAIN_TRACING_V2=true` 且配置了 `LANGCHAIN_API_KEY`，否则静默禁用
- **副作用**：初始化时向 `os.environ` 注入 `LANGCHAIN_TRACING_V2` / `LANGCHAIN_API_KEY` / `LANGCHAIN_PROJECT` / `LANGCHAIN_ENDPOINT`
- **回调**：`get_callbacks()` 供 `llm.py` 合并进各 LLM 实例
- **run 元数据**：`create_run_metadata(project_name, dimension, layer, extra_info)` 生成项目/维度/层级维度（`agent_version: v4.1.0`）

---

## 五、相关文档

- `app/config/README.md` — 领域配置（YAML 维度/阶段定义）与 `settings.py` 分工
- `app/services/README.md` — SSE 事件发布/缓存的实际消费方
- `app/utils/logger.py` — 日志器（跨模块唯一会话 ID 注入）
