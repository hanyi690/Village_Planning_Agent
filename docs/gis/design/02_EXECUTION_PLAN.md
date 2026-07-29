# 村庄规划系统 — 执行方案（统一权威）

> **Status: [RECONCILED] | Type: Execution Plan | Version: 1.0 | Created: 2026-07-26 | Reconciled: 2026-07-29**
> **Scope**: 全局目标 + 模块化分解 + 分波次执行计划
> **Replaces**: 01_CONTRACT_REFACTOR_PLAN.md, reference/OPTIMIZATION_TASKS.md
> **Reconciled into**: 00_SYSTEM_DESIGN.md v4.8 — §5.1 中推翻 00 的四个条款已全部回填。本文档保留作为执行参考。
> **References**: 各模块 README（最贴近代码的权威实现文档）

---

## 第一部分：全局目标

### 1.1 系统定位

> 给定村庄现状资料（三调数据、三区三线、DEM/DOM、上位规划、村民需求），系统产出
> **可解释、可汇交**的村庄规划成果包（一图一表一规则 + 数据库），过程中 LLM 驱动的
> 空间语义理解与空间操作双向闭环。

### 1.2 核心认知修正

本方案基于以下四个核心认知修正，与历史文档的根本分歧：

| # | 认知 | 旧方案（01/00） | 本方案 |
|---|------|----------------|--------|
| 1 | **规划对象定义** | 规划对象 = 规划产出（L3/L4） | 规划对象 = 可能变更的实体（L1-L4），现状地块是规划操作的直接承受者 |
| 2 | **KG 定位** | KG 是 MIP 约束源（性能视角） | KG 是 LLM 空间语义基础设施（语义视角），L1/L2 提供"现在是什么/和谁挨着"的基础事实 |
| 3 | **规划范式** | 规划 = 分区分配（MIP 为主） | 规划 = 图斑级操作（reclassify/modify/split/merge/create）为主，MIP 配额校核为辅，双策略并存 |
| 4 | **约束编译** | MIP 直接消费 SPARQL 结果，不设编译层 | 恢复 ConstraintCompiler，单一约束编译入口，任何丢弃必须记录原因 |

### 1.3 设计原则

| # | 原则 | 含义 |
|---|------|------|
| 1 | **Schema-First** | 所有空间要素先定义类型再编码，下游只消费类型化模型，禁止 raw dict |
| 2 | **单向依赖** | Schema ← Data ← SpatialOps ← KG ← Agent，不反向依赖 |
| 3 | **四形态结构优先** | 矢量/栅格/表格/文档四形态先于语义子类，类型层面设防 |
| 4 | **实体/表达分离** | 设施是空间实体（入 KG），注记是表达要素（不入 KG） |
| 5 | **阶段抽象** | 现状/规划两态要素都有 Base 基类，共享字段上提 |
| 6 | **所有空间计算在 spatial_ops** | 任何模块不内联几何运算，不内联 shapely |
| 7 | **文本描述是一等公民** | raw_text/spatial_hint/description 保留在 KG，支持溯源和查询 |
| 8 | **闭环比对优先** | 用地平衡表、校验报告、收敛断言都是系统自身质量的度量 |

---

## 第二部分：模块化方案

### 模块 A：统一词表与契约层

**目标**：消灭 4 套并行词表，建立唯一受控词表源。

```
modules/schema/encodings/vocabulary.py（新增）
├── PlanningZone(Enum)        # 五区规划用途分区（MIP 主词表）
├── LanduseClass(Enum)        # 地类词表（GB/T 21010 编码集）
├── LANDUSE_TO_ZONE: Dict     # 唯一合法跨词表转换
└── normalize_landuse(raw)    # LLM 自由文本→受控词表，失配进 unmapped 清单
```

**改造点**：
- `parse_contracts.py:ZoneTarget.land_use` 从 `str=""` 改为 `LanduseClass`
- `mip_allocator.py` targets 键改 `PlanningZone`
- `layout_validator.py` 三区检查改对 `PlanningZone` 聚合
- `TargetPatch.zone` 改 `PlanningZone`

