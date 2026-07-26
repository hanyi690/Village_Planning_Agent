# 村庄规划系统 - 模块边界与编码体系审视

> **Status: [CURRENT] | Type: Module Boundary & Encoding Audit | Version: 1.0 | Created: 2026-07-26**
> **Scope**: 审视各模块数据边界、对应关系、编码体系一致性，确定规划对象 vs 参考数据的归属
> **Audience**: 系统架构师、核心开发者
> **关系**: `03_GAP_ANALYSIS.md`（功能断裂）+ `04_ARCHITECTURE_AUDIT.md`（标识契约）的深化--本文聚焦**数据边界与编码体系**

---

## 一、五种图斑的语义辨析

系统中存在 5 种 polygon 图斑类型，它们都是"地块"但语义层次完全不同：

| 类型 | 本质 | 来源 | 编码 | 角色 | 4 必选图层 |
|---|---|---|---|---|---|
| **CurrentLandUseParcel** | 现状的客观记录 | 三调调查 | DLBM（三调编码） | 参考数据（底图） | - |
| **PlannedLandUseParcel** | 规划用地（输入参考 + 产出复用） | 文件加载 / EXECUTE 产出 | QMDLBM + GHYTBM + GHFLBM | 参考 + 产出 | QMDLTB ① |
| **LandUseZone(TDYT)** | 用途管制分区 | 规划师划定 / EXECUTE 产出 | tdyfqdm（4 位） | 规划对象（聚合视图） | TDYT ② |
| **ConstructionCtrlZone(JSYDGZQ)** | 建设管制分区 | 规划师划定 / EXECUTE 产出 | tdkjgzfqdm（2 位） | 规划对象（聚合视图） | JSYDGZQ ③ |
| **PlanningScope(GHCFW)** | 规划村范围 | 行政边界 | djzqdm | 管理数据 | GHCFW ④ |

### PlannedLandUseParcel 的双角色

用户决策：**复用 PlannedLandUseParcel**，通过 L4 version 标签区分：

```
输入参考:  Data 层从 planned/landuse.geojson 加载 -> KG 不消费（仅 bundle 持有）
产出成果:  EXECUTE 产出 -> KG L4 PlannedState（versioned）
```

编码体系相同（QMDLBM/GHYTBM/GHFLBM），但生命周期不同：一个是输入参考，一个是输出成果。

---

## 二、五种图斑的内在规划逻辑联系

### 2.1 规划操作流

```
三调数据（原始 GeoJSON）
    │
    ▼ 基数转换（DLBM -> JQXZYDFLDM）     ← 系统缺失这一步
    │
CurrentLandUseParcel（基期现状图斑）
    │  "这块地现在是什么"（DLBM=0101 水田）
    │
    ├───[大部分不变]──-> 规划地类 = 基期现状地类（reclassify: 保持）
    ├───[部分修改]──-> 规划地类 ≠ 基期现状地类（modify: 0101->0703）
    └───[少数裁剪]──-> split: 一个现状图斑 -> 多个规划图斑
    │
    ▼
PlannedLandUseParcel / QMDLTB（期末地类图斑）── 4 必选图层 ①
    │  "这块地规划后变成什么"（QMDLBM=0703 农村宅基地）
    │  derived_from_bsm -> CurrentLandUseParcel
    │
    ├───[按用途聚合]──-> LandUseZone(TDYT) ── 4 必选图层 ②
    │                   "这片区域是村庄建设区"
    │                   多个 PlannedParcel -> 一个 TDYT 多边形（dissolve）
    │
    └───[按管制聚合]──-> ConstructionCtrlZone(JSYDGZQ) ── 4 必选图层 ③
                        "这片区域允许建设"
                        独立绘制（unary_union，不严格对齐图斑边界）
```

### 2.2 几何关系：聚合 vs 1:1 vs 独立绘制

**用户洞察**："地块和各种分区不一定是完全被覆盖的吧？比如规划分区会重新编辑地块"。

**完全正确**。人类规划师会"重新编辑"分区边界：

