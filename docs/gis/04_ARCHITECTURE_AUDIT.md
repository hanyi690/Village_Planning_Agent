# 村庄规划系统 - 架构规整审视

> **Status: [CURRENT] | Type: Architecture Audit | Version: 1.0 | Created: 2026-07-26**
> **Scope**: 从全局审视各模块是否符合规范、是否优美、修复方向
> **Audience**: 系统架构师、核心开发者
> **关系**: `03_GAP_ANALYSIS.md` 关注"功能断裂"，本文关注"结构优美性与规范性"

---

## 一、核心问题：没有统一的实体标识契约

### 1.1 现状

`SpatialFeature` 基类（`schema/types/base.py:39`）定义了 `bsm: str = ""` 作为所有空间要素的标识码。这是**唯一**被设计为跨层 foreign key 的字段。

但 KG builder 中，只有 `_add_parcels` 遵守了这个契约--存储 `PLN.bsm` literal 谓词。其他 14 个 `_add_*` 函数各自发明 URI 方案：

| 方案                                                     | 使用者                                                  | 问题                                     |
| -------------------------------------------------------- | ------------------------------------------------------- | ---------------------------------------- |
| `PLN.bsm` literal + `parcel_{bsm}_{dlbm}_{area}` URI | Parcel, PlannedParcel                                   | ✅ 正确，可 SPARQL 查询                  |
| BSM 嵌入 URI fragment（`road_{bsm}`），无 literal      | Road, WaterBody                                         | ⚠️ 不可 SPARQL 查询，fallback 到 count |
| name + count（`facility_typed_{name}_{count}`）        | Facility (typed), Facility (ann)                        | ❌ 不稳定，重排即变                      |
| count only（`hazard_line_{count}`）                    | hazard_line, flood_line, zone_conditional, zone_jsydgzq | ❌ 完全不可追溯                          |
| code（`tdyt_{code}`）                                  | Zone (TDYT)                                             | ❌ 同码碰撞                              |
| schema dict（`three_zone_{primary_zone}`）             | ThreeZone, ThreeLine                                    | ❌ 不是 bundle 实体                      |

### 1.2 优美方案：统一标识契约

**原则**：每个 KG 实体必须能通过一个 SPARQL 查询定位回 bundle 中的原始要素。

```python
# ontology.py 新增：统一 ID 策略
class EntityIdPolicy:
    """所有 KG 实体的标识契约。"""

    @staticmethod
    def uri(entity_type: str, bsm: str, version: int = 0) -> URIRef:
        """生成稳定、可查询的实体 URI。"""
        if version > 0:
            return PLN[f"{entity_type}_{bsm}_v{version}"]
        return PLN[f"{entity_type}_{bsm}"]

    @staticmethod
    def attach_bsm(graph, uri, bsm: str):
        """统一存储 bsm literal，使所有实体可 SPARQL 查询。"""
        if bsm:
            graph.add((uri, PLN.bsm, Literal(bsm)))
```

**应用规则**：

- L1 实体：`uri = EntityIdPolicy.uri(type, bsm)`，存 `PLN.bsm` literal
- L3 实体：`uri = EntityIdPolicy.uri("zone_target", zone_id)`，存 `PLN.zone_id` literal（无 bsm，因为是意图而非现状）
- L4 实体：`uri = EntityIdPolicy.uri(type, bsm, version)`，存 `PLN.bsm` + `PLN.derived_from` -> L1

**fallback 策略**（BSM 缺失时）：

- 使用 `ysdm`（要素代码）+ 序号：`{type}_{ysdm}_{seq}`，存 `PLN.ysdm` literal
- 不允许纯 count 索引作为 URI

---

## 二、KG 模块审视

### 2.1 当前不优美之处

#### (a) URI 方案碎片化（见 §一）

14 个 `_add_*` 函数，6 种不同的 URI 方案。这是最大的不优美。

#### (b) ThreeZone/ThreeLine 脱离 bundle

`_add_three_zone_three_line()` 完全不读 `bundle.polygons.three_zones`，而是从 `rule_loader()` schema 字典生成"参考实体"。bundle 中有 `ThreeZoneItem`（带 BSM + geometry + zone_type），被完全忽略。

**后果**：KG 中的三区三线是"概念表"不是"空间实体"，无法做 overlay 验证。

#### (c) L4->L3 链接定义了但未实现

`PlannedZoneEntry.derived_from_target`、`PlannedFacilityEntry.derived_from_target` 等字段在 dataclass 中定义，但 `_apply_planned_state` 从不读取。L4 与 L3 之间无追溯链。

#### (d) L2 层是空壳

`layer2.py` 只有 7 行 docstring。L2 关系实际在 `layer1._add_parcel_relations` 中写入。Mixin 结构名不副实。

