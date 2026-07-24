# GIS Schema 增强 Planning Agent 集成

> **Status: [PROPOSAL]** | **Type: Integration Design Proposal** | **Version: 1.0** | **Updated: 2026-07-21**
> **⚠️ 本提案尚未实现**。所有6个GIS查询工具均为设计稿，对应 DESIGN_GOALS Phase 2.5 设计方向。
> **Relationship to DESIGN_GOALS**: 本提案是 01_DESIGN_GOALS.md Phase 2.5 的延伸，非替代现有设计。
> **References**: BIBLIOGRAPHY.md §G1-5
> **Related**: 01_DESIGN_GOALS.md §3, diagnostics/02_RELIABILITY_ASSESSMENT.md

## Context

当前规划 Agent（Router Agent）产出纯文本报告，与 GIS 系统完全解耦。GIS 系统已有丰富的 schema 设计（6 套编码体系、20 种空间要素类型、SpatialContext 空间锚定、5 种原子操作），但规划 Agent 在生成文本时无法查询 GIS 数据，导致：

1. **规划文本缺乏空间精度**：如"在村东建设展销中心"无法锚定到具体图斑
2. **建设项目无法直接落地**：文本中的项目表停留在文档层面，需人工二次录入 GIS
3. **合规检查滞后**：规划方案是否侵占基本农田，需等到 GIS 布局阶段才能发现
4. **编码标准化缺失**：规划文本用地名称与 GIS 编码体系不对齐

**行业对标**：
- **SuperMap CSPON**：规划助手智能体实现全流程"智能伴随"，建设项目空间适配
- **规易AI**：3 分钟生成结构化规划文档，内置 2000+ 专业术语库
- **姑苏 SiteSeek**："1+1+1+1"体系，AI 驱动项目选址与多维动态评估
- **GeoJSON Agents**：Function Calling (85.71%) vs Code Generation (97.14%)，多 Agent 协作
- **GeoAgentBench**：Plan-and-React 架构，117 个原子 GIS 工具
- **ArchAI**：上传任务书 → AI 识别指标 → 人工确认 → 概念方案 → 总图 → 效果图

---

## 一、增强架构：Planning Agent + GIS 工具集成

### 1.1 当前架构 vs 增强架构

```
当前架构（纯文本，无 GIS 交互）：
  User → Router Agent → [Dimension Reports] → 纯文本输出
                              ↑ RAG only

增强架构（GIS 感知，双向交互）：
  User → Router Agent → [Dimension Reports] → 结构化输出
              ↑               ↑                    ↓
            RAG          GIS Query Tools     OperationSequence
          (法律法规)    (空间查询工具)     (建设项目+空间操作)
                          ↓                    ↓
                    SpatialContext         GIS 定位+落地
                  (空间上下文注入)
```

### 1.2 核心集成点

| 集成点 | 当前状态 | 增强方式 | 涉及文件 |
|--------|----------|----------|----------|
| 空间上下文注入 | 仅 PARSE Agent 使用 | 规划 Agent 也注入 SpatialContext | `agent/graph.py`, `modules/prompts/` |
| GIS 查询工具 | 无 | 新增 6 个查询/操作工具 | `tools/gis/planning_query_tools.py` (新文件) |
| 建设项目添加 | 文本表格 | AI tool 调用 → SpatialOperation | `tools/gis/planning_query_tools.py` (含) |
| 编码标准化 | 自由文本 | DictionaryCenter 查表注入 prompt | `modules/prompts/__init__.py` |
| 合规预检 | 无 | 规划阶段实时检查三区三线 | 复用 `conflict/detector.py` |

---

## 二、新增 GIS 查询工具（6 个）

### 2.1 `query_spatial_context` — 空间上下文查询

**用途**：规划 Agent 生成文本时查询村庄空间概况（地类分布、保护区域、建设边界等）

```python
@tool
async def query_spatial_context(village_name: str, aspect: str = "overview") -> Dict:
    """Query spatial context for a village during planning text generation.

    Args:
        village_name: Village name (e.g., "金田村")
        aspect: Query aspect - "overview" | "landuse" | "protection" | "construction" | "facilities"

    Returns:
        Compact spatial context dict (~2KB) with land-use distribution,
        protection zones, construction boundary, and natural village anchors.
    """
```

**复用**：直接调用 `compute_spatial_context()` 已有逻辑

**集成**：在 Router Agent 节点初始化时注入，或由维度报告节点按需调用

### 2.2 `query_parcel_info` — 地块信息查询

**用途**：查询特定地块或区域的详细信息（地类编码、面积、所属分区、是否在保护区内）

