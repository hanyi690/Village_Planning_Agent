# PARSE 空间接地设计补丁
## —— 闭合 KG_SPATIAL_COGNITION_DESIGN 的 P1-16/17/18 缺口

> 状态:提案(待评审) | 日期:2026-07-29
> 关联:`KG_SPATIAL_COGNITION_DESIGN.md`(架构边界已定,P1-16/17/18 PARSE 待后续)、`spatial_ops/grounding.py`(已实现方向接地)
> 触发:用户提出"目前 KG 查询方案不够 LLM 理解空间信息和定位;KG 应能返回大致范围 BSM 怎么利用;bbox 是不是该在 parse/spatial_ops 解决"

---

## 0. 诊断:架构边界是对的,缺的是契约 + KG 关系未利用

`KG_SPATIAL_COGNITION_DESIGN.md` §二已定硬约束:**KG=语义权威(BSM+关系+语义层,绝不存全几何),spatial_ops=几何权威(全几何运算,无状态)**。这个边界**不需要改**。问题在两处:

### 0.1 现状 grounding.py 的四个具体短板

| # | 短板 | 证据 |
|---|---|---|
| ① | **NL→(方向,地名)是关键词抽取,且只覆盖 direction+place 两种引用** | `ground_zone_spatial_preference` L285-303:`for kw in dir_keywords: if kw in preference_desc`。"学校 500 米内的空地"(距离引用)、"挨着河的地"(拓扑引用)、"东边且非林地的空地"(组合引用)全不适配,落 fallback |
| ② | **依赖 place_mappings 预填充,脆** | L298-304:地名不在 place_mappings 即回退全村质心。"祠堂旁边""老李家那块地"无 place_mapping 即失效 |
| ③ | **完全没用 KG 的 L2 关系** | L279:`parcels = bundle.polygons.get("landuse_current")` 直接拿全量 660 图斑做几何搜索;KG 已缓存的 `located_in/touches/nearby/contains/intersects`(§五 8 关系、§十二跨类型)未被 grounding 消费,几何重算 |
| ④ | **bbox 被降级为"仅可视化"** | L322 注释"仅用于可视化,不作为候选过滤依据了"。bbox 本该是粗筛加速器,现在要么不筛、要么靠 preselected_bsms |

### 0.2 用户两个问题的精确回答(先给结论,详证见 §4/§5)

- **Q:KG 应能返回大致范围 BSM,怎么利用?**
  → KG 通过**属性过滤 + L2 缓存关系**返回候选 BSM 集(语义+拓扑近邻,粗、快);把这批 BSM 作为 spatial_ops 的**搜索空间**(而非全量图斑),spatial_ops 再做方向/距离的**几何精化**。即"KG 出候选、spatial_ops 出精确"的两段式。现状 grounding 跳过了 KG,直接对全量图斑算几何——既慢又浪费 L2。

- **Q:空间定位大致的 bbox 是不是该在 parse/spatial_ops 解决?**
  → **bbox 属几何,归 spatial_ops**(现已在 `resolve_directional_bbox`,位置对);**parse 不产 bbox,产 SpatialReferenceSpec(结构化引用契约)**。bbox 的**角色**要修正:不是"仅可视化",而是**粗筛预过滤**(RTree/空间索引命中)→ 再做精确几何过滤(shapely half-plane/buffer/DE-9IM)。最终答案是**精确 BSM 集**,bbox 是达到它的加速手段。

---

## 1. 核心方案:SpatialReferenceSpec 闭集契约 + 两段式解析

### 1.1 闭环流程

```
用户 NL("村子东边靠近学校的林地")
   │
   ▼  [PARSE · LLM + instructor]  ← 产出结构化 spec,不产 desc 字符串
SpatialReferenceSpec(闭集类型化,见 §2)
   │
   ├─► [KG] 语义解析引用对象 + 属性/L2关系过滤 → candidate_bsms(粗,快)
   │       "学校"→Facility(label~学校) BSM/质心;"林地"→dlbm∈FOREST_CODES 的 Parcel
   │       可用缓存关系:located_in/touches/nearby/contains/intersects
   │
   ▼  [spatial_ops/grounding] 几何精化(在 candidate_bsms 上,非全量)
resolve_reference → 几何运算(半平面/缓冲/DE-9IM) → bbox 粗筛 → 精确 BSM
   │
   ▼
ResolvedSpatialRef { final_bsms, bbox, reference_geometry, confidence, provenance }
```

