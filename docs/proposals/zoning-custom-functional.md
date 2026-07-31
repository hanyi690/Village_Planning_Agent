# 非常规功能分区生成设计
## —— 以「产业功能分区 + 空间结构(心/轴/区)」为例,落地于现有 EXECUTE 架构

> 状态:提案(待评审) | 日期:2026-07-29
> 触发:用户贴金田村产业发展规划图(图例:产业发展中心/一二三产项目点/森林保育区·农业发展区·休闲农业区·康养旅游区·林下开发区 5 类分区)
> 关联:REFACTOR_V3_ENCODING_CENTRIC_PIPELINE.md(§2.4 DSL、§3 消歧梯、§5 registry、§6.1 builder 注册)

---

## 0. "非常规"的三重含义(先拆问题,再谈实现)

这张图与系统现有 `zone_generator` 的"常规"输出相比,差异在三个层面:

| 层面 | 常规(现状系统) | 非常规(这张图) |
|---|---|---|
| **语义** | 分区类型来自封闭标准字典 `ZONE_TYPE_COLORS`(农田保护区/生态保护区…) | 分区类型是**规划师自定义词汇**:森林保育区、康养旅游区、林下开发区……不在任何编码字典里 |
| **生成逻辑** | DLBM 1:1 重分类(`get_zone_type_for_dlbm`),单因子 | **多因子复合**:林下开发区=林地∧非生态红线∧坡度<25°∧近路;康养旅游区=(林地∨水域)∧邻近历史文化资源∧可达性高 |
| **空间表达** | 只有"面"(zones) | **复合空间结构**:心(产业发展中心·点)+ 轴(旅游休闲轴/综合发展轴·线)+ 区(5类功能分区·面)+ 项目点(一二三产),即金田村「二心二轴四区」 |

**核心论点:系统不该把"森林保育区"写进代码,而该提供"让任意自定义分区可声明、可生成、可校核"的机器。非常规 = 配置常规。** 词汇表是项目级配置,生成机器是系统能力。

---

## 1. 现状资产盘点(哪些直接复用,哪些是缺口)

| 资产 | 位置 | 对非常规分区的可用性 |
|---|---|---|
| ZoneGenerator 骨架(reclassify→merge→面积匹配) | `tools/gis/_generation/zone_generator.py` | ✅ 算法骨架直接复用,只需把"DLBM→zone_type"换成"规则→自定义zone_type" |
| 双评价因子引擎 | `tools/gis/_analytics/dynamic_zoning.py` | ✅ 灾害缓冲/红线/基本农田/道路邻近等因子已实现,作 typing_rules 的谓词来源 |
| MIP 分配 + CA 优化 | `_generation/optimizer/mip_allocator.py, ca_refiner.py` | ✅ 分区面积比例微调可选调用 |
| 可达性/等时圈 | `_analytics/accessibility.py, isochrone.py` | ✅ "心"选址的量化依据 |
| 轴构建 | `_generation/axis_builder.py` | ✅ "轴"直接复用 |
| 设施落位 | `_generation/facility_placer.py` | ✅ 项目点落位的机制模板 |
| validator / L1 约束面 | `spatial_ops/constraint_compiler.py` 等 | ✅ 校核"项目不得落入红线/基本农田" |
| 表达式 DSL(§2.4) | v3 提案 `dicts/expr_eval.py` | ✅ typing_rules 的求值器——DSL 投资的第二次兑现 |
| **缺口 G1:自定义分区词汇表** | 现为硬编码 `ZONE_TYPE_COLORS` | ❌ 需 vocabulary YAML(§2) |
| **缺口 G2:多因子类型标注** | 现仅 DLBM 1:1 | ❌ 需 typing_rules 引擎(§3) |
| **缺口 G3:心/轴/区结构组装** | 面、轴各自独立 | ❌ 需 SpatialStructure 组装器(§4) |
| **缺口 G4:项目×分区兼容落位** | facility_placer 无分区兼容概念 | ❌ 需兼容矩阵+落位(§5) |
| **缺口 G5:KG/图例注册** | 自定义层未注册 | ❌ 走 v3 registry 路径(§6) |

---

## 2. 缺口 G1:分区词汇表(项目级配置,非系统代码)

