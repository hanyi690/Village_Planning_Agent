# GIS 数据管道重构实施方案 v3
## —— 编码谱系考证 + 原生 1:N 映射 + LLM 有界消歧 + 面向任意图层的可扩展架构

> 状态:提案(待评审)
> 日期:2026-07-28
> 输入:重构方案 v2(范式对齐版)、scene#2 深度研究(数据需求溯源)、当前代码现状调查(catalog/canonical/encodings/kg 四组)
> 权威顺序提醒:本文档如与模块 README / 02_EXECUTION_PLAN 冲突,以后者为准

---

## 0. 本方案与 v2 的关系:保留骨架,修正四处

v2 的范式骨架(registry 单一元数据源、Software-Defined Assets、GeoSPARQL、immutable/DLQ)方向正确,予以保留。但有四个实质性缺口,本方案修正:

| # | v2 的缺口 | v3 的修正 |
|---|-----------|-----------|
| 1 | "规则引擎而非硬编码推测"只说了方向,没回答**编码到底从哪来、映射为什么是 1:N** | §1 给出编码谱系考证(产生主体/依据标准/赋值时点),§2 给出原生 1:N 统一映射元模型 |
| 2 | 现状三个映射 YAML 三种 schema、运行时全部压平成 1:1 dict(0602 重复键已被静默覆盖) | §2.3 迁移方案:统一为 source→targets[] 结构,运行时不再压平 |
| 3 | "添加新层 1 个 YAML 条目"对**简单层成立,对异构层不成立**(WFS 多层服务、表、文档、自定义解析) | §5 引入 adapter 策略模式:YAML 声明 + adapter 引用 + 字段映射,覆盖 90% 场景;10% 特殊层注册 custom adapter |
| 4 | 未回答"编码消歧要不要 LLM、LLM 怎么不瞎编" | §3 消歧决策梯:LLM 只在**候选闭集**内做选择题并留证据,绝不自由生成编码 |

一个务实调整:**Pydantic Discriminated Union 不是必需的**。现状 `SpatialFeature.layer_type` 字段已存在但 ingest 路径基本不赋值,类型识别才被倒逼成 isinstance 链。最小改动是"ingest 强制赋 layer_type + registry 自动生成路由表"(§5.5),效果与 DU 等价但不动 30+ 个 dataclass。是否全面迁移 Pydantic 模型是独立决策,见 §5.5 取舍。

---

## 1. 编码谱系考证:乡村规划的编码到底是怎么得来的