| 图层 | 与 QMDLTB 的几何关系 | 当前实现 | 应该 |
|---|---|---|---|
| **QMDLTB** | 基准 | MIP 分配 + procedural 生成 | 从 CurrentLandUseParcel 经基数转换 + 操作而来 |
| **TDYT** | 应为聚合（dissolve by 用途） | ❌ 1:1 复制（只改标签不合并几何） | dissolve by GHYTBM/GHFLBM |
| **JSYDGZQ** | 独立绘制 | ✅ unary_union 真实聚合 | 正确 |
| **三区** | 派生（从 planning_zone -> primary_zone） | ❌ 从 rule_loader 生成概念表 | 从 QMDLTB 的 planning_zone 聚合 |

**关键规则**：TDYT/JSYDGZQ 与 QMDLTB 不是严格的包含关系，而是"应该拓扑一致但几何可能不同"。规划师可能：
- TDYT：dissolve 合并相邻同类地块（边界简化）
- JSYDGZQ：独立绘制大范围管制区（不考虑图斑边界）
- 三区三线：从上位规划落实（完全独立几何）

### 2.3 人类规划师的实际操作（HUMAN_PLANNING_WORKFLOW §11）

人类规划师**不重新画图斑**，而是：
1. 加载三调图斑（CurrentLandUseParcel 的几何）
2. 新建"规划地类"字段
3. **字段计算器赋值**：大部分 `规划地类 = 基期现状地类`（批量保持）
4. 逐个修改需要调整的图斑：`规划地类 = 0703`（modify）
5. 少数裁剪：裁剪面工具（split）
6. 输出 QMDLTB

**所以 PlannedParcel 的几何 = CurrentLandUseParcel 的几何（大部分），只是属性变了。**

### 2.4 系统当前的断裂

| 操作 | 人类规划师 | 系统当前 | 差距 |
|---|---|---|---|
| 基数转换 | 字段计算器 DLBM->JQXZYDFLDM | ❌ 不执行 | Data 层缺失 |
| 批量保持现状 | 规划地类 = 基期现状地类 | ❌ MIP 全部分配 | EXECUTE 不支持 reclassify |
| 逐个修改 | 字段计算器改规划地类 | ❌ _apply_operations 假操作 | 只改 area_ha 不改 geometry |
| 裁剪 | 裁剪面工具 | ❌ procedural.py dormant | 真实几何操作未接入 |
| 输出 QMDLTB | 导出图层 | ⚠️ 产出 allocated_geojson(dict) | 不是 typed model |

---

## 三、编码体系全景

### 3.1 多维度并行，不是链式

**用户洞察**："到底应该怎么使用不同的编码体系，有的是三调编码，有的是规划层的"。

编码之间不是简单的链条，而是**同一块地的不同分类视角**：

```
                    同一块地（几何相同）
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    DLBM(三调)      GHYTBM(附录5)    GHFLBM(规划分类)
    "现状是什么"    "规划用途是什么"   "粗分类是什么"
    0101 水田       1100 耕地          1100 农业用地
         │               │               │
         ▼               ▼               ▼
    planning_zone    zone_type        tdyfqdm
    (6值,管制视角)   (9值,功能视角)   (4位,用途分区)
    一般农业区       农业用地          (应来自GHFLBM)
         │
         ▼
    primary_zone(三区)
    农业空间
```

**关键发现**：`tdyfqdm`、`tdkjgzfqdm`、`primary_zone` 不是从 DLBM/GHYTBM 链式推导的，它们是**独立的分类维度**：

| 维度 | 编码 | 值域 | 描述 |
|---|---|---|---|
| 现状用途 | DLBM | 73 类（三调） | 这块地**现在**是什么 |
| 规划用途 | GHYTBM | 21 类（附录5） | 这块地**规划后**是什么 |
| 规划粗分类 | GHFLBM | 10 类 | GHYTBM 的上级归类 |
| 功能分区 | zone_type | 9 值 | 居住/农业/生态/水域... |
| 管制分区 | planning_zone | 6 值 | 农田保护/一般农业/村庄建设... |
| 用途分区 | tdyfqdm | 4 位码 | TDYT 图层的法定编码 |
| 建设管制 | tdkjgzfqdm | 2 位码 | JSYDGZQ 图层的法定编码 |
| 三区 | primary_zone | 3 值 | 生态/农业/建设空间 |