```yaml
# config/zone_vocabularies/jintian_industry.yaml(按村/按片区一份)
vocabulary: jintian_industry_v1
i18n: {zh: 金田村产业功能分区词汇}
zones:
  - type: forest_conservation
    name: 森林保育区
    color: "#5DAE8B"
    priority: 10                 # 一图斑命中多类时,数值小者优先(保育类优先于开发类)
    typing_rules:
      any:
        - within_zone: STBHHX                    # 生态保护红线内
        - all:
            - dlbm_in: ["0301","0302","0305","0307"]   # 林地
            - slope_gte: 25                      # 陡坡林地→保育
  - type: agri_dev
    name: 农业发展区
    color: "#F2C94C"
    priority: 20
    typing_rules:
      all:
        - dlbm_in: ["0101","0102","0103"]        # 耕地
        - within_zone: YJJBNT                    # 基本农田→整治提升型农业区
  - type: leisure_agri
    name: 休闲农业区
    color: "#F2994A"
    priority: 30
    typing_rules:
      all:
        - dlbm_in: ["0101","0102","0103","0201","0204"]   # 耕地+园地
        - not_within_zone: YJJBNT
        - road_distance_lt: 300                  # 临路才有休闲可达性
  - type: wellness_tourism
    name: 康养旅游区
    color: "#9B51E0"
    priority: 40
    typing_rules:
      any:
        - all:
            - dlbm_in: ["0301","0302","0305","0307"]
            - near: {layer: historical_protection, dist_m: 300}   # 邻近祠堂/古树/古驿道
        - all:
            - dlbm_in: ["1101","1104","1107"]    # 水域(河/坑塘/沟渠)
            - road_distance_lt: 500
  - type: under_forest_dev
    name: 林下开发区
    color: "#C9D67A"
    priority: 50
    typing_rules:
      all:
        - dlbm_in: ["0301","0302","0305","0307"]
        - not_within_zone: STBHHX
        - slope_lt: 25
        - road_distance_lt: 500
```

要点:①词汇表**按项目配置**,系统代码不出现任何具体分区名;②`typing_rules` 用 v3 §2.4 的表达式 DSL(`dlbm_in / within_zone / not_within_zone / slope_lt / road_distance_lt / near / all / any / not`),谓词数据来自 L1 KG(图斑、约束面、道路、历史保护点)与双评价因子;③`priority` 解决一图斑多命中(保育>农业>开发,宁可偏保守);④color/name 直接驱动渲染图例。

**词汇表冷启动(LLM 有界角色之一)**:RAG 从 06_相关案例(住建部优秀案例集、金田村规划细化等)提取同类村功能区命名候选 → 人工确认落 YAML。**LLM 参与"建词表",不参与"生成时造词"**——生成时词汇表是闭集。

---

## 3. 缺口 G2:CustomZoningGenerator(复用 ZoneGenerator 骨架)

```python
# tools/gis/_generation/custom_zone_generator.py(新增,~300行,约70%复用 zone_generator)
class CustomZoningGenerator:
    """非常规功能分区生成:声明式 typing_rules → 自定义 zone_type。

    继承 ZoneGenerator 的核心原则:NOT generating coordinates from scratch —
    从 landuse_current 图斑 reclassify + merge,不凭空造坐标。
    """
    def generate(self, parcels, vocabulary, intent, l1_context) -> GeoJSON:
        gdf = load(parcels)
        for each parcel:
            hits = expr_eval.filter(vocabulary.zones, parcel_ctx)   # §2.4 DSL 求值
            if len(hits) == 1:        zone_type = hits[0]                       # L1 确定
            elif len(hits) > 1:       zone_type = min(hits, key=priority)       # priority 裁决
            else:                     zone_type = llm_or_default(parcel_ctx)    # L2 消歧(§6.2)
        grouped = groupby(gdf, zone_type)
        zones = dissolve_clean(grouped)    # unary_union + 去碎片(广东质检:图上<1mm² 碎面剔除)
        if intent.area_targets:            # 可选:面积比例微调
            zones = mip_allocator.adjust(zones, intent.area_targets)
        return to_geojson(zones, props=[zone_id, zone_type, name, color, area_ha,
                                        rule_basis, decided_by])               # provenance 随图斑
```