### 模块 B：ConstraintCompiler

**目标**：单一约束编译入口，任何丢弃必须记录原因。

```
modules/spatial_ops/constraint_compiler.py（新增）
├── CompiledConstraint        # id/scope/zone/field/operator/value/hardness/source/provenance
├── CompilationReport         # compiled[] + dropped[]+reason + conflicts[]+仲裁
└── ConstraintCompiler.compile(bundle, parse_constraints, rule_config) -> CompilationReport
    ├── 三线/VNE/保护地块：从 bundle 类型化层直算（不走 RDF→SPARQL→state 拍平）
    ├── PARSE 约束：normalize 后编译
    └── 冲突仲裁：同 scope+field 保留最严格一条
```

### 模块 C：KG 语义层强化

**目标**：L1-L4 四层都是规划对象，KG 作为 LLM 空间语义基础设施。

**C1: L1/L2 保留并强化语义查询**
- 保留 L1 现状实体（660 地块+道路+水体+设施）、L2 空间关系（touches/nearby/connected）
- ThreeZone/ThreeLine/FarmlandProtection/EcologicalRedline 保持移出 KG（v4.7），通过 ConstraintIndex 访问
- 强化 `semantic.py` 的 `get_entity_context`/`get_parcel_semantic_context` 作为 LLM 工具
- ContextBlock 与 KG 关系交叉验证

**C2: L4 补几何**
- L4 `PlannedParcelEntry` 增加 geometry 字段（WKT 或 BSM→SpatialIndex 引用）
- L4→L3 链接：`derived_from_target` 三元组写入（v4.7 已实现，验证代码层落实）

**C3: SemanticMemoryStore 覆盖全实体**
- 实体注解+关系注解覆盖 L1-L4，LLM 查询时合成返回复合结果

### 模块 D：空间操作引擎

**目标**：spatial_ops 从"只能分析"升级为"能分析+能操作"。

```
modules/spatial_ops/
├── parcel_ops.py（新增）# 几何操作：split/merge/modify/reclassify/create
└── overlay.py（新增）   # L1↔L4 overlay + parcel↔constraint overlay（用 ConstraintIndex）
```

### 模块 E：EXECUTE 双策略并存

**目标**：MIP 配额校核 + 图斑级操作并行，保留 log 方便后续调优。

```
EXECUTE Agent
├── 5a. execute_operations（主策略）→ 调用 parcel_ops 执行 SpatialOperation[]
├── 5b. execute_allocation（配额校核）→ MIP + ConstraintCompiler
├── 5c. execute_facilities → FacilityPlacer
├── 5d. execute_roads（需实现，当前空壳）
├── 5e. execute_axes → AxisBuilder
└── 5f. validate（Worker-Evaluator 循环）
```

### 模块 F：反馈闭环 + 交付门槛

**目标**：校验建议可应用且保证下轮变化；失败不交付成品。

- TargetPatch 协议（zone: PlanningZone + delta_ha/new_bound + reason）
- 收敛断言：每轮目标向量/约束集必须不同，否则 raise ConvergenceError
- DeliveryGate：用地平衡表闭合 ±0.5%、三线违规=0、保护侵入=0

### 模块 G：用地平衡表

**目标**：L1 vs L4 逐地块对比，产出国家级必选成果。

- LandBalanceRow（地类|现状面积|现状比重|规划面积|规划比重|增减）
- 纳入 DeliveryGate 的 land_balance_closed 检查

### 模块 H：输出层完善

**目标**：汇交合规成果。

- 坐标系出口转换（WGS84→CGCS2000）
- 椭球面积重算（TBMJ）
- 4 必选图层 typed model 导出
- TDYT dissolve 聚合（按 GHFLBM，非 1:1 复制）

---

## 第三部分：执行优先级

