# 层级与维度配置

本文档是**28维度配置的唯一来源**，其他文档应引用此表。

## 目录

- [三层架构概览](#三层架构概览)
- [28维度配置总表](#28维度配置总表)
- [Wave波次机制](#wave波次机制)
- [依赖关系](#依赖关系)
- [影响树计算](#影响树计算)

---

## 三层架构概览

| 层级 | 名称 | 维度数 | 执行模式 | 说明 |
|------|------|--------|----------|------|
| Layer 1 | 现状分析 | 12 | Map-Reduce并行 | 分析村庄现状各方面 |
| Layer 2 | 规划思路 | 4 | Wave波次执行 | 确定规划方向和策略 |
| Layer 3 | 详细规划 | 12 | Wave波次执行 | 制定具体规划方案 |

---

## 28维度配置总表

### Layer 1：现状分析（12维度）

| 维度键 | 名称 | 工具绑定 | RAG启用 | 描述 |
|--------|------|----------|---------|------|
| location | 区位与对外交通分析 | - | ✓ | 地理位置与交通区位 |
| socio_economic | 社会经济分析 | population_model_v1 | ✓ | 人口、经济、产业 |
| villager_wishes | 村民意愿与诉求分析 | - | ✓ | 村民需求和诉求 |
| superior_planning | 上位规划与政策导向分析 | - | ✓ | 上位规划要求 |
| natural_environment | 自然环境分析 | wfs_data_fetch | ✓ | 自然环境条件 |
| land_use | 土地利用分析 | gis_coverage_calculator | ✓ | 土地利用现状 |
| traffic | 道路交通分析 | accessibility_analysis | ✓ | 道路交通状况 |
| public_services | 公共服务设施分析 | poi_search | ✓ | 公共服务设施 |
| infrastructure | 基础设施分析 | - | ✓ | 基础设施现状 |
| ecological_green | 生态绿地分析 | - | ✓ | 生态绿地分布 |
| architecture | 建筑分析 | - | ✓ | 建筑状况 |
| historical_culture | 历史文化与乡愁保护分析 | - | ✓ | 历史文化资源 |

### Layer 2：规划思路（4维度）

| 维度键 | 名称 | Wave | L1依赖 | L2同层依赖 |
|--------|------|------|--------|-----------|
| resource_endowment | 资源禀赋分析 | 1 | natural_environment, land_use, socio_economic, historical_culture, architecture, public_services | - |
| planning_positioning | 规划定位分析 | 2 | location, socio_economic, superior_planning | resource_endowment |
| development_goals | 发展目标分析 | 3 | socio_economic, superior_planning | resource_endowment, planning_positioning |
| planning_strategies | 规划策略分析 | 4 | traffic, infrastructure | resource_endowment, planning_positioning, development_goals |

### Layer 3：详细规划（12维度）

| 维度键 | 名称 | Wave | L1依赖 | L2依赖 | L3同层依赖 |
|--------|------|------|--------|--------|-----------|
| industry | 产业规划 | 1 | socio_economic, land_use | resource_endowment, planning_positioning, planning_strategies | - |
| spatial_structure | 空间结构规划 | 1 | natural_environment, land_use, traffic, architecture | planning_positioning, planning_strategies | - |
| land_use_planning | 土地利用规划 | 1 | land_use, natural_environment | planning_positioning, planning_strategies | - |
| settlement_planning | 居民点规划 | 1 | architecture, infrastructure, land_use | planning_strategies | - |
| traffic_planning | 道路交通规划 | 1 | traffic, land_use | planning_strategies | - |
| public_service | 公共服务设施规划 | 1 | public_services, socio_economic | planning_strategies | - |
| infrastructure_planning | 基础设施规划 | 1 | infrastructure, natural_environment | planning_strategies | - |
| ecological | 生态绿地规划 | 1 | natural_environment, ecological_green, land_use | planning_strategies | - |
| disaster_prevention | 防震减灾规划 | 1 | natural_environment, infrastructure | planning_strategies | - |
| heritage | 历史文保规划 | 1 | historical_culture, architecture | planning_strategies | - |
| landscape | 村庄风貌指引 | 1 | architecture, historical_culture, ecological_green | planning_strategies | - |
| project_bank | 建设项目库 | 2 | - | - | industry, spatial_structure, land_use_planning, settlement_planning, traffic_planning, public_service, infrastructure_planning, ecological, disaster_prevention, heritage, landscape |

---

## Wave波次机制

### 波次计算公式

```
Wave = 1 + max(wave of dependencies within same layer)
```

### Layer 2波次执行

```
Wave 1: [resource_endowment]        # 无同层依赖
Wave 2: [planning_positioning]       # 依赖 Wave 1
Wave 3: [development_goals]          # 依赖 Wave 1 + Wave 2
Wave 4: [planning_strategies]        # 依赖全部
```

### Layer 3波次执行

```
Wave 1: [industry, spatial_structure, land_use_planning, settlement_planning,
         traffic_planning, public_service, infrastructure_planning, ecological,
         disaster_prevention, heritage, landscape]  # 11维度并行
Wave 2: [project_bank]               # 依赖 Wave 1 全部
```

### 波次路由代码

```python
# src/orchestration/routing.py
def _route_wave_layer(state: Dict, layer: int, current_wave: int) -> Union[List[Send], str]:
    """路由到波次执行的层级"""
    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total_waves = get_total_waves(layer)

    # 检查当前波次是否完成
    wave_dims = get_wave_dimensions(layer, current_wave)
    wave_completed = all(d in completed for d in wave_dims)

    if wave_completed:
        if current_wave >= total_waves:
            return "collect_results"
        else:
            # 推进到下一波次
            next_wave = current_wave + 1
            next_wave_dims = get_wave_dimensions(layer, next_wave)
            pending = [d for d in next_wave_dims if d not in completed]
            return [Send("analyze_dimension", create_dimension_state(dim, state)) for dim in pending]

    # 执行当前波次的未完成维度
    pending_dims = [d for d in wave_dims if d not in completed]
    return [Send("analyze_dimension", create_dimension_state(dim, state)) for dim in pending_dims]
```

---

## 依赖关系

### 跨层依赖示意

```
Layer 1 (12维度并行)
    ↓ 全部完成后
Layer 2 Wave 1: resource_endowment ← L1[ne, lu, se, hc, ar, ps]
    ↓
Layer 2 Wave 2: planning_positioning ← L1[loc, se, sp] + L2[re]
    ↓
Layer 2 Wave 3: development_goals ← L1[se, sp] + L2[re, pp]
    ↓
Layer 2 Wave 4: planning_strategies ← L1[tr, if] + L2[re, pp, dg]
    ↓ 全部完成后
Layer 3 Wave 1: 11维度 ← 各维度L1依赖 + L2[ps]
    ↓
Layer 3 Wave 2: project_bank ← L3全部11维度
```

### L1维度被引用统计

| L1维度 | 被L2引用 | 被L3引用 | 总引用次数 |
|--------|----------|----------|------------|
| natural_environment | 1(re) | 5(ss, lup, ifp, eco, dp) | 6 |
| land_use | 1(re) | 4(ind, ss, lup, set, trp) | 5 |
| socio_economic | 3(re, pp, dg) | 2(ind, pub) | 5 |
| architecture | 1(re) | 4(ss, set, her, lsc) | 5 |
| infrastructure | 1(pst) | 3(set, ifp, dp) | 4 |
| traffic | 1(pst) | 2(ss, trp) | 3 |
| historical_culture | 1(re) | 2(her, lsc) | 3 |
| ecological_green | - | 2(eco, lsc) | 2 |
| public_services | 1(re) | 1(pub) | 2 |
| location | 1(pp) | - | 1 |
| superior_planning | 2(pp, dg) | - | 2 |

---

## 影响树计算

### 影响树定义

当维度修改时，需要级联更新所有下游维度：

```python
# src/config/dimension_metadata.py
def get_impact_tree(dimension_key: str) -> Dict[int, List[str]]:
    """
    获取维度修改后的影响树

    返回按wave分组的维度列表:
    - Wave 1: 直接依赖该维度的下游维度（可并行）
    - Wave 2: 依赖 Wave 1 维度的下游维度
    - ...
    """
```

### 典型影响树示例

**natural_environment修改**：
```python
{
    1: ["resource_endowment", "spatial_structure", "land_use_planning",
        "infrastructure_planning", "ecological", "disaster_prevention"],
    2: ["planning_positioning", "planning_strategies"],
    3: ["development_goals", "project_bank"]
}
```

**socio_economic修改**：
```python
{
    1: ["resource_endowment", "planning_positioning", "development_goals",
        "industry", "public_service"],
    2: ["planning_strategies"],
    3: ["project_bank"]
}
```

**planning_strategies修改**：
```python
{
    1: ["industry", "spatial_structure", "land_use_planning", "settlement_planning",
        "traffic_planning", "public_service", "infrastructure_planning",
        "ecological", "disaster_prevention", "heritage", "landscape"],
    2: ["project_bank"]
}
```

---

## 配置源文件

维度配置定义在 `src/config/dimension_metadata.py`：

```python
DIMENSIONS_METADATA: Dict[str, Dict[str, Any]] = {
    "location": {
        "key": "location",
        "name": "区位与对外交通分析",
        "layer": 1,
        "dependencies": [],
        "rag_enabled": True,
        "tool": None,
    },
    # ... 其他28维度
}
```

### 关键函数

| 函数 | 职责 |
|------|------|
| `get_layer_dimensions(layer)` | 获取层级维度列表 |
| `get_wave_dimensions(layer, wave)` | 获取波次维度列表 |
| `get_total_waves(layer)` | 获取层级总波次数 |
| `_calculate_wave(dim_key, chain)` | 计算维度执行波次 |
| `get_impact_tree(dim_key)` | 获取修改影响树 |
| `get_downstream_dependencies(dim_key)` | 获取下游依赖 |
| `get_full_dependency_chain()` | 获取完整依赖链 |

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 维度元数据定义 | `src/config/dimension_metadata.py` |
| 波次路由 | `src/orchestration/routing.py` |
| 维度状态创建 | `src/orchestration/nodes/dimension_node.py` |
| 修订影响计算 | `src/orchestration/nodes/revision_node.py` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - Agent核心架构
- [06-tool-system](./06-tool-system.md) - Tool-Dimension绑定
- [08-rag-system](./08-rag-system.md) - RAG配置
- [terminology](./terminology.md) - 维度术语定义