- 输入:`landuse_current`(L1)+ `vocabulary`(§2)+ `intent.custom_zone_targets`(PARSE 扩展,可选)+ `l1_context`(约束面/道路/资源点,KG 查询接口现成的 `kg_constraints/kg_three_lines/kg_protected_parcels_detail`);
- 输出与常规 zone_generator 同构(GeoJSON + color),前端渲染无需分叉——`get_zone_color` 改为 vocabulary-aware(先查自定义词汇表,回落标准 `ZONE_TYPE_COLORS`);
- 碎片处理与广东数据库质检对齐(期末地类层不得小于图上 1mm²),保证后续可入库。

---

## 4. 缺口 G3:空间结构组装(心 + 轴 + 区 → SpatialStructure)

```python
# tools/gis/_generation/structure_assembler.py(新增,~150行)
class SpatialStructureAssembler:
    """把 zones(面)+centers(点)+axes(线)组装为命名空间结构,如「二心二轴四区」。"""
    def assemble(self, zones, intent, roads, facilities, accessibility_ctx) -> SpatialStructure:
        centers = self._locate_centers(intent, facilities, accessibility_ctx)
        # intent 指定(金田村:园寨/黄竹) → 直接锚定现有设施/居民点;
        # 未指定 → accessibility.isochrone 选覆盖最大化的节点(备选)
        axes = axis_builder.build(along=roads.main, through=centers)   # 复用 axis_builder
        return SpatialStructure(name=intent.structure_name,            # "二心二轴四区"
                                centers=centers, axes=axes, zones=zones)
```

- `SpatialStructure` 是一等公民对象(非散放三层的隐式关系),落 `layout_configs`(ExecuteAgentState 现成字段);
- 心 = 现有设施锚点(`facility_anchors`,ExecuteAgentState 现成字段)或可达性最优节点;
- 轴 = axis_builder 沿主路(122乡道)穿心。

---

## 5. 缺口 G4:产业项目点落位(兼容矩阵 + validator)

```yaml
# config/zone_vocabularies/project_compatibility.yaml
compatibility:
  养殖:        {allow: [under_forest_dev, agri_dev],        forbid: [forest_conservation]}
  加工工坊:    {allow: [agri_dev, leisure_agri],            forbid: [forest_conservation, wellness_tourism]}
  民宿/康养:   {allow: [wellness_tourism, leisure_agri],    forbid: [forest_conservation]}
  种植园:      {allow: [agri_dev, leisure_agri, under_forest_dev]}
  集市/美食坊: {allow: [leisure_agri], near_center: true}
```

- 项目清单来源:PARSE 从需求台账/产业项目表提取(金田村实战文档已有结构:项目名/产业类型/位置/面积),或 intent 直给;
- 落位机制复用 `facility_placer`:候选点=兼容分区内图斑质心/邻近中心,逐个过 `validator`(L1 约束面:建设类项目不得碰红线/基本农田——**注意用的是 L1 法定约束,不是自定义分区**);
- 冲突时按 compatibility 换区,再冲突 → warnings(不阻塞,与现有收集制一致)。

---

## 6. 缺口 G5:KG 注册与 LLM 边界

### 6.1 走 v3 registry 路径(这正是"加一层=一条YAML"的验收用例)

```yaml
# gis_layer_registry.yaml 追加
industry_functional_zone:
  i18n: {zh: 产业功能分区}
  geometry_kind: polygon
  group: planning_intent           # 新语义组:规划意图(区别于 constraint)
  ingest: {adapter: features, feature_type: industry_zone}
  bundle_target: {group: polygons, key: industry_zones}
  kg: {entity_type: FunctionalZone, phase: L3, order: 50, enabled: true}
```
```python
@kg_builder('industry_functional_zone')    # v3 §6.1 注册机制
def add_functional_zones(builder, features, *, entry, ctx) -> BuildReport: ...
```

**架构边界(必须守住)**:自定义功能分区落 **KG L3(规划意图层),绝不进 L1 约束面**。L1 只放法定约束(三区三线/灾害线);若把"森林保育区"塞进 L1,validator 会把"保育区内落项目"误判为违规——但它只是规划意图,不是法定禁止。KG 关系:`FunctionalZone -[geo:sfContains]-> Project`、`FunctionalZone -[pln:derived_from]-> Parcel`、`FunctionalZone -[pln:typed_by]-> VocabularyEntry`、`SpatialStructure -[pln:has_component]-> zones/axes/centers`;图斑级 provenance(`pln:rule_basis / pln:decided_by`)与 v3 §6.3 一致。

