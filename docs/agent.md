# 核心智能体文档 (Core Agent Documentation)

> **村庄规划智能体** - 基于 LangGraph 和 LangChain 的智能村庄规划系统，提供 **Web 应用** 和 **CLI 工具** 两种使用方式，采用三层分层架构实现专业的村庄规划辅助。

---

## 目录

- [架构概述](#架构概述)
- [三层规划系统](#三层规划系统)
- [LangGraph 状态图](#langgraph-状态图)
- [统一规划器](#统一规划器)
- [数据流管理](#数据流管理)
- [状态筛选优化](#状态筛选优化)
- [检查点机制](#检查点机制)

---

## 架构概述

### 核心技术栈

- **LangGraph** - 状态图编排框架
- **LangChain** - LLM 应用开发框架
- **Pydantic V2** - 数据验证和序列化
- **FastAPI** - 现代异步 Python Web 框架

### 设计原则

1. **分层架构**: 三层递进式规划（现状分析 → 规划思路 → 详细规划）
2. **并行执行**: 每层内多个维度并行处理，提升效率
3. **状态筛选**: 智能过滤相关维度数据，节省 LLM token 消耗
4. **检查点机制**: 每层完成后自动保存，支持中断恢复
5. **统一规划器**: 基于统一基类的通用架构

---

## 三层规划系统

### Layer 1: 现状分析

**并行维度** (12个):
| 维度ID | 维度名称 | 英文键名 | 说明 |
|---------|-----------|-----------|------|
| 1 | 区位与对外交通分析 | `location` | 村庄的地理位置、对外交通条件 |
| 2 | 社会经济分析 | `socio_economic` | 人口结构、经济状况、收入来源 |
| 3 | 村民意愿分析 | `villager_wishes` | 村民发展意愿、需求调研 |
| 4 | 上位规划分析 | `superior_planning` | 上级规划要求、政策符合性 |
| 5 | 自然环境与资源分析 | `natural_environment` | 地形地貌、气候条件、自然资源 |
| 6 | 村庄用地分析 | `land_use` | 土地利用现状、权属关系 |
| 7 | 道路与交通分析 | `traffic` | 道路网络、交通设施 |
| 8 | 公共服务设施分析 | `public_services` | 教育、医疗、养老设施 |
| 9 | 基础设施分析 | `infrastructure` | 水电、通信、能源 |
| 10 | 生态绿地分析 | `ecological_green` | 绿地空间、生态系统 |
| 11 | 建筑分析 | `architecture` | 传统建筑、历史建筑 |
| 12 | 历史文化分析 | `historical_cultural` | 文化遗产、民俗传统 |

**输出**: `analysis_dimension_reports` (字典，使用英文键名)

---

### Layer 2: 规划思路

**并行维度** (4个):
| 维度ID | 维度名称 | 英文键名 | 说明 |
|---------|-----------|-----------|------|
| 1 | 资源禀赋分析 | `resource_endowment` | 自然资源、人力资源、技术条件 |
| 2 | 规划定位分析 | `planning_positioning` | 发展定位、目标市场 |
| 3 | 发展目标分析 | `development_goals` | 总体目标、阶段规划 |
| 4 | 规划策略分析 | `planning_strategies` | 空间策略、产业布局 |

**输出**: `concept_dimension_reports` (字典)

---

### Layer 3: 详细规划

**分波次执行** (Wave 1-3):

**Wave 1** (11个维度并行):
| 维度ID | 维度名称 | 英文键名 |
|---------|-----------|-----------|
| 1 | 产业规划 | `industry` | 产业发展方向、重点项目 |
| 2 | 空间结构规划 | `spatial_structure` | 用地布局、功能分区 |
| 3 | 土地利用规划 | `land_use_planning` | 用地性质、分区规划 |
| 4 | 聚落体系规划 | `settlement_planning` | 居民点布局、迁并规划 |
| 5 | 综合交通规划 | `traffic` | 道路系统、交通设施 |
| 6 | 公共服务设施规划 | `public_service` | 公建配套、服务网络 |
| 7 | 基础设施规划 | `infrastructure` | 市政设施、管网系统 |
| 8 | 生态保护与修复规划 | `ecological` | 环境治理、生态修复 |
| 9 | 防灾减灾规划 | `disaster_prevention` | 灾害防治、应急响应 |
| 10 | 历史文化遗产保护 | `heritage` | 文化遗产保护、传承利用 |
| 11 | 村庄风貌引导 | `landscape` | 景观设计、风貌塑造 |

**Wave 2** (依赖 Wave 1，项目库):
| 维度ID | 维度名称 | 英文键名 |
|---------|-----------|-----------|
| 12 | 建设项目库 | `project_bank` | 项目储备、建设管理 |

**Wave 3** (剩余维度详细规划)

**输出**: `detailed_dimension_reports` (字典)

---

## LangGraph 状态图

### 状态定义

```python
class PlanningState(TypedDict):
    # 输入数据
    project_name: str
    village_data: str
    task_description: str

    # 层级完成标志
    layer_1_completed: bool = False
    layer_2_completed: bool = False
    layer_3_completed: bool = False

    # 当前层级
    current_layer: int = 1

    # 维度报告 (使用英文键名)
    analysis_dimension_reports: Annotated[dict[str, str], add]
    concept_dimension_reports: Annotated[dict[str, str], add]
    detailed_dimension_reports: Annotated[dict[str, str], add]

    # 其他状态
    pause_after_step: bool = False
    waiting_for_review: bool = False
    execution_complete: bool = False
    execution_error: str | None = None
    last_checkpoint_id: str | None = None
```

### 状态转换流程

```
用户输入
    ↓
main_graph.start()
    ↓
layer1_analysis_node (并行12个维度)
    ↓
analysis_aggregator_node (汇总12个结果)
    ↓
设置 analysis_dimension_reports
    ↓
layer_1_completed = True
    ↓
REST 轮询检测到状态变化
    ↓
前端触发 onLayerCompleted(1)
```

---

## 统一规划器

### 架构设计

```python
from abc import ABC, abstractmethod

class UnifiedBasePlanner(ABC):
    """统一规划器基类"""

    def __init__(
        self,
        llm,              # LLM 实例
        dimension_id: str,  # 维度ID
        dimension_name: str,  # 维度名称
        rag_enabled: bool = True  # 是否启用 RAG
    ):
        self.llm = llm
        self.dimension_id = dimension_id
        self.dimension_name = dimension_name
        self.rag_enabled = rag_enabled

    @abstractmethod
    def get_prompt_template(self) -> str:
        """获取提示词模板（子类实现）"""
        pass

    @abstractmethod
    def get_dimension_dependencies(self) -> list[str]:
        """获取维度依赖（子类实现）"""
        pass

    def filter_state(self, state: dict) -> dict:
        """状态筛选：只传递相关维度数据"""
        dependencies = self.get_dimension_dependencies()
        filtered = {}
        for dep in dependencies:
            if dep in state:
                filtered[dep] = state[dep]
        return filtered

    def analyze(self, state: dict) -> dict:
        """分析方法（通用逻辑）"""
        # 1. 状态筛选
        filtered_state = self.filter_state(state)

        # 2. 构建提示词
        prompt = self.build_prompt(filtered_state)

        # 3. 调用 LLM
        response = self.llm.invoke(prompt)

        # 4. 返回结果
        return {
            f"{self.dimension_id}_report": response.content
        }
```

**支持流式队列**（⭐ NEW）:
```python
class UnifiedBasePlanner(ABC):
    def execute(
        self,
        state: dict,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        enable_langsmith: bool = True,
        streaming: bool = False,
        on_token_callback: Callable[[str, str], None] | None = None,
        streaming_queue: Optional[Any] = None  # ⭐ 新增参数
    ) -> dict:
        # 如果提供流式队列，使用队列回调
        if streaming_queue and streaming:
            def queue_callback(token: str, accumulated: str) -> None:
                streaming_queue.add_token(
                    dimension_key=self.dimension_id,
                    dimension_name=self.dimension_name,
                    layer=self.get_layer(),
                    token=token,
                    accumulated=accumulated
                )

            # 组合回调
            if on_token_callback and queue_callback:
                def combined_callback(token: str, accumulated: str):
                    queue_callback(token, accumulated)
                    on_token_callback(token, accumulated)
            else:
                combined_callback = on_token_callback
        else:
            combined_callback = on_token_callback

        # 调用 LLM
        result = self._invoke_llm(...)

        # 标记维度完成
        if streaming_queue and streaming:
            streaming_queue.complete_dimension(
                dimension_key=self.dimension_id,
                layer=self.get_layer()
            )

        return {
            f"{self.dimension_id}_report": result
        }
```

---

## 数据流管理

### 流式队列管理器（⭐ NEW）

**文件**: `src/utils/streaming_queue.py`

**功能**：
- 按维度隔离 token 队列
- 批处理策略（50 tokens 或 100ms 时间窗口）
- 线程安全操作（Lock 保护）
- 维度完成时返回完整内容

**使用示例**:
```python
from src.utils.streaming_queue import StreamingQueueManager

# 创建队列管理器
queue = StreamingQueueManager(
    batch_size=50,           # 50 tokens 触发刷新
    batch_window=0.1,        # 100ms 时间窗口
    flush_callback=lambda **kwargs: emit_sse_event(**kwargs)
)

# 在规划器中使用
planner.execute(
    state=state,
    streaming=True,
    streaming_queue=queue  # 注入队列管理器
)

# 维度完成时自动标记
full_content = queue.complete_dimension("location", 1)
```

**批处理优化效果**:
- Token → 前端延迟 < 100ms (P95 目标)
- 减少 > 80% 的 DOM 更新次数

---

### 异步存储管道（⭐ NEW）

**文件**: `backend/services/storage_pipeline.py`

**功能**：
- 维度完成时立即写入 Redis（非阻塞）
- 层级完成时批量写入 SQLite
- 文件写入使用后台任务，不阻塞流式传输

**存储策略**：
```
维度完成 → Redis (立即缓存)
    ↓
    streaming_queue.complete_dimension(dimension_key, layer)
    ↓
    await pipeline.store_dimension(
        layer=layer,
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        content=full_content
    )
    ↓
    Redis: 流式缓存（非阻塞）

层级完成 → SQLite (批量) + 文件
    ↓
    所有维度完成
    ↓
    await pipeline.commit_layer(
        layer=layer,
        combined_report=完整报告,
        dimension_reports={所有维度内容}
    )
    ↓
    SQLite: 批量持久化
    后台任务: 文件写入（完全异步）
```

**非阻塞特性**：
- Redis 写入失败不影响流式传输
- SQLite 写入延迟到层级完成时
- 文件写入使用 `asyncio.create_task()`

---

## 状态筛选优化

### 优化原理

**问题**: 传递所有维度数据导致 LLM token 浪费

**解决方案**: 智能筛选只传递相关维度

**依赖关系配置**:
```python
DIMENSION_DEPENDENCIES = {
    "industry": {
        "dependencies": ["analysis_dimension_reports"],
        "reason": "产业规划依赖现状分析结果"
    },
    "spatial_structure": {
        "dependencies": ["analysis_dimension_reports"],
        "reason": "空间规划依赖现状分析结果"
    },
    "settlement_planning": {
        "dependencies": ["analysis_dimension_reports", "spatial_structure"],
        "reason": "聚落规划依赖现状和空间分析结果"
    }
}
```

**筛选效果**:
| 场景 | 无筛选 | 有筛选 | 节省 |
|-------|-------|-------|------|
| Layer 1 (12维度) | ~20k tokens | ~8k tokens | **60%** |
| Layer 2 (4维度) | ~5k tokens | ~2k tokens | **60%** |
| Layer 3 (12维度) | ~20k tokens | ~8k tokens | **60%** |

---

## 检查点机制

### 检查点数据结构

```python
{
    "checkpoint_id": "checkpoint_001_layer1_completed",
    "session_id": "20240101_120000",
    "layer": 1,
    "description": "现状分析完成，进入人工审查",
    "state_snapshot": {...},  # 完整状态快照
    "created_at": "2024-01-01T12:00:00"
}
```

### 检查点功能

- **自动保存**: 每层完成后自动保存检查点
- **状态完整性**: 保存所有维度报告和完整状态
- **中断恢复**: 支持从任意检查点恢复执行
- **灵活回退**: 可回退到任意历史检查点

**恢复流程**:
```
用户点击"回退到检查点"
    ↓
加载检查点 state_snapshot
    ↓
main_graph.restore(checkpointer, config)
    ↓
从检查点继续执行
```

---

## 相关文档

- **[前端实现文档](frontend.md)** - Next.js 14 技术栈、类型系统、SSE/REST 解耦
- **[后端实现文档](backend.md)** - FastAPI 架构、API 端点、数据库状态管理、流式队列、异步存储
- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - Next.js 应用架构、组件设计、状态管理
- **[前端视觉指南](FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范、色彩系统、组件样式
- **[README](../README.md)** - 项目概述和快速开始

---

## 最后更新

**维护者**: Village Planning Agent Team
**更新日期**: 2025-01-11
**版本**: 1.5.0 - 流式响应架构优化版
