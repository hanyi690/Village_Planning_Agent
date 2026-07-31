# 村庄规划系统 - 落地缺陷与设计审视

> **Status: [CURRENT] | Type: Gap Analysis | Version: 1.0 | Created: 2026-07-26**
> **Scope**: 回归规划本质，审视当前各模块距离"可落地的自动化规划生成"的缺陷，含设计级缺陷
> **Audience**: 系统架构师、核心开发者
> **关系**: `00_SYSTEM_DESIGN.md` 的补充--00 描述"设计目标"，本文描述"设计落地的差距"
>
> **阅读顺序**: 先读"一、回归本源"，再读"二、数据流断裂点"，最后按模块看"三、各模块审视"

---

## 一、回归本源：村庄规划到底要做什么

村庄规划的交付物是**一图一表一规则 + GDB 数据库**：

| 交付物 | 本质 | 系统需要的能力 |
|---|---|---|
| **规划图** | 把"现状"改为"规划"后的空间表达 | 空间操作：在现状图层上执行 create/split/merge/modify/reclassify，产出规划图层 |
| **用地平衡表** | 现状各类用地面积 vs 规划各类用地面积的对比 | L1->L4 逐地块对比，按用地分类汇总，计算增减量 |
| **空间管控规则** | 三区三线 + 用地兼容性规则 | 规则提取->规则编码->规则验证三层闭环 |
| **GDB 数据库** | 12+ 标准化图层的 GeoPackage | 每个图层有明确几何 + 属性 schema，可导出 |

**核心矛盾**：当前系统把"规划"理解成了**分区分配 (zone allocation)**，但真正的规划是**对现状空间的操作 (spatial operations on current state)**。这个认知偏差导致了最根本的设计缺陷。

### 规划的两种范式对比

```
范式 A（当前系统）：白纸分配
    现状数据 -> 计算分区配额 -> procedural 从零生成规划多边形 -> 标注为"规划"
    问题：规划图层与现状图层无空间关联，无法回答"哪个现状地块变成了什么"

范式 B（应该的）：现状操作
    现状数据 -> 识别需要变更的地块 -> 执行 split/merge/modify/reclassify -> 产出规划图层
    优势：每个规划地块都有 derived_from 指向现状地块，可计算平衡表，可追溯
```

`parse_contracts.py` 已经定义了 `SpatialOperation`（create/split/merge/modify/reclassify 5 种操作），但全系统没有任何模块执行这些操作。这是"有契约无实现"的核心断裂。

---

## 二、当前数据流全景与断裂点

### 2.1 完整数据流

```
GeoJSON -> DataCatalog -> VillageBundle
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         spatial_ops    KG builder    PARSE agent
         (context+      (L1+L2)       (text->intent)
          relations)        │            │
                            │     ┌──────┘
                            │     ▼  断裂点①：PARSE 查询空 KG
                            │  SpatialPlanningIntent
                            │     │
                            │     ▼  断裂点②：intent 几何粗糙
                            │  EXECUTE agent
                            │     │
                            │     ├── MIP 分配（抽象区域，非地块操作）
                            │     ├── Facility 放置
                            │     ├── Axis 生成
                            │     ├── Road: 空壳
                            │     └── Validate: 断裂点③：constraint 查空
                            │     │
                            │     ▼  断裂点④：无 L1->L4 几何操作
                            │  规划图层（procedural 生成，非现状修改）
                            │     │
                            │     ▼  断裂点⑤：无用地平衡表
                            │  export_gdb + render_map
```

### 2.2 五个断裂点

| # | 断裂点 | 位置 | 后果 |
|---|---|---|---|
| ① | PARSE 在 KG 构建前运行 | `layout_pipeline.py` | PARSE 查询空 KG，`resolve_place` 和 `query_village_kg` 全部失效，LLM 只能靠 ContextBlock 文本"猜" |
| ② | L3 intent 几何粗糙 | `layer3.py` | ZoneTarget 只有 anchor_point + candidate_bbox，EXECUTE 无法做精确空间操作 |
| ③ | constraint 验证空转 | `layer4.check_constraint_violations` | `within_zone` 从不写入 KG，验证永远返回空，验证闭环断裂 |
| ④ | 无真实空间操作 | `execute/agent.py` | EXECUTE 做 MIP 抽象分配 + procedural 图层生成，不是对现状地块做 split/merge/modify |
| ⑤ | 无用地平衡表 | 缺失 | L1->L4 无逐地块对比机制，无法产出"现状XX公顷->规划XX公顷"的平衡表 |

