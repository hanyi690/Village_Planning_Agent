# GIS 效果提升 + 前端交互式集成设计方案

## Context

当前 GIS 布局引擎存在两个核心瓶颈：

1. **文本→参数提取不准**：`parse_planning_text` 用正则解析 LLM 自由文本输出，格式偏差就失败；metrics 中有精确数值但只拼成字符串让 LLM 重读
2. **空间布局粗糙**：MIP 本质是"分类贴标签"，设施放置基于 DLBM 质心+固定偏移

前端 GIS 与主规划流程割裂。

**目标**：先后端效果提升（金田村真实数据验证），再前端交互式集成（编辑+反馈闭环）。

---

## 当前实现详解

### 1. 文本解析链路（`layout_tools.py` + `prompts.py`）

**入口**：`parse_planning_text` 工具（L222-235），数据通过 `InjectedState("reports")` 自动注入。

**核心流程**（`_parse_reports_to_intent`，L169-193）：

```python
# Step 1: 拼接 prompt
prompt_text = _prepare_parse_prompt(reports, village_name)
# → 遍历 13 个 SPATIAL_DIMS，每个维度提取 text_summary（前800字）
# → land_use_planning 维度额外提取 total_area 和 current_land_use（metrics 中含 area/ratio/ha 的字段）
# → 拼成 SPATIAL_LAYOUT_PARSE_PROMPT 的 {planning_text} 占位符

# Step 2: 单次 LLM 调用（自由文本输出）
llm = ChatOpenAI(model=LLM_MODEL, temperature=0, request_timeout=120)
response = llm.invoke(prompt_text)

# Step 3: 正则后处理
_postprocess_llm_response(response.content)
```

**关键缺陷**：

- `_prepare_parse_prompt`（L75-122）：metrics 精确数值（如 `building_construction_sum_ha: 30.5`）只拼成字符串 `current_land_use`，LLM 需要从文本重新解读
- `_postprocess_llm_response`（L125-166）：`re.search(r'```json...')` 正则提取 JSON 脆弱；area_ratio 归一化是简单除法+残差给第一个 zone；无校验、无 confidence
- `SPATIAL_LAYOUT_PARSE_PROMPT`（L49-129）：Prompt 说"严格 JSON"但 LLM 不一定遵守——area_ratio 可能超 [0,1]，land_use 可能不在 8 种选项中

### 2. 知识图谱构建（`kg/builder.py`）

**10 步构建**（L153-220）：Village → Parcels(660) → Constraints(7种PATTERNS) → Indicators(5种) → Zones(三级面积查找) → Spatial Relations → Projects → Regulations → designated_as → Infrastructure

**约束提取**：CONSTRAINT_PATTERNS（7种 metric_key→constraint_id 映射）遍历 reports metrics 自动匹配

**面积目标三级查找**（`_add_zones`）：GIS dissolve > 报告指标 > 硬编码默认值（金田村 78.83/30.50/362.02）

### 3. 分区分配（`mip_solver.py` + `mip_allocator.py`）

**Greedy**：3步（偏好分配→约束检查→兜底填充），偏好成本 0/10/15/1000 四档

**MIP**：PuLP CBC 求解器，目标函数 4 项（面积偏差×10 + DLBM偏好 + 变更惩罚×0.3 - 邻接奖励×0.5），30+ DLBM 编码偏好表

**缺陷**：无紧凑度项（分区碎片化风险）；邻接权重仅 0.5 vs 面积权重 10（5% 影响力）

### 4. 设施放置（`facility_placer.py`）

**4 种策略**：现状保留（POI/质心）、规划新建（质心+固定300m偏移）、改扩建（不变）、迁建（acceptable DLBM质心）

**缺陷**：无覆盖优化；偏移量固定 300m 不考虑村庄大小；`_centroid_of_dlbm` 只取第一个匹配

---

## 行业最佳实践（2026）

根据 Exa 搜索结果，2026 年 LLM 结构化输出的行业共识：

| 方案 | 可靠性 | 适用场景 | 结论 |
|------|--------|----------|------|
| Prompt + 正则解析 | 70-85% | 快速原型 | **不要用于生产** |
| JSON Mode | 80-88% | 仅需有效 JSON | DashScope 支持，但不保证 schema 合规 |
| Function Calling / Tool Use | 95-99% | 需要调用外部动作 | 适用于 Agent 工具 |
| Structured Outputs (strict=True) | 99%+ | OpenAI 专有 | **DashScope 不支持** |
| **Instructor 库** | **99%+** | **Pydantic schema + 自动重试** | **当前项目推荐方案** |

