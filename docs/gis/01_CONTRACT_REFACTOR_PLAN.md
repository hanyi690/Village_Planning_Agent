# 契约先行重构方案（Contract-First Refactor Plan）

> 状态：待评审（2026-07-26）
> 前置：docs/gis/00_SYSTEM_DESIGN.md（总体设计）
> 依据：output/layout_results/jintian_2026-07-24/ 产出反查 + 全链路代码核查

---

## 第一部分：问题定性——为什么"能跑通"却不可用

7-24 跑批形式上全链路成功（solver=Optimal、渲染出图、报告生成），但产出不可用。
逐环节反查后确认：**不是某个模块质量差，而是模块间没有契约，每一环都在静默丢弃上一环的产出**。

### 1.1 已证实的断裂清单（按数据流顺序）

| # | 断裂点 | 证据 | 位置 |
|---|--------|------|------|
| D1 | PARSE 输出词表无约束：`ZoneTarget.land_use: str = ""` 是 LLM 自由文本 | targets 键为"商品林/宅基地"等文档原词 | `parse_contracts.py:65` |
| D2 | PARSE 约束到 MIP 归零：`_spatial_constraint_to_mip` 对 spatial 类约束一律返回 None，无告警 | `parse_constraint_count: 0`（PARSE 明明抽出 2 条） | `allocate.py:22-125` |
| D3 | KG 读取接口已不存在：`kg.get_constraints()` 在 v4.6 重构中被删，调用点未改 | 当前 HEAD 必抛 AttributeError | `tools/gis/kg.py:97` |
| D4 | KG 查询全部静默吞错：12 处 `try/except: pass`，失败即空列表 | `three_line_applied=0, vne_applied=0, protected_excluded=0` | `tools/gis/kg.py:104-154` |
| D5 | 邻接图死通道：`kg_adjacency_map` 取出后仅 log，从未构造 `adjacency_graph` 传入 solve() | MIP 邻接奖励整段死代码 | `allocate.py:222-224, 275-286` |
| D6 | MIP 内部词表错位：偏好成本/变更惩罚/保护排除全按五区词表设计，却被喂地类 targets | 三项全部退化为常数或恒假：changed_pct 恒 100%、preference 全 DEFAULT、建设区排除恒不触发 | `mip_allocator.py:65,173,261-274,429-443` |
| D7 | 校验反馈词表错位：adjustments 的 zone 用三区词表，`zone in target_map`（地类键）恒 False，反馈静默全丢 | 3 轮校验 checks 哈希完全相同（631b28b0），Worker-Evaluator 空转 | `allocate.py:235`、`run_layout_pipeline.py:425` |
| D8 | 约束来源重复冲突：生态保护区下限 371.77ha 与 333.36ha 并存，无去重仲裁 | validation_detail 同轮出现两条矛盾调整 | KG constraints 提取层 |
| D9 | 失败即交付：生产管线 execute→export 是无条件边，`_route_after_validation` 是死代码；所有节点 `except` 返回 `{}` 假成功 | 3 轮全 fail 照常出图出报告 | `layout_pipeline.py:414-422,349-351` |
| D10 | 脚本层断链：6 个 scripts 仍 import 已删除的 `modules.gis` | 7-25 起跑批第一步即崩 | `scripts/run_layout_pipeline.py:100` 等 |

### 1.2 根因

各模块的完成标准是"能产出 artifact"（KG 能导 turtle、MIP 能返回 Optimal、渲染能出 PNG），
而不是"产出被下游正确消费"。系统从未定义：

1. **统一词表**——至少 4 套分区词表并存（PARSE 地类自由文本 / 五区规划分区 / 校验器三区 / VNE），仅有 DLBM→X 单向映射，PARSE 输出→任何词表的映射不存在；
2. **约束编译契约**——约束在 3 个转换点（PARSE→MIP、KG→state、state→MIP）都可以静默消失；
3. **反馈协议**——校验建议无法保证可应用、更无法保证下轮结果变化；
4. **交付验收标准**——"什么算可用的规划成果"在代码和文档中均无定义。

---

## 第二部分：对现有设计文档的评估

00_SYSTEM_DESIGN.md 并非全错，须区分"设计正确但未实现"与"设计本身错误"：

### 2.1 设计正确、实现背离（保留设计，修实现）

| 设计条款 | 现状 |
|----------|------|
| §3.1 KG 不存约束数值/规则/指标（由 bundle.tables/ContextBlock 承载） | 实现仍从报告文本抽约束进 KG，且产生 D8 重复冲突 |
| §3.3 KG 几何计算全部由 spatial_ops 完成 | 部分遵守 |
| §3.5 定义了 `get_constraints/get_three_lines` 等 KG 读取接口 | 接口从未按契约实现，v4.6 后 `get_constraints` 干脆不存在（D3） |
| §5.5 验证闭环 | 闭环存在但空转（D7），无收敛保证 |

