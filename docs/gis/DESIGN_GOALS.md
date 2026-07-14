# GIS 村庄规划系统 — 设计目标

> 版本: 3.0 | 日期: 2026-07-13 | 基于 Trinity 架构 + 双 Agent 模型

## 1. 问题定义

传统村庄规划编制依赖人工在 ArcGIS/QGIS 中逐层叠加分析：
- **图数分离**：规划图与指标表各自维护，边界修改后需手动重新量算面积
- **冲突滞后**：建设用地是否侵占基本农田，需人工多次叠加比对，容易遗漏
- **规则依赖经验**：规划条款以自然语言存在于报告中，执行正确性取决于规划师个人理解

以金田村为例：660 个地块 × 12 个维度报告 × 4 类规划分区 × 3 重约束（建设用地 ≤30.5ha / 农田 ≥80ha / 生态红线 ≥200ha），人工核查一遍约需 4-6 小时，且无法保证无遗漏。

目标：**输入规划报告文本 + GIS 现状数据 → 自动输出符合 GB/T 21010 和 DB22/T 3407-2022 标准的 12 层规划成果包**。

## 2. 目标输出

参考金田村 GDB 实测数据（`docs/金田村村庄规划工程文件.zip`）和国家标准：

```
output/{village_name}/
├── current/                              # 现状 5 层
│   ├── boundary.geojson                  # 行政区划面 (MultiPolygon, 6字段)
│   ├── admin_line.geojson                # 行政区划界线 (MultiLineString, 5字段)
│   ├── landuse.geojson                   # 现状地类图斑 DLBM编码 (MultiPolygon, 9字段)
│   ├── road.geojson                      # 现状道路 (MultiLineString)
│   └── annotation.geojson                # 现状注记 (Point, 注记+分类)
├── planned/                              # 规划 7 层
│   ├── landuse.geojson                   # 规划地类图斑 GHYTBM+GHFLBM双编码 (16字段)
│   ├── farmland_protection.geojson       # 永久基本农田红线 (MultiPolygon)
│   ├── ecological_protection.geojson     # 生态保护红线 (MultiPolygon)
│   ├── historical_protection.geojson     # 历史文化保护线 (MultiPolygon)
│   ├── construction_zone.geojson         # 有条件建设区 (MultiPolygon)
│   ├── hazard_points.geojson             # 地质灾害点 (Point)
│   ├── road.geojson                      # 规划道路 (MultiLineString)
│   └── annotation.geojson                # 规划注记 (Point)
├── tables/
│   └── land_balance.json                 # 用地平衡表 (JSON, 后续→Excel)
└── layout.json                           # 布局配置
```

**字段标准**参照 `backend/app/services/modules/gis/data/gdb_schema.py` 中的 `GDB_LAYER_REGISTRY`（12 层完整字段定义）。

## 3. 架构设计

### 3.1 Trinity 三层模型

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1: PLANNING KG (规划知识图谱)                             │
│  将规划报告文本 + GIS 地块属性 → RDF 三元组                      │
│  提供 SPARQL 查询接口，让 LLM 动态获取约束值                      │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2: AGENTIC PIPELINE (智能体流水线)                        │
│  PARSE Agent (1 tool) → LAYOUT Agent (11 tools)                  │
│  LLM ReAct 决策，通过 state 注入通信                              │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3: SPATIAL GENERATOR (空间生成器)                         │
│  MIP 优化 + CA 细化 → 程序化几何生成                              │
│  硬约束保证（保护地块变量锁定）+ 软约束松弛（面积偏差最小化）       │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Agent 子图设计：PARSE + LAYOUT 双 Agent

```
                    ┌─────────────────────┐
   reports ────────►│    PARSE Agent      │
   gis_data         │  1 tool:            │
                    │  parse_planning_text │
                    └──────┬──────────────┘
                           │ intent_json (state 注入)
                           ▼
                    ┌─────────────────────┐
                    │    LAYOUT Agent     │
   gis_data ───────►│  11 tools:          │
   kg_turtle        │  build_kg → query_kg│
                    │  → detect_conflicts  │
                    │  → allocate_zones    │
                    │  → generate_layout   │
                    │  → validate_layout   │
                    │  + export_gdb        │
                    │  + render_map        │
                    │  + 4 data tools      │
                    └──────┬──────────────┘
                           ▼
                    12-layer output
```

**设计理由：**