---

## 三、各模块应该做什么 vs 实际做到什么

### 3.1 Schema 模块

**应该做到**：定义规划全过程的数据契约--现状、意图、操作、规划结果、输出。

**实际状态**：
- ✅ 现状类型完整（VillageBundle + CurrentLandUseParcel）
- ✅ 意图类型完整（SpatialPlanningIntent + ZoneTarget/FacilityTarget/AxisTarget/RoadTarget）
- ⚠️ 空间操作类型有定义但未落地
- ❌ 规划结果类型不完整

**缺失**：
1. `SpatialOperation`（create/split/merge/modify/reclassify）定义了 5 种操作，但**没有操作执行器接口**--谁来执行 split？谁来做 merge？操作参数（split 的切割线、merge 的目标地块列表）无 schema 定义
2. **用地平衡表类型缺失**--没有 `LandBalanceRow` / `LandBalanceTable` 的 schema 定义
3. **L4 PlannedParcel 没有 geometry 字段**--只有 BSM + 属性变更，没有实际规划几何
4. `PlanBlock` 是 delta（非 morphology），不继承 `SpatialCognitiveUnit`，导致 L4 实体无法参与语义查询

### 3.2 Data 模块

**应该做到**：加载现状数据 + 加载已有规划数据（如有）+ 提供标准化 typed model。

**实际状态**：
- ✅ 现状加载完整（6 编码系统验证）
- ✅ VillageBundle morphological 分组

**缺失**：
1. **现状->规划的空间对照能力缺失**--`planned/landuse.geojson` 有 582 个规划地块，但 Data 层只把它当另一个"现状"加载，没有"对照"语义
2. **规划数据与现状数据的 BSM 不一一对应**（660 现状 vs 582 规划），Data 层没有提供任何对照/映射机制

### 3.3 Spatial Ops 模块

**应该做到**：系统中**所有**空间计算的唯一发生地--包括规划操作的空间执行。

**实际状态**：
- ✅ `compute_context_blocks`（8 种认知卡片）
- ✅ `compute_parcel_relations`（touches/nearby/connected）
- ✅ `build_spatial_index`（EXECUTE 桥接，刚加的）
- ❌ **`grounding.py` 不存在**--PARSE 空间接地无法执行
- ❌ **无空间操作引擎**--split/merge/modify 的几何执行没有实现
- ❌ **无 L1↔L4 overlay 分析**--不知道哪个规划地块覆盖了哪些现状地块
- ❌ **无 buffer/clip/dissolve 工具**--空间管控区生成、三线退让距离计算无处发生

**这是最大的能力缺口**：spatial_ops 目前只能"分析"不能"操作"。规划的 create/split/merge/modify/reclassify 全部需要几何操作，但 spatial_ops 没有任何此类函数。

### 3.4 KG 模块

**应该做到**：存储空间实体的语义关系，作为 PARSE↔EXECUTE 的桥梁。

**实际状态**：
- ✅ L1 现状实体完整（660 地块 + 道路 + 水体 + 设施）
- ✅ L2 空间关系（touches/nearby/connected）
- ✅ L3 intent 虚拟实体（ZoneTarget/FacilityTarget/AxisTarget）
- ✅ L4 PlannedState 稀疏写入 + 版本对比
- ✅ SemanticMemoryStore 注解写入
- ✅ 架构约束严格（无 shapely，无反向依赖）