三段职责清晰,严格落在现有边界上:
- **PARSE+LLM**:NL → spec(语义,闭集,不碰坐标)
- **KG**:spec 中的引用对象解析 + 候选 BSM(语义+缓存关系,不碰几何运算)
- **spatial_ops**:候选 BSM 上做几何精化(方向/距离/精确拓扑,不碰语义)

### 1.2 LLM 的边界(与 v3 §3、ZONING 方案同源)

LLM 产 **SpatialReferenceSpec**(结构化、闭集类型、instructor 强制校验),**不产** SPARQL、不产坐标、不产 bbox。spec 是"空间查询 DSL",类比编码 DSL(v3 §2.4)与分区 typing_rules(ZONING 方案 §2)——同一套有界 LLM 范式第三兑现。

---

## 2. SpatialReferenceSpec:闭集类型契约

```python
# modules/schema/contracts/spatial_ref_contracts.py(新增)
class RefObject(BaseModel):
    """引用对象:解析到 KG 实体或图层组"""
    kind: Literal["entity_type", "layer_group", "place_name", "bsm", "village"]
    # entity_type: {facility:"学校", parcel:"林地"} → KG 语义查询
    # layer_group: "water" / "farmland_protection" → KG 图层组(§八 GisLayerSet)
    # place_name: "刘村"/"祠堂" → place_mappings/gazetteer
    # bsm: 已知具体实体
    # village: 村域整体(质心作参考系)
    filter: dict | None = None        # entity_type 时的属性过滤,如 {label~:"学校"}、{dlbm_in:FOREST_CODES}

class SpatialReferenceSpec(BaseModel):
    """PARSE 产出的空间引用规约。闭集,LLM 只能填,不能造类型。"""
    type: Literal["directional", "distance", "topological", "attributive", "composed"]
    reference: RefObject | None = None     # attributive 可无 reference
    # directional
    direction: Literal["N","NE","E","SE","S","SW","W","NW"] | None = None
    # distance
    relation: Literal["within","beyond"] | None = None
    distance_m: float | None = None
    # topological(对齐 GeoSPARQL/v3 §6.2):located_in/touches/nearby/contains/intersects
    topo: Literal["located_in","touches","nearby","contains","intersects"] | None = None
    # attributive:纯属性,无空间约束(如"所有林地"),KG 直出
    attr_filter: dict | None = None
    # composed
    op: Literal["and","or","not"] | None = None
    children: list["SpatialReferenceSpec"] | None = None
```

**类型清单(闭集,覆盖 NL 空间引用的 5 类)**:

| type | NL 例子 | 解析路径 |
|---|---|---|
| directional | "村子东边的林地" | KG 出林地候选 BSM → spatial_ops 半平面(east of 村质心)精化 |
| distance | "学校 500 米内的空地" | KG 出学校 Facility BSM/质心 + 空地候选 → spatial_ops 500m buffer 相交 |
| topological | "挨着河的地""红线内的宅基地" | **直接走 KG L2 缓存关系**(touches/intersects/located_in),无需几何运算 |
| attributive | "所有基本农田" | KG 属性查询直出 BSM(无空间约束) |
| composed | "东边且非林地的空地" | children 用 and/not 组合,递归解析 |

**关键收益**:topological 类**绕过几何运算直接命中 KG 缓存**——这是"利用 KG 返回大致范围 BSM"最直接的兑现,也是对 L2 关系层(§十二,现 facility located_in parcel 已 1385 条)的真正消费。

---

## 3. 两段式解析实现(改造 grounding.py,不重写)

### 3.1 KG 侧:候选 BSM 查询(语义+L2 关系)

新增 `kg/queries/spatial_ref.py`(挂 parse_queries 命名空间,structured 返回,符合 §十):

```python
def resolve_candidates(spec: SpatialReferenceSpec, kg) -> CandidateSet:
    """KG 侧:解析引用对象 + 属性/L2 关系过滤,返回候选 BSM(粗)。不做几何运算。"""
    # 1. 引用对象解析
    if spec.reference.kind == "entity_type":
        ref_bsms = kg_query_facility_by_label(spec.reference.filter)  # "学校"→Facility BSM
    elif spec.reference.kind == "layer_group":
        ref_bsms = kg_query_layer_group(spec.reference.filter)        # "water"→WaterBody BSM
    elif spec.reference.kind == "place_name":
        ref_bsms = gazetteer.resolve(spec.reference.filter)           # place_mappings
    # 2. 属性候选(attr_filter):"林地"→dlbm∈FOREST_CODES 的 Parcel BSM
    attr_bsms = kg_query_parcels_by_attr(spec.attr_filter) if spec.attr_filter else None
    # 3. topological 类直接用 L2 关系闭合
    if spec.type == "topological":
        return CandidateSet(bsms=kg_query_relation(ref_bsms, spec.topo))  # SPARQL: ?p pln:located_in ?ref
    return CandidateSet(bsms=attr_bsms or ALL_PARCELS, ref_bsms=ref_bsms)
```