### 2.2 设计本身错误（本方案推翻）

| 设计条款 | 为什么错 | 本方案替代 |
|----------|----------|------------|
| §3.5 "MIP 直接消费 SPARQL 结果，不经过 ConstraintCompiler" | 被实证证伪：SPARQL 空结果静默传播为 applied=0，无任何环节发现。RDF→dict→MIP 缺少显式编译和丢弃审计 | 引入 **ConstraintCompiler**（§4.3），任何丢弃必须记录原因 |
| §3.2 L1 现状实体层 + L2 空间关系层全量入 RDF | 实证无消费者：EXECUTE 从不回查 KG；adjacency 是死通道（D5）；SPARQL 结果 build 时拍平进 state 后 KG 即失效。L1/L2 只贡献了 6s 构建耗时和第二真相源漂移 | **KG 收缩为规划语义层**（§4.4，即"KG 只保留规划对象"） |
| 词表隐式约定（各模块自带词表，无中央 enum） | D1/D6/D7 的共同根源 | **受控词表 + 唯一映射源**（§4.2） |

---

## 第三部分：目标picture——重构后的数据流

```
报告文本 ──PARSE──> SpatialPlanningIntent        [词表: 受控 enum，越界即拒绝]
                       │
DataCatalog(bundle) ───┼──ConstraintCompiler──> CompiledConstraintSet + CompilationReport
  ├ 三线/VNE/保护地块 ──┘                          [每条约束: 编译成功 | 丢弃(原因) | 冲突(仲裁)]
  ├ spatial_ops.adjacency ────────────────────> AdjacencyGraph（直接进 MIP，不绕 RDF）
  │
  └────> MIP EXECUTE ──> AllocationResult        [同一 enum；changed_pct 真实可比]
              │  ▲
              ▼  │ TargetPatch（同一 enum，可直接应用；应用后断言下轮模型变化）
          Validator ──> ValidationReport
              │
              ▼
         DeliveryGate ──pass──> 导出成品（GeoPackage/图/报告/用地平衡表）
              └──fail──> 导出诊断包（violations + CompilationReport + trace），不出成品

KG v5（收缩后）：只写 L3 意图实体 + L4 PlanBlock 增量（规划对象），
供意图追溯/操作审计/多版本对比/人机解释使用——不在 MIP 关键路径上。
```

---

## 第四部分：五个核心设计

### 4.1 契约总则

- 所有跨模块传递对象必须是 `modules/schema/contracts/` 下的 Pydantic 模型，禁止 raw dict；
- 任何"转换/编译"环节必须产出 **报告对象**（成功 n 条 / 丢弃 m 条+原因 / 冲突 k 条+仲裁结果），丢弃数 >0 但无报告 = bug；
- 禁止 `try/except: pass`：失败要么显式降级（写入 StageResult.warnings），要么 fail-fast。

### 4.2 受控词表（解决 D1/D6/D7）

**决策：MIP 主变量在"规划用途分区"（五区）层级优化；地类作为分区内细分目标。**

```python
# modules/schema/encodings/vocabulary.py（新增，唯一词表源）

class PlanningZone(str, Enum):
    """规划用途分区（MIP 主词表，与 DLBM_TO_PLANNING_ZONE 值域一致）"""
    VILLAGE_CONSTRUCTION = "村庄建设区"
    FARMLAND_PROTECTION = "农田保护区"
    GENERAL_AGRICULTURE = "一般农业区"
    FORESTRY_DEVELOPMENT = "林业发展区"
    ECOLOGICAL_PROTECTION = "生态保护区"

class LanduseClass(str, Enum):
    """地类词表（分区内细分目标 + 用地平衡表），成员从 GB/T 21010 编码集生成"""
    CULTIVATED = "耕地"
    ORCHARD = "园地"
    COMMERCIAL_FOREST = "商品林"
    ...

# 唯一合法的跨词表转换入口（复用现有 code_sets 数据，禁止其他模块私建映射）
LANDUSE_TO_ZONE: Dict[LanduseClass, PlanningZone]
def normalize_landuse(raw: str) -> Tuple[Optional[LanduseClass], str]:
    """LLM 自由文本 → 受控词表。返回 (匹配项 | None, 归一化说明)。
    别名表 + 编码表双路匹配；失配不静默——进入 ParseProduct.unmapped 清单。"""
```

PARSE 契约收紧：

```python
class ZoneTarget(BaseModel):
    land_use: LanduseClass                 # 原来是 str = ""，现在越界即 ValidationError
    raw_term: str                          # 文档原词，留审计
    planning_zone: PlanningZone            # 由 LANDUSE_TO_ZONE 派生，非 LLM 直出
    area_ratio: float
    ...
```