**设计缺陷**：
1. **`within_zone` 从不写入**--L1 地块没有 `pln:within_zone` 关系指向 Zone 实体，导致所有约束验证空转。原因是 `_add_parcels` 不再从 DLBM 推导 planning_zone（v4.6 改动），但**没有替代机制**来建立 parcel->zone 关系
2. **L4 PlannedParcel 无几何**--只存 BSM + 属性 delta，EXECUTE 无法从 KG 查到规划几何
3. **L1↔L4 无空间关联**--没有 `pln:replaces` / `pln:derived_from` 三元组连接规划地块和现状地块（`derived_from` 只在 split/merge 场景定义，普通 modify 没有）
4. **L3 intent 几何存为 WKT 粗略框**--但 KG 无能力验证这个框与 L1 的空间关系

### 3.5 PARSE Agent

**应该做到**：理解规划文本->提取意图->空间接地->产出可执行 SpatialPlanningIntent。

**实际状态**：
- ✅ Think-Then-Format 模式（Qwen3.7 兼容）
- ✅ 四路扇出（projects/targets/regulations/tables）
- ✅ 确定性后处理（code 修正、anchor 填充）
- ❌ **查询空 KG**--pipeline 顺序 bug，PARSE 跑在 KG 构建前
- ❌ **空间接地不存在**--`grounding.py` 未实现，`resolve_place` 只做 ContextBlock 文本匹配 + 天地图 geocode，无法做"村北靠近刘村"->BBox+候选 BSM 的精确接地
- ❌ **SpatialOperation 提取不可靠**--LLM 产出的 create/split/merge/modify/reclassify 只是标签，没有几何参数

### 3.6 EXECUTE Agent

**应该做到**：执行空间操作->生成规划图层->验证合规性->产出可导出结果。

**实际状态**：
- ✅ MIP 分区分配（`MIPZoneAllocator`）
- ✅ Facility 放置（`FacilityPlacer`）
- ✅ Axis 生成 + 空间管控区 + 用地分区
- ❌ **Road 生成空壳**
- ❌ **无真实空间操作**--MIP 分配的是"区域配额"，不是对具体地块做 split/merge
- ❌ **procedural 生成 ≠ 现状修改**--`_generate_function_zones` 是从零生成多边形，不是在现状地块上操作
- ❌ **验证空转**--constraint 验证依赖 `within_zone`（空），LayoutValidator 只检查面积/邻接，不检查三线冲突
- ❌ **无用地平衡表生成**--没有 L1->L4 对比汇总
- ❌ **@tool 绕过**--直接调用 tools/gis 私有函数，耦合严重

### 3.7 输出层 (export_gdb + render_map)

**应该做到**：导出 12 层标准 GeoPackage + 渲染规划图。

**实际状态**：⚠️ 存在但**未验证**--没有测试验证导出的 GDB 是否符合标准，没有验证渲染的图是否正确。

---

## 四、设计缺陷（架构级）

### 缺陷 1：规划 = 分区分配 ≠ 空间操作

**最根本的设计偏差**。当前系统把规划理解为"在一张白纸上画分区"（MIP allocation + procedural generation），但真实规划是"在现状图上做修改"（parcel-level operations）。

```
当前：  白纸 -> MIP 分区 -> procedural 生成多边形 -> 标注为"规划"
应该：  现状图 -> 识别需要变更的地块 -> 执行 split/merge/modify/reclassify -> 产出规划图
```

**后果**：
- 无法产出用地平衡表（没有 L1->L4 逐地块对比）
- 规划图层与现状图层无空间关联（规划多边形和现状多边形是两套独立几何）
- 无法回答"这个规划地块是由哪个现状地块变更来的"

### 缺陷 2：pipeline 顺序错误

```
当前（错误）：parse_intent -> fetch_gis_data -> build_kg -> execute
应该（正确）：fetch_gis_data -> build_kg_l1l2 -> parse_intent -> write_kg_l3 -> execute
```

PARSE 在 KG 构建前运行，导致所有 KG 查询工具失效。这不是实现 bug，是**设计顺序错误**。

### 缺陷 3：约束系统设计断裂

`pln:within_zone` 是约束验证的核心关系，但**从未被写入**。v4.6 移除了"从 DLBM 推导 planning_zone"的逻辑（正确决定），但**没有建立替代机制**来确定地块属于哪个管控区。

