> [!WARNING] **DEPRECATED — 历史参考**
> 版本号已过时。当前数据库 Schema 以 `database/models.py` 和 [README.md](../README.md) 为准。
> 表名（SQL）vs 模型类名（Python）的映射以代码实现为准。

# 数据库Schema

> **更新日期**: 2026-07-08
> **版本**: v4.0 (LangGraph 1.2 interrupt/resume)

本文档详细说明数据库表结构和关系。

## 目录

- [表结构概览](#表结构概览)
- [PlanningSession表](#planningsession表)
- [UISession表](#uisession表)
- [DimensionReport表](#dimensionreport表)
- [UploadedFile表](#uploadedfile表)
- [PlanningTextDocument表](#planningtextdocument表)
- [LangGraph Checkpoint表](#langgraph-checkpoint表)

---

## 表结构概览

| 表名 | 职责 | 管理方式 |
|------|------|----------|
| planning_sessions | 规划会话业务元数据 | SQLModel |
| ui_sessions | UI会话管理 | SQLModel |
| dimension_reports | 维度报告内容存储 | SQLModel |
| uploaded_files | 上传文件存储 | SQLModel |
| planning_text_documents | 规划文本文档（版本化） | SQLModel |
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

## UISession表

### 表结构

```python
class UISession(SQLModel, table=True):
    """UI 会话表"""
    __tablename__ = "ui_sessions"

    conversation_id: str = Field(primary_key=True)
    status: str = Field(default="idle", index=True)
    project_name: Optional[str] = None
    task_id: Optional[str] = Field(index=True)  # Links to planning session

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| conversation_id | str | 主键，UI会话ID |
| status | str | 会话状态（idle/active/completed） |
| project_name | str | 项目名称 |
| task_id | str | 关联的规划会话ID |

---

## UploadedFile表

### 表结构

```python
class UploadedFile(SQLModel, table=True):
    """上传文件存储表"""
    __tablename__ = "uploaded_files"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="planning_sessions.session_id", ondelete="CASCADE", index=True)

    # File classification
    file_category: str = Field(index=True)  # "village_data", "task_description", "constraint"
    file_type: str = Field(index=True)       # "document", "geojson", "shapefile", etc.

    # File metadata
    filename: str = Field(max_length=255)
    original_filename: str = Field(max_length=255)
    file_size: int
    content_type: str = Field(max_length=100)

    # Parsed content
    parsed_text: Optional[str] = Field(default=None, sa_column=Text())
    gis_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    gis_data_type: Optional[str] = None  # "boundary", "water", "road", "residential", etc.

    # Processing status
    parse_status: str = Field(default="pending")  # "pending", "success", "failed"
    parse_error: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.now)
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 自增主键 |
| session_id | str | 会话ID（外键，级联删除） |
| file_category | str | 文件分类 |
| file_type | str | 文件类型 |
| filename | str | 存储文件名 |
| original_filename | str | 原始文件名 |
| file_size | int | 文件大小（字节） |
| content_type | str | MIME类型 |
| parsed_text | Text | 解析后的文本内容 |
| gis_data | JSON | GIS数据（GeoJSON格式） |
| gis_data_type | str | GIS数据类型推断 |
| parse_status | str | 解析状态 |

---

## PlanningTextDocument表

### 表结构

```python
class PlanningTextDocument(SQLModel, table=True):
    """规划文本文档表（版本化）"""
    __tablename__ = "planning_text_documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="planning_sessions.session_id", ondelete="CASCADE", index=True)

    # Version management
    version: int = Field(default=1, index=True)
    document_id: str = Field(unique=True, index=True)  # UUID

    # Content
    markdown_content: str = Field(sa_column=Text())
    json_content: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Metadata
    article_count: int = Field(default=0)
    generated_at: datetime = Field(default_factory=datetime.now)
    generation_duration_seconds: Optional[float] = None

    # Status
    status: str = Field(default="completed")  # pending, generating, completed, failed
    error_message: Optional[str] = None

    # Version metadata
    trigger_reason: Optional[str] = None  # "initial", "dimension_change", "manual"
    changed_dimensions: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 自增主键 |
| session_id | str | 会话ID（外键，级联删除） |
| version | int | 版本号 |
| document_id | str | UUID（外部引用） |
| markdown_content | Text | Markdown格式规划文本 |
| json_content | JSON | JSON格式结构化内容 |
| article_count | int | 文章条目数 |
| status | str | 生成状态 |
| trigger_reason | str | 生成触发原因 |
| changed_dimensions | JSON | 变更的维度列表 |

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
    "previous_layer": 0,
    # Cascade revision fields
    "need_revision": false,
    "is_revision": false,
    "revision_impact_tree": {0: ["dim_a"], 1: ["dim_b", "dim_c"]},
    "revision_completed_dims": ["dim_a"],
    "revision_feedback": "...",
    "last_revised_dimensions": ["dim_a"],
    # Performance fields
    "pending_reports": [],
    "layer_char_counts": {},
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