```python
@tool
async def query_parcel_info(
    location_desc: str,
    query_type: str = "landuse"
) -> Dict:
    """Query parcel information by location description or parcel ID.

    Args:
        location_desc: Location description (e.g., "刘村小组东侧") or parcel BSM
        query_type: "landuse" | "zone" | "compliance" | "neighbors"

    Returns:
        Parcel info: dlbm, name, area, zone_type, protection_status, adjacent_parcels
    """
```

**复用**：复用 `place_resolver.py` 地名解析 + `conflict/detector.py` 合规检查

### 2.3 `check_planning_compliance` — 合规预检

**用途**：规划方案实时检查是否与三区三线冲突

```python
@tool
async def check_planning_compliance(
    operation_type: str,  # "create" | "reclassify" | "modify"
    location_desc: str,
    land_use_name: str,
    area_sqm: float = None,
) -> Dict:
    """Pre-check if a planning operation complies with spatial constraints.

    Args:
        operation_type: Type of operation
        location_desc: Location description
        land_use_name: Planned land use name
        area_sqm: Area in square meters (for create operations)

    Returns:
        Compliance result: {compliant: bool, conflicts: [...], suggestions: [...]}
    """
```

**复用**：直接复用 `conflict/detector.py` 的检测逻辑 + `DictionaryCenter` 编码查表

### 2.4 `lookup_land_use_code` — 用地编码独立查表

**用途**：规划 Agent 独立查询用地分类名称 ↔ 标准编码对照（不依赖 PARSE Agent）

```python
@tool
async def lookup_land_use_code(
    land_use_name: str,
    encoding_system: str = "appendix5"
) -> Dict:
    """Look up land-use classification codes by name.

    Independent from PARSE Agent — available to any planning agent node.

    Args:
        land_use_name: Land use name (e.g., "经营性建设用地", "水田")
        encoding_system: Encoding system - "gbt21010" | "tugui" | "appendix5" |
                         "ghflbm" | "ydyhfldm" | "vne"

    Returns:
        Dict with code, name, zone_type, planning_zone, candidates (if ambiguous)
    """
```

**复用**：复用 `DictionaryCenter.lookup()` + `candidate_engine.py` 候选项生成

**与 PARSE Agent 版本的区别**：
- PARSE Agent 的 `lookup_land_use_code` 是 PARSE 子图内部工具
- 此版本独立暴露给 Router Agent，任何维度节点都可调用
- 增加了 `encoding_system` 参数，支持跨体系查询

### 2.5 `resolve_place_name` — 地名解析独立工具

**用途**：将自然语言位置描述解析为候选图斑列表（不依赖 PARSE Agent）

```python
@tool
async def resolve_place_name(
    location_desc: str,
    search_radius_m: float = 200.0,
) -> Dict:
    """Resolve a natural language location description to candidate parcels.

    Independent from PARSE Agent — available to any planning agent node.
    Enables the planning agent to ground location references in spatial data.

    Args:
        location_desc: Location description (e.g., "刘村小组东侧", "晒谷场北边")
        search_radius_m: Search radius in meters (default 200m)

    Returns:
        Dict with candidate_parcels, resolved_anchor, confidence,
        spatial_context (nearby features)
    """
```

**复用**：复用 `place_resolver.py` 已有逻辑 + `SpatialContext.natural_villages`

**与 PARSE Agent 版本的区别**：
- PARSE Agent 的 `resolve_place_name` 仅在 PARSE 子图内使用
- 此版本独立暴露，规划 Agent 生成文本时可直接调用
- 返回更丰富的上下文信息（附近要素、邻接关系）

### 2.6 `add_construction_project` — 建设项目添加

**用途**：将规划文本中的建设项目直接添加到 GIS 操作队列

```python
@tool
async def add_construction_project(
    project_name: str,
    area_sqm: float,
    land_use_name: str,
    location_desc: str = "",
    notes: str = "",
) -> Dict:
    """Add a construction project from planning text to GIS operation queue.

    This tool bridges planning text and GIS: it creates a SpatialOperation
    with spatial anchor, compliance check, and standard encoding.

    Args:
        project_name: Project name (e.g., "农产品展销中心")
        area_sqm: Area in square meters
        land_use_name: Planned land use (e.g., "经营性建设用地")
        location_desc: Location description (e.g., "刘村小组东侧")
        notes: Additional notes

    Returns:
        Operation result with spatial anchor, compliance, and GHYTBM code
    """
```