```
设计意图：  parcel --within_zone--> Zone(生态红线/基本农田/建设区)
验证逻辑：  check_constraint_violations() 查 within_zone -> 返回违反列表
实际状态：  within_zone 从不写入 -> 验证永远返回空
```

**根因**：Zone 实体（ThreeZone/ThreeLine）有几何，Parcel 有几何，但 KG 不存几何，spatial_ops 的 overlay 结果没有回写 KG。

### 缺陷 4：L4 无几何，无法支撑空间操作

L4 PlannedParcel 只存 BSM + 属性 delta（dlbm 变了、area 变了），不存几何。但规划操作（split/merge）必然改变几何。没有几何的 L4 无法：
- 导出规划图层（GDB 需要几何）
- 计算用地平衡表（需要面积，面积来自几何）
- 验证空间合规（需要几何做 overlay）

### 缺陷 5：SpatialOperation 有定义无执行

`parse_contracts.py` 定义了 5 种 SpatialOperation（create/split/merge/modify/reclassify），但：
- PARSE 提取的 operation 只有标签 + target_bsm，没有几何参数
- EXECUTE 没有 operation executor，MIP 分配和 procedural 生成都不消费 SpatialOperation
- spatial_ops 没有几何操作函数

**完整的 operation 流程断裂**：
```
应该：  PARSE 提取 operation -> EXECUTE 执行 operation -> spatial_ops 做几何 -> L4 存结果
实际：  PARSE 提取 operation（标签）-> EXECUTE 忽略 operation -> MIP/procedural 另起炉灶
```

### 缺陷 6：ContextBlock 与 KG 双轨制无闭环

ContextBlock 是 spatial_ops 产出的空间认知卡片（给 LLM 看），KG 是空间实体关系图（给程序查）。两者**描述同一空间事实但无交叉验证**：
- ContextBlock 说"刘村在村北" -> KG 没有这个关系
- KG 有 `touches` 关系 -> ContextBlock 不消费它
- ContextBlock 的 `ConstraintZoneAnchor` 列出受限地块 BSM -> KG 的 `within_zone` 为空

---

## 五、距离落地可用的优先级排序

> **注**：本表为本文审视视角的快照。03/04/05 三份审计的 P0/P1 条目存在交叠且编号各自独立，
> **执行以 `reference/OPTIMIZATION_TASKS.md` 统一任务清单为准**，本表只引用不新增。

### P0（不修复就无法运行）

| # | 缺陷 | 修复方向 | 涉及模块 |
|---|---|---|---|
| 1 | pipeline 顺序错误 | 调整为 fetch->build_kg->parse->execute | `layout_pipeline.py` |
| 2 | `within_zone` 不写入 | spatial_ops 计算 parcel↔zone overlay -> 回写 KG L2 | `spatial_ops`, `kg/builder` |
| 3 | `grounding.py` 不存在 | 实现 PARSE 空间接地（BBox+候选 BSM+排除集） | `spatial_ops/grounding.py` |

### P1（不修复无法产出可用规划）

| # | 缺陷 | 修复方向 | 涉及模块 |
|---|---|---|---|
| 4 | 无真实空间操作 | spatial_ops 新增 `parcel_ops.py`：split/merge/modify/reclassify 的几何执行 | `spatial_ops`, `schema/contracts` |
| 5 | L4 无几何 | L4 PlannedParcel 增加 geometry 字段（WKT 或引用 spatial_ops 结果） | `kg/builder/layer4.py`, `schema/contracts` |
| 6 | 无 L1↔L4 overlay | spatial_ops 新增 `overlay_analysis`：规划几何->覆盖的现状地块列表 | `spatial_ops/bridge.py` |
| 7 | Road 生成空壳 | 实现 PlannedRoad 生成器 | `tools/gis/_generation/`, `execute/` |
| 8 | 无用地平衡表 | 新增 `LandBalanceTable` schema + 生成器（L1 vs L4 逐地块汇总） | `schema`, `tools/gis` |

### P2（不修复无法达到交付质量）