#### (e) RoadTarget 是死实体

`ontology.py` 声明了 `RoadTarget`（L3），`layer3.py` 的 `_L3_TYPES` 集合包含它，但 `build_intent_layer` 从不创建。

#### (f) README §2.3 方法名过时

KG README 的实体->bundle 映射表引用了不存在的方法：`_add_infrastructure_from_typed`、`_add_constraints_from_typed`（v4.6 已删除）。

### 2.2 修复方向

| #  | 问题                  | 修复                                                                                              | 优先级     |
| -- | --------------------- | ------------------------------------------------------------------------------------------------- | ---------- |
| K1 | URI 方案碎片化        | 引入`EntityIdPolicy`，所有 `_add_*` 统一使用 bsm literal                                      | P0         |
| K2 | ThreeZone 脱离 bundle | `_add_three_zone_three_line` 改读 `bundle.polygons.three_zones`                               | P0         |
| K3 | L4->L3 链接未实现     | `_apply_planned_state` 读取 `derived_from_target` 字段，写 `pln:derived_from_target` 三元组 | P1         |
| K4 | L2 空壳               | 将`_add_parcel_relations` 移入 `layer2.py`，或合并 layer1+layer2                              | P2         |
| K5 | RoadTarget 死实体     | 要么实现，要么从 ontology 删除                                                                    | P2后续实现 |
| K6 | README 过时           | 更新方法名表、新增 URI 策略章节、新增实体标识契约章节                                             | P0         |

### 2.3 优美的 KG 应该是什么样

```
每个 KG 实体:
  ├── URI: {type}_{bsm}        (L1) / {type}_{bsm}_v{version}  (L4)
  ├── PLN.bsm: Literal(bsm)    (统一可查询)
  ├── PLN.entity_type: type    (类型声明)
  ├── PLN.layer: L1/L3/L4      (层归属)
  └── 属性谓词                  (type-specific)

每个 KG 关系:
  ├── subject URI (L1/L3/L4 实体)
  ├── predicate (touches/nearby/derived_from/...)
  └── object URI 或 Literal

SPARQL 查询:
  "BSM=xxx 的实体" -> ?s pln:bsm "xxx" -> 唯一确定
  "L4 规划实体源自哪个 L1" -> ?l4 pln:derived_from ?l1
  "L4 规划源自哪个 L3 意图" -> ?l4 pln:derived_from_target ?l3
```

---

## 三、Schema 模块审视

### 3.1 当前不优美之处

#### (a) BSM 契约未显式化

`SpatialFeature.bsm` 是 `str = ""`（空字符串默认值）。这意味着 BSM 可以缺失，但 Schema 没有提供"BSM 缺失时的生成策略"或"BSM 必填校验"。结果是大量 BSM 为空的要素进入系统，下游 KG 无法追溯。

#### (b) 缺少规划结果类型

- `LandBalanceRow` / `LandBalanceTable` 完全缺失
- `PlannedLandUseParcel` 有定义但与 L4 `PlannedParcelEntry` 重复（两套模型）
- `SpatialOperation` 有 5 种操作定义但无操作参数 schema（split 的切割线、merge 的目标列表）

#### (c) PlanBlock 不继承 SpatialCognitiveUnit

L4 的 `PlanBlock` / `ParcelChange` / `FacilityChange` / `RoadChange` 不继承 `SpatialCognitiveUnit`，导致 L4 实体无法参与语义查询。这是设计不一致。

### 3.2 修复方向

| #  | 问题                    | 修复                                                             | 优先级 |
| -- | ----------------------- | ---------------------------------------------------------------- | ------ |
| S1 | BSM 契约弱              | `bsm` 改为 computed field：缺失时用 `ysdm + seq` 生成稳定 ID | P1     |
| S2 | 缺平衡表类型            | 新增`LandBalanceRow` + `LandBalanceTable` schema             | P1     |
| S3 | SpatialOperation 无参数 | 为 5 种操作各定义参数 dataclass                                  | P1     |
| S4 | PlanBlock 不继承 SCU    | L4 delta 继承 SpatialCognitiveUnit                               | P2     |

---

## 四、Spatial Ops 模块审视

### 4.1 当前不优美之处

#### (a) 只有"分析"没有"操作"

spatial_ops 有 context（认知卡片）、geometry（关系计算）、bridge（空间索引）、relations（方向邻接），但**没有任何几何操作函数**：split、merge、clip、buffer、dissolve 全部缺失。

规划的 create/split/merge/modify/reclassify 全部需要几何操作，这是 spatial_ops 最大的能力缺口。

#### (b) grounding.py 是空文件

