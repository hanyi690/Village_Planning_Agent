# 数据库Schema

> **更新日期**: 2026-05-21
> **版本**: v3.0 (统一架构)

本文档详细说明数据库表结构和关系。

## 目录

- [表结构概览](#表结构概览)
- [PlanningSession表](#planningsession表)
- [DimensionReport表](#dimensionreport表)
- [DimensionRevision表](#dimensionrevision表)
- [LangGraph Checkpoint表](#langgraph-checkpoint表)

---

## 表结构概览

| 表名 | 职责 | 管理方式 |
|------|------|----------|
| planning_sessions | 规划会话业务元数据 | SQLModel |
| dimension_reports | 维度报告内容存储 | SQLModel |
| dimension_revisions | 维度版本历史 | SQLModel |
| checkpoints | LangGraph状态快照 | AsyncSqliteSaver |
| checkpoint_blobs | 状态二进制数据 | LangGraph |

---

## PlanningSession表

### 表结构

```python
# backend/app/database/models.py
class PlanningSession(SQLModel, table=True):
    """规划会话表（精简版 - 只存储业务元数据）"""
    __tablename__ = "planning_sessions"

    # Primary key
    session_id: str = Field(primary_key=True)

    # Basic info
    project_name: str = Field(index=True)
    village_name: str = Field(default="", index=True)

    # 行政区划信息
    province: str = Field(default="")
    city: str = Field(default="")
    county: str = Field(default="")
    township: str = Field(default="")
    planning_period: str = Field(default="2022-2035年")

    # User input
    village_data: Optional[str] = Field(default=None, sa_column=Text())
    task_description: str = Field(default="制定村庄发展规划")
    constraints: str = Field(default="无特殊约束")

    # Output
    output_path: Optional[str] = None

    # Error info
    execution_error: Optional[str] = Field(default=None, sa_column=Text())

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | str | 主键，UUID |
| project_name | str | 项目名称 |
| village_name | str | 村庄名称 |
| province | str | 省份 |
| city | str | 地级市 |
| county | str | 县/区 |
| township | str | 乡镇 |
| planning_period | str | 规划期限 |
| village_data | Text | 村庄数据文本 |
| task_description | str | 任务描述 |
| constraints | str | 约束条件 |
| created_at | datetime | 创建时间 |
| completed_at | datetime | 完成时间 |

---

## DimensionReport表

### 表结构

```python
class DimensionReport(SQLModel, table=True):
    """维度报告表"""
    __tablename__ = "dimension_reports"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="planning_sessions.session_id", index=True)
    dimension_key: str = Field(index=True)
    layer: int = Field(index=True)

    # Version management
    version: int = Field(default=1, index=True)
    report_id: str = Field(unique=True, index=True)

    # Content
    content: str = Field(sa_column=Text())
    summary: str = Field(sa_column=Text())

    # Metadata
    revision_trigger: Optional[str] = None

    # Knowledge sources
    knowledge_sources: Optional[List[Dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSON)
    )

    # GIS data references
    gis_data: Optional[List[Dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSON)
    )

    generated_at: datetime = Field(default_factory=datetime.now)
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 自增主键 |
| session_id | str | 会话ID（外键） |
| dimension_key | str | 维度标识 |
| layer | int | 层级（1/2/3） |
| version | int | 版本号 |
| report_id | str | UUID（外部引用） |
| content | Text | 报告全文 |
| summary | Text | 结构化摘要（JSON） |
| knowledge_sources | JSON | 知识来源列表 |
| gis_data | JSON | GIS 数据引用 |

---

## DimensionRevision表

### 表结构

```python
class DimensionRevision(SQLModel, table=True):
    """维度修订表（历史日志）"""
    __tablename__ = "dimension_revisions"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="ui_sessions.conversation_id", index=True)
    layer: int = Field(index=True)
    dimension_key: str = Field(index=True)

    content: str = Field(sa_column=Text())
    previous_content: Optional[str] = Field(default=None, sa_column=Text())
    previous_content_hash: Optional[str] = None

    reason: Optional[str] = None
    created_by: Optional[str] = None
    version: int = Field(default=1, index=True)

    created_at: datetime = Field(default_factory=datetime.now)
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 自增主键 |
| session_id | str | 会话ID |
| layer | int | 层级 |
| dimension_key | str | 维度标识 |
| content | Text | 当前版本内容 |
| previous_content | Text | 前一版本内容 |
| version | int | 版本号 |
| reason | str | 修订原因 |

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

### 状态数据结构

Checkpoint 中存储的 AgentState 结构：

```python
{
    "session_id": "uuid",
    "project_name": "项目名称",
    "phase": "layer1" | "layer2" | "layer3" | "completed",
    "current_wave": 1,
    "completed_dimensions": {
        "layer1": ["location", "socio_economic", ...],
        "layer2": ["resource_endowment", ...],
        "layer3": [...]
    },
    "config": {
        "village_data": "...",
        "task_description": "...",
        "constraints": "...",
        "rag_enabled": true,
        "rag_layer_config": {1: true, 2: true, 3: true}
    },
    "step_mode": false,
    "execution_paused": false,
    "pause_after_step": false,
    "previous_layer": 0,
    "messages": [...],
    "metadata": {...}
}
```

---

## WAL模式配置

```python
# backend/app/database/engine.py
conn = await aiosqlite.connect(get_db_path())
await conn.execute("PRAGMA journal_mode=WAL")
await conn.execute("PRAGMA synchronous=NORMAL")
```

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 模型定义 | `backend/app/database/models.py` |
| 数据库引擎 | `backend/app/database/engine.py` |
| 异步操作 | `backend/app/database/operations.py` |
| 报告存储 | `backend/app/services/report_store.py` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - Checkpoint机制
- [04-backend-api](./04-backend-api.md) - CheckpointService
- [08-rag-system](./08-rag-system.md) - 知识来源追踪