**内部流程**：
1. `land_use_name` → `DictionaryCenter.lookup(land_use_name)` → GHYTBM 编码
2. `location_desc` → `resolve_place_name(location_desc)` → 候选图斑列表
3. 候选图斑 → `check_compliance(parcel, operation)` → 合规预检
4. 构造 `SpatialOperation(action="create", ...)` → 加入 OperationSequence
5. 返回结构化结果：`{project_name, ghytbm, anchor, compliance, confirmation_url}`

---

## 三、SpatialContext 注入规划 Prompt

### 3.1 注入策略

在规划 Agent 的 system prompt 中注入压缩版 SpatialContext（~500 tokens），提供：

```
【村庄空间概况】
- 总面积: 438.23 ha, 建设边界: 21.66 ha
- 地类分布: 水田 98.54ha(22.5%), 林地 187.3ha(42.7%), 宅基地 15.8ha(3.6%)...
- 保护区域: 基本农田 98.54ha, 生态红线 367.68ha
- 自然村: 刘村小组(村北), 陈屋(村东), 晒谷场(村南)
- 空间关系: 刘村小组 north_of 陈屋, 晒谷场 south_of 陈屋
```

### 3.2 DictionaryCenter 编码参考表注入

从 `dicts/encodings/` 提取用地分类名称对照表（~300 tokens）：

```
【用地分类参考】(GHYTBM 附录5)
- 经营性建设用地: 2124 | 农村宅基地: 2121 | 公共管理与公共服务: 2211
- 公路用地: 2311 | 农村道路: 2312 | 水田: 0101 | 旱地: 0102
...
```

### 3.3 Prompt 模板修改

关键修改点在 `backend/app/modules/prompts/__init__.py`：

```python
# 当前: 纯 RAG 上下文
rag_context = rag_service.format_for_prompt(retrieved_chunks)

# 增强: RAG + SpatialContext + 编码参考表
spatial_context = compute_spatial_context(gis_data)
encoding_table = DictionaryCenter.to_prompt_table()  # 已有方法
prompt = _build_prompt(rag_context, spatial_context, encoding_table, deps, tools)
```

---

## 四、建设项目 Tool-Calling 集成

### 4.1 建设项目添加流程

```
规划文本提到建设项目 → AI 调用 add_construction_project tool
    → 自动填充: 项目名、面积、用途编码(GHYTBM)
    → SpatialAnchor: 空间锚定候选图斑
    → ComplianceCheck: 合规预检
    → 返回确认信息 + 空间定位建议
```

### 4.2 规划文本 → GIS 定位闭环

```
规划文本生成 → 建设项目提取 → 空间锚定 → 合规预检 → 人工确认 → GIS 执行
     ↑                                                              ↓
     └────────── 空间反馈注入（位置冲突/约束违反）←──────────────────┘
```

### 4.3 规划 Agent 输出增强

当前规划 Agent 输出纯 Markdown，增强后输出包含：

```json
{
  "dimension": "infrastructure",
  "report_text": "建议在刘村小组东侧新建农产品展销中心...",
  "construction_projects": [
    {
      "project_name": "农产品展销中心",
      "area_sqm": 400,
      "land_use_name": "经营性建设用地",
      "ghytbm": "2124",
      "location_desc": "刘村小组东侧、晒谷场北边",
      "spatial_anchor": {
        "candidate_parcels": ["XG-005"],
        "confidence": 0.85,
        "resolution_status": "partial"
      },
      "compliance": {
        "in_construction_boundary": true,
        "not_farmland": true,
        "not_ecological_redline": true
      }
    }
  ],
  "spatial_constraints": [
    {
      "type": "area_constraint",
      "land_use": "基本农田",
      "operator": ">=",
      "target_area_ha": 98.54
    }
  ]
}
```

---

## 五、Prompt 优化策略

### 5.1 System Prompt 增强

```
你是一个村庄规划专家助手。在生成规划文本时，你可以调用以下工具获取空间信息：

1. query_spatial_context — 查询村庄空间概况（地类分布、保护区域、建设边界）
2. query_parcel_info — 查询特定地块信息（地类编码、面积、所属分区）
3. check_planning_compliance — 检查规划操作合规性（三区三线冲突检测）
4. lookup_land_use_code — 查询用地分类名称对应的标准编码（6套编码体系）
5. resolve_place_name — 将位置描述解析为候选地块（空间锚定）
6. add_construction_project — 将建设项目添加到 GIS 操作队列（空间锚定+合规预检）

【重要原则】
- 提到具体位置时，必须先调用 query_parcel_info 确认空间锚定
- 提到建设项目时，必须调用 add_construction_project 添加到操作队列
- 用地分类名称必须使用 DictionaryCenter 标准名称（见注入的编码参考表）
- 涉及基本农田/生态红线区域时，必须调用 check_planning_compliance 预检
```