返回 `CandidateSet{bsms, ref_bsms, ref_geometry_optional}`——**这就是"KG 返回的大致范围 BSM"**,作为 spatial_ops 的搜索空间。

### 3.2 spatial_ops 侧:几何精化(在候选上,非全量)

改造 `grounding.py`,新增统一入口 `resolve_spatial_ref`:

```python
def resolve_spatial_ref(spec, candidates: CandidateSet, bundle, constraint_index) -> ResolvedSpatialRef:
    """spatial_ops 侧:在 candidates.bsms 上做几何精化。bbox 作粗筛,精确过滤收尾。"""
    if spec.type == "topological":
        return ResolvedSpatialRef(bsms=candidates.bsms)   # KG 已闭合,免几何
    if spec.type == "attributive":
        return ResolvedSpatialRef(bsms=candidates.bsms)   # 纯属性,免几何
    # directional / distance 需几何
    ref_geom = resolve_ref_geometry(candidates.ref_bsms, bundle)   # 引用对象几何(质心/图层 union)
    if spec.type == "directional":
        bbox = resolve_directional_bbox(ref_geom.centroid, spec.direction)  # 复用现有函数
        coarse = rtree_filter(candidates.bsms, bbox)              # ★ bbox 粗筛(恢复 bbox 的加速角色)
        final = [b for b in coarse if in_half_plane(centroid(b), ref_geom.centroid, spec.direction)]
    elif spec.type == "distance":
        buf = ref_geom.buffer(deg(spec.distance_m))
        bbox = buf.bounds
        coarse = rtree_filter(candidates.bsms, bbox)              # ★ 粗筛
        final = [b for b in coarse if centroid(b).within(buf)]    # 精确
    # 通用:约束排除(复用 query_excluded_parcels)
    final = [b for b in final if b not in query_excluded_parcels(constraint_index, parcels_by_bsm(final))]
    return ResolvedSpatialRef(bsms=final, bbox=bbox, ref_geometry=ref_geom,
                              provenance={spec_type:spec.type, kg_candidates:len(candidates.bsms),
                                          final_count:len(final), decided_by:"rule"})
```

**对现有 grounding.py 的改造点(增量,不破坏)**:
- 保留 `resolve_directional_bbox / query_parcels_in_bbox / query_parcels_near_entity / query_excluded_parcels / compute_proximity_weights`(原语复用);
- `ground_zone_spatial_preference / ground_facility_spatial_preference / ground_linear_spatial_preference` 改为**薄包装**:先调 `kg.resolve_candidates(spec)` 拿候选,再调 `resolve_spatial_ref` 精化——把"对全量 660 图斑算几何"换成"对 KG 候集算几何";
- bbox 从"仅可视化"恢复为 `rtree_filter` 的粗筛输入(§0.1 短板④修复)。

---

## 4. BSM 的利用(回答 Q1,展开)

KG 返回的"大致范围 BSM"在两段式中扮演**搜索空间裁剪器**:

| 场景 | KG 候选(粗) | spatial_ops 精化(细) | 收益 |
|---|---|---|---|
| "东边的林地" | dlbm∈FOREST_CODES 的 Parcel BSM(可能 200 个) | 半平面 east 过滤 → 50 个 | 几何运算量 660→200→50 |
| "学校 500 米内" | Facility(label~学校) BSM(几个) + 全量 Parcel | buffer 相交 → N 个 | 引用对象免几何解析,KG 直给 |
| "挨着河的地" | WaterBody BSM + `touches`/`intersects` L2 关系 → Parcel BSM | **免几何**(L2 已缓存) | 零几何运算,纯 SPARQL |
| "红线内的宅基地" | YJJBNT Zone + `located_in` L2 → 宅基地 Parcel BSM | 免几何 | 零几何 |

**BSM 是 KG(语义身份)与 spatial_ops(几何)的唯一 join key**——这本来就是 EntityIdPolicy(§L1 `PLN[f"{type}_{bsm}"]`)的设计意图,本方案只是让 grounding 真正按这个 key 去 KG 取候选,而不是绕过 KG 直接翻 bundle。

现状短板③(L279 直接 `bundle.polygons.get("landuse_current")`)的根因:grounding 在 PARSE 阶段调用,而 bundle 此时已加载——所以图省事直接拿 bundle。但 bundle 是全量、无关系索引;KG 才有 L2 关系和属性索引。修复就是 grounding 接收 `kg` 句柄(或预取的 CandidateSet),按 BSM 取候选。

