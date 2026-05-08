# 数据库Schema

本文档详细说明数据库表结构和关系。

## 目录

- [表结构概览](#表结构概览)
- [PlanningSession表](#planningsession表)
- [LangGraph Checkpoint表](#langgraph-checkpoint表)

---

## 表结构概览

| 表名 | 职责 | 管理方式 |
|------|------|----------|
| planning_sessions | 规划会话业务元数据 | SQLModel |
| checkpoints | LangGraph状态快照 | AsyncSqliteSaver |
| checkpoint_blobs | 状态二进制数据 | LangGraph |

---

## PlanningSession表

### 表结构

```python
# backend/database/models.py
class PlanningSession(SQLModel, table=True):
    """规划会话表"""
    __tablename__ = "planning_sessions"

    session_id: str = Field(primary_key=True)
    project_name: str = Field(index=True)
    village_data: Optional[str]
    task_description: str
    constraints: str
    output_path: Optional[str]
    execution_error: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | str | 主键，UUID |
| project_name | str | 项目名称 |
| village_data | Text | 村庄数据JSON |
| task_description | str | 任务描述 |
| created_at | datetime | 创建时间 |
| completed_at | datetime | 完成时间 |

---

## LangGraph Checkpoint表

### checkpoints表

LangGraph AsyncSqliteSaver自动管理：

| 字段 | 类型 | 说明 |
|------|------|------|
| thread_id | TEXT | 会话ID |
| checkpoint_id | TEXT | 检查点ID |
| checkpoint | JSON | 状态数据 |
| metadata | JSON | 元数据 |

---

## WAL模式配置

```python
# backend/database/engine.py
# 启用WAL模式
conn.execute(text("PRAGMA journal_mode=WAL"))
conn.execute(text("PRAGMA synchronous=NORMAL"))
```

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 模型定义 | `backend/database/models.py` |
| 数据库引擎 | `backend/database/engine.py` |
| 异步操作 | `backend/database/operations_async.py` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - Checkpoint机制
- [04-backend-api](./04-backend-api.md) - CheckpointService