### 5.2 维度报告 Prompt 模板

每个维度报告的 prompt 模板增加：

```
【村庄空间概况】
{spatial_context_summary}

【用地分类参考】
{encoding_reference_table}

【合规约束】
- 基本农田保护面积 >= {farmland_area} ha (不可减少)
- 生态红线面积 >= {ecological_area} ha (不可侵占)
- 建设用地 <= {construction_area} ha (不可突破)
```

### 5.3 RAG 查询增强

当前 RAG 查询只搜索文本知识库，增强后同时查询：

1. **文本知识库**（现有）：法律法规、技术规范、案例
2. **空间数据**（新增）：地块信息、保护区域、建设边界
3. **编码字典**（新增）：DictionaryCenter 用地分类对照

---

## 六、实现路线图

### Phase 1 — 工具层（1-2 天）

- [ ] 新建 `backend/app/tools/gis/planning_query_tools.py`
  - `query_spatial_context` tool — 村庄空间概况查询
  - `query_parcel_info` tool — 地块信息查询
  - `check_planning_compliance` tool — 合规预检
  - `lookup_land_use_code` tool — 用地编码独立查表（跨 6 套编码体系）
  - `resolve_place_name` tool — 地名解析独立工具（空间锚定）
  - `add_construction_project` tool — 建设项目添加到 GIS 操作队列
- [ ] 复用已有模块：`spatial_context.py`, `place_resolver.py`, `conflict/detector.py`, `DictionaryCenter`, `candidate_engine.py`

### Phase 2 — Prompt 层（1 天）

- [ ] 修改 `backend/app/modules/prompts/__init__.py`
  - 注入 SpatialContext 摘要到维度报告 prompt
  - 注入 DictionaryCenter 编码参考表
  - 增加合规约束提示
- [ ] 修改 `backend/app/modules/prompts/parse_prompts.py`（如需要）

### Phase 3 — Agent 集成（2-3 天）

- [ ] 修改 `backend/app/agent/graph.py` Router Agent
  - 注册新的 GIS 查询工具
  - 初始化时加载 SpatialContext
  - 维度报告节点绑定工具
- [ ] 修改维度报告节点，支持 tool calling
- [ ] 输出格式增强：Markdown + 结构化 JSON（建设项目 + 空间约束）

### Phase 4 — 前端展示（2 天）

- [ ] 规划报告页面新增建设项目定位卡片
- [ ] 地图飞到候选位置 + 确认对话框
- [ ] 确认后触发 GIS 操作

### Phase 5 — 验证（1 天）

- [ ] 端到端测试：用户提问 → 规划 Agent 调用 GIS 工具 → 输出含空间锚定的报告
- [ ] 合规预检测试：在基本农田区域规划建设项目 → 检测到冲突
- [ ] 建设项目落地测试：从规划文本到 GIS 操作的完整闭环

---

## 七、关键复用清单

| 已有模块 | 路径 | 复用方式 |
|----------|------|----------|
| SpatialContext 计算 | `modules/gis/spatial_context.py` | 直接调用 `compute_spatial_context()` |
| 空间锚定模型 | `agent/gis/parse/state.py` | 复用 `SpatialAnchor`, `SpatialOperation` |
| 地名解析 | `tools/gis/place_resolver.py` | 复用 `resolve_place_name` |
| 编码查表 | `modules/gis/schema/dicts/loader.py` | 复用 `DictionaryCenter.lookup()` |
| 编码参考表 | `modules/gis/schema/dicts/loader.py` | 复用 `DictionaryCenter.to_prompt_table()` |
| 候选项引擎 | `modules/gis/schema/dicts/candidate_engine.py` | 复用 `propose_classification_candidates()` |
| 合规检测 | `modules/gis/conflict/detector.py` | 复用冲突检测逻辑 |
| 动态分区 | `modules/gis/schema/dynamic_zoning.py` | 复用 `DynamicZoningEngine` |
| RAG 服务 | `modules/rag/service.py` | 扩展查询维度（增加空间数据源） |
| 编码对照表 | `modules/gis/schema/code_sets.py` | 复用 `DLBM_TO_DLMC`, `get_zone_type_for_dlbm` |

---

## 八、行业参考与设计理念

### 8.1 核心设计理念

