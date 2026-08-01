# 实现计划：产出可用的布局图（金田村样例，全闭环）

> 目标：整合 handoff 分支的 EXPLORE/Binder/道路规划/services 层实现到当前工作区，重跑 L1->L2->L3 LLM 分析（L2/L3 补 KG 查询 I2），EXPLORE 探索 KG 产出 ExplorationInstruction，Binder 绑定 bundle 几何，format_bound_intent 转 SpatialPlanningIntent，EXECUTE 生成布局（含道路子系统），最终产出 PNG + GeoJSON/GPKG + MapLibre 三种布局图。

---

## 一、仓库状态澄清（关键发现）

### 1.1 分支与工作区

| 项 | 值 |
|----|-----|
| 本地分支 | `feature/flash-llm-explore-agent` @ `9ca30f70`（实际是 main HEAD + 文档提交） |
| 远程 handoff 分支 | `origin/agent/kg-schema-gis-handoff-20260730` @ `25e24847` |
| 工作区状态 | clean，HEAD = `9ca30f70`，kg 模块已提交（28 文件，但无 interface.py） |

### 1.2 工作区已有（main 架构，已提交到 9ca30f70）

| 组件 | 状态 | 说明 |
|------|------|------|
| `modules/kg/` | ✅ 28 文件 | 有 KGManager/PlanningKG/builder/queries/memory/ontology，**无 interface.py** |
| `modules/kg/manager.py` | ✅ | 有 get_session_kg/get_or_build_layer1/register_session，**无 require_session_kg** |
| `modules/data/` + `modules/schema/` + `modules/spatial_ops/` | ✅ | 5 层架构的 Data/Schema/SpatialOps 层 |
| `agent/gis/layout_pipeline.py` (9节点) | ✅ | fetch->build_kg->parse->write_l3->conflicts->execute->export->render |
| `agent/gis/execute/agent.py` (7节点) | ✅ | route->layout->facility->axis->road->validate->write_l4 |
| `agent/gis/parse/agent.py` | ✅ | 纯正则 4 模式提取 |
| `tools/gis/*` | ✅ | generate/allocate/export/render/conflict/kg/validate |
| `agent/graph.py` 主图 (5节点) | ✅ | conversation->analyze_dimension->completion->gis_agent |

### 1.3 handoff 分支独有（需整合，origin/agent/kg-schema-gis-handoff-20260730 @ 25e24847）