**核心原理**：OpenAI 的 `response_format: {type: "json_schema", strict: true}` 在解码层强制约束 schema，但这是 OpenAI 专有功能。

**DashScope 兼容性**（Exa 搜索 + **实测验证 2026-07-03**）：
- `json_schema` 模式：**可用**（实测通过 `with_structured_output(method='json_schema')`）
- `json_schema + strict=True`：**可用**（实测通过！DashScope 支持 strict 参数）
- `json_mode`：**失败**（需要消息包含 "JSON" 关键词，不适合结构化解析）
- `function_calling`：**可用**（Instructor 底层使用的模式）
- 已知兼容性问题：空 `tools=[]` 返回 400（LangChain Agent 场景，不影响纯结构化输出）
- **Instructor 实测更快**：2.6s vs LangChain `json_schema` 3.9s

**Instructor 库**（项目已验证可用）：
- 通过 `instructor.from_openai(OpenAI(base_url=DASHSCOPE_API_BASE))` 包装 DashScope
- `max_retries=3` 自动重试：LLM 输出违反 Pydantic schema 时自动重试而非报错
- 不依赖 provider-native `strict=True`，兼容性更强
- 已在 `summary/generator.py` 中验证可用

**对当前项目的影响**：
- `_postprocess_llm_response` 中的正则解析被 Instructor 替代
- area_ratio 归一化**保留**为 `_semantic_validate` 中的修正步骤（Instructor 不保证 area_ratio 总和=1.0）
- 不需要三层架构——两层就够了（metrics 直接提取 + Instructor 结构化输出）

---

## 阶段一：GIS 后端效果提升

### 1.1 解析模块重构（核心改进）

#### 问题分析

当前链路层级过多且每层有语义偏移：

```
原始报告 → reports.metrics（精确数值）
         → reports.summary.text_summary（LLM 生成的摘要文本，有随机性）
         → _prepare_parse_prompt 拼接（格式化偏移）
         → LLM 自由文本输出（随机性）
         → 正则提取 JSON（格式偏移）
         → area_ratio 归一化（语义偏移）
         → UnifiedSpatialIntent
```

7 层转换，每层都可能偏移。而且 summary 和最终解析本质相同——都是解析 LLM 生成的文本，用正则匹配不可靠。

#### 重构方案：两层架构 + Instructor

**核心理念**：删掉中间层，用 Instructor 库（Pydantic schema + 自动重试）保证格式正确，metrics 精确数值作为 prompt 注入而非让 LLM 重新解读。

```
reports.metrics（精确数值） ─→ 直接注入 prompt 作为锚定值
                         │
reports.content（原始文本） ─→ 作为上下文背景
                         │
                         ↓
Instructor(IntentSchema, max_retries=3)
                         ↓
Pydantic IntentOutput（schema 验证 + 自动重试，99%+ 可靠）
                         ↓
UnifiedSpatialIntent
```

**从 7 层简化到 3 层**，消除了 text_summary 拼接、正则提取、归一化三个偏移层。

#### 实现细节

**1. 定义 Pydantic Schema**（替代 `_postprocess_llm_response` + 正则）

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class ZoneOutput(BaseModel):
    """功能分区意图 — schema 约束保证 area_ratio∈[0,1], land_use 只能是 8 种之一"""
    zone_id: str = Field(description="分区编号，如 Z01")
    land_use: str = Field(
        description="用地类型",
        json_schema_extra={"enum": [
            "居住用地", "产业用地", "公共服务用地",
            "生态绿地", "交通用地", "水域", "农业用地", "商业用地"
        ]}
    )
    dlbm: str = Field(description="主要地类编码，如 2121", pattern=r"^\d{2,4}$")
    area_ratio: float = Field(description="面积占比(0-1)", ge=0, le=1)
    direction: str = Field(
        description="空间方向",
        json_schema_extra={"enum": [
            "center", "north", "south", "east", "west",
            "northeast", "northwest", "southeast", "southwest", "periphery",
            "east-west", "north-south"
        ]},
        default="center"
    )
    reference_feature: str = Field(default="", description="位置参考，如'靠近村委会'")
    adjacent_to: List[str] = Field(default_factory=list)
    avoid_adjacent_to: List[str] = Field(default_factory=list)
    density: str = Field(
        description="开发密度",
        json_schema_extra={"enum": ["high", "medium", "low"]},
        default="medium"
    )