---

## 5. bbox 的归属与角色(回答 Q2,展开)

| 问题 | 答案 | 依据 |
|---|---|---|
| bbox 该在 parse 还是 spatial_ops? | **spatial_ops**(几何权威,§二) | 现 `resolve_directional_bbox` 已在 spatial_ops/grounding.py,位置正确;parse 产 spec 不产几何 |
| bbox 的角色? | **粗筛预过滤器**(RTree/空间索引命中) → 精确几何过滤收尾;最终答案是精确 BSM,bbox 是加速手段 | 现状 L322 把 bbox 降为"仅可视化"是矫枉过正,应恢复粗筛角色 |
| 何时不需要 bbox? | topological/attributive 类(KG 直出 BSM,免几何) | §3.2 |
| bbox 也返回给谁? | EXECUTE(可视化/粗定位)、前端(地图聚焦)、debug | DualPayload.structured 已有 bbox 字位(§九) |

**两段式查询的经典模式**(数据库空间查询的标准做法):`bbox 粗筛(RTree,O(log n))` → `精确几何(shapely,O(候选数))`。现状要么不筛(全量算)要么靠 LLM preselected_bsms(语义粗定位),缺了中间的 bbox 粗筛层——本方案补上。

---

## 6. 落地与验收

### 6.1 改动清单(增量,不动架构边界)

| # | 文件 | 改动 | 估算 |
|---|---|---|---|
| 1 | `schema/contracts/spatial_ref_contracts.py`(新) | SpatialReferenceSpec / RefObject / CandidateSet / ResolvedSpatialRef | ~120行 |
| 2 | `kg/queries/spatial_ref.py`(新) | resolve_candidates(属性+L2 关系查询) | ~150行 |
| 3 | `spatial_ops/grounding.py`(改) | 新增 resolve_spatial_ref;3 个 ground_* 改薄包装;恢复 bbox 粗筛 | ~100行净增 |
| 4 | `agent/gis/parse/agent.py`(改) | LLM 产 spec(instructor),替代/补充 preference_desc 字符串 | ~80行 |
| 5 | `spatial_ops/geometry.py`(改) | 补 rtree_filter / in_half_plane / buffer 原语(若缺) | ~60行 |

### 6.2 验收(金田村可测)

| 用例 | 期望 |
|---|---|
| "村子东边的林地" | directional:KG 出林地候选→半平面精化;bbox 粗筛生效;最终 BSM 全在村东半平面 |
| "学校 500 米内的空地" | distance:KG 出学校 Facility BSM→buffer 相交;非全量算 |
| "挨着河的地" | topological:**零几何运算**,KG `touches/intersects` L2 直出 |
| "红线内的宅基地" | topological:KG `located_in` L2 直出 |
| "东边且非林地的空地" | composed:and(directional, not(attributive 林地))递归解析 |
| "祠堂旁边"(无 place_mapping) | entity_type Facility(label~祠堂)→KG 出 BSM→distance 精化;不再回退全村质心 |

### 6.3 与既有定案的衔接

- **KG/spatial_ops 边界**(设计文档§二):**不变**,本方案是在边界两侧各补一块(KG 补候选查询、spatial_ops 补 spec 精化),不越界;
- **8 关系**(§五):topological 类直接消费 located_in/touches/nearby/contains/intersects,兑现 §十二"待 spatial_ops 实现"的跨类型关系;
- **DualPayload**(§九):ResolvedSpatialRef 的 bbox/bsms 可直接塞 structured,semantic 部分由三层认知摘要承担;
- **v3 expr_eval DSL**(REFACTOR_V3 §2.4):SpatialReferenceSpec 的 attr_filter 可复用同一 DSL(`dlbm_in/field_equals`),第三兑现 DSL 投资;
- **PARSE P1-16/17/18**(设计文档状态行"待后续"):本方案即该项的完成设计。

## 7. 一句话总结

架构边界不用动(KG 语义 / spatial_ops 几何已对);缺的是 **PARSE 产结构化 SpatialReferenceSpec(闭集契约,instructor 强制)+ grounding 按 BSM 从 KG 取候选(用上 L2 关系,topological 类免几何)+ bbox 恢复粗筛角色**。BSM 是 KG 与 spatial_ops 的唯一 join key,bbox 是几何精化的加速器而非最终答案——parse 给语义 spec,KG 给候选 BSM,spatial_ops 给精确 BSM+bbox。