| 决策 | 理由 |
|------|------|
| **为什么双 Agent？** | 文本理解（温度 0.2，需要创造性提取意图）与空间推理（温度 0，确定性操作）的可靠性要求不同。Intent schema 变更时 LAYOUT 零影响 |
| **为什么不三 Agent（PARSE + REASON + GENERATE）？** | REASON（约束推理）与 GENERATE（布局生成）在 13 工具场景下共享同一 KG 和 landuse 数据，分离反而增加 state 传递开销。LAYOUT Agent 的 ReAct 内循环已包含"查询→推理→分配→验证"的完整推理链 |
| **通信协议** | 通过 LangGraph TypedDict state 注入：`ParseAgentState.intent_json → LayoutAgentState.intent`，类型安全、可追踪 |
| **fallback** | 保留 `create_gis_agent_graph()` 单一 Agent（全部 13 工具），用于简单场景和测试 |

### 3.3 代码位置

```
app/agent/gis/           # Agent 编排层 (3 文件)
  agent.py               # create_parse/layout/gis_agent_graph()
  state.py               # ParseAgentState / LayoutAgentState / GISAgentState
  prompts.py             # PARSE / LAYOUT / GIS system prompts

app/tools/gis/           # @tool 层 (11 文件, 13 工具)
  parse.py               # parse_planning_text
  kg.py                  # build/query_knowledge_graph
  conflict.py            # detect_conflicts
  allocate.py            # allocate_zones (MIP + greedy)
  generate.py            # generate_layout (CA + facility + axis)
  validate.py            # validate_layout (8 checks)
  export.py              # export_gdb (12层 + 用地平衡表)
  render.py              # render_map (MapLibre 图层)
  data.py                # fetch_gis_data + search_poi
  analytics.py           # calculate_gis_coverage + analyze_accessibility

app/services/modules/gis/ # 纯服务层 (无 @tool)
  zone_schema/           # 编码系统单一真相源
  providers/             # 天地图/高德/OSM
  data/                  # 数据获取 + GDB schema
  analysis/              # 空间分析
  kg/                    # RDF 知识图谱
  conflict/              # 冲突检测-消解
  optimizer/             # MIP + CA 优化器
  validation/            # 布局验证
  utils/                 # 坐标/面积/GeoJSON 工具
```

## 4. 编码体系

三套正交编码，定义在 `zone_schema/`（唯一真相源）：

| 体系 | 来源 | 用途 | 示例 |
|------|------|------|------|
| **DLBM / GHYTBM** | 三调工作分类 (GB/T 21010) | 现状/规划地类 → 8 功能分区 | `2121`=宅基地 → `居住用地` |
| **YDYHFLDM** | 自然资发〔2023〕234 号 | 基数转换上报 | `2121` → `0702` (农村宅基地) |
| **V/N/E** | 住建部村庄规划用地分类 | 前端统计口径 | `2121` → `V11` (住宅用地) |

两套分区（互不混用）：

| 分区体系 | 类别数 | 来源 | 使用者 |
|---------|--------|------|--------|
| **功能分区** | 7+1 类 | DLBM → zone_type | `render_planning_layout`, function_zone 图层 |
| **规划分区** | 4 区 | DLBM → planning_zone | MIP allocator, planning_zone 图层 |

编码覆盖：金田村实测 660 地块 100% 可映射。

## 5. 工具流水线

```
PARSE ──► KG ──► CONFLICT ──► ALLOCATE ──► GENERATE ──► VALIDATE ──► EXPORT ──► RENDER
```

| # | 步骤 | 功能 | 设计理由 | 外部参考 |
|---|------|------|---------|---------|
| 1 | **PARSE** | LLM 解析 12 维度规划报告 → `UnifiedSpatialIntent` | 自然语言约束提取，比规则 NLP 更准确 | PlanGPT-VL (2025) 验证了 LLM 提取规划意图的可行性 |
| 2 | **KG** | 构建 RDF 图谱 (660 parcels × ~10 triples) + SPARQL 查询 | 结构化约束后 LLM 可动态查询，避免 prompt 注入 | OntoPlanningRegulations (2025) KG 模式 |
| 3 | **CONFLICT** | 跨维度指标冲突检测（metric/constraint/spatial 三类） | 13 维度独立规划必然出现冲突，需在分配前统一 | 专利 CN202511326944 "刚性约束底线自动校核" |
| 4 | **ALLOCATE** | MIP 分配 4 规划分区 + 硬约束锁定保护地块 | MILP 保证全局最优解（村级 <1000 地块在 30s 内） | GenPlanner (PyPI) 的 MILP + relation_matrix 模式 |
| 5 | **GENERATE** | CA 细化 + 设施选址（4 策略）+ 轴生成（一核一带三区） | CA 消除分区碎片，设施基于服务半径规则 | GenPlanner 的 Voronoi 细化（下一步参考方向） |
| 6 | **VALIDATE** | 8 项空间检查 + 合规验证（最多 3 轮） | 独立验证确保输出质量 | BlocksNet 的 iterative provision assessment |
| 7 | **EXPORT** | 标准 12 层 GeoJSON + 用地平衡表 | 与 GDB 标准和 ArcGIS 入库规范对齐 | bxgis 的 Arcpy GDB 导出流程 |
| 8 | **RENDER** | GeoJSON → MapLibre 前端图层（GB/T 21010 配色） | 数据驱动渲染，前端零配置 | — |