**前 5 个是地块级属性**（每个图斑一个值），**后 3 个是分区级属性**（每个分区多边形一个值）。

### 3.2 各图层使用的编码

| 4 必选图层 | 字段 | 编码体系 | 来源标准 |
|---|---|---|---|
| **GHCFW**（规划村范围） | djzqdm | GB/T 2260 行政区划码 | 管理类 |
| **QMDLTB**（期末地类图斑） | DLBM + QMDLBM + GHYTBM + GHFLBM | 三调 + 粤国土资规保发〔2009〕67号 + 附录5 + ghflbm | 核心规划 |
| **TDYT**（土地用途分区） | tdyfqdm | 粤国土资规保发〔2009〕67号（4 位乡规码） | 核心规划 |
| **JSYDGZQ**（建设用地管制区） | tdkjgzfqdm | 粤国土资规保发〔2009〕67号（01-06 或 510-540） | 核心规划 |

### 3.3 编码映射的基数关系

| 映射步骤 | 基数 | 说明 |
|---|---|---|
| DLBM -> GHYTBM | **多:1** | 无官方映射表，appendix5.yaml 有反向 dlbm_ref 但不可靠 |
| GHYTBM -> GHFLBM | **多:1** | `GHFLBM_TO_GHYTBMS`: 如 2120 ← [2121,2122,2123,2124,2125,2126] |
| GHYTBM -> zone_type | **多:1** | 如 2121/2100 都 -> 居住用地 |
| GHYTBM -> VNE | **多:1** | 如 1100/1200/1340/1500 都 -> E23 |
| zone_type -> planning_zone | **多:1** | 启发式，非确定性（`if "林" in ghytmc`） |
| planning_zone -> primary_zone | **多:1** | 确定性，6->3 硬编码 |
| tdyfqdm <-> tdkjgzfqdm | **无映射** | 两个独立图层，并行 facet，不链式推导 |
| tdkjgzfqdm -> primary_zone | **无直接映射** | 三区从 planning_zone 派生，不从 TDKJGZFQDM |

---

## 四、编码体系缺陷（10 项）

### GAP-A: TDYTFQDM 编码体系错误 🔴

- **声明**（spatial_types.py:562）: TDYTFQDM = TD/T 1028-2010 4 位乡规码
- **实际**（land_use_zone_generator.py:254）: 写入 VNE 字母码（V11/E23/N1）
- **后果**: TDYT 图层的法定编码字段填入了错误编码体系的值
- **修复**: 生成器应查 GHFLBM -> TDYTFQDM 映射，而非 GHYTBM -> VNE

### GAP-B: TDKJGZFQDM 双编码体系冲突 🔴

| 来源 | 编码 | 数量 |
|---|---|---|
| spatial_types.py SPACE_CONTROL_ZONE_TYPES | 01,02,03,04,05,06 | 6 值 |
| space_control_generator.py + planning_zone_rules.yaml | 510,520,530,540 | 4 值 |

- 01-06 含永久基本农田保护区(05)和生态保护红线区(06)，510-540 无对应
- 540(禁止建设区)把 01-06 中的 04+05+06 合并
- **修复**: 统一为一套编码，建议用 01-06（更细，符合三区三线要求）

### GAP-C: dlbm_to_planning_zone 测试假阳性 🟡

- `DLBM_TO_PLANNING_ZONE` 仅从 tugui.yaml 构建（appendix5 无 planning_zone 字段）
- tugui.yaml 无 "0101"（有 "0110"），测试 `assert dlbm_to_planning_zone("0101") == "一般农业区"` 靠默认值通过
- **修复**: 补充 tugui 编码或改测试用 tugui 实有编码

### GAP-D: DLBM->GHYTBM 正向映射不存在 🔴

- appendix5.yaml 有反向 `dlbm_ref`（GHYTBM -> DLBM），但：
  - `code_sets.py` 从不加载 `dlbm_ref`
  - `dlbm_ref` 本身不可靠（混用 gbt21010/ydyhfldm 编码）
- **后果**: 基数转换无法自动执行（DLBM 无法推导出 GHYTBM）
- **修复**: 构建正向 DLBM->GHYTBM 映射表，或在 ingest 阶段要求源数据提供 GHYTBM