class FacilityOutput(BaseModel):
    """设施意图"""
    facility_id: str
    facility_type: str = Field(
        description="设施类型",
        json_schema_extra={"enum": [
            "村委会", "学校", "卫生站", "文化站",
            "市场", "养老服务", "产业服务中心", "停车场"
        ]}
    )
    status: str = Field(
        description="设施状态",
        json_schema_extra={"enum": ["现状保留", "规划新建", "规划改扩建", "规划迁建"]},
        default="现状保留"
    )
    location_hint: str = Field(default="", description="位置提示，如'村庄中心'")
    service_radius: int = Field(default=500, description="服务半径(米)", ge=100, le=2000)

class AxisOutput(BaseModel):
    """发展轴意图"""
    axis_id: str
    axis_type: str = Field(
        description="发展轴类型",
        json_schema_extra={"enum": ["primary", "secondary", "corridor", "connector"]}
    )
    direction: str = Field(
        description="发展方向",
        json_schema_extra={"enum": [
            "center", "north", "south", "east", "west",
            "northeast", "northwest", "southeast", "southwest",
            "east-west", "north-south"
        ]},
        default="east-west"
    )
    reference_feature: str = Field(default="")

class IntentOutput(BaseModel):
    """规划意图 — 替代 SPATIAL_LAYOUT_PARSE_PROMPT + 正则解析"""
    zones: List[ZoneOutput] = Field(description="功能分区列表，area_ratio 总和应≈1.0")
    facilities: List[FacilityOutput] = Field(description="设施布局列表")
    axes: List[AxisOutput] = Field(default_factory=list, description="发展轴列表")
    rationale: str = Field(default="", description="规划布局总体说明")
    metadata: dict = Field(default_factory=dict, description="元数据(总面积等)")
```

**关键**：Pydantic schema 中的 `Field(ge=0, le=1)` 和 `json_schema_extra={"enum": [...]}` 被 Instructor 编译为 function calling 参数——LLM 输出会被 Pydantic 验证，违反则自动重试（`max_retries=3`）。虽然不像 OpenAI `strict=True` 那样在 token 级阻止，但重试机制实际效果等价——3 次重试后仍失败的概率极低。

**2. 重写解析函数**（替代 `_parse_reports_to_intent` + `_postprocess_llm_response`）

```python
async def _aparse_reports_to_intent(
    reports: Dict, village_name: str,
) -> Dict:
    """两层架构：metrics 锚定 + LLM 结构化输出。"""

    # Layer 1: metrics 精确提取（复用 KG builder 的 CONSTRAINT_PATTERNS）
    anchors = _extract_metric_anchors(reports)
    # → {"建设用地": 30.5, "农田": 78.83, "生态": 362.02, "总面积": 2352.56}
    # → 每个值附带来源字段: "建设用地=30.5ha (来源: land_use_planning.metrics.building_construction_sum_ha)"

    # Layer 2: Instructor 结构化输出（Pydantic schema + max_retries=3）
    from app.core.instructor_client import get_instructor_client, get_flash_model

    client = get_instructor_client()
    model = get_flash_model()

    try:
        intent_output: IntentOutput = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            max_tokens=2000,
            temperature=0,
            max_retries=3,
            response_model=IntentOutput,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error("structured parse failed: %s", e)
        return _make_result(False, error=f"结构化解析失败: {e}")

    # 直接转 UnifiedSpatialIntent（无需正则、无需归一化）
    intent = _output_to_intent(intent_output, anchors)

    # 轻量校验（schema 已保证格式正确，只需检查语义）
    validation = _semantic_validate(intent, anchors)
    if not validation.passed:
        # 单次修正（不需要3轮——schema约束已消除格式问题）
        correction = _build_correction_prompt(validation, intent, anchors)
        intent_output = await structured_llm.ainvoke(correction)
        intent = _output_to_intent(intent_output, anchors)

    return _make_result(True, {
        "zone_count": len(intent.zones),
        "facility_count": len(intent.facilities),
        "axis_count": len(intent.axes),
        "intent_json": intent_output.model_dump(),
        "anchor_confidence": anchors.confidence,
        "validation": validation.to_dict(),
    })