| # | 缺陷 | 修复方向 | 涉及模块 |
|---|---|---|---|
| 9 | 验证闭环不完整 | LayoutValidator 集成 spatial_ops overlay 做三线冲突检测 | `tools/gis/_validation/` |
| 10 | @tool 绕过 | EXECUTE 节点改用公共 API | `execute/agent.py` |
| 11 | ContextBlock↔KG 无闭环 | ContextBlock 的 anchor BSM 与 KG 关系交叉验证 | `spatial_ops/context.py`, `kg` |
| 12 | L3 intent 几何粗糙 | PARSE 接地后用 spatial_ops 精确化 candidate_bsms | `parse/agent.py`, `spatial_ops/grounding.py` |

---

## 六、一个完整自动化系统应该有的流程

```
 1. fetch_gis_data          -> VillageBundle (现状)
 2. build_kg_l1l2           -> KG (L1 现状实体 + L2 空间关系)
    └── spatial_ops: compute parcel↔zone overlay -> 写入 within_zone
 3. parse_intent            -> SpatialPlanningIntent
    ├── spatial_ops.grounding: 接地"村北"->BBox->候选 BSM
    ├── KG query: 查现状用地分布、约束区、邻接关系
    └── LLM: 产出 ZoneTarget + FacilityTarget + SpatialOperation
 4. write_kg_l3             -> KG (L3 intent 虚拟实体)
 5. execute:
    5a. execute_operations  -> 对现状地块执行 split/merge/modify/reclassify
        └── spatial_ops.parcel_ops: 几何操作 -> 产出规划几何
    5b. execute_allocation  -> MIP 分区配额（约束：面积、邻接、三线）
    5c. execute_facilities  -> Facility 放置
    5d. execute_roads       -> 路网生成
    5e. execute_axes        -> 发展轴 + 空间管控区
 6. write_kg_l4             -> KG (L4 PlannedState with geometry)
 7. validate                -> 空间合规验证（三线冲突、面积比例、连通性）
    └── spatial_ops: overlay(规划几何, 约束区) -> 违反列表
    └── 失败 -> 回 5a 调整
 8. generate_balance_table  -> L1 vs L4 逐地块对比 -> 用地平衡表
 9. export_gdb              -> 12 层 GeoPackage
10. render_map             -> 规划图
```

**当前系统在第 5 步就断了**--没有真实空间操作，第 6-8 步都建立在不完整的基础上。

---

## 七、结论

当前系统的**架构分层（Schema←Data←SpatialOps←KG←Agent）是正确的**，KG 的四层设计也是合理的。但存在一个**根本认知偏差**：把规划理解成"分区分配"而非"空间操作"。

这导致：
- spatial_ops 只有"分析"能力没有"操作"能力
- EXECUTE 做 MIP 优化而非几何操作
- L4 存属性 delta 而非几何
- 无法产出用地平衡表

**最小可行修复路径**：P0 三项（pipeline 顺序 + within_zone + grounding）-> P1 四项（空间操作引擎 + L4 几何 + overlay + 平衡表）。修完 P0+P1 后，系统才能跑通"现状->意图->操作->规划->验证->输出"的完整闭环。

---

## 附录 A：文件权重索引

以下文件在架构中权重最高，修改时需格外谨慎：

| 文件 | 角色 |
|---|---|
| `schema/types/canonical.py` | VillageBundle 定义 |
| `schema/contracts/parse_contracts.py` | PARSE↔KG↔EXECUTE 契约 |
| `kg/builder/base.py` + `kg/README.md` | KG 构建入口 + 设计 |
| `agent/gis/layout_pipeline.py` | 顶层编排 |
| `agent/gis/parse/agent.py` | PARSE Think-Then-Format |
| `agent/gis/execute/agent.py` | EXECUTE Worker-Evaluator 循环 |
| `data/ingest.py` | 唯一的 raw->typed 端口 |
| `data/catalog/catalog.py:load_village_bundle` | bundle 加载器 |
| `spatial_ops/geometry.py:compute_parcel_relations` | 唯一的 shapely 用户 |
| `tests/integration/test_kg_jintian_e2e.py` | 架构约束 + e2e 验证 |