### GAP-E: PLANNING_ZONE_COLORS 导入不存在文件 🟡

- `classification.py:216` 导入 `from .colors import PLANNING_ZONE_COLORS`
- `colors.py` 文件不存在
- **修复**: 创建 colors.py 或删除导入

### GAP-F: field_defaults.yaml 引用不存在的 lookup 🟡

- 引用 `ghflbm_to_code`、`ghflbm_to_name`、`space_control_code`、`space_control_name`
- 这些 lookup 在 code_sets.py 中不存在
- **修复**: 实现这些 lookup 或删除规则

### GAP-G: dlbm_ref 混用编码体系 🟡

- `2123` -> `dlbm_ref: "1300"`（ydyhfldm 码，gbt21010 无 1300）
- `2126` -> `dlbm_ref: "0601"`（工业用地，语义错误，应为村内交通）
- **修复**: 审查并修正所有 dlbm_ref

### GAP-H: GHYTMC_TO_PLANNING_ZONE 用字符串包含启发式 🟡

- `code_sets.py:128-148` 用 `if "林" in ghytmc` 规则
- 非确定性，可能误分类
- **修复**: 用显式映射表替代字符串包含

### GAP-I: 三区不是 4 必选图层 🟡

- 系统把 ThreeZone 当独立实体存储（从 rule_loader 生成）
- 实际三区是从 planning_zone 派生的（`PLANNING_ZONE_TO_PRIMARY_ZONE`）
- **修复**: 三区改为派生关系，不从 rule_loader 生成

### GAP-J: zone_type 值域不统一 🟡

- 三个来源定义了不同的 zone_type 值域：
  - ConstructionCtrlZone 文档: 6 值（01-06）
  - planning_zone_rules.yaml: 4 值（510-540）
  - 广东指南: 4 值（允许/限制/有条件/禁止）
- **修复**: 统一值域

---

## 五、各模块数据边界审视

### 5.1 Data 模块

```
当前边界:
  输入: GeoJSON 文件
  处理: 编码验证 + 类型化(ingest)
  输出: VillageBundle(typed)
  
缺失:
  ❌ 基数转换: 三调 DLBM -> 规划用途 JQXZYDFLDM 不发生
  ❌ 现状-规划对照: 660 现状 vs 582 规划 无映射机制
  ❌ BSM 缺失处理: 默认空字符串，不生成稳定 ID
```

**应做**: Data 应增加"基数转换"步骤（用户决策：Data 层 ingest 阶段执行），将三调编码转换为规划用途编码。这是 HUMAN_PLANNING_WORKFLOW §8 明确要求的"现状->规划第一步"。

### 5.2 KG 模块

```
当前边界:
  输入: VillageBundle + ParcelRelations + Intent + PlannedState
  处理: L1 实体构建 + L2 关系注入 + L3 意图 + L4 规划增量
  输出: RDF 图(SPARQL 可查询)
  
缺失:
  ❌ within_zone 不写入: parcel->Zone 关系空，约束验证空转
  ❌ L4 无几何: PlannedParcel 只有 BSM+属性 delta
  ❌ L4->L3 链接未实现: derived_from_target 字段定义但不读
  ❌ URI 碎片化: 6 种方案，仅 Parcel 存 PLN.bsm literal
  ❌ ThreeZone 脱离 bundle: 读 rule_loader 而非 bundle.polygons.three_zones
```

**应做**:
- spatial_ops 计算 parcel↔constraint polygon overlay -> KG 写 within_zone
- L4 PlannedParcel 增加几何引用（通过 BSM -> SpatialIndex）
- 统一 EntityIdPolicy（见 `04_ARCHITECTURE_AUDIT.md`）

### 5.3 Spatial Ops 模块

```
当前边界:
  输入: VillageBundle
  处理: ContextBlock 计算 + ParcelRelations 计算 + SpatialIndex 查询
  输出: ContextBlock 列表 + ParcelRelations + SpatialIndex(运行时)
  
缺失:
  ❌ 无几何操作: split/merge/modify/create 的几何执行不存在
  ❌ grounding.py 不存在: PARSE 空间接地无法执行
  ❌ 无 overlay 分析: parcel↔constraint polygon 相交计算不存在
  ❌ SpatialIndex 只覆盖 parcels: 不索引 roads/facilities/water/constraints
  ❌ 无基数转换工具
```