改造点：`parse_contracts.py`、PARSE 后处理器（新增 normalize 步骤）、
`mip_allocator.py`（targets 键改 PlanningZone + 分区内地类子目标）、
`layout_validator.py`（三区检查改为对 PlanningZone 聚合）、反馈 patch（§4.5）。

### 4.3 ConstraintCompiler（解决 D2/D3/D4/D8）

替代"PARSE→MIP 散转换 + KG→state 拍平"两条暗渠，单一编译入口：

```python
# modules/schema/contracts/constraint_contracts.py

class CompiledConstraint(BaseModel):
    id: str
    scope: Literal["global", "zone", "parcel_set"]
    zone: Optional[PlanningZone] = None
    parcel_bsms: Optional[List[str]] = None
    field: str                              # e.g. "area_ha"
    operator: Literal["<=", ">=", "=="]
    value: float
    hardness: Literal["hard", "soft"]
    weight: Optional[float] = None          # soft 时必填
    source: Literal["parse", "three_line", "vne", "protected", "rule_yaml", "feedback"]
    provenance: str                         # 原文/规则条目/查询名，可追溯

class CompilationReport(BaseModel):
    compiled: List[CompiledConstraint]
    dropped: List[Dict[str, str]]           # {source_item, reason} —— 必填，不允许静默丢
    conflicts: List[Dict[str, Any]]         # 同 scope+field 冲突 → 仲裁规则：hard>soft，取更严边界，记录被覆盖项

# modules/spatial_ops/constraint_compiler.py
class ConstraintCompiler:
    def compile(self, bundle: VillageBundle,
                parse_constraints: List[SpatialConstraint],
                rule_config: RuleConfig) -> CompilationReport: ...
```

关键变化：

- 三线/VNE/保护地块约束**直接从 bundle 类型化层计算**（spatial_ops），不再走 RDF→SPARQL→state 拍平链（D3/D4 整条通道废除）；
- D8 重复冲突在 `conflicts` 里显式仲裁（同 scope+field 保留最严格一条，记录被覆盖项）；
- MIP 侧断言：`CompilationReport.compiled` 非空但某类 `applied==0` → raise，禁止静默归零。

### 4.4 KG 收缩为规划语义层（回应"KG 应该只保留规划对象"）

**结论：采纳。** 实证依据：L1/L2 的三个理论用途全部另有实路——

| L1/L2 原定用途 | 实际情况 | 承接方 |
|----------------|----------|--------|
| 邻接关系→MIP | 死通道（D5），从未进 MIP | `spatial_ops.build_adjacency_graph(bundle)` 直连 solve() |
| 三线/VNE/保护→约束 | 静默归零（D4） | ConstraintCompiler（§4.3） |
| PARSE 空间接地 | 已用 context_blocks + constraint_index（bundle 派生），不查 KG | 维持现状 |

KG v5 范围：

- **保留 L3**（意图虚拟实体：ZoneTarget/FacilityTarget/Axis/Road/Operation，锚点用 BSM 引用现状地块，不复制属性）；
- **保留 L4**（PlanBlock 增量，版本化规划成果）；
- **删除 L1/L2 构建路径**（现状实体与空间关系不再入 RDF；`_add_spatial_relations` 及 Layer1 缓存机制随之下线）；
- KG 职责重新定位：意图追溯、操作审计、多版本对比、人机解释。**不在 MIP 关键路径上**——KG 故障不再能让布局静默劣化；
- `queries/tools.py` 中仍被引用的现状类模板（get_three_lines/count_by_vne 等）改由 spatial_ops 等价函数承接后删除。

预期收益：KG 构建从 ~6s 降至 <1s；消灭第二真相源；D3/D4/D5 连根拔除。

### 4.5 反馈协议 + 交付门槛（解决 D7/D9）

```python
# modules/schema/contracts/execution_contracts.py

class TargetPatch(BaseModel):
    zone: PlanningZone                      # 与 MIP targets 同词表——按构造保证可应用
    delta_ha: float
    new_bound: Optional[Tuple[str, float]] = None   # 直接给硬界，比累加 delta 更稳
    reason: str
    source_check: str

class ValidationReport(BaseModel):
    checks: List[CheckResult]               # check 词表 = PlanningZone
    passed: bool
    patches: List[TargetPatch]

# EXECUTE 重试循环的收敛断言：
#   应用 patches 后，目标向量/约束集必须与上一轮不同，否则 raise ConvergenceError
#   连续两轮 violations 集合不变 → 提前终止并标记 non_convergent（不再空转满 3 轮）

class DeliveryGate(BaseModel):
    """出口硬门槛——不满足则只出诊断包，不出成品"""
    land_balance_closed: bool               # 用地平衡表闭合 ±0.5%
    three_line_violations: int              # 必须 == 0
    protected_intrusions: int               # 必须 == 0
    changed_parcels_pct: float              # ≤ 阈值（默认 15%，村庄规划经验值，可配）
    zones_complete: bool                    # 必备分区齐全
```

