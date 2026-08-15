# Bootstrap 引导层

> 本 README 以 `backend/app/bootstrap/` 实际代码为准（核验日期 2026-08-15）。

## 定位

负责 FastAPI 应用生命周期（lifespan）与依赖组合根。它只做“启动/关闭 + 组装”，
不包含业务算法；`app.main` 保持薄入口，脚本和 acceptance 测试可以复用同一套生命周期。

## 文件职责

| 文件 | 职责 |
|---|---|
| `lifespan.py` | FastAPI `lifespan` 上下文：初始化数据库、`CompositionRoot`、`PlanningRuntimeService`；把 readiness 写入 `app.state.readiness`；注册 SSE event loop；日志轮转清理任务；关闭时释放 runtime、数据库引擎和 KG worker pool |
| `composition.py` | `CompositionRoot`：懒初始化 `ReportStore`、`TaskSupervisor`、context reader 单例，并写入 `infrastructure/registry` 默认值；`reset()` 供测试使用 |

## 启动顺序（`lifespan`）

```text
app.main:app
  → bootstrap/lifespan.py
      → database.init_async_db()            # 建表/迁移，失败则 readiness=failed 并抛错
      → CompositionRoot.initialize()        # ReportStore + TaskSupervisor
      → PlanningRuntimeService.initialize() # runtime 单例（含 graph/checkpointer 等）
      → event_hub.save_event_loop(...)      # SSE 在线事件循环
  → 启动日志清理后台任务
  → yield（服务运行）
  → 关闭：PlanningRuntimeService.shutdown → dispose_async_engine → shutdown_database → KG pool shutdown
```

## 边界规则

- 启动失败必须把 `app.state.readiness` 标记为 failed，不允许带病对外提供 `/api/health=ready`。
- 组合根是唯一持有服务单例生命周期的位置；模块通过 `infrastructure/registry` 读取默认单例。
- 测试可通过 `CompositionRoot.reset()` 复位单例状态。