**应做**:
- 新增 `parcel_ops.py`: 真实几何 split/merge/modify（参考 procedural.py 的 dormant 代码）
- 实现 `grounding.py`: PARSE 空间接地
- 扩展 `bridge.py`: SpatialIndex 覆盖所有 KG 实体类型对应的 bundle 要素
- 新增 overlay: parcel↔constraint polygon -> 写入 KG within_zone

### 5.4 PARSE Agent

```
当前边界:
  输入: 规划文本 + KG 查询工具 + ContextBlock
  处理: Think-Then-Format -> SpatialPlanningIntent + SpatialOperation + SpatialConstraint
  输出: SpatialPlanningIntent(typed) + operation_sequence + constraint_set
  
缺失:
  ❌ 查询空 KG: pipeline 顺序错误，PARSE 在 KG 构建前运行
  ❌ 空间接地不存在: grounding.py 未实现
  ❌ SpatialOperation 无几何参数: split 有 split_ratio 但无切割线
```

### 5.5 EXECUTE Agent

```
当前边界:
  输入: SpatialPlanningIntent + operation_sequence + VillageBundle + KG 上下文
  处理: MIP 分配 + Facility 放置 + Axis 生成 + _apply_operations(假操作) + 验证
  输出: allocated_geojson + layout_configs(图层列表)
  
缺失:
  ❌ _apply_operations 是假操作: split 只改 area_ha 不改 geometry
  ❌ procedural.py 有真实几何操作但 dormant
  ❌ 不产出 PlannedLandUseParcel(typed): 产出 allocated_geojson(dict)
  ❌ 不产出 LandUseZone/ConstructionCtrlZone(typed): 只产出 layer dict
  ❌ 不产出用地平衡表
  ❌ 验证空转: within_zone 不写入
  ❌ Road 生成空壳
```

**关键发现**: EXECUTE 的 `_apply_operations`（tools/gis/generate.py:573-689）与 procedural.py 的 `merge_parcels`/`split_by_area` 存在能力重复但都未正确接入：
- `_apply_operations`: 属性级假操作（改 area_ha，不改 geometry）
- `procedural.py`: 真实几何操作（dissolve/intersect），但标注 "not currently used in production"

### 5.6 输出层

```
当前边界:
  输入: layout_configs(图层列表) + allocated_geojson
  处理: export_gdb(每层写 GeoJSON) + render_map(PNG)
  输出: GeoJSON 文件 + land_balance.json + PNG
  
缺失:
  ❌ 不产出 .mdb: 只有 GeoJSON，无 Personal Geodatabase
  ❌ 不产出 5 目录汇交结构
  ❌ land_balance.json 不完整: 只有总量，无 L1vsL4 逐地块对比
  ❌ 不产出管制规则 PDF
  ❌ 不产出现状图（两图之一）
```

---

## 六、规划对象 vs 参考数据的模块归属

### 6.1 用户决策的 KG 范围

用户明确："KG 应该只需要规划对象"、"这些就不能通过空间操作层桥接吗"。

| 实体 | 类型 | 当前归属 | 应归属 | 处理方式 |
|---|---|---|---|---|
| CurrentLandUseParcel | 参考 | Data->KG L1 | Data->KG L1 | ✅ 正确 |
| PlannedLandUseParcel | 规划对象 | Data 加载->KG 不消费 | EXECUTE 产出->KG L4 | 复用类型，L4 version 标签 |
| Road/Facility(现状) | 参考 | Data->KG L1 | Data->KG L1 | ✅ 正确 |
| Road/Facility(规划) | 规划对象 | 不存在 | EXECUTE 产出->KG L4 | 需实现 |
| LandUseZone(TDYT) | 规划对象+参考 | Data 加载->KG L1 Zone | 双角色：参考+产出 | L4 version 区分 |
| ConstructionCtrlZone | 规划对象+参考 | Data 加载->KG L1 Zone | 双角色：参考+产出 | L4 version 区分 |
| FarmlandProtection | 参考 | Data 加载->KG 不消费 | spatial_ops 桥接 | ✅ 正确 |
| EcologicalRedline | 参考 | Data 加载->KG 不消费 | spatial_ops 桥接 | ✅ 正确 |
| ThreeZone/ThreeLine | 参考(上位落实) | KG 从 rule_loader 生成 | spatial_ops 桥接或派生 | 改为派生 |
| 基数转换结果 | 规划对象(中间态) | 不存在 | Data 层产出 | 需实现 |
| 用地平衡表 | 规划对象(成果) | export 层雏形 | 独立生成器 | 需完善 |

