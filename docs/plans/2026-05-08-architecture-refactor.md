# 架构重构：配置驱动与服务隔离

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 Village Planning Agent 重构为插件化、配置驱动、服务边界清晰的精简系统

**Architecture:**
- Phase 1: 配置外置（YAML）替代硬编码维度配置
- Phase 2: Agent 核心解耦，统一工具执行协议
- Phase 3: GIS/RAG 服务独立，统一 SSE 通信
- Phase 4: 前端简化，错误处理加固

**Tech Stack:** Python, FastAPI, LangGraph, Pydantic, YAML, React, Zustand

---

## Phase 1: 配置外置与领域模型抽象

### Task 1.1: 创建 YAML 配置文件

**Files:**
- Create: `config/planning_phases.yaml`

**Step 1: 创建配置目录**

```bash
mkdir -p config
```

**Step 2: 创建 YAML 配置文件**

```yaml
# config/planning_phases.yaml
phases:
  - id: layer1
    name: "现状分析"
    execution: parallel
    dimensions:
      - key: location
        name: "区位与对外交通分析"
        tools: []
        rag_query: "区位分析 交通"
        depends_on: []
      - key: socio_economic
        name: "社会经济分析"
        tools: ["population_model_v1"]
        rag_query: "人口 预测"
        depends_on: []
      - key: land_use
        name: "土地利用分析"
        tools: ["gis_coverage_calculator"]
        rag_query: "土地利用 标准"
        depends_on: []
      # ... 其他 Layer 1 维度

  - id: layer2
    name: "规划思路"
    execution: wave
    dimensions:
      - key: resource_endowment
        name: "资源禀赋分析"
        tools: []
        rag_query: "资源禀赋"
        depends_on: []
      - key: planning_positioning
        name: "规划定位分析"
        tools: []
        rag_query: "规划定位"
        depends_on: ["resource_endowment"]
      - key: development_goals
        name: "发展目标分析"
        tools: []
        rag_query: "发展目标"
        depends_on: ["resource_endowment", "planning_positioning"]
      - key: planning_strategies
        name: "规划策略分析"
        tools: []
        rag_query: "规划策略"
        depends_on: ["resource_endowment", "planning_positioning", "development_goals"]

  - id: layer3
    name: "详细规划"
    execution: wave
    dimensions:
      - key: industry
        name: "产业规划"
        tools: []
        rag_query: "产业规划 农村"
        depends_on: []
      # ... 其他 Layer 3 维度
```

**Step 3: 提交配置文件**

```bash
git add config/planning_phases.yaml
git commit -m "feat(config): add YAML-based planning phases configuration"
```

---

### Task 1.2: 实现配置加载器

**Files:**
- Create: `src/config/loader.py`
- Create: `tests/config/test_loader.py`

**Step 1: 编写配置加载器测试**

```python
# tests/config/test_loader.py
import pytest
from src.config.loader import load_config, PlanningConfig

def test_load_config_returns_planning_config():
    config = load_config("config/planning_phases.yaml")
    assert isinstance(config, PlanningConfig)

def test_config_has_three_phases():
    config = load_config("config/planning_phases.yaml")
    assert len(config.phases) == 3
```

**Step 2: 实现配置模型和加载器**

```python
# src/config/loader.py
from pydantic import BaseModel
from typing import List, Optional
import yaml

class DimensionConfig(BaseModel):
    key: str
    name: str
    tools: List[str] = []
    rag_query: str = ""
    depends_on: List[str] = []

class PhaseConfig(BaseModel):
    id: str
    name: str
    execution: str
    dimensions: List[DimensionConfig]

class PlanningConfig(BaseModel):
    phases: List[PhaseConfig]

def load_config(path: str = "config/planning_phases.yaml") -> PlanningConfig:
    with open(path, encoding="utf-8") as f:
        return PlanningConfig(**yaml.safe_load(f))
```

**Step 3: 提交**

```bash
git add src/config/loader.py tests/config/test_loader.py
git commit -m "feat(config): add Pydantic-based config loader"
```

---

### Task 1.3: 实现依赖计算器

**Files:**
- Create: `src/config/dependency_calculator.py`

**核心逻辑**：

```python
def calculate_waves(dimensions: List[Dict]) -> Dict[str, int]:
    """Wave = 1 + max(wave of dependencies)"""
    waves = {}
    for dim in dimensions:
        deps = dim.get("depends_on", [])
        if not deps:
            waves[dim["key"]] = 1
        else:
            waves[dim["key"]] = 1 + max(waves.get(d, 1) for d in deps)
    return waves
```

---

## Phase 2: Agent 核心解耦

### Task 2.1: 统一工具执行协议

**Files:**
- Modify: `src/tools/registry.py`

```python
class ToolResult(TypedDict):
    status: str  # "success" | "error" | "partial"
    data: Any
    error: Optional[str]

class Tool(Protocol):
    async def execute(self, context: dict) -> ToolResult:
        ...
```

---

### Task 2.2: 重构 ToolRegistry

```python
class ToolRegistry:
    @classmethod
    async def run(cls, name: str, context: dict) -> ToolResult:
        tool = cls._tools.get(name)
        if not tool:
            return ToolResult(status="error", error=f"Tool not found: {name}")
        try:
            return await tool.execute(context)
        except Exception as e:
            return ToolResult(status="error", error=str(e))
```

---

### Task 2.3: 创建通用分析节点

**Files:**
- Create: `src/orchestration/nodes/analyze_dimension_v2.py`

流程:
1. 从配置获取维度信息
2. 并行执行工具
3. 并行执行 RAG 检索
4. 组装 Prompt
5. 流式调用 LLM
6. 推送 SSE 事件

---

## Phase 3: 服务层重构

### Task 3.1: GIS 服务独立

```python
class GisService:
    async def fetch(self, village_name: str, types: List[str]) -> GisResult:
        # 优先级: 用户上传 > 缓存 > API > 兜底
```

### Task 3.2: RAG 服务独立

```python
class RagService:
    async def search(self, query: str, top_k: int = 3) -> RagResult:
```

### Task 3.3: 统一 SSE 通信

SSE 事件直接携带完整数据，取消 Signal-Fetch 模式。

---

## Phase 4: 前端简化

### Task 4.1: 状态管理精简

- 去除维度内容完整存储
- 报告以 Message 形式存储
- GIS 图层直接从 SSE 事件更新

---

## 验收标准

| 检查项 | 验证方式 |
|--------|----------|
| 配置外置 | YAML 加载成功 |
| 工具协议 | 单工具失败不阻断维度 |
| GIS 服务 | 数据源切换对 Agent 透明 |
| SSE 统一 | 前端无需发 REST 请求 |

---

**Plan saved. Two execution options:**

1. **Subagent-Driven (this session)** - Fresh subagent per task + review

2. **Parallel Session (separate)** - Open new session with executing-plans

**Which approach?**