| 理念 | 来源 | 本项目应用 |
|------|------|-----------|
| **规划助手智能体** | SuperMap CSPON | 规划 Agent 集成 GIS 工具，实现"智能伴随" |
| **空间适配** | SuperMap CSPON | 建设项目通过 tool calling 自动匹配候选地块 |
| **结构化术语库** | 规易AI | DictionaryCenter 6 套编码体系注入 prompt |
| **AI 选址** | 姑苏 SiteSeek | `query_parcel_info` + `check_planning_compliance` |
| **Function Calling** | GeoJSON Agents | 规划 Agent 通过 tool calling 调用 GIS 查询 |
| **Plan-and-React** | GeoAgentBench | 规划 Agent 先生成方案，再调用工具验证/修正 |
| **人工确认门控** | ArchAI | 建设项目落地前需人工确认（已有设计） |
| **地名解析** | 乡村用地选址专利 | `resolve_place_name` + 空间关系推理 |

### 8.2 关键学术参考

1. **GeoJSON Agents** (arXiv:2509.08863): Function Calling vs Code Generation，多 Agent LLM 架构用于地理空间分析
2. **GeoAgentBench** (arXiv:2604.13888): 117 个原子 GIS 工具 + Plan-and-React 架构
3. **City-LEO** (arXiv:2406.10958): LLM 生成 MIP 约束 + E2E 优化
4. **PlanGEN** (Google Research 2025): ConstraintAgent → SolutionAgent → VerificationAgent → SelectionAgent
5. **JackDaw** (PoliRural+ 2026): 工具预过滤 + RAG + 值工程模型编排
6. **DRL 村庄规划** (北师大珠海 2026): GNN 拓扑建模 + PPO 强化学习 + 动作掩码机制

### 8.3 RAG 文档库中可直接利用的规范

| 类别 | 文档 | 增强用途 |
|------|------|----------|
| 技术规范 | 《村庄规划用地分类指南》 | 用地分类标准注入 prompt |
| 技术规范 | GB/T 21010-2017《土地利用现状分类》 | DLBM 编码体系对照 |
| 技术规范 | 《国土空间调查、规划、用途管制用地用海分类指南》 | 用地用海分类编码 |
| 技术规范 | 《广东省村庄规划编制基本技术指南（试行）》 | 编制模板 + 合规检查规则 |
| 技术规范 | 《村土地利用规划编制技术导则》 | 规划编制流程参考 |
| 政策文件 | 《乡村振兴用地政策指南（2023 年）》 | 建设项目用地合规 |
| 法律 | 《中华人民共和国城乡规划法》 | 规划法律依据 |
| 法律 | 《中华人民共和国土地管理法》 | 土地利用法律约束 |
| 案例 | 多个村庄规划案例 | 规划文本格式参考 |

---

## 九、验证方案

### 9.1 端到端测试场景

**场景 1：空间感知规划生成**
```
输入: "为金田村编制基础设施规划"
期望: Agent 调用 query_spatial_context → 输出包含具体空间位置的规划文本
      如"建议在刘村小组东侧新建农产品展销中心（约400㎡）"
      而非"建议在合适位置建设展销中心"
```

**场景 2：建设项目添加**
```
输入: "在晒谷场北边新建400㎡展销中心"
期望: Agent 调用 add_construction_project → 返回结构化项目信息
      {project_name: "农产品展销中心", ghytbm: "2124",
       spatial_anchor: {candidate_parcels: ["XG-005"], confidence: 0.85}}
```

**场景 3：合规预检**
```
输入: "在基本农田区域规划建设产业园区"
期望: Agent 调用 check_planning_compliance → 检测到冲突
      {compliant: false, conflicts: ["基本农田保护区，禁止建设"]}
```

### 9.2 回归测试

- 现有规划文本生成功能不受影响（工具调用是可选的增强）
- RAG 查询功能不受影响（新增空间数据源是扩展）
- GIS 布局管线不受影响（OperationSequence 格式兼容）

---

## 附录：与 01_DESIGN_GOALS.md 的对齐

本探索文档的设计完全对齐 `01_DESIGN_GOALS.md v5.1`：

| DESIGN_GOALS 原则 | 本文档落实 |
|-------------------|-----------|
| Agent 是专业绘图员 | 规划 Agent 通过 tool calling 查询/预检，不替代规划决策 |
| 所有规划文本统一解析为 OperationSequence | `add_construction_project` 直接生成 SpatialOperation |
| 5 种原子操作 | 复用 SpatialOperation 的 action 字段 |
| DictionaryCenter 单一真相源 | 编码查表全部通过 DictionaryCenter |
| 人工确认 | 建设项目落地前确认卡片（已有设计） |
| SpatialContext 注入 | 扩展到规划 Agent（不仅限于 PARSE Agent） |
| 合规检查是前置条件 | `check_planning_compliance` 在规划阶段即可预检 |