README 设计了完整的 grounding API（resolve_directional_bbox、query_parcels_in_bbox、compute_proximity_weights、ground_zone_spatial_preference），但文件不存在。PARSE 的空间接地完全无法执行。

#### (c) 三职责不对称

- 职责 A（KG 输入）：✅ 完整
- 职责 B（PARSE 接地）：❌ 未实现
- 职责 C（EXECUTE 桥接）：✅ 刚实现

### 4.2 修复方向

| #  | 问题                    | 修复                                                                         | 优先级 |
| -- | ----------------------- | ---------------------------------------------------------------------------- | ------ |
| O1 | 无几何操作              | 新增`parcel_ops.py`：split/merge/modify/reclassify/create 的几何执行       | P0     |
| O2 | grounding 不存在        | 实现`grounding.py`                                                         | P0     |
| O3 | 无 overlay 分析         | `bridge.py` 新增 `overlay_analysis(planned_geom) -> List[OverlapResult]` | P1     |
| O4 | 无 buffer/clip/dissolve | 新增`geometry_ops.py` 通用几何工具                                         | P1     |

---

## 五、Data 模块审视

### 5.1 当前不优美之处

#### (a) 现状-规划对照语义缺失

Data 层把 `planned/landuse.geojson` 当另一个"现状"加载，没有"对照"语义。660 现状地块 vs 582 规划地块，BSM 不一一对应，Data 层不提供任何映射机制。

#### (b) BSM 缺失不报错

ingest 阶段如果 GeoJSON 没有 BSM 字段，`bsm` 默认空字符串，不报错。导致下游 KG 只能用 count 索引。

### 5.2 修复方向

| #  | 问题           | 修复                                                              | 优先级 |
| -- | -------------- | ----------------------------------------------------------------- | ------ |
| D1 | 无对照语义     | 新增`compute_parcel_mapping(current, planned) -> ParcelMapping` | P1     |
| D2 | BSM 缺失不报错 | ingest 阶段 BSM 缺失时生成稳定 ID（ysdm+seq）并 warning           | P1     |

---

## 六、Agent 模块审视

### 6.1 PARSE Agent

#### 不优美之处

- pipeline 顺序错误（PARSE 在 KG 构建前运行）
- 空间接地不存在（grounding.py 未实现）
- SpatialOperation 提取只有标签无参数

#### 修复方向

| #  | 问题             | 修复                                   | 优先级 |
| -- | ---------------- | -------------------------------------- | ------ |
| P1 | pipeline 顺序    | 调整为 fetch->build_kg->parse->execute | P0     |
| P2 | 空间接地         | 实现 grounding.py，PARSE 调用          | P0     |
| P3 | operation 无参数 | SpatialOperation schema 补充参数       | P1     |

### 6.2 EXECUTE Agent

#### 不优美之处

- 无真实空间操作（MIP 分配 ≠ 地块操作）
- procedural 生成 ≠ 现状修改
- 验证空转（within_zone 不写入）
- @tool 绕过（直接调用私有函数）
- Road 生成空壳

#### 修复方向

| #  | 问题       | 修复                                                      | 优先级 |
| -- | ---------- | --------------------------------------------------------- | ------ |
| E1 | 无空间操作 | EXECUTE 调用 spatial_ops.parcel_ops 执行 operation        | P0     |
| E2 | 验证空转   | spatial_ops 计算 parcel↔zone overlay -> 写入 within_zone | P0     |
| E3 | @tool 绕过 | 提取公共 generation API                                   | P2     |
| E4 | Road 空壳  | 实现 PlannedRoad 生成器                                   | P1     |

---

## 七、全局优美性评估

### 7.1 优美的地方

| 设计                                                | 评价                         |
| --------------------------------------------------- | ---------------------------- |
| 四层单向依赖（Schema<-Data<-SpatialOps<-KG<-Agent） | ✅ 严格，测试守护            |
| VillageBundle morphological 分组                    | ✅ 类型安全，isinstance 派发 |
| KG 四层生命周期（L1/L2/L3/L4）                      | ✅ 概念清晰                  |
| L4 稀疏写入                                         | ✅ 高效，只写 delta          |
| SemanticMemoryStore                                 | ✅ 语义注解与 RDF 分离       |
| Think-Then-Format                                   | ✅ 巧妙的 LLM 兼容方案       |
| clone_static_layer 会话隔离                         | ✅ 正确的并发模型            |

### 7.2 不优美的地方

