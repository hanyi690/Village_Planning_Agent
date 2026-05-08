# 工具系统架构

本文档详细说明工具注册机制和Tool-Dimension绑定。

## 目录

- [ToolRegistry注册机制](#toolregistry注册机制)
- [工具分类](#工具分类)
- [Tool-Dimension绑定表](#tool-dimension绑定表)
- [工具执行流程](#工具执行流程)

---

## ToolRegistry注册机制

### 类设计

```python
# src/tools/registry.py
class ToolRegistry:
    """工具注册中心"""

    _tools: Dict[str, Callable] = {}
    _tool_metadata: Dict[str, ToolMetadata] = {}

    @classmethod
    def register(cls, name: str):
        """装饰器：注册工具"""
        def decorator(func: Callable) -> Callable:
            cls._tools[name] = func
            return func
        return decorator

    @classmethod
    def execute_tool(cls, name: str, context: Dict) -> str:
        """执行工具并返回结果"""
        tool_func = cls._tools.get(name)
        if not tool_func:
            raise ValueError(f"工具不存在: {name}")
        return tool_func(context)
```

### ToolMetadata

```python
@dataclass
class ToolMetadata:
    """工具元数据"""
    name: str
    description: str
    input_schema: Optional[Type[BaseModel]] = None
    display_name: Optional[str] = None
    parameters: Optional[Dict] = None
```

---

## 工具分类

| 类别 | 工具 | 功能 |
|------|------|------|
| GIS分析 | `gis_coverage_calculator` | 地类覆盖率计算 |
| GIS分析 | `accessibility_analysis` | 可达性分析 |
| GIS分析 | `poi_search` | POI搜索 |
| GIS分析 | `wfs_data_fetch` | WFS数据获取 |
| 人口预测 | `population_model_v1` | 人口预测模型 |
| 知识检索 | `knowledge_search` | RAG知识检索 |

---

## Tool-Dimension绑定表

### Layer 1绑定

| 维度 | 工具 | 说明 |
|------|------|------|
| socio_economic | population_model_v1 | 人口预测支撑社会经济分析 |
| natural_environment | wfs_data_fetch | WFS获取自然环境数据 |
| land_use | gis_coverage_calculator | 计算土地利用覆盖率 |
| traffic | accessibility_analysis | 道路可达性分析 |
| public_services | poi_search | POI搜索公共服务设施 |

### Layer 3绑定

| 维度 | 工具 | 说明 |
|------|------|------|
| spatial_structure | planning_vectorizer | 规划空间结构矢量化 |
| traffic_planning | isochrone_analysis | 等时圈分析 |
| public_service | facility_validator | 设施配置验证 |
| ecological | ecological_sensitivity | 生态敏感性分析 |

### 配置示例

```python
# src/config/dimension_metadata.py
"socio_economic": {
    "key": "socio_economic",
    "name": "社会经济分析",
    "layer": 1,
    "tool": "population_model_v1",  # 绑定工具
    "rag_enabled": True,
}
```

---

## 工具执行流程

### GenericPlanner中的工具钩子

```python
# src/planners/generic_planner.py
class GenericPlanner:
    def _execute_tool_hook(self, state: dict) -> str:
        """执行配置的tool字段绑定的工具"""
        if self.tool_name:
            context = self._prepare_tool_context(state)
            result = ToolRegistry.execute_tool(self.tool_name, context)
            return f"\n【参考数据 - {self.tool_name}】\n{result}\n"
        return ""

    def build_prompt(self, state: dict) -> str:
        """构建Prompt时自动注入工具输出"""
        params = self._prepare_prompt_params(state)
        params["tool_output"] = self._execute_tool_hook(state)
        return self.prompt_template.format(**params)
```

### 执行序列

```
GenericPlanner.execute()
    ↓
build_prompt()
    ↓
_execute_tool_hook()
    ↓
ToolRegistry.execute_tool(tool_name, context)
    ↓
工具函数执行 -> 返回结果
    ↓
结果注入到Prompt
    ↓
LLM调用
```

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 工具注册 | `src/tools/registry.py` |
| 内置工具 | `src/tools/builtin/__init__.py` |
| 人口预测 | `src/tools/builtin/population.py` |
| 工具绑定配置 | `src/config/dimension_metadata.py` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [03-layer-dimension](./03-layer-dimension.md) - 维度工具绑定详情
- [08-rag-system](./08-rag-system.md) - 知识检索工具
- [02-agent-core](./02-agent-core.md) - GenericPlanner设计