```

**3. metrics 锚定提取**（替代 `_prepare_parse_prompt` 中的字符串拼接）

```python
def _extract_metric_anchors(reports: Dict) -> MetricAnchors:
    """从 reports.metrics 直接提取精确数值，复用 KG builder 的映射。"""
    from app.services.modules.gis.layout.kg.builder import CONSTRAINT_PATTERNS, INDICATOR_PATTERNS

    anchors = MetricAnchors()
    for dim_key, report in reports.items():
        metrics = report.get("summary", {}).get("metrics", {})

        if dim_key == "land_use_planning":
            for pattern in CONSTRAINT_PATTERNS:
                key = pattern["metric_key"]
                if key in metrics and metrics[key] is not None:
                    val = float(metrics[key])
                    if pattern["constraint_id"] == "construction_cap":
                        anchors.construction_area_ha = val
                    elif pattern["constraint_id"] == "farmland_min":
                        anchors.farmland_area_ha = val
                    elif pattern["constraint_id"] == "ecological_redline_min":
                        anchors.ecological_area_ha = val
                    elif pattern["constraint_id"] == "permanent_farmland_min":
                        anchors.permanent_farmland_ha = val

            if metrics.get("total_area"):
                anchors.total_area_ha = float(metrics["total_area"])

            # 计算精确比例
            if anchors.total_area_ha and anchors.total_area_ha > 0:
                anchors.zone_ratios = {
                    "村庄建设区": anchors.construction_area_ha / anchors.total_area_ha,
                    "农田保护区": anchors.farmland_area_ha / anchors.total_area_ha,
                    "生态保护区": anchors.ecological_area_ha / anchors.total_area_ha,
                }

    anchors.confidence = _compute_anchor_confidence(anchors)
    return anchors
```

**关键**：复用 KG builder 已有的 `CONSTRAINT_PATTERNS`（7 种 metric_key→constraint_id 映射），字段名和 constraint_id 映射已在 KG 构建中验证过。

**4. 新 Prompt**（替代 `SPATIAL_LAYOUT_PARSE_PROMPT`）

```
你是乡村规划空间结构解析助手。

**任务**: 将规划报告解析为结构化意图数据。

**村庄**: {village_name}

**已知精确数值（请严格遵循）**:
{anchors}
例: 如果"建设用地=30.5ha"，则建设类分区 area_ratio 总和应≈30.5/2352.56≈1.3%

**规划上下文**:
{planning_context}

请输出结构化规划意图。
```

**5. 轻量语义校验**（替代 `_postprocess_llm_response` 归一化 + Tier 3 多轮校验）

```python
def _semantic_validate(intent: UnifiedSpatialIntent, anchors: MetricAnchors) -> ValidationResult:
    """语义校验——格式已由 schema 保证，只检查语义合理性。"""
    violations = []

    # 1. area_ratio 总和≈1.0（schema 已保证每个∈[0,1]，但总和可能≠1）
    total = intent.total_area_ratio
    if abs(total - 1.0) > 0.05:
        violations.append(f"area_ratio总和={total:.3f}")

    # 2. 锚定值交叉校验（唯一需要的校验）
    if anchors.zone_ratios:
        construction_ratio = sum(
            z.area_ratio for z in intent.zones
            if z.land_use in {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}
        )
        expected = anchors.zone_ratios.get("村庄建设区", 0)
        if abs(construction_ratio - expected) > 0.05:
            violations.append(
                f"建设区比例: LLM={construction_ratio:.3f}, 精确值={expected:.3f}"
            )

    # 3. 必需分区存在
    present = {z.land_use for z in intent.zones}
    if "农业用地" not in present:
        violations.append("缺少农业用地分区")

    return ValidationResult(passed=len(violations) == 0, violations=violations)
```

**为什么只需要一次修正**：
- Instructor `max_retries=3` 已保证格式合规（违反 schema 自动重试）
- 语义校验最多发现 2 类问题：总和≠1 和 锚定值偏差
- 单次修正 prompt 只需指出偏差值，LLM 在 schema 约束下自动调整

#### 删除的代码

| 函数 | 原因 |
|------|------|
| `_postprocess_llm_response`（L125-166） | 正则提取 JSON 被 Instructor 替代 |
| `_prepare_parse_prompt`（L75-122） | 字符串拼接被 metrics 锚定 + 结构化 prompt 替代 |
| `SPATIAL_LAYOUT_PARSE_PROMPT`（L49-129） | 自由文本 prompt 被 STRUCTURED_PARSE_PROMPT 替代 |
| `ZONE_AREA_ADJUSTMENT_PROMPT`（L131-152） | area_ratio 归一化被 schema 约束替代 |
| `_dict_to_intent` 中的归一化逻辑 | 不需要——schema 保证 area_ratio∈[0,1]，LLM 在锚定下输出总和≈1 |

#### 解析结果在后续流程中的改进

```
parse_planning_text（两层架构）
  ↓ IntentOutput（Pydantic, 99%+ schema 合规） + MetricAnchors
  ↓