### 6.2 LLM 的三处有界使用(与 v3 §3 消歧梯同源)

| 位置 | LLM 做什么 | 边界 |
|---|---|---|
| 词汇表冷启动 | 从案例集 RAG 提取候选命名 | 人工确认后才入 YAML;生成时词汇表闭集 |
| 歧义图斑标注 | 无命中/多命中 priority 无法裁决时,在**词汇表闭集**内选择+举证 | 走 v3 L2:instructor 结构化输出、缓存、low-confidence→default 或 DLQ |
| intent 解析 | "搞个康养旅游区"→映射到 vocabulary entry | 模糊匹配+消歧,不创造词表外类型 |

**LLM 永远不做的**:生成分区几何(坐标)。几何 100% 来自确定性地理处理(reclassify/dissolve/clip/buffer)。

---

## 7. 端到端数据流(对照金田村图)

```
RAG 案例集/金田村规划细化 ──[LLM 冷启动+人工确认]──> jintian_industry.yaml(5类词汇)
                                                              │
L1 KG: parcels(dlbm/坡度) + 约束面(生态红线/基本农田) + 道路 + 历史保护点
                                                              ▼
                              CustomZoningGenerator(typing_rules, expr_eval)
                                  │  歧义图斑 → LLM L2(闭集消歧)
                                  ▼
                        5 类分区面(dissolve+去碎片+MIP 面积微调)
                                  ▼
            SpatialStructureAssembler:园寨/黄竹 2 心 + 122乡道 2 轴 + 5 区
                                  ▼
            项目落位(兼容矩阵:养殖→林下开发区…;validator 过 L1 红线/农田)
                                  ▼
        bundle.polygons.industry_zones + points.projects + layout_configs[SpatialStructure]
                                  ▼
        KG L3:FunctionalZone×5 + Project×N + SpatialStructure「二心二轴四区」(含 provenance)
                                  ▼
        render(词汇表驱动图例色/名)→ 与参考图同构的产业发展规划图 → export GeoJSON/GDB
```

## 8. 落地步骤与工作量

| # | 内容 | 文件 | 估算 | 依赖 |
|---|---|---|---|---|
| 1 | vocabulary loader + expr_eval 谓词扩充(dlbm_in/slope/road_distance/near) | `dicts/expr_eval.py`, `config/zone_vocabularies/` | ~120行 | v3 Step 2(DSL) |
| 2 | CustomZoningGenerator | `tools/gis/_generation/custom_zone_generator.py` | ~300行 | 1 |
| 3 | SpatialStructureAssembler + centers 选址 | `_generation/structure_assembler.py` | ~150行 | 2, accessibility |
| 4 | 兼容矩阵 + 项目落位 | `project_compatibility.yaml`, facility_placer 扩展 | ~100行 | 2, validator |
| 5 | registry 条目 + FunctionalZone KG builder | `gis_layer_registry.yaml`, `kg/builder/` | ~80行 | v3 Step 5 |
| 6 | intent 扩展(custom_zone_targets/structure_name)+ 渲染 vocabulary-aware | parse_contracts, render | ~80行 | 1 |
| 7 | 金田村端到端验收:复现「二心二轴四区」5 区结构 | tests/ | — | 全部 |

**验收标准(可测)**:①5 类分区面全部落在合规图斑上(保育区 100% 覆盖生态红线内林地);②项目点 0 违规(不碰 L1 红线/基本农田);③结构完整(2 心 2 轴 5 区齐备,项目点 100% 落在兼容分区内);④KG L3 可查(SPARQL:每个分区 derived_from 哪些图斑、typed_by 哪条规则);⑤渲染图例与参考图语义一致。

## 9. 一句话总结

非常规分区不是新问题,是"**自定义词汇 × 声明式规则 × 现有生成栈**"的组合:词汇表交给项目级 YAML(LLM 辅助冷启动、人工确认),类型标注交给 DSL 规则引擎(复用 v3 expr_eval),几何交给确定性地理处理(复用 zone_generator/dissolve/MIP),结构交给组装器(复用 axis_builder/accessibility),校核交给 L1 validator,落图交给 v3 registry+KG L3——系统提供机器,规划师提供词汇,LLM 只在闭集内消歧,绝不造词、绝不画几何。