### 6.2 聚合关系存储

用户决策：**KG 关系层**（PlannedParcel 通过 `PLN.within_zone` -> PlannedZone 关联）。

但用户正确指出："地块和各种分区不一定是完全被覆盖的"。所以：
- `within_zone` 关系表示"地块**主要属于**哪个分区"（基于 planning_zone 或 GHFLBM）
- 分区几何可能与地块聚合几何不完全一致（规划师可能重新编辑边界）
- `within_zone` 是**语义归属**，不是严格的几何包含

---

## 七、完整数据流（应有 vs 当前）

### 7.1 应有的数据流

```
三调 GeoJSON
  -> Data 层基数转换(JQXZYDFLDM)
  -> KG L1(现状实体 + within_zone)
  -> PARSE(查询 KG -> 产出 Intent + Operation)
  -> EXECUTE(执行 Operation -> 几何操作)
  -> KG L4(规划成果 + 几何)
  -> 用地平衡表(L1 vs L4 对比)
  -> GDB 导出
```

### 7.2 当前的数据流

```
三调 GeoJSON
  -> Data(验证不转换)
  -> KG L1(实体无 within_zone)
  -> PARSE(查空 KG -> 靠 ContextBlock 猜)
  -> EXECUTE(MIP 分配 + 假操作 + procedural 生成)
  -> allocated_geojson(独立几何，与现状无关联)
  -> GeoJSON 文件(无平衡表)
```

### 7.3 断裂根因

| 断裂点 | 根因 | 影响 |
|---|---|---|
| 基数转换缺失 | Data 层只验证不转换 | 规划操作建立在错误分类基础上 |
| within_zone 空转 | spatial_ops 无 overlay，KG 不写 | 约束验证永远返回空 |
| EXECUTE 假操作 | _apply_operations 只改属性不改几何 | split/merge 不产生真实几何变化 |
| L4 无几何 | PlannedParcelEntry 无 geometry 字段 | 无法导出规划图层 |
| 无平衡表 | 无 L1vsL4 逐地块对比 | 必选成果缺失 |

---

## 八、模块边界重新定义

| 模块 | 应做 | 不应做 |
|---|---|---|
| **Data** | 加载 + 验证 + **基数转换** | 不做规划操作 |
| **KG** | 存储规划对象实体的**空间关系**（within_zone/derived_from） | 不存参考数据几何、不做计算 |
| **spatial_ops** | 分析(overlay/buffer/index) + **操作(split/merge/modify 几何)** + 桥接(BSM->geometry) | 不做规划决策 |
| **PARSE** | 理解文本 -> **接地** -> 产出 Intent + Operation | 不做空间操作 |
| **EXECUTE** | 消费 Operation -> **调用 spatial_ops 执行几何操作** -> 产出规划图层 | 不内联几何计算 |
| **输出** | L1vsL4 对比 -> **平衡表** + GDB + 图 | - |

---

## 九、修复优先级

### P0（不修复无法运行）

| # | 修复 | 模块 | 理由 |
|---|---|---|---|
| 1 | pipeline 顺序 | Agent | PARSE 查空 KG |
| 2 | within_zone 写入 | spatial_ops+KG | 约束验证空转 |
| 3 | 真实几何操作 | spatial_ops | EXECUTE 假操作 |
| 4 | 基数转换 | Data | 现状->规划第一步缺失 |
| 5 | GAP-A: TDYTFQDM 编码 | schema/generation | 编码体系错误 |
| 6 | GAP-B: TDKJGZFQDM 统一 | schema/generation | 编码体系冲突 |

### P1（不修复无法产出可用规划）