| 组件 | 文件 | 用途 | 依赖 |
|------|------|------|------|
| **EXPLORE Agent** | `agent/gis/explore/agent.py` + `contracts.py` | 文本->ExplorationInstruction（6域分类+BSM识别+KG查询） | `require_session_kg`+`query_session_template`（interface.py） |
| **KG interface.py** | `modules/kg/interface.py` | `require_session_kg`/`open_kg_session`/`query_session_template` 稳定集成边界 | manager.py 的 `require_session_kg` 方法（handoff 有，工作区无） |
| **SpatialEntityBinder** | `agent/gis/spatial_entity_binder.py` | ExplorationInstruction -> 绑定 bundle 几何（BSM 精确匹配） | ExploreFlashAgent 产出 + VillageBundle |
| **format_bound_intent** | `agent/gis/format_bound_intent.py` | 绑定实体 -> SpatialPlanningIntent（ZoneTarget/FacilityTarget/AxisTarget/RoadTarget） | Binder 产出 + parse_contracts |
| **services/modules/gis/** | 80 文件 | 旧版完整 GIS 服务层（layout engine/road planner/KG builder/optimizer） | 独立旧架构，与 5 层架构部分冲突 |
| **road/ 子系统** | 16 文件 | 道路规划全流程（planner/network_builder/text_structurer/spatial_binder/evaluator/terrain_router/qgis_package） | services/modules/gis/ 内部 |
| **layout/engine.py** | 900 行 | SpatialLayoutEngine（conflict->zone->kg_alloc->render） | services/modules/gis/layout/ |
| **layout/planning_intent.py** | 743 行 | UnifiedSpatialIntent 声明式模型 | services/modules/gis/layout/ |
| **Flash LLM 配置** | settings.py 中 GIS_EXPLORE_* | 独立 Flash 模型配置 | app/core/llm.py（工作区已有） |

### 1.4 依赖关系（整合顺序）

```
interface.py (require_session_kg)
    ↑ 依赖
    │
ExploreFlashAgent (explore/agent.py)
    │ 产出 ExplorationInstructionCollection
    ▼
DeterministicBundleBinder (spatial_entity_binder.py)
    │ 绑定 bundle 几何，产出 FeatureCollection
    ▼
format_bound_spatial_intent (format_bound_intent.py)
    │ 转 SpatialPlanningIntent
    ▼
layout_pipeline.py (parse_intent 节点消费 intent)
    │
    ▼
EXECUTE (execute/agent.py) + road/ 子系统（可选）
```

---

## 二、整合策略

### 2.1 整合范围决策

| handoff 组件 | 整合方式 | 理由 |
|-------------|---------|------|
| `modules/kg/interface.py` | **直接 checkout** | 纯新增文件，无冲突，提供 require_session_kg 稳定边界 |
| `modules/kg/manager.py` 的 `require_session_kg` | **patch 合入** | 工作区 manager.py 缺此方法，interface.py 依赖它 |
| `agent/gis/explore/` (agent.py + contracts.py + __init__.py) | **直接 checkout** | 纯新增，EXPLORE 是 KG 探索的必要前置 |
| `agent/gis/spatial_entity_binder.py` | **直接 checkout** | 纯新增，Binder 连接 Explore 产出与 bundle 几何 |
| `agent/gis/format_bound_intent.py` | **直接 checkout** | 纯新增，转 bound entities -> SpatialPlanningIntent |
| `services/modules/gis/` | **不 checkout** | 旧架构，与 5 层 modules/ 冲突；layout engine/road 已有 5 层等价物 |
| `road/` 子系统 | **暂不 checkout** | 道路规划是增量功能，先用 5 层的 spatial_ops/road_planner.py |
| Flash LLM 配置 | **patch 合入 settings.py** | GIS_EXPLORE_LLM_ENABLED/MODEL/TEMPERATURE/MAX_TOKENS |

### 2.2 核心数据流（整合后）

```
NL输入(金田村)
  │
  ▼ 主图 conversation 节点路由
L1现状分析(12维并行)
  │ _optimize_semantics 查 KG 认知（I2: 现已实现静态 DIM_KG_MAP）
  │ 产出: 12份L1报告 -> DB
  │
  ▼ Wave 调度
L2规划定位(4维波次)
  │ I2改造: _optimize_semantics 闸门放开, 查 analysis+shared_queries
  │ KG 实例统一: get_any_kg -> require_session_kg
  │ 产出: 4份L2报告 -> DB
  │
  ▼ Wave 调度
L3详细规划(12维波次)
  │ I2改造: 查 execute+shared_queries
  │ detailed.py prompt 产出自然语义空间内容（功能分区表/项目清单/空间结构）
  │ 产出: 12份L3报告(含自然语义空间意向) -> DB
  │
  ▼ L3完成 -> 自动/手动路由到 gis_agent
gis_agent 节点
  │ 1. 从DB取 L3 报告文本（_get_reports_and_summaries）
  │ 2. EXPLORE: ExploreFlashAgent.explore(planning_text) -> ExplorationInstructionCollection
  │    - 文本分块 -> 6域分类 -> BSM识别 -> KG查询(require_session_kg)
  │ 3. BINDER: DeterministicBundleBinder(bundle).bind(instructions) -> bound FeatureCollection
  │    - BSM 精确匹配 bundle 几何，未解析的标记 candidate
  │ 4. FORMAT: format_bound_spatial_intent(bound_entities) -> SpatialPlanningIntent
  │    - ZoneTarget/FacilityTarget/AxisTarget/RoadTarget
  │ 5. layout_pipeline: fetch -> build_kg -> parse(消费intent) -> write_l3 -> execute -> export -> render
  │    EXECUTE: MIP分配 + 功能区/规划分区 + Evaluator Gate + write_l4
  │
  ▼
产出: layout_configs + export_gdb(12层GeoJSON) + render_map(MapLibre JSON)
  │
  ▼ 脚本层补充
PNG静态总图 + GPKG导出
```

### 2.3 EXPLORE 在维度分析中的角色（I2 改造的关键）

EXPLORE 有两种使用方式，本次都要用：

1. **桥接模式**（L3 完成后）：ExploreFlashAgent.explore(planning_text) 产出 ExplorationInstructionCollection，经 Binder -> format_bound_intent -> SpatialPlanningIntent，交给 layout_pipeline
2. **维度认知模式**（L1/L2/L3 每维度分析时）：替代 `_optimize_semantics` 静态 DIM_KG_MAP，为每个维度动态提供 KG 空间认知

**本次实现深度**：
- 桥接模式：**完整实现**（checkout explore/ + binder + format_bound_intent）
- 维度认知模式：**I2 改闸门**（放开 dim_layer!=1，L2/L3 查 KG），但暂不升级为 ExploreFlashAgent 维度认知调用（那是 EXPLORE 的完整三模式统一，后续迭代）

---

## 三、分阶段实施

### 阶段0：整合 handoff 分支组件 [基础准备]

#### Step 0.1: checkout 纯新增文件（无冲突）

从 `origin/agent/kg-schema-gis-handoff-20260730` checkout 以下文件到工作区：

```bash
git checkout origin/agent/kg-schema-gis-handoff-20260730 -- \
  backend/app/modules/kg/interface.py \
  backend/app/agent/gis/explore/__init__.py \
  backend/app/agent/gis/explore/agent.py \
  backend/app/agent/gis/explore/contracts.py \
  backend/app/agent/gis/spatial_entity_binder.py \
  backend/app/agent/gis/format_bound_intent.py
```

**验证**：
- `interface.py` 导入 manager.py 的 `get_kg_manager`（工作区已有）
- `explore/agent.py` 导入 `require_session_kg`/`query_session_template`（来自 interface.py）
- `spatial_entity_binder.py` 导入 `ExplorationInstructionCollection`（来自 explore/contracts.py）
- `format_bound_intent.py` 导入 `parse_contracts`（工作区 modules/schema/contracts/ 已有）

#### Step 0.2: patch manager.py 添加 require_session_kg 方法

工作区 `modules/kg/manager.py` 有 `get_session_kg`（返回 Optional），缺 `require_session_kg`（返回或 raise）。

**从 handoff 分支提取 `require_session_kg` 方法实现**：
```python
def require_session_kg(self, session_id: str) -> Any:
    """Return only session_id's KG or raise a clear isolation error."""
    kg = self.get_session_kg(session_id)
    if kg is None:
        raise RuntimeError(f"No KG registered for session {session_id!r}. Call open_kg_session first.")
    return kg
```

**位置**：manager.py 的 `get_session_kg` 方法之后

#### Step 0.3: 更新 kg/__init__.py 导出 interface

在工作区 `modules/kg/__init__.py` 末尾添加：
```python
from .interface import (
    KGSessionSnapshot, open_kg_session, require_session_kg,
    replace_session_intent, apply_session_planned_state,
    query_session_sparql, query_session_template, close_kg_session,
)
```
并加入 `__all__`

#### Step 0.4: patch settings.py 添加 Flash LLM 配置

从 handoff 分支提取 GIS_EXPLORE_* 配置项：
```python
GIS_EXPLORE_MODEL = os.getenv("GIS_EXPLORE_MODEL", "qwen-flash")
GIS_EXPLORE_MAX_TOKENS = int(os.getenv("GIS_EXPLORE_MAX_TOKENS", "1200"))
GIS_EXPLORE_TEMPERATURE = float(os.getenv("GIS_EXPLORE_TEMPERATURE", "0.1"))
GIS_EXPLORE_LLM_ENABLED = os.getenv("GIS_EXPLORE_LLM_ENABLED", "false").lower() in {"1", "true", "yes"}
```

#### Step 0.5: 验证整合后导入链

```python
# 测试导入
from app.modules.kg import require_session_kg, query_session_template, open_kg_session
from app.agent.gis.explore import ExploreFlashAgent, explore_planning_text
from app.agent.gis.spatial_entity_binder import DeterministicBundleBinder, bind_exploration_to_bundle
from app.agent.gis.format_bound_intent import format_bound_spatial_intent
```

---

### 阶段1：I2 改造 + LLM 重跑 L1->L2->L3

#### Step 1.1: I2 改造 - 放开 L2/L3 KG 查询闸门

**文件**: `backend/app/agent/analysis/node.py:661-668`

修改 `_optimize_semantics`：
- 删除 `if dim_layer != 1: return ""`
- 按层分派查询命名空间（L1=analysis_queries / L2=analysis+shared / L3=execute+shared）
- KG 实例：`get_any_kg()` -> `require_session_kg(session_id)`（有 fallback 到 get_any_kg）

#### Step 1.2: 预构建 session KG

在 L1 分析开始前（graph.py 的 analyze_dimension_node 首次调用时），通过 `open_kg_session()` 预构建 session KG：
- 加载金田村 DataCatalog 数据 -> VillageBundle
- 调 `open_kg_session(session_id, village_name, bundle)` 构建 L1+L2 KG
- 后续 L2/L3 的 `_optimize_semantics` 可通过 `require_session_kg` 查询

#### Step 1.3: L3->gis_agent 自动路由（I6 部分）

修改 `routing.py:238-240`：L3 完成 + 非 step_mode 时自动路由到 gis_agent

#### Step 1.4: 新建 CLI 驱动脚本

`scripts/run_planning_pipeline.py`：构造金田村 NL 输入 -> 跑完整主图 -> 产出 L3 报告

#### Step 1.5: 跑通并诊断

- L1: 12 维度完成，KG 认知注入
- L2: 4 维度完成，KG 约束校核注入
- L3: 12 维度完成，KG 现状结构注入，报告含【功能分区表】

---

### 阶段2：EXPLORE 桥接 -> PARSE -> EXECUTE -> 布局图产出

#### Step 2.1: gis_agent 整合 EXPLORE+Binder+format_bound_intent

修改 `agent/graph.py` 的 `gis_agent_node`：
```python
# 1. 从DB取 L3 报告文本
reports, summaries = await _get_reports_and_summaries(state)
planning_text = "\n".join(r.get("content","") for r in reports.values())

# 2. EXPLORE: 文本 -> ExplorationInstructionCollection
from app.agent.gis.explore import ExploreFlashAgent
explore_agent = ExploreFlashAgent(session_id=session_id, village_name=village_name)
instructions = explore_agent.explore(planning_text)

# 3. BINDER: 绑定 bundle 几何
from app.agent.gis.spatial_entity_binder import DeterministicBundleBinder
binder = DeterministicBundleBinder(gis_bundle)
bound_entities = binder.bind(instructions)

# 4. FORMAT: -> SpatialPlanningIntent
from app.agent.gis.format_bound_intent import format_bound_spatial_intent
intent = format_bound_spatial_intent(
    village_name=village_name,
    bound_entities=bound_entities,
    fallback_intent=SpatialPlanningIntent(),  # 正则提取作 fallback
)

# 5. layout_pipeline 消费 intent
pipeline = build_layout_pipeline()
layout_result = await pipeline.ainvoke({...,"intent": intent})
```

**注意**：当前 graph.py:97 有独立的 `create_parse_agent_graph()` 双重 parse（断点⑧），整合后移除，EXPLORE+Binder+format 产出的 intent 直接注入 layout_pipeline

#### Step 2.2: 跑通 pipeline 并诊断

- EXPLORE 产出 instruction 数量 > 0
- Binder 绑定成功率（confirmed/candidate/unresolved 分布）
- format_bound_intent 产出 zone_targets ≥ 2
- layout_pipeline 9 节点全部执行
- layout_configs ≥ 2 层

#### Step 2.3: 适配 render_integrated_map.py 产出 PNG

修正路径 `docs/gis/jintian_boundary/` -> `data/gis/jintian/current/`，从 pipeline 产出渲染

#### Step 2.4: 补充 GPKG 导出

脚本层用 geopandas 将 12 层 GeoJSON 写入 .gpkg

#### Step 2.5: 验证 MapLibre + 整理产出目录

---

## 四、改动清单

### 新增文件（从 handoff checkout）

| 文件 | 来源 |
|------|------|
| `modules/kg/interface.py` | handoff 分支 |
| `agent/gis/explore/__init__.py` | handoff 分支 |
| `agent/gis/explore/agent.py` | handoff 分支 |
| `agent/gis/explore/contracts.py` | handoff 分支 |
| `agent/gis/spatial_entity_binder.py` | handoff 分支 |
| `agent/gis/format_bound_intent.py` | handoff 分支 |

### 核心代码修改（patch）

| 文件 | 改动 | 行数 |
|------|------|------|
| `modules/kg/manager.py` | 加 `require_session_kg` 方法 | ~8行 |
| `modules/kg/__init__.py` | 导出 interface | ~8行 |
| `core/settings.py` | 加 GIS_EXPLORE_* 配置 | ~6行 |
| `agent/analysis/node.py` | I2 改闸门 + KG 实例统一 | ~40行 |
| `agent/graph.py` | KG 预构建 + gis_agent 整合 EXPLORE+Binder+format + 移除双重parse | ~50行 |
| `agent/routing.py` | L3->gis_agent 自动路由 | ~5行 |

### 新增脚本

| 文件 | 用途 |
|------|------|
| `scripts/run_planning_pipeline.py` | 主图驱动 CLI |
| `scripts/render_integrated_map.py` | PNG 渲染（适配路径） |

### 不 checkout / 不修改

| 项 | 原因 |
|------|------|
| `services/modules/gis/`（80文件） | 旧架构，与 5 层 modules/ 冲突；layout engine 已有 5 层等价物 |
| `road/` 子系统（16文件） | 增量功能，先用 5 层 spatial_ops/road_planner.py |
| `detailed.py` prompt | intent 按 prompt 规则生成，不改 |
| `layout_pipeline.py` 9节点 | 已就绪 |
| `execute/agent.py` 7节点 | 已就绪 |

---

## 五、风险与回退

| 风险 | 概率 | 回退方案 |
|------|------|----------|
| interface.py 与工作区 manager.py 签名不兼容 | 中 | patch 适配，interface.py 调用的方法工作区已有（get_kg_manager/get_session_kg） |
| explore/agent.py 导入 app.core.llm.create_llm 签名不同 | 中 | 检查工作区 llm.py，适配 create_flash_llm |
| require_session_kg 在 L1 前 KG 未构建时 raise | 高 | _optimize_semantics 中 try/except fallback 到 get_any_kg |
| LLM 调用超时/限流（28次） | 中 | checkpointer 断点续跑 |
| EXPLORE 从 L3 报告提取 instruction 为空 | 低 | format_bound_intent 有 fallback_intent 参数 |
| Binder 绑定全 unresolved（BSM 不匹配） | 中 | format 仍产出 intent（带 candidate_bsms），EXECUTE 可处理 |
| DataCatalog 加载金田村失败 | 中 | 脚本直接读 GeoJSON |

---

## 六、验证标准

### 阶段0验收（整合）

| 项 | 标准 |
|----|------|
| 导入链 | `from app.agent.gis.explore import ExploreFlashAgent` 成功 |
| require_session_kg | manager.py 有此方法，interface.py 可调 |
| settings | GIS_EXPLORE_LLM_ENABLED 可读 |

### 阶段1验收（LLM 重跑 + I2）

| 项 | 标准 |
|----|------|
| L1/L2/L3 完成 | DB 新增 28 份报告 |
| L2 KG 查询 | L2 报告含"空间语义补充"段落 |
| L3 KG 查询 | L3 报告含"空间语义补充"段落 |
| L3 空间结构 | spatial_structure 报告含【功能分区表】 |

### 阶段2验收（布局图产出）

| 项 | 标准 |
|----|------|
| EXPLORE 产出 | instructions ≥ 5 条 |
| Binder 绑定 | ≥ 1 条 confirmed/candidate |
| intent | zone_targets ≥ 2 |
| pipeline | 9 节点全部执行 |
| GeoJSON | ≥ 5 文件导出 |
| GPKG | QGIS 可打开 |
| PNG | ≥ 1920x1080，含图例 |
| MapLibre | layer_count > 0 |

---

## 七、执行顺序

```
阶段0（整合基础）:
  Step 0.1 (checkout 新文件) ──> Step 0.2 (patch manager.py)
       │                              │
       ▼                              ▼
  Step 0.3 (patch __init__.py) ──> Step 0.4 (patch settings.py)
       │
       ▼
  Step 0.5 (验证导入链)

═══════════════════════════════════════════

阶段1（LLM 重跑 + I2）:
  Step 1.1 (改闸门) ──> Step 1.2 (KG 预构建) ──> Step 1.3 (路由) ──> Step 1.4 (CLI) ──> Step 1.5 (诊断)

═══════════════════════════════════════════

阶段2（EXPLORE 桥接 + 布局产出）:
  Step 2.1 (gis_agent 整合 EXPLORE+Binder+format) ──> Step 2.2 (跑通诊断)
       │
       ▼
  Step 2.3 (PNG) ┐
  Step 2.4 (GPKG) ├─ 并行
  Step 2.5 (MapLibre+整理) ┘
```

预计工作量：阶段0 (~2h) + 阶段1 (~6h) + 阶段2 (~4h) = ~12h

---

## 八、不做什么

| 不做 | 原因 |
|------|------|
| 不 checkout services/modules/gis/ | 旧架构，与 5 层冲突 |
| 不 checkout road/ 子系统 | 增量功能，后续迭代 |
| 不实现 EXPLORE 维度认知模式（完整三模式统一） | 本次先用 I2 改闸门为 L2/L3 提供 KG 认知，EXPLORE 维度认知模式是后续升级 |
| 不改 detailed.py prompt | intent 按 prompt 规则生成 |
| 不实现 L3 校核轮（I5） | [PLANNED] 后续 |
| 不实现结构化问题清单（I1） | [PLANNED] P2 |