| 设计                         | 评价                          |
| ---------------------------- | ----------------------------- |
| URI 方案碎片化（6 种方案）   | ❌ 违反"统一契约"，应一种方案 |
| ThreeZone 脱离 bundle        | ❌ 违反"数据驱动"，成了概念表 |
| L4->L3 链接定义不实现        | ❌ "死字段"，设计但不落地     |
| spatial_ops 只有分析没有操作 | ❌ 规划的核心能力缺失         |
| pipeline 顺序错误            | ❌ 基本流程错误               |
| within_zone 不写入           | ❌ 验证闭环断裂               |
| BSM 契约不统一执行           | ❌ 契约定义了但不强制         |
| count-based URI              | ❌ 不稳定，不可追溯           |
| PlanBlock 不继承 SCU         | ❌ 设计不一致                 |

### 7.3 优美性评分

| 维度                  | 评分 | 说明                                              |
| --------------------- | ---- | ------------------------------------------------- |
| **架构分层**    | 9/10 | 严格单向依赖，测试守护                            |
| **类型系统**    | 8/10 | morphological 分组优秀，BSM 契约弱                |
| **KG 设计**     | 7/10 | 四层概念好，URI 碎片化、ThreeZone 脱离、L2 空壳   |
| **Spatial Ops** | 5/10 | 分析能力完整，操作能力全缺                        |
| **Agent 设计**  | 6/10 | Think-Then-Format 好，pipeline 顺序错、空间操作缺 |
| **数据流闭环**  | 4/10 | 第 5 步断裂，无空间操作->无平衡表->无完整输出     |
| **一致性**      | 5/10 | 契约定义不执行、死字段、命名漂移                  |

**总体**：6.3/10 - 骨架优美，肌肉不完整。需要补"空间操作"这块核心肌肉。

---

## 八、修复优先级总表

### P0（不修复无法运行）

| # | 模块       | 修复                                              | 影响               |
| - | ---------- | ------------------------------------------------- | ------------------ |
| 1 | Agent      | pipeline 顺序改为 fetch->build_kg->parse->execute | PARSE 查空 KG      |
| 2 | KG         | 统一 URI 方案（EntityIdPolicy + bsm literal）     | 实体不可追溯       |
| 3 | KG         | ThreeZone/ThreeLine 改读 bundle                   | 三区三线无空间实体 |
| 4 | KG         | within_zone 写入（spatial_ops overlay -> KG L2）  | 验证空转           |
| 5 | SpatialOps | 实现 grounding.py                                 | PARSE 空间接地     |
| 6 | SpatialOps | 实现 parcel_ops.py（split/merge/modify）          | 无空间操作         |
| 7 | KG         | 更新 README（URI 策略、方法名、标识契约）         | 文档误导           |

### P1（不修复无法产出可用规划）

| #  | 模块       | 修复                                          | 影响                 |
| -- | ---------- | --------------------------------------------- | -------------------- |
| 8  | Schema     | 新增 LandBalanceTable + SpatialOperation 参数 | 无平衡表、操作无参数 |
| 9  | KG         | L4 PlannedParcel 增加 geometry                | L4 无几何            |
| 10 | KG         | L4->L3 链接实现（读 derived_from_target）     | L4 不可追溯意图      |
| 11 | SpatialOps | overlay_analysis（规划几何->现状地块）        | 无 L1↔L4 对照       |
| 12 | Agent      | EXECUTE 调用 parcel_ops 执行 operation        | 无真实规划操作       |
| 13 | Agent      | Road 生成器实现                               | Road 空壳            |
| 14 | Data       | BSM 缺失时生成稳定 ID                         | 下游不可追溯         |

### P2（不修复无法达到交付质量）

| #  | 模块   | 修复                                | 影响            |
| -- | ------ | ----------------------------------- | --------------- |
| 15 | KG     | L2 层实质化（或合并 layer1+layer2） | 结构名不副实    |
| 16 | KG     | RoadTarget 实现或删除               | 死实体          |
| 17 | Schema | PlanBlock 继承 SpatialCognitiveUnit | L4 不可语义查询 |
| 18 | Agent  | @tool 绕过修复                      | 耦合            |
| 19 | KG     | 各模块 README 同步更新              | 文档漂移        |

---

## 九、结论

当前系统的**骨架是优美的**（四层依赖、morphological 分组、KG 四层生命周期），但**肌肉不完整**：

1. **标识层**：BSM 契约定义了但不强制执行，导致 6 种 URI 方案并存
2. **操作层**：spatial_ops 只有分析没有操作，规划的核心能力缺失
3. **闭环层**：pipeline 顺序错、within_zone 不写、L4 无几何，多处断裂

**最小修复路径**：先统一标识契约（P0-2），再补空间操作能力（P0-6），最后修复闭环（P0-1, P0-4）。修完后系统才具备"现状->意图->操作->规划->验证->输出"的完整能力。

优美的系统应该有一个统一的原则贯穿始终：**每个实体可追溯、每个操作可执行、每个关系可验证**。当前系统在这三点上都有缺口。