(依据:scene#2 研究报告 §2/§3/§6,溯源至 GB/T 21010-2017、用地用海分类指南、广东指南及其数据库汇交要求、村土导则、李巍手册)

### 1.1 三类编码,三个产生主体,三个赋值时点

| 编码 | 产生主体 | 依据标准 | 赋值时点 | 村庄规划中的角色 |
|---|---|---|---|---|
| **现状地类编码 DLBM** | 国土调查单位(非规划师) | 三调工作分类(13一级/68二级)→ GB/T 21010(12一级/73二级) | 调查时点,遥感+实地判读 | **法定底数,直接继承,不可改**;字段含 DLBM/DLMC/QSXZ/ZLDWDM/TBMJ/GDPDJB/ZZSXDM/CZCSXM(203=村庄) 等 ≥30 个 |
| **规划地类编码 QMDLBM / GHFLBM / GHYTBM** | 规划编制单位 | 广东:QMDLBM 用 tugui(省县级土规库标准)、GHYTBM 用 appendix5(省技术指南附录5,21条);GHFLBM 为粗口径规划分类(1:N 下挂 appendix5) | 规划编制时点 | 期末地类图斑 QMDLTB 的核心字段,共 18 字段(TBH/DLBM/DLMJ/QMDLBM/GHFLBM/GHYTBM/LSYSXZB1/2…) |
| **分区编码 TDYTFQDM / JSYDGZQ** | 规划编制单位 | 广东数据库标准:TDYT 图层 TDYTFQDM 分区代码;JSYDGZQ 图层 TDKJGZFQDM ∈ {允许建设区, 限制建设区, 有条件建设区, 禁止建设区} | 规划编制时点 | 用途管制与管制分区的法定表达 |
| 行政区划代码 XZQHDM | 民政/国标 | GB/T 2260,**12 位 = 县级以上6 + 镇级3 + 村级3** | 调查/编制通用 | 一切实体挂接的主键前缀(BSM 之外) |
| 用地用海分类 ydyhfldm | 自然资源部(2023版 24/113/140) | 《国土空间调查、规划、用途管制用地用海分类指南》 | 新标过渡期 | 与三调地类的官方对应见该指南附录F |
| 村庄用地分类 V/N/E | 住建部 | 《村庄规划用地分类指南》(3大类/10中类/15小类) | 住建口规划 | 与 GB50137 三大类对照(V↔H14) |

**结论 1:没有任何一个编码是"设计出来的字符串",全部是法定枚举闭集 + 官方对应表。** 这直接决定了:①系统内编码字典必须原文照录标准(现 gbt21010.yaml 已如此,好);②映射必须忠实表达官方的"一一对应/一对多"两种情形;③LLM 永远不允许创造编码,只能在闭集内选择。

### 1.2 "不是一一对应"是官方明认的常态,且官方给了四种消歧方法

李巍手册表 2-21/2-22(基数转换)明确:三调地类→规划地类存在两类转换——

- **一一对应**:如 0702 农村宅基地→0703 农村宅基地;
- **一对多**:如 05H1 商业服务业设施用地→6 类、08H2 科教文卫用地→8 类、0809 公用设施用地→11 类、09 特殊用地→7 类。

官方细分四法(按优先级):**方法一 POI 辅助;方法二 地形图辅助;方法三 影像判读辅助;方法四 补充调查**(前三法都无法判读时)。

**结论 2:"一对多"不是数据脏,是标准的内在结构。** 官方四法中,方法一/二/三都是**机器可先执行的确定性通道**(POI 服务、地形图字段、影像指标),方法四对应人工;LLM 的角色是当确定性通道证据不足时,融合上下文在候选闭集内给出"建议选择+证据",见 §3。这与项目 candidate_engine.py 已有的"只提候选、绝不自动决定"语义完全同构——v3 是对它的正规化,不是另起炉灶。

### 1.3 项目现状的三个硬伤(来自代码调查)

1. 三个映射三种 schema:`dlbm_to_ghytbm`(1主+1备单值 alternative)、`sddlbm_to_ydyhfldm`(真 1:N + when)、`ghflbm_to_tdytfqdm`(N:1 无条件);运行时**全部压平为 1:1 dict**,条件信息丢失。
2. `dlbm_to_ghytbm.yaml` 中 `0602` 出现两次(→2130 采矿、→1510 设施农用地),dict 加载时**静默覆盖**,一条映射已丢失。
3. `planning_zone_rules.yaml` 的 decision_rules 有 priority/condition/params 且 rule_loader 已 typed 加载,但 **condition 字符串的求值器散落在别处**,规则引擎是半拉子。

---

## 2. 统一编码元模型(Encoding Meta-Model)

### 2.1 编码体系字典:统一 schema(向后兼容迁移)

```yaml
# dicts/encodings/<system>.yaml
version: "2023"
standard: "国土空间调查、规划、用途管制用地用海分类指南"
system: ydyhfldm            # 机器名,全局唯一
authority: "自然资源部"      # 新增:产生主体(§1.1)
role: planned               # 新增: current(现状继承) | planned(规划赋值) | admin | reference
code_format: "4位数字"
levels: 3                    # 新增:分类层级数
classes:
  - code: "0703"
    name: "农村宅基地"
    parent: "07"             # 层级父子(新增,统一有)
    cross_refs:              # 体系内 cross-reference(替代各自为政的 dlbm_ref/vne/zone_type 字段)
      gbt21010: ["0702"]
      vne: ["V11"]
```

迁移:appendix5 的 `zone_type/vne/ydyhfldm` 字段、ghflbm 的 `ghytbms` 列表、tugui 的 `planning_zone/primary_zone/categories` 全部迁入 `cross_refs` 结构;`loader.py` 的 DictionaryCenter 增加 schema 版本探测,旧字段读取走兼容 shim(一次性,标记 deprecated)。

### 2.2 映射字典:原生 1:N 统一 schema

```yaml
# dicts/mappings/sddlbm_to_ydyhfldm.yaml(从 references/ 移入,统一目录)
version: "1.0"
source_system: sddlbm
target_system: ydyhfldm
basis: "用地用海分类指南附录F(官方对应)"   # 新增:映射的权威来源,必须填写
mappings:
  - source: "05H1"
    default: "0900"                        # 无上下文时的缺省(原 candidate)
    decision: context                      # auto(唯一) | context(需消歧) | manual
    targets:
      - code: "0900"
        when: null                         # 恒真 → 缺省
        confidence: exact
      - code: "0901"
        when: 'poi_match(["商业","店铺","超市","商场"])'
        evidence_hint: [poi]
        confidence: conditional
      - code: "0902"
        when: 'poi_match(["办公","写字楼","商务"])'
        evidence_hint: [poi]
        confidence: conditional
      - code: "0903"
        when: 'imagery_indicator("nightlight_high") or poi_match(["KTV","影院","娱乐"])'
        evidence_hint: [imagery, poi]
        confidence: conditional
```

要点:
- `targets[]` 原生列表,**运行时绝不压平**;`default` 单独标注,替代"dict 覆盖"的隐式语义;
- `when` 是**可序列化表达式 DSL** 的字符串形式(§2.4),不是自由文本;
- `evidence_hint` 声明该候选依赖哪条官方消歧通道(§1.2 的 poi/地形图/影像/补充调查);
- `basis` 必填——每个映射必须能回溯到标准出处(scene#2 的溯源原则落到数据层);
- N:1 映射(ghflbm→tdytfqdm)用同一 schema 表达(`targets` 恒为单元素,`decision: auto`)。

### 2.3 迁移清单(含 bug 修复)

| 现有文件 | 迁移动作 |
|---|---|
| `references/dlbm_to_ghytbm.yaml` | 转统一 schema;**修复 0602 重复键**:拆为两条 target(2130 采矿 / 1510 设施农用地),when 分别挂 `field_equals("QSXZ","10")`(国有→采矿)与影像/补充调查,decision: context |
| `references/sddlbm_to_ydyhfldm.yaml` | 转统一 schema;`needs_human_decision: true` → `decision: manual`;alternatives.when 自由文本 → DSL 表达式(人工翻译一次,约 20 条) |
| `rules/ghflbm_to_tdytfqdm.yaml` | 转统一 schema,decision: auto;**修正键名拼写 tdyfqdm→tdytfqdm**(加载器兼容期双读) |
| `loader.py` `_PROPOSAL_FILES` 硬编码 | 删除;改为扫描 `dicts/mappings/` 目录,按 `source_system/target_system` 自注册 |
| `code_sets.py` 各压平 dict | 保留只读兼容视图(标记 deprecated),新代码一律走 `MappingRegistry.resolve()` |

### 2.4 条件表达式 DSL(小型、可测试、可沙盒求值)

```
expr      := or_expr
or_expr   := and_expr ("or" and_expr)*
and_expr  := atom ("and" atom)*
atom      := "(" expr ")" | func_call | comparison | "null"
func_call := ident "(" [arg ("," arg)*] ")"
comparison:= field op literal   ; op ∈ == != in starts_with ends_with gt lt
内建函数  : poi_match([kw...])              ; POI 通道
            field_equals("F","v")           ; 图斑属性
            within_zone("YJJBNT")           ; 空间通道(KG/spatial_ops)
            imagery_indicator("name")       ; 影像通道
            area_gt(hectares)               ; 面积阈值
```

求值器单点实现于 `dicts/expr_eval.py`,输入 `MappingContext`(parcel_attrs / poi_hits / zone_membership / imagery_signals)。**planning_zone_rules.yaml 的 condition 字符串同步迁到该 DSL**,把散落的求值逻辑收编进同一引擎(rule_loader 继续负责 typed 加载,expr_eval 负责求值,职责分离)。

---

## 3. 消歧决策梯:LLM 放在哪、怎么放

### 3.1 四级阶梯(确定性递减,成本递增)

```
L0 auto      targets 仅 1 个(或 when=null 恒真)        → 直接映射,零成本
L1 context·确定性通道  when 表达式可求值且唯一命中      → 规则引擎决定,零 LLM
        (官方方法一/二/三的机器化:POI / 地形图字段 / 影像指标 / within_zone)
L2 context·LLM 辅助   多候选幸存 or 证据不足           → LLM 在候选闭集内选择+留证据
L3 manual    decision:manual,或 LLM confidence 低于阈值 → 人工队列(DLQ 第三类)
```

### 3.2 为什么必须有 L2,以及为什么 L2 不能是"LLM 生成编码"

- 必须有:实测中 `05H1/08H2/0809/09` 这类一对多占了转换歧义的大头,而 POI/地形图两通道在偏远村庄经常都无覆盖(方法四补充调查就是为此存在)。纯规则会在这些村退化成"全走 default",转换质量不可控。
- 不能生成:编码是法定枚举闭集(§1 结论1)。LLM 自由生成必然产生标准不存在的码,且无法审计。因此 L2 的 LLM 任务是**选择题 + 举证**,不是填空题。

### 3.3 L2 具体设计(复用现有设施)

复用 `backend/app/core/instructor_client.py`(`get_instructor_client()` + `get_flash_model()`)做结构化输出;复用 `candidate_engine.py` 的 `ClassificationProposal` 语义,扩展为:

```python
# dicts/disambiguation.py(新增)
class Candidate(BaseModel):
    code: str
    when_expr: str | None
    surviving_evidence: list[str]      # L1 已命中的证据

class DisambiguationContext(BaseModel):
    source_system: str
    source_code: str
    parcel_attrs: dict                 # 图斑全属性(DLBM/DLMC/QSXZ/TBMJ/ZZSXDM...)
    neighbors: list[dict]              # KG EntityCard 摘要: within_zone/touches 邻居
    poi_hits: list[dict]               # POI 通道结果(可能为空)
    zone_membership: list[str]         # 所在控制面(YJJBNT/STBHHX/JSYDGZQ...)
    village_profile: str               # RAG 村庄画像(产业/地貌,≤200字,来自现状报告 chunks)
    candidates: list[Candidate]        # 闭集,LLM 只能从中选

class DisambiguationDecision(BaseModel):
    chosen_code: str                   # 必须 ∈ candidates(validator 强制)
    confidence: Literal["high","medium","low"]
    rationale: str                     # ≤100字,引用证据
    evidence: list[str]
    decided_by: Literal["llm"] = "llm"
    model: str                         # 记录 model 版本
    reviewed: bool = False             # 人工复核标志
```

调用策略(成本控制):
1. **缓存**:key = `hash(source_code, zone_membership, poi_signature, village_id)`,同村同类图斑只调一次;
2. **批处理**:按 (source_code, village) 分组,一组一次调用,组内图斑共享决策;
3. **降级**:`low` confidence 或验证失败 → 落 L3 人工队列,不阻塞管道(DLQ 语义与 v2 一致);
4. **审计**:决策写入图斑属性 `_mapping_provenance = {decided_by, confidence, rationale, model, ts}` 并同步入 KG 谓词(§6.3);`reviewed=false` 的决策在交付质检报告中单列。

### 3.4 与 candidate_engine 的关系

`CandidateEngine.propose()` 升级为决策梯的统一入口:

```python
def resolve(self, source_system, target_system, source_code, ctx: MappingContext) -> Resolution:
    mapping = self.mappings.get(source_system, target_system, source_code)
    if mapping is None:                       → Resolution.unmapped()      # 进 DLQ 第一类
    if mapping.decision == "auto":            → Resolution.auto(default)
    hits = expr_eval.filter(mapping.targets, ctx)
    if len(hits) == 1:                        → Resolution.rule_based(hit) # L1
    if mapping.decision == "manual":          → Resolution.manual(alts)    # L3
    decision = llm_disambiguate(ctx, hits)    # L2,带缓存/批处理/降级
    return Resolution.llm(decision)
```

---

## 4. 分区编码推导的规则化(回答"分区编码怎么设置")

分区编码不是独立赋值,而是**地类 + 控制线 + 规则**的推导结果:

| 分区字段 | 推导链 | 规则载体 |
|---|---|---|
| TDYTFQDM(用途分区) | GHYTBM/GHFLBM →(N:1 映射)→ TDYTFQDM;冲突时 planning_zone_rules.decision_rules(priority 降序)裁决 | `mappings/ghflbm_to_tdytfqdm.yaml` + `rules/planning_zone_rules.yaml` |
| TDKJGZFQDM(管制分区) | 三区三线叠加:落在 YJJBNT→禁止建设区(基本农田图斑内规划用途必须为农用地,广东 8 条衔接约束之一);村庄建设边界内→允许建设区;边界外生态/农田区外→限制建设区;声明留白→有条件建设区 | `rules/construction_zone_codes.yaml` + 广东 8 条衔接约束(应固化为 `rules/gd_linkage_constraints.yaml`,validator 直接消费) |
| planning_zone / primary_zone | tugui 字典 cross_refs + `_GHYTBM_TO_PLANNING_ZONE` 24 条(从 code_sets.py 迁入 rules) | `rules/planning_zone_rules.yaml` |

v3 动作:①`_GHYTBM_TO_PLANNING_ZONE`(code_sets.py L162-188)迁出硬编码进 rules YAML;②condition 统一走 §2.4 DSL;③广东 8 条衔接硬约束从 scene#2 报告固化为机器可执行规则集(它们是 validator 的现成规则,也是 EXECUTE 通道"管制规则校验"函数的依据)。

---

## 5. 图层注册表扩展:面向"后续各种 GIS 图层"

### 5.1 registry 元模型(在 v2 草案上补全)

```yaml
# schema/types/gis_layer_registry.yaml · 条目全集
layer_types:
  water:
    i18n: {zh: 水系, en: water}
    geometry_kind: polygon            # point|line|polygon|raster|table|document
    group: natural                    # 语义组(constraint|natural|transport|facility|landuse|admin|hazard...)
    ingest:
      adapter: features               # ★ adapter 引用(§5.2)
      feature_type: water
      field_mapping:                  # ★ 中文别名→canonical 字段(收编 _LANDUSE_ALIASES 思路)
        dlbm: ["DLBM", "地类编码", "dlbm"]
        name: ["MC", "名称", "NAME"]
    encodings:                        # ★ 本层参与哪些编码体系与映射
      dlbm_field: dlbm
      systems: [gbt21010]
      mappings: [{from: gbt21010, to: appendix5, on: dlbm}]
    spatial:
      is_constraint: false
      participates: [water_overlap]   # 参与的空间分析(命名分析器)
    bundle_target: {group: polygons, key: water_bodies}
    kg:                              # KG 侧声明性配置(不含函数名,见 §6.1 注册机制)
      entity_type: WaterBody
      uri_policy: "L1:{type}_{bsm}"
      phase: L1                      # L1|L3|L4,决定在 build_from_bundle 哪个阶段跑
      order: 30                      # 同 phase 内的执行序(升序)
      enabled: true                  # 可整体关闭某层 KG 落图
    validation:
      required_fields: [dlbm]
      geometry: {must_be_valid: true, dlq_on_error: true}
```

`GisLayerTypeEntry` Pydantic 模型同步扩展(嵌套模型:IngestSpec/EncodingsSpec/SpatialSpec/BundleTarget/KgSpec/ValidationSpec)。

### 5.2 adapter 策略模式:90% 新层不改 Python

现状 ingest 只有 parcels/features/raster 三条硬路径。v3 定义 6 个标准 adapter:

| adapter | 适用 | 实现基础 |
|---|---|---|
| `parcels` | 地类图斑类(现状/规划) | 现 `result_to_parcels`(消除 tempfile,§7) |
| `features` | 一般点/线/面要素 | 现 `result_to_features`(同上) |
| `wfs_layers` | api_vector 多层服务(sources.yaml 的 layers[]) | 现 wfs.py 包装 |
| `raster` | DEM/DOM/slope 等 | 现 `result_to_raster` |
| `table` | 属性表(台账/指标) | 现 table_types |
| `document` | 文本类 | 现 documents/loader |

YAML 中 `ingest.adapter: <name>` + `field_mapping` 即完成接入;adapter 签名统一:

```python
class IngestAdapter(Protocol):
    def load(self, data: dict, entry: GisLayerTypeEntry, ctx: IngestContext) -> AdapterResult:
        """data: fetch 后的内存对象(不落临时文件);返回 features+warnings+dlq"""
```

特殊层(如需要逐图斑调外部服务的)实现同名协议并在代码中注册:`ADAPTERS.register("custom_soil", SoilAdapter())`——这是唯一需要写 Python 的情形,且不改引擎。

### 5.3 bundle 动态化

`PointLayerGroup/LineLayerGroup/PolygonLayerGroup` 改为 `_layers: Dict[str, List[Any]]`,由 registry 按 `bundle_target` 自动创建 key;现有 property(landuse_current 等)保留为兼容访问器;`constraint_polygons` 等聚合 property 改为"查 registry 中 `spatial.is_constraint==true` 的所有层"(v2 草案思路,直接采纳)。`all_features()`/`to_geojson_dict()` 遍历 _layers,不再枚举字段。

### 5.4 类型路由:tag 赋值 + 路由表自动生成(替代 isinstance 链,也替代硬上 DU)

- ingest 出口**强制** `feature.layer_type = entry.layer_type`(现状该字段空转);
- `layer_registry.py` 在 `build_registry_from_yaml()` 时自动生成 `ROUTING: Dict[layer_type, (adapter, model_class, bundle_target)]`——`_TYPE_BINDINGS` 从手写改为从 YAML 派生(保留覆盖钩子);
- `_assign_to_bundle` 删除 33 分支 isinstance 链,改为 `bundle.group(entry.bundle_target).append(feat)`;
- `_init_feature_registry()`(ingest.py L452)改为直接读 ROUTING。

### 5.5 Pydantic DU 取舍(回应 v2)

| 方案 | 收益 | 成本 | 建议 |
|---|---|---|---|
| A. layer_type tag + registry 路由(§5.4) | 消除 isinstance 链;改动局限在 ingest/catalog/registry 三处 | 无运行时验证收益 | **采纳为本期方案** |
| B. 全面迁移 Pydantic v2 + DU | 解析期验证、序列化免费、DU 自动路由 | 30+ dataclass 重写,GeoJSON 中文别名字段映射要重做,下游 KG/layer1 1369 行全部回归 | 列为 v3.1 独立评估,不与本期耦合;若做,tag 复用 §5.4 已赋值的 layer_type 作 discriminator |

---

## 6. KG 构建自动化与 GeoSPARQL 对齐

### 6.1 builder 注册机制:装饰器绑定 + YAML 声明(Option 3)+ 启动期校验

**决策:采用"两者结合"——YAML 声明 KG 侧关注点(entity_type/uri_policy/phase/order/enabled),装饰器把函数绑定到 layer_type。** 不用纯 YAML 字符串引用(`kg.builder: _add_water_bodies`),也不用纯装饰器。

取舍依据:

| 方案 | 致命缺陷 | 是否采纳 |
|---|---|---|
| 1. 纯装饰器 `@kg_builder('water')`,YAML 只放 entity_type | 管道执行序/条件/enabled 等"调度关注点"无处安放,要么塞进装饰器(实现与配置混杂),要么再开一处配置 → 仍是两处;且"某 layer_type 是否产出 KG 实体"要 grep Python 才知道,单源真理被打破 | 否 |
| 2. 纯 YAML `kg.builder: _add_water_bodies` | 字符串→函数 getattr 反射;**函数重命名时 YAML 静默失效,运行时才暴露**(layer1.py 1369 行 + layer3/4,真实维护风险);IDE 跳转/重构全断;还要造"哪个模块持有哪个 builder"的解析机制 | 否 |
| 3. YAML 声明 + 装饰器绑定 | 两处都要改,但职责分离干净;join key 是 layer_type(本就是全系统规范标识);**启动期可做双向校验把"漏改"从运行时故障提升为启动失败** | **采纳** |

**职责切分(关键)**:
- **YAML 答"管道怎么跑"**:entity_type 名、uri_policy、phase(L1/L3/L4)、order、enabled——全是声明性、非 Python 人员可改、调试时一眼看清全管道执行序;
- **装饰器答"哪个函数实现"**:`@kg_builder('water')` 挂在函数上,IDE 可跳转、可重命名(重命名函数不动 decorator key,因为 key 是 layer_type 不是函数名)。

```python
# kg/builder/registry.py(新增,极小)
_BUILDER_BINDINGS: dict[str, KgBuilderBinding] = {}

def kg_builder(layer_type: str):
    """把函数注册为某 layer_type 的 KG builder。layer_type 必须在 gis_layer_registry.yaml 已声明。"""
    def deco(fn):
        if layer_type in _BUILDER_BINDINGS:
            raise ConfigError(f"layer_type {layer_type!r} 已绑定 builder:{_BUILDER_BINDINGS[layer_type].fn.__name__}")
        _BUILDER_BINDINGS[layer_type] = KgBuilderBinding(fn=fn, layer_type=layer_type)
        return fn
    return deco

# layer1.py —— 现有 mixin 方法改为模块级函数 + 装饰器(顺带消除 mixins.py 的间接绑定)
@kg_builder('water')
def add_water_bodies(builder, features, *, entry, ctx) -> BuildReport: ...

@kg_builder('landuse_current')
def add_parcels(builder, features, *, entry, ctx) -> BuildReport: ...
```

```python
# kg/builder/base.py —— build_from_bundle 改为按 YAML 调度,不再硬编码调用序
def build_from_bundle(self, bundle, ...):
    for phase in (Phase.L1, Phase.L3, Phase.L4):
        entries = [e for lt, e in GIS_LAYER_REGISTRY.items()
                   if e.kg and e.kg.enabled and e.kg.phase == phase]
        entries.sort(key=lambda e: e.kg.order)
        for entry in entries:
            binding = _BUILDER_BINDINGS.get(entry.layer_type)
            if binding is None:           # 启动校验已保证不会到这,防御
                continue
            features = bundle.group(entry.bundle_target) if entry.bundle_target else []
            report = binding.fn(self, features, entry=entry, ctx=ctx)
            self._merge_report(report)
```

**启动期双向校验(本方案的护城河,把 Option 3 的"两处维护"风险压到最低)**:

```python
# app 启动时(app/modules/kg/builder/__init__.py 导入末尾)
def _validate_builder_registry():
    yamled = {lt for lt, e in GIS_LAYER_REGISTRY.items() if e.kg and e.kg.enabled and e.kg.entity_type}
    bound = set(_BUILDER_BINDINGS)
    missing = yamled - bound                       # YAML 说要建,没函数 → 启动失败
    orphan = bound - set(GIS_LAYER_REGISTRY.keys())  # 装饰器绑了,YAML 没声明 → 启动失败
    if missing: raise ConfigError(f"缺少 builder:{missing}")
    if orphan:   raise ConfigError(f"装饰器绑定了未注册的 layer_type:{orphan}")
```

效果:函数被重命名 → 装饰器仍有效(key 是 layer_type);layer_type 在 YAML 被改名 → 装饰器变 orphan → **启动即报错**,不会拖到运行时静默跳过。这是 Option 2 永远做不到的。

**额外收益**:现有 `mixins.py` 把 layer1/3/4 模块函数绑到 Layer1Mixin 的间接层可一并删除——builder 直接是注册过的模块函数,`build_from_bundle` 通过 binding.fn 调用,不再需要 mixin 方法分发。layer2 已空化,无影响。

**条件执行**:需要"bundle 有水系才跑"这类前置条件时,在 builder 函数体内首行 `if not features: return BuildReport.empty()` 即可(实现自描述,比 YAML `when:` 表达式更直接);只有跨层依赖(如 parcels 必须先于 facilities)才用 YAML `order` 表达,避免再造条件表达式 DSL。

### 6.2 谓词映射(自定义→GeoSPARQL,向后兼容双写)

| 现有 | 标准 | 处置 |
|---|---|---|
| Relations.touches | geo:sfTouches | 双写一季后弃旧 |
| Relations.intersects | geo:sfIntersects | 同上 |
| Relations.contains | geo:sfContains | 同上 |
| Relations.nearby | pln:nearby | 保留(无标准对应),文档化为扩展 |
| within_zone / designated_as / connects / delineates(兼容位) | pln:* | 保留并正式纳入扩展词典 |
| 几何 | geo:hasGeometry + geo:asWKT(WKT literal) | 新增,实体同时落 centroid(现有)与 WKT |
| 重叠定量 | pln:overlap_pct(挂 OverlapNode) | 保留(与 L2 关系定案一致) |

GEO 命名空间目前在 ontology.py 只声明未使用,本期开始真实使用;SemanticPredicates 全部保留为 pln: 扩展,并补词典文档(对齐 KG 查询接口定案:~10 查询模式 + 谓词词典)。

### 6.3 编码决策 provenance 入 KG

新增扩展谓词:`pln:decided_by {rule|llm|human|default}`、`pln:decision_confidence`、`pln:decision_evidence`、`pln:mapping_basis`(映射的标准出处,§2.2 的 basis)。这让"编码可回溯到教材和规范"从文档层落实到**图斑级数据层**——也是 scene#2 溯源原则的最终落点。

---

## 7. 质量与幂等(DLQ + immutable)

- **DLQ 三类分流**:①几何无效(must_be_valid 失败)→ `dlq/geometry`;②映射缺失(unmapped)→ `dlq/mapping`;③待人工(manual/low-confidence)→ `dlq/review`。每类带原始 feature + 原因 + 来源 layer_type;管道不中断(v2 方向,与现状 warnings 收集制兼容——现状仅 strict=True 才抛,保持)。
- **消除 tempfile**:ingest.py L647/L675 两处 `NamedTemporaryFile` 改为直接解析内存 dict(adapter 签名已按此设计,§5.2)。
- **hash-keyed artifacts**:`raw_gis_data/typed_features/village_bundle/spatial_relations/kg_graph` 五层 asset 各以 `hash(source_path + mtime + registry_version + mappings_version)` 为键持久化;同键跳过,实现 v2 的 immutable/idempotent。SDA 的调度先用轻量 Python 编排表达(不引入 Dagster 依赖,asset 边界与声明式依赖保留,引擎后置)。

---

## 8. 分阶段实施计划

| Step | 内容 | 主要文件 | 验收标准 | 风险 |
|---|---|---|---|---|
| 0 | 冻结行为:金田村数据跑 golden bundle + golden KG,快照对比基线 | tests/(新增) | 基线可重复 | 无 |
| 1 | 统一 mapping schema + 迁移三映射 + 修 0602 键覆盖 + mappings/ 目录自注册 | dicts/, loader.py, code_sets.py(兼容视图) | 0602 两候选均可达;旧 lookup 函数输出不变(兼容视图对齐测试) | 中:压平依赖点排查 |
| 2 | 表达式 DSL + expr_eval 求值器 + planning_zone_rules condition 迁移 + _GHYTBM_TO_PLANNING_ZONE 出硬编码 | dicts/expr_eval.py(新), rules/*.yaml, code_sets.py | 全部 condition 可求值;规则单测覆盖 | 低 |
| 3 | layer_type 强制赋值 + ROUTING 自动派生 + 删 _assign_to_bundle isinstance 链 + _TYPE_BINDINGS 改 YAML 派生 | catalog.py, layer_registry.py, ingest.py | golden bundle 与基线一致(Step 0 快照) | 高:核心路径,靠快照兜底 |
| 4 | registry 元模型扩展 + 6 adapter + canonical 动态 _layers + 兼容 property | types/, data/(adapters 新包), canonical.py | 新增一个测试层只改 YAML 即入 bundle;旧 property 行为不变 | 中 |
| 5 | builder registry 循环 + 签名统一 + GeoSPARQL 双写 + provenance 谓词 | kg/builder/, ontology.py | golden KG 旧谓词仍在;新谓词按映射表出现 | 中 |
| 6 | L2 LLM 消歧通道(缓存/批处理/降级)+ DLQ 三类 + 质检报告(reviewed=false 单列) | dicts/disambiguation.py(新), pipeline | 05H1 用例:POI 命中走 L1;无 POI 走 L2 且 provenance 完整;manual 进 DLQ 不阻塞 | 中:成本与一致性,缓存命中率监控 |

依赖关系:0→1→2→3→4→5→6;1+2 可与 3 并行(不同文件域),但合并顺序保持 2→3。

---

## 9. 回应你的三个问题(总结)

**Q1 怎么规范地自动处理各异 GIS 数据?**
adapter 策略模式(6 标准 + custom 扩展)+ geopandas read_file 自动格式检测(file_vector driver 已有)+ field_mapping 中文别名声明。新层 = 1 条 YAML(选 adapter + 字段映射 + bundle_target + kg 映射),90% 场景零 Python;类型路由靠强制 layer_type tag + registry 派生路由表,isinstance 链与 _TYPE_BINDINGS 手写表同时消除。

**Q2 怎么规范地管理(添加一种数据太复杂)?**
两级单一入口:**图层**走 `gis_layer_registry.yaml`(§5.1 元模型全集),**编码与映射**走 `dicts/`(encodings 统一 schema + mappings 统一 1:N schema + 目录自注册,§2)。runtime 不再压平映射、不再散落硬编码(_GHYTBM_TO_PLANNING_ZONE、startswith("31") 水域兜底均迁规则)。

**Q3 编码到底怎么来的 / 分区编码怎么设置 / 要不要 LLM?**
- 编码全部是法定枚举闭集:现状 DLBM 由国土调查产生(三调/GB/T21010),规划编码(QMDLBM=tugui、GHYTBM=appendix5、GHFLBM)与分区编码(TDYTFQDM、TDKJGZFQDM 四值)由规划单位按省级数据库标准赋值,XZQHDM 按 GB/T 2260(6+3+3)。
- 一对多是标准内在结构,官方消歧四法 = POI/地形图/影像/补充调查;系统设计为 **L0 直映 → L1 规则消歧(前三法机器化)→ L2 LLM 候选闭集内选择+举证 → L3 人工队列**。
- LLM 需要,但有界:只在候选闭集内做选择题、输出证据、落 provenance(decided_by/confidence/reviewed),绝不生成编码;缓存+批处理控成本,low confidence 降级人工。这把"可回溯到教材和规范"落实到了图斑级。

---

## 附录:本方案引用的现状事实(代码调查摘要)

- catalog.py L312-439 `load_village_bundle()`、L538-626 `_assign_to_bundle` 33 个 isinstance 分支、L404 `dlbm.startswith("31")` 水域兜底;
- layer_registry.py L80-135 `_TYPE_BINDINGS` 手写表;canonical.py 23+8+5 硬编码 LayerGroup 字段,无 _layers;
- ingest.py L452 `_init_feature_registry`、L647/L675 tempfile;验证收集制(strict=False 默认);
- 6 体系字典 schema 各异;3 映射 3 种 schema 且运行时压平;0602 键被覆盖;`_PROPOSAL_FILES` 硬编码;
- candidate_engine 已有 ClassificationProposal(exact/conditional/ambiguous)+ _match_context 关键词窄化(无量化评分);
- ontology.py GEO 命名空间零使用;Relations 8 active + 4 兼容;
- builder/base.py 硬编码顺序调用 mixin;layer1.py 1369 行建 10 类实体;layer2 已空化,关系由 spatial_ops.bridge 预计算注入;
- instructor_client.py 提供 get_instructor_client()/get_flash_model(),L2 直接复用。