## 6. 技术决策记录

| 决策 | 选择 | 不选 | 理由 |
|------|------|------|------|
| **优化算法** | MIP (PuLP) | DRL / GA / 模拟退火 | 村级 <1000 地块，MIP 30s 内最优解，无需启发式 |
| **知识表示** | RDF / SPARQL | SQL / JSON Schema / Prolog | RDF 无 schema 变更即可添加约束类型；SPARQL 可被 LLM 生成 |
| **编排** | LangGraph ReAct | 固定 pipeline / Airflow | 各村约束差异大，LLM 需动态选策略 |
| **约束力度** | 硬约束（保护地块 MIP 变量锁定）+ 软约束（面积 slack） | 全软约束 | 生态红线/基本农田是法律红线，不可违反 |
| **空间细化** | CA (Cellular Automata) | Voronoi / GAN | CA 简单可解释，GAN 需要大量训练样本且输出不可控 |
| **坐标系** | WGS-84 (内部) + GCJ-02 (高德) + CGCS2000 (天地图) | 单一坐标系 | 三个数据源使用不同坐标系，坐标转换为已知算法 |
| **地图渲染** | MapLibre GL JS | Leaflet / OpenLayers | 国产化兼容（不含 Google 服务）、矢量瓦片性能、GL JSON 样式规范 |

## 7. 外部可行性验证

| 功能维度 | 本项目实现 | GenPlanner (PyPI) | BlocksNet (40★) | DRL-urban-planning (清华,Nature) | 专利 CN202511326944 | bxgis |
|---------|-----------|-------------------|-----------------|--------------------------------|-------------------|-------|
| MILP 分区分配 | ✅ | ✅ | ❌ (模拟退火) | ❌ (DRL) | ❌ | ❌ |
| 邻接约束矩阵 | ✅ (zone_schema) | ✅ | ❌ | ❌ | ❌ | ❌ |
| 规则引擎冲突检测 | ✅ (conflict.py) | ❌ | ❌ | ❌ | ✅ | ✅ |
| 用地平衡表 | ⚠️ (JSON) | ❌ | ✅ | ❌ | ✅ | ✅ (Excel) |
| 可达性分析 | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| 道路网络生成 | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ |
| 知识图谱 | ✅ (RDF) | ❌ | ❌ | ❌ | ❌ | ❌ |
| GDB 标准输出 | ⚠️ (GeoJSON) | ❌ | ❌ | ❌ | ❌ | ✅ (Arcpy .gdb) |
| 12 层完整输出 | ⚠️ (7/12) | ❌ | ❌ | ❌ | ❌ | ✅ |
| DRL 优化 | ❌ (Phase 3) | ❌ | ❌ | ✅ | ❌ | ❌ |

**结论**：我们以 MIP + KG + Conflict 三个独特组合覆盖了现有开源方案的盲区。GenPlanner 最接近但缺 KG 和冲突检测；DRL-urban-planning 专注土地利用但缺规划约束和标准输出。

## 8. 路线图

### Phase 1 — 当前 (2026-07)
- [x] Trinity 架构 + 双 Agent
- [x] 13 个 @tool 流水线
- [x] MIP 分配 + 硬约束保护地块锁定
- [x] 8 项空间验证
- [ ] 完整 12 层 GeoJSON 输出 + 用地平衡表 JSON
- [ ] 164/164 确定件测试通过 + e2e 测试迁移

### Phase 2 — 下一迭代
- [ ] export: 用地平衡表 Excel 输出、标准字段补全
- [ ] allocate: Voronoi 细化参考 GenPlanner
- [ ] generate: 道路网络规划生成
- [ ] data: PostGIS 空间索引迁移（>1000 地块时性能优化）
- [ ] 省级标准扩展（广东 GD 专题叠加层）

### Phase 3 — 探索方向
- [ ] DRL 土地优化（参考清华 DRL-urban-planning, Nature Comp Sci 2023）
- [ ] GAN 村庄布局生成（参考 CGAN Rural Plan, FoAR 2025）
- [ ] 实时协同编辑 + 移动端预览
- [ ] 规则库标准化（参考专利 CN202511326944 的可执行规则语法）