```
模块A（词表）─┐
              ├─→ 模块B（编译器）─┐
模块C1（KG语义）┘                  ├─→ 模块E（EXECUTE双策略）─┐
                                  │                          ├─→ 模块F（闭环+门槛）─→ 模块G（平衡表）─→ 模块H（输出）
模块D（空间操作）─────────────────┘                          │
                                                              │
模块C2（L4几何）──────────────────────────────────────────────┘
```

### Wave 1：契约统一（4-5 天）

| 模块 | 任务 | 产出 |
|------|------|------|
| A | 创建 `vocabulary.py`，收紧 `ZoneTarget` 契约 | PlanningZone/LanduseClass enum + normalize_landuse |
| B | 创建 `ConstraintCompiler` + `CompilationReport` | 约束编译入口，零静默丢弃 |
| C1 | 强化 `semantic.py` LLM 语义查询接口 | get_entity_context 覆盖全实体 |

### Wave 2：执行能力（5-6 天）

| 模块 | 任务 | 产出 |
|------|------|------|
| D | 创建 `parcel_ops.py` + `overlay.py` | 真实几何操作引擎 |
| C2 | L4 增加 geometry 字段 | PlannedParcelEntry 有几何 |
| E | EXECUTE 双策略接入 | MIP + 图斑操作并行+log |

### Wave 3：闭环交付（3-4 天）

| 模块 | 任务 | 产出 |
|------|------|------|
| F | TargetPatch + DeliveryGate | 反馈闭环 + 交付门槛 |
| G | LandBalanceTable 生成器 | 用地平衡表 |
| H | 输出层完善 | 汇交合规成果 |

---

## 第四部分：文档权威关系

```
模块 README（schema v4.3 / kg v4.7 / spatial_ops / parse / execute / data v4.6）
    ↑ 最权威，最贴近代码实现

02_EXECUTION_PLAN.md（本方案）
    ↑ 执行方案，统一各 README 先进设计

03_GAP_ANALYSIS.md / 04_ARCHITECTURE_AUDIT.md / 05_MODULE_BOUNDARY_AUDIT.md
    ↑ 诊断参考，P0/P1/P2 优先级编号以本方案 Wave 1/2/3 为准

00_SYSTEM_DESIGN.md
    ↑ 架构参考，§3.2/§3.5/§3.6/§5.1 以本方案和 README 为准

reference/HUMAN_PLANNING_WORKFLOW.md / EXA_FINDINGS.md
    ↑ 外部对标基线

archive/（含 01_CONTRACT_REFACTOR_PLAN.md, OPTIMIZATION_TASKS.md）
    ↑ 历史参考，已过时
```

---

## 第五部分：与历史文档的冲突处理

### 5.1 00_SYSTEM_DESIGN.md 中以下条款被本方案推翻

| 条款 | 原文 | 本方案 |
|------|------|--------|
| §3.2 | L1/L2 全量入 RDF，但实证无消费者 → 建议收缩 | L1/L2 保留，作为 LLM 空间语义基础设施 |
| §3.5 | MIP 直接消费 SPARQL 结果，不经过 ConstraintCompiler | 恢复 ConstraintCompiler，任何丢弃必须记录原因 |
| §3.6 | ThreeZone/ThreeLine 列为 L1 KG 实体 | 保持 v4.7 移出 KG，改 ConstraintIndex |
| §5.1 | MIP 降级为配额测算与校核 | 双策略并存：MIP 配额校核 + 图斑级操作 |

### 5.2 01_CONTRACT_REFACTOR_PLAN.md 已归档

其有价值的部分（受控词表设计、ConstraintCompiler、DeliveryGate）已并入本方案模块 A/B/F。

### 5.3 03/04/05 审计文档的 P0/P1/P2 优先级编号作废

以本方案 Wave 1/2/3 为准。已完成的部分不再追溯：
- `grounding.py`（03/04 标为 P0 缺失）→ 已实现
- pipeline 顺序（03/04 标为 P0 错误）→ 已修正为 fetch→build_kg→parse→execute
- EntityIdPolicy（04 标为 P0 碎片化）→ 已实现