| # | 修复 | 模块 | 理由 |
|---|---|---|---|
| 7 | L4 几何 | KG | 无导出几何 |
| 8 | 用地平衡表 | 输出 | 必选成果缺失 |
| 9 | EntityIdPolicy | KG | 实体不可追溯 |
| 10 | grounding 实现 | spatial_ops | PARSE 空间接地 |
| 11 | GAP-D: DLBM->GHYTBM 映射 | schema | 基数转换前置依赖 |
| 12 | GAP-I: 三区改为派生 | KG | 概念混淆 |
| 13 | TDYT dissolve 聚合 | generation | TDYT 应聚合非 1:1 复制 |

### P2（不修复无法达到交付质量）

| # | 修复 | 模块 | 理由 |
|---|---|---|---|
| 14 | GAP-C: 测试假阳性 | tests | 测试不验证真实映射 |
| 15 | GAP-E/F/G/H: 编码清理 | schema | 编码体系不一致 |
| 16 | .mdb 导出 | 输出 | 汇交格式 |
| 17 | 通则式模式 | 全局 | 第三种输出模式 |

---

## 附录 A：编码体系映射全表

### DLBM(三调) -> GHYTBM(附录5) -> 分区推导链

```
DLBM(三调)     GHYTBM(附录5)    GHFLBM    zone_type      planning_zone    primary_zone
─────────────────────────────────────────────────────────────────────────────────────────
0101 水田      1100 耕地        1100      农业用地       农田保护区        农业空间
0102 水浇地    1100 耕地        1100      农业用地       农田保护区        农业空间
0103 旱地      1100 耕地        1100      农业用地       农田保护区        农业空间
0201 果园      1200 园地        1200      农业用地       一般农业区        农业空间
0301 乔木林地  1340 商品林      1300      农业用地       林业发展区        农业空间
0301 乔木林地  1350 生态林      1300      生态绿地       生态控制区        生态空间
0702 农村宅基地 2121 宅基地      2120      居住用地       村庄建设区        建设空间
0809 公用设施  2141 基础设施    2140      公共服务用地   村庄建设区        建设空间
0601 工业用地  2150 经营性      2150      产业用地       村庄建设区        建设空间
1101 河流水面  3100 水域        3100      水域           生态控制区        生态空间
```

> **注意**：同一 DLBM(0301 乔木林地) 可映射到两个 GHYTBM（1340 商品林 / 1350 生态林），
> 取决于林业部门认定。这是"一对多"基数转换的典型场景。

### 4 必选图层编码对照

```
QMDLTB:  DLBM(4) + QMDLBM(4) + GHYTBM(4) + GHFLBM(4) + GHYTMC(20)
TDYT:    TDYTFQDM(4) ← 应来自 GHFLBM 聚合（当前错误写 VNE）
JSYDGZQ: TDKJGZFQDM(2) ← 应统一为 01-06（当前冲突 01-06 vs 510-540）
GHCFW:   DJZQDM(12) + MJ + BZ
```

---

## 附录 B：文件权重索引

| 文件 | 角色 |
|---|---|
| `schema/types/spatial_types.py` | 5 种图斑类型定义 + 编码字段 |
| `schema/encodings/code_sets.py` | 编码映射函数（6 个体系） |
| `schema/encodings/dicts/appendix5.yaml` | GHYTBM 21 类定义 |
| `schema/encodings/dicts/tugui.yaml` | QMDLBM 规划编码 |
| `schema/encodings/dicts/planning_zone_rules.yaml` | 管制分区 510-540 定义 |
| `tools/gis/_generation/land_use_zone_generator.py` | TDYT 生成器（GAP-A） |
| `tools/gis/_generation/space_control_generator.py` | JSYDGZQ 生成器（GAP-B） |
| `tools/gis/_generation/optimizer/procedural.py` | 真实几何操作（dormant） |
| `tools/gis/generate.py:_apply_operations` | 假操作（属性级） |
| `agent/gis/layout_pipeline.py` | 顶层编排（pipeline 顺序） |
| `agent/gis/execute/agent.py` | EXECUTE 子图 |
| `data/ingest.py` | 唯一 raw->typed 端口（无基数转换） |
