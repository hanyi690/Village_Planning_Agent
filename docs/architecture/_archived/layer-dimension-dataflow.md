# 维度与层级数据流

本文档详细说明三层规划架构、维度依赖关系和数据传递机制。

## 目录

- [三层架构概览](#三层架构概览)
- [维度元数据配置](#维度元数据配置)
- [依赖链机制](#依赖链机制)
- [数据传递流程](#数据传递流程)
- [依赖关系图](#依赖关系图)

---

## 三层架构概览

### 架构说明

村庄规划采用三层递进式架构:

| 层级 | 名称 | 维度数 | 执行模式 | 说明 |
|------|------|--------|----------|------|
| Layer 1 | 现状分析 | 12 | Map-Reduce 并行 | 分析村庄现状各方面 |
| Layer 2 | 规划思路 | 4 | Wave 波次执行 | 确定规划方向和策略 |
| Layer 3 | 详细规划 | 12 | Wave 波次执行 | 制定具体规划方案 |

### Layer 1: 现状分析

12个维度，无内部依赖，可完全并行执行:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Layer 1: 现状分析                         │
├─────────────────────────────────────────────────────────────────┤
│ location         │ 区位与对外交通分析                              │
│ socio_economic   │ 社会经济分析                                    │
│ villager_wishes  │ 村民意愿与诉求分析                              │
│ superior_planning│ 上位规划与政策导向分析                          │
│ natural_environment│ 自然环境分析                                  │
│ land_use         │ 土地利用分析                                    │
│ traffic          │ 道路交通分析                                    │
│ public_services  │ 公共服务设施分析                                │
│ infrastructure   │ 基础设施分析                                    │
│ ecological_green │ 生态绿地分析                                    │
│ architecture     │ 建筑分析                                        │
│ historical_culture│ 历史文化与乡愁保护分析                         │
└─────────────────────────────────────────────────────────────────┘
          ↓ (全部完成后进入 Layer 2)
```

### Layer 2: 规划思路

4个维度，存在依赖关系，按 Wave 执行：

```
┌─────────────────────────────────────────────────────────────────┐
│                        Layer 2: 规划思路                          │
├─────────────────────────────────────────────────────────────────┤
│ Wave 1:                                                          │
│   resource_endowment    │ 资源禀赋分析 (无同层依赖)              │
│                        │                                          │
│ Wave 2:                                                          │
│   planning_positioning  │ 规划定位分析 (依赖 resource_endowment)  │
│                        │                                          │
│ Wave 3:                                                          │
│   development_goals     │ 发展目标分析 (依赖 resource_endowment,  │
│                        │                   planning_positioning)   │
│                        │                                          │
│ Wave 4:                                                          │
│   planning_strategies   │ 规划策略分析 (依赖前3个维度)            │
└─────────────────────────────────────────────────────────────────┘
          ↓ (全部完成后进入 Layer 3)
```

| Wave | 维度 | 依赖关系 |
|------|------|----------|
| Wave 1 | resource_endowment | 无同层依赖 |
| Wave 2 | planning_positioning | 依赖 resource_endowment |
| Wave 3 | development_goals | 依赖 resource_endowment, planning_positioning |
| Wave 4 | planning_strategies | 依赖前3个维度 |

### Layer 3: 详细规划

12个维度，部分存在依赖关系:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Layer 3: 详细规划                          │
├─────────────────────────────────────────────────────────────────┤
│ Wave 1:                                                          │
│   industry             │ 产业规划                                 │
│   spatial_structure    │ 空间结构规划                             │
│   land_use_planning    │ 土地利用规划                             │
│   settlement_planning  │ 居民点规划                               │
│   traffic_planning     │ 道路交通规划                             │
│   public_service       │ 公共服务设施规划                         │
│   infrastructure_planning│ 基础设施规划                           │
│   ecological           │ 生态绿地规划                             │
│   disaster_prevention  │ 防震减灾规划                             │
│   heritage             │ 历史文保规划                             │
│   landscape            │ 村庄风貌指引                             │
│                        │                                          │
│ Wave 2:                                                          │
│   project_bank         │ 建设项目库 (依赖上述所有维度)            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 维度元数据配置

### DIMENSIONS_METADATA 结构

维度配置定义在 `src/config/dimension_metadata.py`:

```python
DIMENSIONS_METADATA: Dict[str, Dict[str, Any]] = {
    # Layer 1 示例
    "location": {
        "key": "location",
        "name": "区位与对外交通分析",
        "layer": 1,
        "dependencies": [],  # Layer 1 无依赖
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄的地理位置、交通区位、区域关系等",
        "prompt_key": "location_analysis"
    },

    # Layer 2 示例 - 有依赖
    "planning_positioning": {
        "key": "planning_positioning",
        "name": "规划定位分析",
        "layer": 2,
        "dependencies": {
            "layer1_analyses": ["location", "socio_economic", "superior_planning"],
            "layer2_concepts": ["resource_endowment"]
        },
        "result_key": "concept_result",
        "rag_enabled": False,
        "tool": None,
        "description": "确定村庄的发展定位",
        "prompt_key": "planning_positioning"
    },

    # Layer 3 示例 - 有工具绑定
    "socio_economic": {
        "key": "socio_economic",
        "name": "社会经济分析",
        "layer": 1,
        "dependencies": [],
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": "population_model_v1",  # 绑定人口预测工具
        "description": "分析村庄人口、经济、产业等社会经济状况",
        "prompt_key": "socio_economic_analysis"
    },
}
```

### 依赖配置格式

依赖配置使用结构化格式:

```python
# 跨层依赖示例
"dependencies": {
    "layer1_analyses": ["natural_environment", "land_use", "socio_economic"],  # 依赖 Layer 1 维度
    "layer2_concepts": ["resource_endowment"],  # 依赖 Layer 2 维度
    "layer3_plans": ["industry", "spatial_structure"]  # 依赖 Layer 3 维度（同层依赖）
}
```

### 工具绑定

通过 `tool` 字段绑定工具:

```python
# 带工具的维度配置
"traffic": {
    "key": "traffic",
    "name": "道路交通分析",
    "layer": 1,
    "tool": "accessibility_analysis",  # 可达性分析工具
    # ...
}
```

### RAG 启用

通过 `rag_enabled` 字段控制是否启用 RAG:

```python
# Layer 3 中法规相关的维度启用 RAG
"land_use_planning": {
    "key": "land_use_planning",
    "name": "土地利用规划",
    "layer": 3,
    "rag_enabled": True,  # 关键维度：涉及法规条文和技术指标
    # ...
}
```

---

## 依赖链机制

### 跨层依赖定义

跨层依赖定义了维度对其他层级维度的依赖:

```python
# src/config/dimension_metadata.py
def get_full_dependency_chain() -> Dict[str, Dict[str, Any]]:
    """
    获取完整的三层依赖关系映射

    自动计算 wave 值：基于同层内部依赖关系拓扑排序

    Returns:
        {dimension_key: {
            layer1_analyses: [...],
            layer2_concepts: [...],
            layer3_plans: [...],
            wave: N,
            depends_on_same_layer: [...]
        }}
    """
    chain = {}

    for key, config in DIMENSIONS_METADATA.items():
        layer = config.get("layer")
        deps = config.get("dependencies", {})

        if layer == 3:
            depends_on_same_layer = deps.get("layer3_plans", [])
        elif layer == 2:
            depends_on_same_layer = deps.get("layer2_concepts", [])
        else:
            depends_on_same_layer = []

        chain[key] = {
            "layer": layer,
            "layer1_analyses": deps.get("layer1_analyses", []) if layer >= 2 else [],
            "layer2_concepts": deps.get("layer2_concepts", []) if layer == 3 else [],
            "layer3_plans": deps.get("layer3_plans", []) if layer == 3 else [],
            "depends_on_same_layer": depends_on_same_layer,
            "wave": 1  # 默认值，后续自动计算
        }

    # 自动计算每个维度的 wave
    for key in chain:
        chain[key]["wave"] = _calculate_wave(key, chain)

    return chain
```

### 同层依赖和 Wave 计算

Wave 值基于同层依赖关系拓扑排序计算:

```python
def _calculate_wave(dimension_key: str, chain: Dict[str, Dict[str, Any]]) -> int:
    """
    递归计算维度的执行波次

    Wave = 1 + max(wave of dependencies within same layer)
    """
    if dimension_key not in chain:
        return 1

    deps = chain[dimension_key]
    same_layer_deps = deps.get("depends_on_same_layer", [])

    if not same_layer_deps:
        return 1

    # 递归计算依赖的 wave
    max_dep_wave = 0
    for dep_key in same_layer_deps:
        if dep_key in chain:
            dep_wave = chain[dep_key].get("wave", 1)
            if dep_wave == 1:
                dep_wave = _calculate_wave(dep_key, chain)
                chain[dep_key]["wave"] = dep_wave
            max_dep_wave = max(max_dep_wave, dep_wave)

    return max_dep_wave + 1
```

### 影响树计算

当维度修改时，需要计算级联更新的影响范围:

```python
def get_impact_tree(dimension_key: str) -> Dict[int, List[str]]:
    """
    获取维度修改后的影响树（级联更新范围）

    当一个维度被修改后，需要级联更新所有依赖它的下游维度。
    返回按 wave 分组的维度列表，支持并行调度：
    - Wave 1: 直接依赖该维度的下游维度（可并行）
    - Wave 2: 依赖 Wave 1 维度的下游维度（可并行）
    - ...

    Example:
        >>> get_impact_tree("natural_environment")
        {
            1: ["resource_endowment", "ecological", "spatial_structure"],
            2: ["planning_positioning", "planning_strategies"],
            3: ["development_goals", "project_bank"]
        }
    """
    impact_tree: Dict[int, List[str]] = {}
    visited = {dimension_key}
    current_wave_dims = [dimension_key]
    wave = 0

    while current_wave_dims:
        next_wave_dims = []
        for dim in current_wave_dims:
            downstream = get_downstream_dependencies(dim)
            for dep_dim in downstream:
                if dep_dim not in visited:
                    visited.add(dep_dim)
                    next_wave_dims.append(dep_dim)

        if next_wave_dims:
            wave += 1
            impact_tree[wave] = next_wave_dims

        current_wave_dims = next_wave_dims

    return impact_tree
```

### 下游依赖查询

```python
_DOWNSTREAM_DEPENDENCIES_CACHE = None

def get_downstream_dependencies(dimension_key: str) -> List[str]:
    """
    获取依赖指定维度的所有下游维度（反向依赖）

    用于维度修复时确定需要级联更新的下游维度。
    """
    global _DOWNSTREAM_DEPENDENCIES_CACHE

    if _DOWNSTREAM_DEPENDENCIES_CACHE is None:
        cache = {}
        for key, config in DIMENSIONS_METADATA.items():
            deps = config.get("dependencies", {})

            if isinstance(deps, list):
                continue

            for dep in deps.get("layer1_analyses", []):
                if dep not in cache:
                    cache[dep] = []
                cache[dep].append(key)

            for dep in deps.get("layer2_concepts", []):
                if dep not in cache:
                    cache[dep] = []
                cache[dep].append(key)

            for dep in deps.get("layer3_plans", []):
                if dep not in cache:
                    cache[dep] = []
                cache[dep].append(key)

        _DOWNSTREAM_DEPENDENCIES_CACHE = cache

    return _DOWNSTREAM_DEPENDENCIES_CACHE.get(dimension_key, [])
```

---

## 数据传递流程

### create_dimension_state 构建子状态

维度分析前，需要构建包含依赖数据的子状态:

```python
# src/orchestration/nodes/dimension_node.py
def create_dimension_state(
    dimension_key: str,
    parent_state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    为 Send API 创建维度分析子状态

    包含:
    - 维度标识信息
    - 依赖的上下文数据
    - 执行配置
    """
    config = get_dimension_config(dimension_key)
    if not config:
        raise ValueError(f"Unknown dimension: {dimension_key}")

    # 获取依赖的上下文
    dependencies = config.get("dependencies", {})
    reports = parent_state.get("reports", {})

    # 构建 prompt 上下文
    prompt_context = _build_prompt_context(
        dimension_key=dimension_key,
        dependencies=dependencies,
        reports=reports,
        parent_state=parent_state
    )

    return {
        "dimension_key": dimension_key,
        "dimension_name": config.get("name", dimension_key),
        "layer": config.get("layer", 1),
        "result_key": config.get("result_key", "analysis_result"),
        "prompt_context": prompt_context,
        "session_id": parent_state.get("session_id", ""),
        "project_name": parent_state.get("project_name", ""),
        "config": parent_state.get("config", {}),
        "is_revision": False,
    }
```

### reports 状态传递机制

`reports` 是跨层级数据传递的核心:

```python
# 状态定义
reports: Dict[str, Dict[str, str]]  # {layer1: {dim: content}, layer2: {...}, layer3: {...}}

# 维度完成后更新
def analyze_dimension_for_send(state: Dict[str, Any]) -> Dict[str, Any]:
    # ... 执行分析

    return {
        "dimension_results": [{
            "dimension_key": dimension_key,
            "result": result_content,
            "success": True,
        }],
        "sse_events": [/* SSE 事件列表 */],
    }

# 结果收集时合并到 reports
async def collect_layer_results(state: Dict[str, Any]) -> Dict[str, Any]:
    dimension_results = state.get("dimension_results", [])
    reports = dict(state.get("reports", {}))
    layer_key = f"layer{layer}"

    for result in dimension_results:
        dim_key = result.get("dimension_key")
        if result.get("success") and dim_key:
            reports[layer_key][dim_key] = result.get("result", "")

    return {"reports": reports}
```

### completed_dimensions 追踪

`completed_dimensions` 追踪已完成的维度:

```python
# 状态定义
completed_dimensions: Dict[str, List[str]]  # {layer1: [dim1, dim2, ...], ...}

# 完成检查
def _check_layer_completion(state: Dict[str, Any], layer: int) -> Union[List[Send], str]:
    completed = state.get("completed_dimensions", {})
    layer_key = f"layer{layer}"
    completed_dims = completed.get(layer_key, [])
    total_dims = get_layer_dimensions(layer)

    pending = [d for d in total_dims if d not in completed_dims]

    if not pending:
        return "collect_results"  # 层级完成

    return [Send("analyze_dimension", create_dimension_state(d, state)) for d in pending]
```

### Revision 时的级联更新

当用户修改维度时，触发级联更新:

```python
# src/orchestration/nodes/revision_node.py
async def revision_node(state: UnifiedPlanningState) -> Dict[str, Any]:
    target_dimensions = state.get("revision_target_dimensions", [])

    # 获取需要更新的所有维度
    impact_tree = get_revision_wave_dimensions(
        target_dimensions=target_dimensions,
        completed_dimensions=get_all_completed_dimensions(state)
    )

    # 按波次执行更新
    for wave in sorted(impact_tree.keys()):
        wave_results = []
        for dim_key in impact_tree[wave]:
            result = await analyze_dimension_revision(state, dim_key)
            wave_results.append(result)

        # 等待当前波次完成
        # ...

    return {
        "need_revision": False,
        "pause_after_step": True,
    }
```

---

## 详细跨层依赖关系

### Layer 2 维度依赖 Layer 1 详情

每个 Layer 2 维度依赖特定的 Layer 1 分析结果：

| Layer 2 维度 | 依赖的 Layer 1 维度 | 说明 |
|-------------|-------------------|------|
| **resource_endowment** | natural_environment, land_use, socio_economic, historical_culture, architecture, public_services | 综合分析村庄资源，需要自然环境、土地、社会经济、历史文化、建筑、公服等现状数据 |
| **planning_positioning** | location, socio_economic, superior_planning | 确定发展定位需要区位、社会经济、上位规划信息 |
| **development_goals** | socio_economic, superior_planning | 制定目标依赖社会经济数据和上位规划要求 |
| **planning_strategies** | traffic, infrastructure | 规划策略需要道路交通和基础设施分析支撑 |

### Layer 2 同层依赖详情

| Layer 2 维度 | 同层依赖 | Wave |
|-------------|---------|------|
| **resource_endowment** | 无 | 1 |
| **planning_positioning** | resource_endowment | 2 |
| **development_goals** | resource_endowment, planning_positioning | 3 |
| **planning_strategies** | resource_endowment, planning_positioning, development_goals | 4 |

```
依赖链：
natural_environment ─┐
land_use ─┤
socio_economic ─┤──────────► resource_endowment (Wave 1)
historical_culture ─┤              │
architecture ─┤                    ↓
public_services ─┘        planning_positioning (Wave 2)
                                  │
location ─────────────────────────┤
socio_economic ───────────────────┤
superior_planning ────────────────┤
                                  ↓
                          development_goals (Wave 3)
                                  │
traffic ──────────────────────────┤
infrastructure ───────────────────┤
                                  ↓
                          planning_strategies (Wave 4)
```

---

### Layer 3 维度依赖详情

每个 Layer 3 维度依赖特定的 Layer 1 和 Layer 2 结果：

| Layer 3 维度 | Layer 1 依赖 | Layer 2 依赖 | Wave |
|-------------|-------------|-------------|------|
| **industry** | socio_economic, land_use | resource_endowment, planning_positioning, planning_strategies | 1 |
| **spatial_structure** | natural_environment, land_use, traffic, architecture | planning_positioning, planning_strategies | 1 |
| **land_use_planning** | land_use, natural_environment | planning_positioning, planning_strategies | 1 |
| **settlement_planning** | architecture, infrastructure, land_use | planning_strategies | 1 |
| **traffic_planning** | traffic, land_use | planning_strategies | 1 |
| **public_service** | public_services, socio_economic | planning_strategies | 1 |
| **infrastructure_planning** | infrastructure, natural_environment | planning_strategies | 1 |
| **ecological** | natural_environment, ecological_green, land_use | planning_strategies | 1 |
| **disaster_prevention** | natural_environment, infrastructure | planning_strategies | 1 |
| **heritage** | historical_culture, architecture | planning_strategies | 1 |
| **landscape** | architecture, historical_culture, ecological_green | planning_strategies | 1 |
| **project_bank** | 无跨层依赖 | 无跨层依赖 | 2（依赖上述11个） |

### Layer 3 同层依赖

只有 **project_bank** 依赖其他 Layer 3 维度：

```python
"project_bank": {
    "dependencies": {
        "layer3_plans": [
            "industry",
            "spatial_structure",
            "land_use_planning",
            "settlement_planning",
            "traffic_planning",
            "public_service",
            "infrastructure_planning",
            "ecological",
            "disaster_prevention",
            "heritage",
            "landscape"
        ]
    }
}
```

### Layer 3 依赖来源分析

统计各 Layer 1 维度被 Layer 3 引用的次数：

| Layer 1 维度 | 被 Layer 3 引用次数 | 引用的 Layer 3 维度 |
|-------------|-------------------|-------------------|
| natural_environment | 5 | spatial_structure, land_use_planning, infrastructure_planning, ecological, disaster_prevention |
| land_use | 4 | industry, spatial_structure, land_use_planning, settlement_planning, traffic_planning |
| socio_economic | 2 | industry, public_service |
| architecture | 4 | spatial_structure, settlement_planning, heritage, landscape |
| traffic | 2 | spatial_structure, traffic_planning |
| infrastructure | 3 | settlement_planning, infrastructure_planning, disaster_prevention |
| public_services | 1 | public_service |
| ecological_green | 2 | ecological, landscape |
| historical_culture | 2 | heritage, landscape |

---

## 依赖关系图

### 完整三层依赖关系图

```mermaid
graph TB
    subgraph Layer1["Layer 1: 现状分析 (12维度并行)"]
        L1_loc[location<br/>区位交通]
        L1_se[socio_economic<br/>社会经济]
        L1_vw[villager_wishes<br/>村民诉求]
        L1_sp[superior_planning<br/>上位规划]
        L1_ne[natural_environment<br/>自然环境]
        L1_lu[land_use<br/>土地利用]
        L1_tr[traffic<br/>道路交通]
        L1_ps[public_services<br/>公共服务]
        L1_if[infrastructure<br/>基础设施]
        L1_eg[ecological_green<br/>生态绿地]
        L1_ar[architecture<br/>建筑]
        L1_hc[historical_culture<br/>历史文化]
    end

    subgraph Layer2["Layer 2: 规划思路 (4波次)"]
        L2_re[resource_endowment<br/>资源禀赋<br/>Wave 1]
        L2_pp[planning_positioning<br/>规划定位<br/>Wave 2]
        L2_dg[development_goals<br/>发展目标<br/>Wave 3]
        L2_pst[planning_strategies<br/>规划策略<br/>Wave 4]
    end

    subgraph Layer3["Layer 3: 详细规划 (2波次)"]
        L3_ind[industry<br/>产业规划]
        L3_ss[spatial_structure<br/>空间结构]
        L3_lup[land_use_planning<br/>土地利用规划]
        L3_set[settlement_planning<br/>居民点规划]
        L3_trp[traffic_planning<br/>道路交通规划]
        L3_pub[public_service<br/>公共服务规划]
        L3_ifp[infrastructure_planning<br/>基础设施规划]
        L3_eco[ecological<br/>生态绿地规划]
        L3_dp[disaster_prevention<br/>防震减灾]
        L3_her[heritage<br/>历史文保]
        L3_lsc[landscape<br/>村庄风貌]
        L3_pb[project_bank<br/>项目库<br/>Wave 2]
    end

    %% Layer 1 -> Layer 2 详细依赖
    L1_ne --> L2_re
    L1_lu --> L2_re
    L1_se --> L2_re
    L1_hc --> L2_re
    L1_ar --> L2_re
    L1_ps --> L2_re

    L1_loc --> L2_pp
    L1_se --> L2_pp
    L1_sp --> L2_pp
    L2_re --> L2_pp

    L1_se --> L2_dg
    L1_sp --> L2_dg
    L2_re --> L2_dg
    L2_pp --> L2_dg

    L1_tr --> L2_pst
    L1_if --> L2_pst
    L2_re --> L2_pst
    L2_pp --> L2_pst
    L2_dg --> L2_pst

    %% Layer 1+2 -> Layer 3 详细依赖
    L1_se --> L3_ind
    L1_lu --> L3_ind
    L2_re --> L3_ind
    L2_pp --> L3_ind
    L2_pst --> L3_ind

    L1_ne --> L3_ss
    L1_lu --> L3_ss
    L1_tr --> L3_ss
    L1_ar --> L3_ss
    L2_pp --> L3_ss
    L2_pst --> L3_ss

    L1_lu --> L3_lup
    L1_ne --> L3_lup
    L2_pp --> L3_lup
    L2_pst --> L3_lup

    L1_ar --> L3_set
    L1_if --> L3_set
    L1_lu --> L3_set
    L2_pst --> L3_set

    L1_tr --> L3_trp
    L1_lu --> L3_trp
    L2_pst --> L3_trp

    L1_ps --> L3_pub
    L1_se --> L3_pub
    L2_pst --> L3_pub

    L1_if --> L3_ifp
    L1_ne --> L3_ifp
    L2_pst --> L3_ifp

    L1_ne --> L3_eco
    L1_eg --> L3_eco
    L1_lu --> L3_eco
    L2_pst --> L3_eco

    L1_ne --> L3_dp
    L1_if --> L3_dp
    L2_pst --> L3_dp

    L1_hc --> L3_her
    L1_ar --> L3_her
    L2_pst --> L3_her

    L1_ar --> L3_lsc
    L1_hc --> L3_lsc
    L1_eg --> L3_lsc
    L2_pst --> L3_lsc

    %% Layer 3 同层依赖 - project_bank
    L3_ind --> L3_pb
    L3_ss --> L3_pb
    L3_lup --> L3_pb
    L3_set --> L3_pb
    L3_trp --> L3_pb
    L3_pub --> L3_pb
    L3_ifp --> L3_pb
    L3_eco --> L3_pb
    L3_dp --> L3_pb
    L3_her --> L3_pb
    L3_lsc --> L3_pb
```

### Layer 2 波次执行图

```mermaid
graph LR
    subgraph Wave1["Wave 1"]
        W1_1[resource_endowment<br/>依赖6个L1维度]
    end

    subgraph Wave2["Wave 2"]
        W2_1[planning_positioning<br/>依赖L1+resource_endowment]
    end

    subgraph Wave3["Wave 3"]
        W3_1[development_goals<br/>依赖L1+前2个L2]
    end

    subgraph Wave4["Wave 4"]
        W4_1[planning_strategies<br/>依赖L1+前3个L2]
    end

    W1_1 --> W2_1
    W1_1 --> W3_1
    W2_1 --> W3_1
    W1_1 --> W4_1
    W2_1 --> W4_1
    W3_1 --> W4_1
```

### Layer 3 波次执行图

```mermaid
graph TB
    subgraph Wave1["Wave 1 (11维度并行)"]
        W1_1[industry]
        W1_2[spatial_structure]
        W1_3[land_use_planning]
        W1_4[settlement_planning]
        W1_5[traffic_planning]
        W1_6[public_service]
        W1_7[infrastructure_planning]
        W1_8[ecological]
        W1_9[disaster_prevention]
        W1_10[heritage]
        W1_11[landscape]
    end

    subgraph Wave2["Wave 2"]
        W2_1[project_bank<br/>依赖上述11个]
    end

    W1_1 --> W2_1
    W1_2 --> W2_1
    W1_3 --> W2_1
    W1_4 --> W2_1
    W1_5 --> W2_1
    W1_6 --> W2_1
    W1_7 --> W2_1
    W1_8 --> W2_1
    W1_9 --> W2_1
    W1_10 --> W2_1
    W1_11 --> W2_1
```

---

## 影响树示例

当修改某维度时，需要级联更新所有下游维度。以下是典型维度的影响树：

### natural_environment 修改的影响树

```python
# 修改 natural_environment 会触发以下级联更新
get_impact_tree("natural_environment") = {
    1: ["resource_endowment", "spatial_structure", "land_use_planning",
        "infrastructure_planning", "ecological", "disaster_prevention"],
    2: ["planning_positioning", "planning_strategies"],
    3: ["development_goals", "project_bank"]
}
```

**影响分析**：
- Wave 1: 6个维度直接依赖 natural_environment
- Wave 2: planning_positioning（通过 resource_endowment）和 planning_strategies
- Wave 3: development_goals 和 project_bank

### socio_economic 修改的影响树

```python
get_impact_tree("socio_economic") = {
    1: ["resource_endowment", "planning_positioning", "development_goals",
        "industry", "public_service"],
    2: ["planning_strategies", "project_bank"],
    3: ["project_bank"]  # 通过 industry/public_service
}
```

**影响分析**：
- Wave 1: 5个维度直接依赖 socio_economic
- Wave 2: planning_strategies（通过前序 L2 维度）
- Wave 3: project_bank

### planning_strategies 修改的影响树

```python
get_impact_tree("planning_strategies") = {
    1: ["industry", "spatial_structure", "land_use_planning", "settlement_planning",
        "traffic_planning", "public_service", "infrastructure_planning",
        "ecological", "disaster_prevention", "heritage", "landscape"],
    2: ["project_bank"]
}
```

**影响分析**：
- Wave 1: 11个 Layer 3 维度全部依赖 planning_strategies
- Wave 2: project_bank 依赖上述所有维度

---

## 关键文件路径

| 功能 | 文件路径 | 关键函数 |
|------|----------|----------|
| 维度元数据定义 | `src/config/dimension_metadata.py` | `DIMENSIONS_METADATA` |
| 完整依赖链计算 | `src/config/dimension_metadata.py` | `get_full_dependency_chain` |
| Wave拓扑排序 | `src/config/dimension_metadata.py` | `_calculate_wave` |
| 影响树计算 | `src/config/dimension_metadata.py` | `get_impact_tree` |
| 修订波次维度 | `src/config/dimension_metadata.py` | `get_revision_wave_dimensions` |
| 下游依赖查询 | `src/config/dimension_metadata.py` | `get_downstream_dependencies` |
| 层级维度列表 | `src/config/dimension_metadata.py` | `get_layer_dimensions` |
| 波次维度列表 | `src/config/dimension_metadata.py` | `get_dimensions_by_wave` |
| 维度状态创建 | `src/orchestration/nodes/dimension_node.py` | `create_dimension_state` |
| 状态定义 | `src/orchestration/state.py` | `UnifiedPlanningState` |
| 规划路由 | `src/orchestration/routing.py` | `route_by_phase` |
| 修订节点 | `src/orchestration/nodes/revision_node.py` | `revision_node` |
| 报告筛选辅助 | `src/config/dimension_metadata.py` | `filter_reports_by_dependency` |

---

## 28维度完整配置参考

### Layer 1 完整配置

| 维度键 | 名称 | 工具 | RAG | 依赖 |
|--------|------|------|-----|------|
| location | 区位与对外交通分析 | - | ✓ | [] |
| socio_economic | 社会经济分析 | population_model_v1 | ✓ | [] |
| villager_wishes | 村民意愿与诉求分析 | - | ✓ | [] |
| superior_planning | 上位规划与政策导向分析 | - | ✓ | [] |
| natural_environment | 自然环境分析 | wfs_data_fetch | ✓ | [] |
| land_use | 土地利用分析 | gis_coverage_calculator | ✓ | [] |
| traffic | 道路交通分析 | accessibility_analysis | ✓ | [] |
| public_services | 公共服务设施分析 | poi_search | ✓ | [] |
| infrastructure | 基础设施分析 | - | ✓ | [] |
| ecological_green | 生态绿地分析 | - | ✓ | [] |
| architecture | 建筑分析 | - | ✓ | [] |
| historical_culture | 历史文化与乡愁保护分析 | - | ✓ | [] |

### Layer 2 完整配置

| 维度键 | 名称 | Wave | L1依赖 | L2同层依赖 |
|--------|------|------|--------|-----------|
| resource_endowment | 资源禀赋分析 | 1 | natural_environment, land_use, socio_economic, historical_culture, architecture, public_services | [] |
| planning_positioning | 规划定位分析 | 2 | location, socio_economic, superior_planning | resource_endowment |
| development_goals | 发展目标分析 | 3 | socio_economic, superior_planning | resource_endowment, planning_positioning |
| planning_strategies | 规划策略分析 | 4 | traffic, infrastructure | resource_endowment, planning_positioning, development_goals |

### Layer 3 完整配置

| 维度键 | 名称 | Wave | L1依赖 | L2依赖 | L3同层依赖 |
|--------|------|------|--------|--------|-----------|
| industry | 产业规划 | 1 | socio_economic, land_use | resource_endowment, planning_positioning, planning_strategies | [] |
| spatial_structure | 空间结构规划 | 1 | natural_environment, land_use, traffic, architecture | planning_positioning, planning_strategies | [] |
| land_use_planning | 土地利用规划 | 1 | land_use, natural_environment | planning_positioning, planning_strategies | [] |
| settlement_planning | 居民点规划 | 1 | architecture, infrastructure, land_use | planning_strategies | [] |
| traffic_planning | 道路交通规划 | 1 | traffic, land_use | planning_strategies | [] |
| public_service | 公共服务设施规划 | 1 | public_services, socio_economic | planning_strategies | [] |
| infrastructure_planning | 基础设施规划 | 1 | infrastructure, natural_environment | planning_strategies | [] |
| ecological | 生态绿地规划 | 1 | natural_environment, ecological_green, land_use | planning_strategies | [] |
| disaster_prevention | 防震减灾规划 | 1 | natural_environment, infrastructure | planning_strategies | [] |
| heritage | 历史文保规划 | 1 | historical_culture, architecture | planning_strategies | [] |
| landscape | 村庄风貌指引 | 1 | architecture, historical_culture, ecological_green | planning_strategies | [] |
| project_bank | 建设项目库 | 2 | - | - | industry, spatial_structure, land_use_planning, settlement_planning, traffic_planning, public_service, infrastructure_planning, ecological, disaster_prevention, heritage, landscape |

---

## 相关文档

- [Agent核心实现](./agent-core-implementation.md) - Router Agent 架构
- [工具系统实现](./tool-system-implementation.md) - Tool-Dimension 绑定
- [前端状态管理](./frontend-state-dataflow.md) - 前端如何展示维度进度