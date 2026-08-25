# Core 层

> 全局环境配置加载。经过蓝本重构后，`core/` 仅保留 `settings.py`（配置源头）；
> LLM 工厂、SSE 事件类型、LangSmith 追踪已迁出到各自蓝本层（见下）。

---

## 一、文件清单

| 模块 | 职责 | 关键导出 |
|------|------|----------|
| `settings.py` | 环境配置加载（.env → 模块级常量） | 全量配置常量（见 `app/config/README.md` 关联） |

> `core/settings.py` 是配置源头（环境变量优先，其次 cwd/root `.env`）；`app/config/` 是**领域配置**（YAML 维度/阶段定义）。两者分工见 `app/config/README.md`。

---

## 二、已迁出模块

| 原位置 | 新位置 |
|--------|--------|
| `core/llm.py`（`create_llm` / `create_flash_llm` / `LLMProvider` / `get_provider`） | `infrastructure/llm/factory.py` |
| `core/instructor_client.py`（`get_instructor_client` / `get_structured_model`） | `infrastructure/llm/instructor_client.py` |
| `core/tracing.py`（LangSmith 单例 `get_langsmith_manager` / `create_run_metadata`） | `infrastructure/llm/tracing.py` |
| `core/events.py`（`SSEEventType`，全系统唯一来源） | `contracts/events.py`（跨层共享契约，底层） |

`infrastructure/llm/factory.py` 与 `tracing.py` 之间的内部引用在 `infrastructure/llm` 包内完成；
`contracts/events.py` 为底层契约，不依赖任何 app 内上层模块。

---

## 三、相关文档

- `app/config/README.md` — 领域配置（YAML 维度/阶段定义）与 `settings.py` 分工
