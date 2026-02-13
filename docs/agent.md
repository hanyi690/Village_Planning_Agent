# 核心智能体文档 (Core Agent Documentation)

> **村庄规划智能体** - 基于 LangGraph 和 LangChain 的智能村庄规划系统

## 目录

- [架构概述](#架构概述)
- [三层规划系统](#三层规划系统)
- [LangGraph 状态图](#langgraph-状态图)
- [统一规划器](#统一规划器)
- [流式队列集成](#流式队列集成)
- [状态筛选优化](#状态筛选优化)

---

## 架构概述

### 核心技术栈

- **LangGraph** - 状态图编排框架
- **LangChain** - LLM 应用开发框架
- **Pydantic V2** - 数据验证和序列化

### 设计原则

1. **分层架构**: 三层递进式规划（现状分析 → 规划思路 → 详细规划）
2. **并行执行**: 每层内多个维度并行处理，提升效率
3. **状态筛选**: 智能过滤相关维度数据，节省 LLM token 消耗
4. **检查点机制**: 每层完成后自动保存，支持中断恢复
5. **统一规划器**: 基于统一基类的通用架构
6. **流式队列集成**: 支持维度级实时流式输出

---

## 三层规划系统

### Layer 1: 现状分析

**并行维度** (12个):
| 维度ID | 维度名称 | 英文键名 |
|---------|-----------|-----------|
| 1 | 区位与对外交通分析 | `location` |
| 2 | 社会经济分析 | `socio_economic` |
| 3 | 村民意愿分析 | `villager_wishes` |
| 4 | 上位规划分析 | `superior_planning` |
| 5 | 自然环境与资源分析 | `natural_environment` |
| 6 | 村庄用地分析 | `land_use` |
| 7 | 道路与交通分析 | `traffic` |
| 8 | 公共服务设施分析 | `public_services` |
| 9 | 基础设施分析 | `infrastructure` |
| 10 | 生态绿地分析 | `ecological_green` |
| 11 | 建筑分析 | `architecture` |
| 12 | 历史文化分析 | `historical_cultural` |

**输出**: `analysis_dimension_reports` (字典)

---

### Layer 2: 规划思路

**并行维度** (4个):
| 维度ID | 维度名称 | 英文键名 |
|---------|-----------|-----------|
| 1 | 资源禀赋分析 | `resource_endowment` |
| 2 | 规划定位分析 | `planning_positioning` |
| 3 | 发展目标分析 | `development_goals` |
| 4 | 规划策略分析 | `planning_strategies` |

**输出**: `concept_dimension_reports` (字典)

---

### Layer 3: 详细规划

**分波次执行** (Wave 1-3):

**Wave 1** (11个维度并行):
| 维度ID | 维度名称 | 英文键名 |
|---------|-----------|-----------|
| 1 | 产业规划 | `industry` |
| 2 | 空间结构规划 | `spatial_structure` |
| 3 | 土地利用规划 | `land_use_planning` |
| 4 | 聚落体系规划 | `settlement_planning` |
| 5 | 综合交通规划 | `traffic` |
| 6 | 公共服务设施规划 | `public_service` |
| 7 | 基础设施规划 | `infrastructure` |
| 8 | 生态保护与修复规划 | `ecological` |
| 9 | 防灾减灾规划 | `disaster_prevention` |
| 10 | 历史文化遗产保护 | `heritage` |
| 11 | 村庄风貌引导 | `landscape` |

**Wave 2** (依赖 Wave 1，项目库):
| 维度ID | 维度名称 | 英文键名 |
|---------|-----------|-----------|
| 12 | 建设项目库 | `project_bank` |

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

    # 维度报告
    analysis_dimension_reports: Annotated[dict[str, str], add]
    concept_dimension_reports: Annotated[dict[str, str], add]
    detailed_dimension_reports: Annotated[dict[str, str], add]

    # 其他状态
    pause_after_step: bool = False
    waiting_for_review: bool = False
    execution_complete: bool = False
    execution_error: str | None = None
```

### 状态转换流程

```
用户输入
    ↓
main_graph.start()
    ↓
layer1_analysis_node (并行12个维度)
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

**文件**: `src/planners/unified_base_planner.py`

**核心类**:
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

    def execute(
        self,
        state: dict,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        enable_langsmith: bool = True,
        streaming: bool = False,
        on_token_callback: Callable[[str, str], None] | None = None,
        streaming_queue: Optional[Any] = None  # 流式队列参数
    ) -> dict:
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

---

## 流式队列集成

### 支持流式队列

**核心实现**:
```python
class UnifiedBasePlanner(ABC):
    def execute(
        self,
        state: dict,
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
                combined_callback = on_token_callback or queue_callback
        else:
            combined_callback = on_token_callback

        # 调用 LLM
        result = self._invoke_llm(
            prompt=prompt,
            streaming=streaming,
            on_token_callback=combined_callback
        )

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

### 筛选效果

| 场景 | 无筛选 | 有筛选 | 节省 |
|-------|-------|-------|------|
| Layer 1 (12维度) | ~20k tokens | ~8k tokens | **60%** |
| Layer 2 (4维度) | ~5k tokens | ~2k tokens | **60%** |
| Layer 3 (12维度) | ~20k tokens | ~8k tokens | **60%** |

---

## 相关文档

- **[前端实现文档](frontend.md)** - Next.js 14 技术栈、维度级流式响应、SSE/REST 解耦
- **[后端实现文档](backend.md)** - FastAPI 架构、异步数据库、流式队列
- **[前端组件架构](../FRONTEND_COMPONENT_ARCHITECTURE.md)** - 组件设计、状态管理
- **[前端视觉指南](../FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范
- **[README](../README.md)** - 项目概述和快速开始

---

**最后更新**: 2026-02-12
**维护者**: Village Planning Agent Team
**版本**: 2.0.0 - 流式响应架构优化版
