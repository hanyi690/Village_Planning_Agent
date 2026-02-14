# 核心智能体文档 (Core Agent Documentation)

> **村庄规划智能体** - 基于 LangGraph 的智能村庄规划系统

## 目录

- [架构概述](#架构概述)
- [三层规划系统](#三层规划系统)
- [AsyncSqliteSaver 状态持久化](#asyncsqlitesaver-状态持久化)
- [LangGraph 状态图](#langgraph-状态图)
- [暂停/恢复机制](#暂停恢复机制)
- [统一规划器](#统一规划器)
- [状态筛选优化](#状态筛选优化)

---

## 架构概述

### 核心技术栈

- **LangGraph 1.0.8+** - 状态图编排框架
- **LangChain** - LLM 应用开发框架
- **AsyncSqliteSaver** - SQLite 持久化（langgraph-checkpoint-sqlite 3.0.3+）
- **Pydantic V2** - 数据验证和序列化

### 设计原则

1. **分层架构**: 三层递进式规划（现状分析 → 规划思路 → 详细规划）
2. **并行执行**: 每层内多个维度并行处理，提升效率
3. **状态持久化**: AsyncSqliteSaver 自动保存状态到 SQLite
4. **状态筛选**: 智能过滤相关维度数据，节省 LLM token 消耗
5. **统一规划器**: 基于统一基类的通用架构
6. **检查点机制**: 每层完成后自动保存，支持中断恢复

### 核心优势

✅ **自动状态管理**: AsyncSqliteSaver 自动持久化，无需手动维护
✅ **毫秒级恢复**: 从 checkpoint 毫秒级还原完整状态
✅ **数据一致性**: AI 状态 = 数据库内容，天然匹配
✅ **代码简洁**: 删除手动同步逻辑，精简数据库模型

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

**AsyncSqliteSaver 存储**:
```python
state["analysis_dimension_reports"] = {
    "location": "区位分析报告...",
    "socio_economic": "社会经济分析报告...",
    # ... 12 个维度
}
state["layer_1_completed"] = True
state["previous_layer"] = 1
state["current_layer"] = 2
# AsyncSqliteSaver 自动保存到 checkpoints 表
```

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

**AsyncSqliteSaver 存储**:
```python
state["concept_dimension_reports"] = {
    "resource_endowment": "资源禀赋分析...",
    "planning_positioning": "规划定位分析...",
    # ... 4 个维度
}
state["layer_2_completed"] = True
state["previous_layer"] = 2
state["current_layer"] = 3
# AsyncSqliteSaver 自动保存
```

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

**AsyncSqliteSaver 存储**:
```python
state["detailed_dimension_reports"] = {
    "industry": "产业规划...",
    "spatial_structure": "空间结构规划...",
    # ... 12 个维度
}
state["layer_3_completed"] = True
state["previous_layer"] = 3
state["current_layer"] = 4
# AsyncSqliteSaver 自动保存
```

---

## AsyncSqliteSaver 状态持久化

### 架构设计

**核心概念**: SQLite 作为 AI 的"自动硬盘"

```
┌─────────────────────────────────────────────────────┐
│                LangGraph 执行图                    │
│                                                      │
│  状态变化 → AsyncSqliteSaver.put()                  │
│             ↓                                      │
│  自动序列化 → checkpoints 表                        │
│                                                      │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│              SQLite 数据库                         │
│                                                      │
│  ┌──────────────────────────────────────────┐       │
│  │   checkpoints 表 (AI 状态快照)            │       │
│  │   - thread_id                            │       │
│  │   - checkpoint_id                        │       │
│  │   - checkpoint (JSON/二进制)             │       │
│  │   - layer_X_completed                    │       │
│  │   - analysis_dimension_reports           │       │
│  │   - concept_dimension_reports            │       │
│  │   - detailed_dimension_reports           │       │
│  │   - pause_after_step                     │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

### 状态保存流程

```
LangGraph 节点执行
  ↓
状态更新: state["layer_1_completed"] = True
  ↓
graph.update_state(config, updates)
  ↓
AsyncSqliteSaver.put(config, checkpoint)
  ↓
自动序列化 → checkpoints 表
  ↓
返回新 checkpoint_id
```

### 状态恢复流程

```
API: GET /api/planning/status/{session_id}
  ↓
config = {"configurable": {"thread_id": session_id}}
  ↓
graph.get_state(config)
  ↓
AsyncSqliteSaver.get(config)
  ↓
从 checkpoints 表读取完整状态
  ↓
返回 StateSnapshot
  ↓
提取状态值 (layer_X_completed, reports, etc.)
```

---

## 暂停/恢复机制

### 暂停流程

```
步进模式 (step_mode=True)
  ↓
层级完成 (layer_X_completed=True)
  ↓
PauseManagerNode 检测到暂停条件
  ↓
设置 state["pause_after_step"] = True
  ↓
路由到 END 终止执行
  ↓
后台执行检测到 pause_after_step
  ↓
生成 pause_event_key = f"pause_layer_{current_layer}"
  ↓
如果 pause_event_key 不在 sent_pause_events 中:
  ↓
发送 pause 事件
  ↓
sent_pause_events.add(pause_event_key)
  ↓
_set_session_value(session_id, "sent_pause_events", sent_pause_events)
  ↓
前端 REST 轮询检测到 pauseAfterStep=true
  ↓
显示审查 UI
```

**关键节点**: `src/nodes/tool_nodes.py:PauseManagerNode`
```python
class PauseManagerNode(BaseNode):
    def execute(self, state: StateDict) -> StateDict:
        layer_1_completed = state.get("layer_1_completed", False)
        layer_2_completed = state.get("layer_2_completed", False)
        layer_3_completed = state.get("layer_3_completed", False)
        any_layer_completed = layer_1_completed or layer_2_completed or layer_3_completed

        if state.get("step_mode", False) and any_layer_completed:
            logger.info(f"[暂停管理] 步进模式：检测到层级完成，设置pause_after_step=True")
            return {"pause_after_step": True}

        return {}
```

**关键路由**: `src/orchestration/main_graph.py:route_after_pause`
```python
def route_after_pause(state: VillagePlanningState) -> Literal["layer1_analysis", "layer2_concept", "layer3_detail", "end"]:
    step_mode = state.get("step_mode", False)
    any_layer_completed = state.get("layer_1_completed", False) or \
                          state.get("layer_2_completed", False) or \
                          state.get("layer_3_completed", False)

    if step_mode and any_layer_completed:
        logger.info("[主图-路由] 步进模式：检测到层级完成，终止执行以便前端触发审查")
        return "end"

    # 根据当前层级路由
    current_layer = state.get("current_layer", 1)
    if current_layer == 1:
        return "layer1_analysis"
    elif current_layer == 2:
        return "layer2_concept"
    else:
        return "layer3_detail"
```

### 恢复流程

```
用户点击"批准"
  ↓
POST /api/planning/review/{session_id}?action=approve
  ↓
清除 pause 标志:
  - initial_state["pause_after_step"] = False
  - session["sent_pause_events"].clear()
  ↓
推进 current_layer
  ↓
调用 _resume_graph_execution()
  ↓
继续执行 LangGraph
```

---

## LangGraph 状态图

### 状态定义

```python
class PlanningState(TypedDict):
    # 输入数据
    project_name: str
    village_data: str
    task_description: str
    step_mode: bool

    # 层级完成标志（由 AsyncSqliteSaver 管理）
    layer_1_completed: bool = False
    layer_2_completed: bool = False
    layer_3_completed: bool = False

    # 层级追踪
    previous_layer: int = 1
    current_layer: int = 1

    # 维度报告（由 AsyncSqliteSaver 管理）
    analysis_dimension_reports: Annotated[dict[str, str], add]
    concept_dimension_reports: Annotated[dict[str, str], add]
    detailed_dimension_reports: Annotated[dict[str, str], add]

    # 暂停相关（由 AsyncSqliteSaver 管理）
    pause_after_step: bool = False
    waiting_for_review: bool = False

    # 其他状态
    need_human_review: bool = False
    human_feedback: str | None = None
    need_revision: bool = False
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
设置 analysis_dimension_reports, layer_1_completed, previous_layer=1, current_layer=2
    ↓
AsyncSqliteSaver.put() → 自动保存
    ↓
ToolBridgeNode 检测到 step_mode + layer_1_completed
    ↓
路由到 PauseManagerNode
    ↓
设置 pause_after_step=True
    ↓
路由到 END (暂停)
    ↓
REST 轮询检测到 pauseAfterStep=true
    ↓
前端显示审查 UI
    ↓
用户批准
    ↓
清除 pause 标志，推进 current_layer
    ↓
恢复执行 → layer2_concept_node
```

---

## 统一规划器

### 基类设计

**文件**: `src/planners/unified_base_planner.py`

```python
class UnifiedBasePlanner(ABC):
    """
    统一规划器基类

    所有规划器继承此基类，确保一致的接口和行为
    """

    @abstractmethod
    async def plan_dimension(
        self,
        dimension_key: str,
        dimension_name: str,
        context: dict[str, Any]
    ) -> str:
        """
        规划单个维度

        Args:
            dimension_key: 维度键名（如 "location"）
            dimension_name: 维度名称（如 "区位分析"）
            context: 上下文信息（包含相关维度报告）

        Returns:
            维度规划报告
        """
        pass

    def get_relevant_context(
        self,
        dimension_key: str,
        all_reports: dict[str, str]
    ) -> dict[str, str]:
        """
        获取相关上下文

        Args:
            dimension_key: 当前维度键名
            all_reports: 所有维度报告

        Returns:
            相关维度报告字典
        """
        # 根据维度键名返回相关维度
        pass
```

### 实现示例

**文件**: `src/planners/generic_planner.py`

```python
class GenericPlanner(UnifiedBasePlanner):
    """通用规划器实现"""

    def __init__(self, llm: BaseLanguageModel):
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一个专业的村庄规划师..."),
            ("human", "{dimension_name}\n\n{context}")
        ])

    async def plan_dimension(
        self,
        dimension_key: str,
        dimension_name: str,
        context: dict[str, Any]
    ) -> str:
        # 获取相关上下文
        relevant_context = self.get_relevant_context(
            dimension_key,
            context.get("all_reports", {})
        )

        # 调用 LLM
        chain = self.prompt | self.llm
        result = await chain.ainvoke({
            "dimension_name": dimension_name,
            "context": json.dumps(relevant_context, ensure_ascii=False)
        })

        return result.content
```

---

## 状态筛选优化

### 优化目标

节省 40-60% LLM token 消耗

### 实现原理

**文件**: `src/planners/unified_base_planner.py`

```python
def get_relevant_context(
    self,
    dimension_key: str,
    all_reports: dict[str, str]
) -> dict[str, str]:
    """
    获取相关上下文（智能筛选）

    只返回与当前维度相关的维度报告，减少 token 消耗
    """
    # 维度相关性映射
    relevance_map = {
        "location": ["socio_economic", "traffic", "land_use"],
        "socio_economic": ["location", "villager_wishes", "public_services"],
        # ... 其他维度
    }

    relevant_keys = relevance_map.get(dimension_key, [])
    return {k: all_reports[k] for k in relevant_keys if k in all_reports}
```

### 效果对比

**优化前**:
- 传递所有 12 个维度报告
- Token 消耗：~50,000 tokens

**优化后**:
- 只传递 3-5 个相关维度报告
- Token 消耗：~20,000 tokens
- **节省：60%**

---

## 数据流总结

### 完整数据流

```
用户输入
  ↓
POST /api/planning/start
  ↓
main_graph.start()
  ↓
Layer 1: 12 个维度并行
  ↓
AsyncSqliteSaver.put() → checkpoints 表
  ↓
ToolBridgeNode → PauseManagerNode → END (暂停)
  ↓
REST 轮询读取状态 (pauseAfterStep=true)
  ↓
前端显示审查 UI
  ↓
用户批准 → 清除 pause 标志
  ↓
恢复执行 → Layer 2: 4 个维度并行
  ↓
AsyncSqliteSaver.put() → checkpoints 表
  ↓
REST 轮询读取状态
  ↓
前端显示流式文本
  ↓
Layer 3: 12 个维度并行
  ↓
AsyncSqliteSaver.put() → checkpoints 表
  ↓
REST 轮询读取状态
  ↓
前端显示流式文本
  ↓
完成
```

### 状态持久化流程

```
LangGraph 执行
  ↓
状态更新
  ↓
AsyncSqliteSaver.put()
  ↓
checkpoints 表
  ↓
REST 轮询
  ↓
前端更新 UI
```

### 暂停/恢复流程

```
步进模式 + 层级完成
  ↓
PauseManagerNode 设置 pause_after_step=True
  ↓
路由到 END
  ↓
后台执行检测暂停 → 发送 pause 事件
  ↓
_set_session_value 保存 sent_pause_events
  ↓
前端 REST 轮询检测到 pauseAfterStep=true
  ↓
显示审查 UI
  ↓
用户批准 → POST /api/planning/review/{id}?action=approve
  ↓
清除 pause 标志 → 恢复执行
```