build_knowledge_graph
  ↓ _add_zones 使用 anchors 精确面积（替代硬编码默认值）
  ↓ KG 约束: 从 CONSTRAINT_PATTERNS 自动提取
  ↓
allocate_zones(targets=anchors.zone_ratios × total_area, constraints=kg_constraints)
  ↓ targets 有精确来源，不再依赖 Agent 自行组装或硬编码
  ↓
generate_layout → validate_layout
```

### 1.2 MIP 紧凑度提升

**当前目标函数** → **增加紧凑度项**：

```
+ compactness_weight(=0.2) * Σ_i Σ_z x[i][z] * dist(centroid_i, zone_center_z)^2
```

迭代计算：第1轮用 DLBM 原生质心，第2轮用第1轮分配结果更新质心。

### 1.3 设施覆盖优化

**当前** → **改为覆盖得分选择**：

```python
def _place_new_optimized(fac_type, landuse_geojson):
    """最大化 800m 覆盖范围内居民点数量。"""
    candidates = _get_candidate_positions(fac_type, landuse_geojson)
    residential_geoms = _get_residential_geometries(landuse_geojson)
    best = max(candidates, key=lambda c: _count_within_radius(c, residential_geoms, 800))
    return best
```

### 1.4 金田村基准验证

| 指标 | 目标 |
|------|------|
| 分区面积 MAE | <5% |
| 地块分配 IoU | >0.7 |
| 紧凑度指数 | >0.5 |

---

## 阶段二：前端交互式集成

### 2.1 集成点：新增 gis_edit_node

### 2.2 可编辑图层（planning_zone/facility_point/development_axis）

### 2.3 验证反馈 UI

---

## 方案优势

| 维度 | 当前 | 改进后 | 优势 |
|------|------|--------|------|
| **解析可靠性** | 正则提 JSON ~70-85% | Instructor + Pydantic schema ~99%+ | schema 验证 + 自动重试（3 次） |
| **架构简洁性** | 7 层转换 | 3 层（metrics→锚定→LLM结构化输出） | 消除 text_summary/正则/归一化三层偏移 |
| **通用性** | 硬编码金田村面积 | metrics 锚定动态提取 + KG dissolve | 换村庄只需换数据 |
| **代码量** | `_postprocess_llm_response` + `_prepare_parse_prompt` + `_dict_to_intent` 归一化 ≈ 150 行 | `_extract_metric_anchors` + `_output_to_intent` ≈ 80 行 | 减少 70 行脆弱代码 |
| **可审计性** | LLM 黑盒 | anchors 每个值有来源字段 + schema 约束保证格式 | 知道值从哪来，格式不可能错 |

**核心创新**：
1. **Instructor 替代正则** — 项目已验证 Instructor + DashScope 可用（`summary/generator.py` 在用），`max_retries=3` 自动重试保证 schema 合规。OpenAI `strict=True` 在 DashScope 不可用。
2. **metrics 锚定注入** — 精确数值直接告诉 LLM "建设用地=30.5ha"，比让它从文本猜准得多。
3. **复用 KG CONSTRAINT_PATTERNS** — 字段映射已在 KG 构建中验证过，不需要重新维护一套映射表。

---

## 关键文件清单

### 阶段一（后端）
| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `backend/app/tools/gis/layout_tools.py` | 重写 | 两层架构替代 7 层；删除正则解析；新增 `_extract_metric_anchors` + `_aparse_reports_to_intent_v2` |
| `backend/app/services/modules/gis/layout/planning_intent.py` | 增加 | IntentOutput Pydantic schema + MetricAnchors dataclass |
| `backend/app/agent/gis/prompts.py` | 修改 | STRUCTURED_PARSE_PROMPT 替代 SPATIAL_LAYOUT_PARSE_PROMPT |
| `backend/app/services/modules/gis/layout/optimizer/mip_allocator.py` | 修改 | 紧凑度项 |
| `backend/app/services/modules/gis/layout/facility_placer.py` | 修改 | 覆盖优化 |
| `backend/tests/test_gis_benchmarks.py` | 新增 | 基准测试 |

### 阶段二（前端+集成）
| 文件 | 改动类型 |
|------|----------|
| `backend/app/agent/graph.py` | 修改（新增 gis_edit_node） |
| `backend/app/agent/state.py` | 修改 |
| `frontend/.../gis/MapView.tsx` | 修改（编辑模式） |
| `frontend/.../gis/EditableLayerFactory.ts` | 新增 |
| `frontend/.../gis/ValidationResultCard.tsx` | 新增 |