生产管线改造：`execute → gate` 条件边取代无条件 `execute → export_gdb`；
节点级 `except: return {}` 全部改为 StageResult 显式上报，管线级决定降级或终止。

### 4.6 MIP 目标函数修正（依赖 4.2 后才有意义）

- 词表统一后 `native_zone == zt` 恢复可比 → 变更惩罚真实生效；`changed_pct` 恢复真实语义并纳入 DeliveryGate；
- 目标偏差改为**分级**：偏差 ≤10% 目标区间软惩罚，>10% 部分权重×10，>25% 硬上限（防止 7-24 式 +146% 偏差仍报 Optimal）；
- 邻接奖励接活（AdjacencyGraph 直连）后，保留现有线性化实现。

---

## 第五部分：分阶段实施计划

每阶段独立可验收、可回滚；验收标准全部可脚本化断言。

### Phase 0：止血（0.5 天）
- scripts 层 6 个文件迁移到 DataCatalog / 归档（`render_planning_layout.py` 归档）；
- `tools/gis/kg.py:97` 移除对已删除 `get_constraints` 的调用（临时返回空+显式 warning，Phase 2 整体替代）；
- 跑通金田村基线并存档全部指标（作为后续阶段的对照组）。
- **验收**：`run_layout_pipeline --source mineru` 全程无 Exception；基线指标 json 存档。

### Phase 1：受控词表（1-2 天）
- 新增 `vocabulary.py`（PlanningZone/LanduseClass enum + normalize_landuse + LANDUSE_TO_ZONE）；
- ZoneTarget 契约收紧；PARSE 后处理 normalize 步骤 + unmapped 清单；
- MIP targets / validator / TargetPatch 全部切换 enum。
- **验收**：① 全链路无自由文本 zone 键；② 构造一条三区反馈 patch，断言 100% 命中 target_map；③ changed_pct 出现真实值（≠100%）。

### Phase 2：ConstraintCompiler（2 天）
- 实现 CompiledConstraint/CompilationReport + spatial_ops 侧三线/VNE/保护地块直算；
- `_spatial_constraint_to_mip` 逻辑并入 Compiler 并补 dropped 审计；
- MIP 侧 applied==0 断言。
- **验收**：金田村数据下 three_line/vne/protected applied 均 >0（或 dropped 有明确原因记录）；D8 冲突进 conflicts 且只剩一条生效。

### Phase 3：反馈闭环 + 交付门槛（1-2 天）
- TargetPatch 协议 + 收敛断言 + 提前终止；
- DeliveryGate 接入生产管线条件边；节点 StageResult 化，废除 `except: return {}`。
- **验收**：① 人为注入必失败约束，断言各轮 checks 哈希不同或提前终止；② fail 时无成品输出、有诊断包。

### Phase 4：KG 收缩（2-3 天）
- 下线 L1/L2 构建；保留并补齐 L3（PARSE 落库）/L4（PlanBlock）；
- queries 模板迁移/删除；KGManager 缓存机制简化。
- **验收**：管线在 rdflib 不可用时仍能完成 MIP+校验+导出（KG 只影响审计功能）；KG 构建 <1s；e2e 测试适配后全绿。

### Phase 5：回归基准（1 天）
- 金田村 e2e：对照 Phase 0 基线，出对比报告。
- **验收**：DeliveryGate 全绿，或每项红灯有可解释的约束依据（而非工程缺陷）。

**总计约 7-9 个工作日。** 依赖序：P0 → P1 → P2 → P3 → P4（P4 可与 P3 并行）→ P5。

---

## 第六部分：需要你拍板的决策点

| # | 决策 | 方案默认 | 备选 |
|---|------|----------|------|
| Q1 | MIP 主变量词表层级 | 五区（规划分区）+ 分区内地类子目标 | 纯地类层优化，事后聚合成五区（现状做法，校验语义弱） |
| Q2 | KG 收缩幅度 | 只留 L3+L4（规划对象），L1/L2 下线 | 保留 L1 实体但只存 BSM 引用（折中，仍有维护成本） |
| Q3 | changed_pct 门槛 | 15%（可配） | 按村庄类型分级（集聚提升/城郊融合/搬迁撤并阈值不同） |
| Q4 | DeliveryGate fail 行为 | 不出成品、出诊断包 | 出带"FAIL"水印的草稿成品（利于人工介入） |
| Q5 | Phase 顺序 | 止血→词表→编译器→闭环→KG 收缩 | 若近期要演示，可 P0 后先做 P3 门槛（防止坏成果外流） |
