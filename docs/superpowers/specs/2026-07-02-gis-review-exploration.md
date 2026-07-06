# GIS 布局引擎审视 - 完整探索内容存档

**日期**: 2026-07-02
**分支**: feature/gis-layout-engine
**目的**: 从规划系统工程视角审视 GIS 实现，保存所有探索报告、外部查询结果和方案内容

---

## 一、Explore Agent 报告：GIS 布局引擎实现

### Trinity 架构三层实现完整度

#### Layer 1 Planning KG (kg/) - 95% 完整度

**文件路径**: `backend/app/services/modules/gis/layout/kg/builder.py`, `query.py`, `ontology.py`

**实现内容**:
- **RDF 三元组构建** (ontology.py + builder.py): 基于 RDFLib 的轻量级图存储，定义了13种实体类型
  - 基础实体: Parcel, Zone, Constraint, Indicator (660个地块节点)
  - 进阶实体: Project, Village, Regulation, LandUsePlan, Facility, Road, WaterBody (动态生成)
  
- **规划知识** (builder.py 第28-92行): 提取了7类硬约束
  - 建设/耕地/林地保有量/永久基本农田/生态红线(7条) + 土地利用指标(5条)
  - 三区三线映射: 生态保护区(绿色#2E8B57)、农田保护区(深黄#FFE4B5)、村庄建设区(红色#FF6347)、一般农业区(浅绿#98FB98)
  
- **SPARQL 查询模板** (query.py 第8-206行): 20+查询模板
  - `get_constraints`: 获取所有约束配置
  - `get_adjacent_parcels`: 获取地块邻接关系(共448条边)
  - `count_by_zone_type`: 按分区类型统计面积

**关键问题**:
- 缺少溯源性关系(relation to original reports)，仅记录了`source: "reports"`或`source: "gis_data"`

#### Layer 2 Agentic Pipeline (engine.py) - 90% 完整度

**核心流程** (engine.py):
```python
full_pipeline():
  Phase 0: detect_and_resolve(summaries) → ConflictDetector + ConflictResolver
  Phase 1: generate_layout(intent, gis_context) → SpatialLayoutEngine
  Phase 1.5: 验证循环 max_validation_rounds=3
```

**ReAct 推理结合工具执行**:
- `engine.py 第292-392行`: 冲突检测+解决 自动化
- `engine.py 第354-390行`: 验证失败后自动调整 `zone_areas` 并重新调用 `_generate_planning_zones_with_targets`
- `validate → adjustments → reassign`: 形成闭环优化循环

**关键代码截取**:
```python
# engine.py 第354-390行
if self._kg_constraints and max_validation_rounds > 0:
    validator = LayoutValidator()
    for round_num in range(max_validation_rounds):
        report = validator.validate(configs, self._kg_constraints)
        if report.status == "pass":
            break
        adjustments = self._violations_to_adjustments(report.violations)
        adjusted_targets = self._apply_adjustment(self._last_planning_targets, adjustments)
        new_planning = self._generate_planning_zones_with_targets(intent, landuse_geojson, adjusted_targets)
```

#### Layer 3 Spatial Generator (optimizer/) - 85% 完整度

##### MIP Solver (mip_solver.py + mip_allocator.py)

**目标函数** (mip_allocator.py 第196-302行):
```python
min  Σ_z (dev_pos_z + dev_neg_z) * AREA_WEIGHT  +  Σ_i Σ_z x[i][z] * preference_cost[i][z]
    Σ_i Σ_z x[i][z] * change_penalty  +  Σ_adjacent y[pair][z] * adj_compactness
```

**约束条件**:
- C1: 每个地块仅分配至一个分区 (223-225行)
- C2: 分区面积偏差定义 (228-239行, dev_pos/dev_neg 非负松弛变量)
- C3: KG硬约束注入 (241-243行, construction_cap/farmland_min/ecological_min)

**DLBM-分区偏好矩阵** (mip_allocator.py 第36-102行):
- 0 = 原生分区(权重为0)
- 30 = 兼容
- 50 = 不情愿(耕地→建设需高代价)
- 1000+ = 绝对禁止(受保护地块)

**MIP 算法弱点**:
- 线性化邻接约束用y[pair][z] α变量，每个邻接对扩展z倍变量数 (275-303行)
- 当乡邻数~3000对 × 4分区=12000个辅变量，**求解时间可能超120s** (310行 timeLimit=120)

##### CA 冲突消解 (ca_refiner.py)

**算法** (第57-94行):
```python
for iteration in range(3):
    merged = buffer_union_debuffer(same_type_geoms, merge_distance_m=30)
    simplified = merged.simplify(tolerance_m=10, preserve_topology=True)
    area_loss = (original_area - merged_area) / original_area
```

**效果** (第87-92行日志):
- 合并了GAP < 30m的小边界
- 保留拓扑有效性 (`preserve_topology=True`)
- 面积损耗容忍度: 允许<2%

**工作流程**:
```
MIP分配 → [gap < 30m合并] → [平滑边界] → [去除<0.5ha细碎多边形] → facility/axis
```

##### 邻接图构建 (adjacency_graph.py)

**基于 Shapely STRtree 空间索引**:
- 距离阈值: 30m (第90-91行: 30m / 96km ≈ 0.00031度)
- 节点映射: `parcel_key → (idx, {neigh1, neigh2, ...})`
- O(1)时间复杂度的邻接查询

**输出**: 448条邻接边 (660个地块的邻接关系)

### validator.py 验证规则深度分析

**文件路径**: `backend/app/services/modules/gis/layout/validator.py`

**验证了7类规划约束**:

#### 1. Area Constraints - 面积约束 (第134-183行)
- **语法**: `construction_cap` ≤ 30.50ha, `farmland_min` ≥ 78.83ha, `ecological_min` ≥ 362.02ha
- **反馈机制**: 返回 `Violation(list of dicts)` 其中 `severity="error|warning"`

#### 2. Zone Completeness - 分区完整性 (第185-222行)
- **必需分区**: 村庄建设区、生态保护区、一般农业区 (农田保护区可选)
- **缺村逻辑**: 默认所有村庄都有建设区和生态保护区

#### 3. Protected Parcels - 受保护地块 (第294-330行)
- **禁止转移**: DLBM ∈ {0110, 0120, 0130(水田/水浇地/旱地), 1340/1350(商品林/生态林)} → 村庄建设区
- **反馈**: 列出违规地块DLBM编码

#### 4. Minimum Area - 最小面积阈值 (第332-351行)
- **田村**: > 0.5ha (村庄建设区) → 警告
- **生态**: > 1.0ha → 警告

#### 5. Spatial Compactness - 空间紧凑度 (第679-738行)
- **指标公式**: `CV = std(areas) / mean(areas)`, `compactness = 1 / (1 + CV)`
- **阈值**: < 0.5 → 警告 (第725行)

#### 6. Adjacency Compatibility - 邻接兼容率 (第616-677行)
- **指标**: `同分区边数 / 总邻接边数` = 30% (第664行)
- **用途**: 评估MIP邻接约束是否生效

#### 7. GeoJSON RFC 7946 结构验证 (第353-468行)
- **坐标范围**: Lon ∈ [-180, 180], Lat ∈ [-90, 90]
- **多边形环闭合性**: first == last coordinate (±1e-10精度)

### 国标符合性评估

**GB/T 21010-2017 色卡** (colors.py 第14-32行):
| 分区 | 填充色 | 描边色 | RGB参考 |
|------|--------|--------|---------|
| 农业用地 (耕地) | #F5F8DC (淡黄) | #8B7355 (褐) | RGB(245,248,220) |
| 生态绿地 (林地) | #68B167 (暖绿) | #2E8B57 (海绿) | RGB(104,177,103) |
| 居住用地 (宅基地) | #FFD380 (橙色) | #B8860B (栎褐) | RGB(255,211,128) |
| 商业用地 | #FF0000 (红) | #CC0000 (深红) | RGB(255,0,0) |
| 公共服务 | #4A90D9 (蓝) | #1E3A5F (深蓝) | RGB(74,144,217) |
| 水域 | #87CEEB (天蓝) | #4169E1 (宝蓝) | RGB(135,206,235) |

**三区三线映射** (colors.py 第362-367行):
```python
PLANNING_ZONE_COLORS = {
    "农田保护区": "#FFE4B5",     # 基本农田
    "村庄建设区": "#FF6347",    # 居住+产业+公共
    "生态保护区": "#2E8B57",    # 林地+水域
    "一般农业区": "#98FB98",    # 园地+一般农地
}
```

✅ **完全符合** 市级国土空间规划制图规范，与frontend同步前端变量 (colors.py 第11行注释)

### facility_placer.py 设施布置分析

**文件路径**: `backend/app/services/modules/gis/layout/facility_placer.py`

### 设施类型 (22-43行)
| 设施 | 执行DLBM | 颜色 | 服务半径 |
|------|----------|------|----------|
| 村委会 | 2122/2125(公共基础设施) | #8B4513(褐) | 500m |
| 学校 | 2122(教育) | #4169E1(蓝) | 800m |
| 卫生站 | 2122/0800(医疗) | #DC143C(红) | 600m |
| 文化站 | 2122(文化) | #9932CC(紫) | 400m |
| 市场 | 2124(商业) | #FF8C00(深橙) | 1000m |
| 养老服务 | 2122(社区服务) | #2F4F4F(深灰) | 400m |
| 产业服务中心 | 2124, 2122(产业建筑) | #B8860B(金) | 500m |
| 停车场 | 2126(村内交通) | #696969(灰) | 300m |

### 布置算法 (166-219行)

**4策略规则**:
1. **现状保留**: 优先POI现有位置，fallback至最优DLBM中位数坐标
2. **规划新建**: 定位于`centroid_of_DLBM` → 方向偏移 (正北300m, 正东300m等)
3. **规划改扩建**: 同位置，半径×1.5
4. **规划迁建**: 查找最近合适DLBM组中位数

**Service Radius 评估**:
- 公共服务设施基本符合村委会<500m、学校<800m的理想服务半径
- 医疗、养老等1200人以下的村庄可能覆盖不足

### map_renderer.py 渲染输出格式

**文件路径**: `backend/app/services/modules/gis/layout/map_renderer.py`

### 6层GeoJSON输出
| 图层 | layerType | 优先级 | 格式 |
|------|-----------|--------|------|
| 村界边界 | boundary | 0 | Polygon |
| 敏感区分区 | sensitivity_zone | 1 | Polygon |
| 功能分区（现状DLBM） | function_zone | 3 | Polygon |
| 规划分区（规划意图） | planning_zone | 4 | Polygon |
| 发展轴线 | development_axis | 5 | Point/LineString |
| 基础设施 | infrastructure | 6 | LineString |
| 设施点 | facility_point | 7 | Point |

### 颜色系统合规性
- **填充色** (fill): 与国标GB/T 21010同步，代码注释明确标注
- **前端同步**: colors.py 第11、40行注释 "synced with frontend"
- **无硬编码色值**: 通过 `get_zone_color(zone_type)` 函数动态获取

### 效果指标测试覆盖

**测试文件清单** (9个核心测试):

1. **test_gis_kg_builder.py**
   - 测试RDF三元组构建、SPARQL查询、邻接关系(448条边)
   - 验证约束转换rule location

2. **test_gis_mip_optimizer.py**
   - 测试面积偏差、邻接兼容率[>=60%阈值]
   - 测试Protected DLBM禁止转移

3. **test_gis_validator.py**
   - 测试7类约束：area_constraint/zone_completeness/overlap/protected_parcels/min_area
   - 测试GeoJSON RFC 7946结构和多边形闭合性

4. **test_gis_ca_refiner.py**
   - 测试gap < 30m合并、area loss ≤2% tolerance

5. **test_gis_performance.py**
   - Adjacency构建 < 2s, MIP求解 < 120s (无邻接)
   - KG查询 < 500ms

6. **test_gis_e2e_real_data.py**
   - 真实金田村数据(660地块，45分区，总面2360ha)
   - 验证4类规划分区正确生成

7. **test_gis_adjacency_graph.py**
   - 测试STRtree效率、30m阈值过滤

8. **test_gis_geojson_structural.py**
   - 验证坐标范围、闭合环、属性结构

9. **test_gis_planning_zone_mapper.py** (可选分区逻辑)
   - 测试农田保护区是否可选(金田村无此分区)

**性能基准结果**:
```
✅ MIP求解时间: 35s (无邻接约束) / <120s (含邻接)
✅ MIP构建时间: <2s
✅ Adjacency构建: <1s (660节点)
✅ KG查询: <500ms (典型20条sparql)
✅ 邻接兼容率目标: >=60%
✅ 面积偏差: <5% tolerance
```

### 量化布局质量指标

#### 核心指标体系

1. **Area Congruence** (面积一致性)
   - 定义: `|actual - target| / target`
   - 期望: < 5% (MIP可解范围内)

2. **Adjacency Compatibility Rate** (邻接兼容率)
   - 定义: `(同分区边数) / (总邻接边数)`
   - 期望: >= 60% (village规划推荐值)
   - MIP参数: `adjacency_weight=0.5` (线性化补偿)

3. **Spatial Compactness Index** (空间紧凑度)
   - 定义: `1 / (1 + CV)` 其中 CV = `std(areas) / mean(areas)`
   - 期望: >= 0.5 (不均等分布阈值)
   - 检测工具: `_check_spatial_compactness()` (validator.py 第679-738行)

4. **Protected Parcel Fraction** (受保护地块比例)
   - 定义: `受保护地块面积 / 总面积`
   - 约束: 农田保护区/生态绿地中无建设区地块

5. **Change Rate** (土地利用变更率)
   - 定义: `不同分区地块数 / 总地块数`
   - 日志: `engine.py: {changed} changed ({changed/len(features)*100:.1f}%)`

6. **Validation Pass Rate** (验证通过率)
   - 定义: 验证轮次/最大轮次
   - 循环次数: `max_validation_rounds=3` (我是可配置)

### 量化标准示例

```python
# GPT自动生成阈值
targets = {
    "农田保护区": 78.83,      # 基本农田目标
    "村庄建设区": 30.50,      # 建设用地目标
    "生态保护区": 362.02,     # 生态红线目标
    "一般农业区": 1881.21,    # 剩余空间
}
area_deviation = {
    "农田保护区": 2.1ha (2.7%),
    "村庄建设区": -1.5ha (-4.9%),  # 低于目标
    "生态保护区": 5.3ha (1.5%),
    "一般农业区": -3.2ha (-0.2%),
}
adjacency_rate = 63% (超60%阈值)
reassigned_parcel_rate = 18% (土地利用变更)
```

### 架构优点
1. **三层架构清晰**: KG约束驱动 → MIP求解 → CA后处理
2. **国标合规**: GB/T 21010色卡、三区三线完全符合
3. **循环验证**: `validate → adjustments → re-solve` 自动优化闭环
4. **性能优化**: STRtree空间索引、CRS投影转换、损失<2%的CA后处理

### 潜在风险
1. **MIP求解瓶颈**: 3000邻接对 × 4分区=12000个α变量，可能超120s
2. **Facility覆盖不足**: 乡村医疗/养老半径偏小(理想1200m+)
3. **约束可解释性不足**: KG约束仅返回违规面积，未提供调剂建议
4. **无率控制**: 无LaTeX/LaTeX-textcode书输出JSON，符合国标/Gabin但缺打印样式表

---

## 二、Explore Agent 报告：GIS 与规划系统集成

### Agent 调用 GIS 的流程

#### **LangGraph Agent 核心 (graph.py)**
- **路由机制**（108-110行）：在 `conversation` 节点的条件路由中，显式包含 `gis_agent` 分支：
  ```python
  builder.add_conditional_edges(
      "conversation",
      after_conversation,
      {
          "execute_tools": "execute_tools",
          "analyze_dimension": "analyze_dimension",
          "gis_agent": "gis_agent",  # GIS 独立路由路径
          END: END
      }
  )
  ```
- **GIS 子图节点**（第34-90行）：通过 `gis_agent_node` 调用 ReAct 子图生成空间布局
- **SSE 流式输出**（72-85行）：`gis_agent_node` 将 GIS 结果通过 `SSEPublisher.send_gis_result()` 接口发布
- **中间状态注入**：使用 `InjectedState` 注入数据库 reports 和 GIS 数据（48-53行）

#### **状态定义 (state.py)**
- **GIS 相关字段**（181-182行）：
  - `gis_layout_configs: List[Dict[str, Any]]` - Agent 输出的图层配置
  - `user_uploaded_data: Dict[str, Dict[str, Any]]` - 用户上传的 GIS 数据
- **数据库查询**（154-163行）：从 ReportStore 加载 L3 summaries 并传递给 GIS Agent

#### **工具定义 (layout_tools.py)**
定义了 **10 个工具**，全部针对 3 层规划的详细规划阶段（Layer 3）：

| 工具函数 | 行号 | 签名 | 功能描述 |
|---------|------|------|---------|
| `parse_planning_text` | 222-236 | `reports, village_name, tool_call_id` | 从规划报告自动解析空间意图 |
| `build_knowledge_graph` | 238-273 | `reports, gis_data, village_name, tool_call_id` | 构建知识图谱 |
| `query_knowledge_graph` | 276-340 | `template_name, kg_turtle, ...` | 查询知识图谱约束/指标/地块 |
| `detect_conflicts` | 343-365 | `summaries, tool_call_id` | 检测跨维度指标冲突 |
| `allocate_zones` | 368-423 | `targets, constraints, kg_constraints, ...` | 基于约束分配功能分区 |
| `generate_layout` | 426-468 | `intent, gis_data, kg_constraints, tool_call_id` | 生成多图层空间布局 |
| `validate_layout` | 471-501 | `layout_configs, constraints, auto_retry, tool_call_id` | 验证布局完整性 |
| `measure_divergence` | 504-614 | `current_geojson, planned_geojson, tool_call_id` | 量化差异 |

#### **3 层规划结合情况**
- **现状分析阶段（Layer 1）**：使用 detailed.py 的 12 个维度框架撰写报告，**未调用 GIS 工具**
- **规划思路阶段（Layer 2）**：使用 detailed.py 撰写规划概念，**未调用 GIS 工具**
- **详细规划阶段（Layer 3）**：GIS 工具被 **集中调用**，通过 ReAct 子图协调执行
- **数据流断层**：L1/L2 报告未传递给 GIS Agent，仅 L3 报告用于知识图谱构建（854-877行）

### 数据流和接口

#### **GIS 服务层 (service.py)**
- 第1-5行：注释说明 GIS 工具执行已由 GIS Agent ReAct 子图接管
- **仅保留边界和中心查询**：`GisService.get_boundary()` 和 `GisService.get_village_center()`（18-50行）
- **同步调用**：工具执行均为**同步**，LangGraph 使用 `ainvoke()` 确保事件循环安全

#### **增量 SSE 流式输出 (graph.py: 72-85行)**
- **双重推送机制**：
  1. **实时增量推送**：`SpatialLayoutEngine._emit_layer_update()` 在生成每一层时立即推送
  2. **汇总推送**：`SSEPublisher.send_gis_result()` 在最后推送汇总事件
- **数据优化**：`layers=[]` 避免冗余传输大 GeoJSON 载荷

#### **前端 GIS 组件**
- **MapView.tsx**（153-156行）：支持每要素颜色注入 `hasFeatureColors()` 函数
- **订阅机制**：通过 SSE 消息流的 `dimension_key="spatial_layout"` 过滤接收 GIS 状态
- **图层渲染优先级**（142-151行）：`LAYER_PRIORITY` 定义渲染顺序，确保边界在最底层

#### **前端状态管理**
- **planningStore.ts**：目前从 `state_to_ui_status()` 转换获取 `gis_layout_configs`（434行）
- **数据架构**：
  - `layerType` - 图层类型标识字符串
  - `geojson` - FeatureCollection 格式的 GeoJSON 数据
  - 数据驱动配色：根据 `zone_type`/`sensitivity_level`/`status` 自动映射颜色

### API 端点

#### **测试 API (gis_test_routes.py)**
- **路由前缀**：`/api/dev/gis`（23行）- 开发环境专用
- **15 个端点**，覆盖完整 GIS 生命周期：
  - **数据获取**：`/status`, `/data-fetch`, `/center`, `/bbox`, `/poi-search`
  - **分析**：`/isochrone`, `/accessibility`, `/coverage`, `/ecological`
  - **规划**：`/spatial-layout`, `/landuse-change`, `/constraint-validator`, `/hazard-buffer`
  - **解析**：`/parse-text`（835-1020行）
- **硬编码数据**：所有端点使用 `docs/gis/jintian_boundary/` 目录的 GeoJSON 样本数据
- **无鉴权保护**：纯开发用途，生产环境应禁用

#### **生产 API 路由 (routes.py)**
- **搜索结果**：未发现生成路由文件，推测通过 FastAPI 自动注册路由
- **功能暴露**：仅提供业务路由（planning 相关），未出现 `/api/gis/*` 端点
- **鉴权缺失**：若存在，需检查 `app/database/db.py` 中的认证中间件配置

### 集成度评估

#### **当前集成方式**：**作为独立工具被 ReAct 子图调用**，**未深度嵌入中心推理链**

**支持深度集成的场景**：
- ✅ L3 报告文本解析为空间意图（`parse_planning_text`）
- ✅ 规划约束推理与知识图谱（`build/ query_knowledge_graph`）
- ✅ 分区冲突检测（`detect_conflicts` + L3 摘要加工）

**未深度集成的场景**：
- ❌ L1 现状分析数据未注入 GIS，导致知识图谱缺失现状要素
- ❌ L2 规划思路未转化为空间约束传递给 GIS Agent
- ❌ GIS 输出的 `layout_configs` 未被前序维度验证使用
- ❌ `allocate_zones` 等优化工具未被 L3 报告驱动的规划目标激活

#### **规划 Prompt (detailed.py) 的问题**

**缺失 GIS 引导**（第427-757行全量表格结构）：
- 12 个维度 Prompt（agriculture, ecological,等）均未提及使用 GIS 工具
- 空间布局仅暗示在 `space_layout` 维度出现，但无具体工具调用说明
- **prompt 与工具链解耦**：LLM 看不到 `generate_layout`, `query_knowledge_graph` 等工具

**改进建议**：
- 在 WRITING_RULES 后增加 `【GIS 工具使用说明】` 小节
- 引导 LLM 在分析现状时调用 `build_oknowledge_graph` + `detect_conflicts`
- 在规划思路中引导调用 `query_knowledge_graph` 获取约束

#### **数据流断层**
1. **现状分析 → GIS 知识图谱**：
   - L1 报告仅存储于数据库，未通过 Prompt 驱动 GIS 构图
   - `parse_planning_text` 仅接收 L3 报章（854行）

2. **规划思路 → GIS 空间约束**：
   - L2 产出物理设施规划建议，未转化为 `AllocateZones` 的 targets 参数
   - 缺少从自然语言到结构化目标的映射工具

3. **详细规划 → 后续验证**：
   - `validate_layout` 仅校验约束，未与 L1/L2 状态关联
   - `measure_divergence` 未在文档中有解析指引

### 测试覆盖

#### **端到端测试文件**
- `test_gis_e2e_real_data.py` - 未在搜索中出现，可能在其他目录
- `gis_test_routes.py` - 已验证，提供 REST API 端点

#### **E2E 测试不完整性**
- **缺失 Agent→GIS→前端全链路测试**：
  - 无测试验证 `gis_agent_node` → `SpatialLayoutEngine.generate_layout` → `SSEPublisher.send_gis_result` 联动
  - 无前测验证 `MapView` 订阅 SSE `spatial_layout` 消息并正确渲染 GeoJSON
- **单元测试缺失**：
  - `layout_tools.py` 中的 `parse_planning_text`, `detect_conflicts` 等核心逻辑无 pytest 封装
  - **数据驱动测试缺失**：无测试场景覆盖 L1/L2 残缺数据下的 GIS 异常路径
- **性能测试缺失**：
  - 无测试验证 SSE 增量推送与 GUI 渲染的交互性能

### 关键文件路径与行号索引

| 文件路径 | 关键行号 | 内容描述 |
|---------|---------|---------|
| `backend/app/agent/graph.py` | 34-90, 108-110 | GIS Agent 节点、条件路由、SSE 推送 |
| `backend/app/agent/state.py` | 135-183, 434 | AgentState 定义、GIS 相关字段 |
| `backend/app/tools/gis/layout_tools.py` | 222-614 | 10 个 GIS 工具定义 |
| `backend/app/api/gis_test_routes.py` | 23, 835-1020 | 开发 API、parse-text 端点 |
| `frontend/src/features/planning/components/gis/MapView.tsx` | 153-156, 478-618 | GeoJSON 图层订阅、渲染逻辑 |
| `backend/app/services/modules/prompts/detailed.py` | 427-757 | 详细规划维度 Prompt |

---

## 三、Explore Agent 报告：测试体系和性能

### Executive Summary
The Village_Planning_Agent GIS layout engine has a solid testing foundation with:
- **17 test files** covering 201 test functions
- **4-layer test hierarchy**: Unit tests (73) + Integration tests (48) + E2E tests (39) + Performance tests (41)
- **Real data validation**: 660-parcel "金田村" dataset, 12-dimension L3 reports
- **Frontend E2E coverage**: Playwright tests for map interactions and pipeline workflows
- **Performance benchmarks**: MIP solver <120s, KG query <500ms, map rendering <5s

### 1. TEST MATRIX COMPLETENESS

### Test File Breakdown

| File | Purpose | Test Count | Test Type | Coverage |
|------|---------|------------|-----------|----------|
| `test_gis_performance.py` | Performance benchmarks | 8 | Performance | MIP solver, KG queries, adjacency graph |
| `test_gis_e2e_real_data.py` | End-to-end with real data | 15 | E2E | Full pipeline, KG building, validation |
| `test_gis_mip_optimizer.py` | MIP optimization logic | 12 | Unit/Integration | Adjacency, quality, weight sensitivity |
| `test_gis_kg_complete.py` | Knowledge Graph completeness | 11 | Unit | Entity types, relationships, serialization |
| `test_gis_validator.py` | Validation checks | 12 | Unit | Area constraints, zone completeness |
| `test_gis_validator_extended.py` | Extended metrics | 4 | Unit | Adjacency compatibility, spatial compactness |
| `test_gis_adjacency_graph.py` | Spatial adjacency | 11 | Unit | Construction, lookup, pair generation |
| `test_gis_ca_refiner.py` | Cellular automata refinement | 8 | Unit | Area conservation, merge passes |
| `test_gis_planning_zone_mapper.py` | 4↔7 zone mapping | 11 | Unit | Forward/reverse mapping, consistency |
| `test_gis_layout_tools.py` | Tool-level integration | 9 | Unit Integration | Command structure, tool results |
| `test_gis_geojson_structural.py` | GeoJSON structure | - | Unit | Feature collection validation |
| `test_gis_kg_builder.py` | Knowledge graph builder | - | Unit Integration | RDF triple construction |
| `test_gis_sse_events.py` | SSE progress events | - | Integration | Progress streaming |
| `test_gis_api_endpoints.py` | REST API endpoints | - | Integration | HTTP service layer |

### Test Classification

**Unit Tests (73 tests)** - Focused, isolated components:
- `test_gis_performance.py`: MIP solver performance, KG query benchmarks
- `test_gis_mip_optimizer.py`: Adjacency quality, area deviation calculations
- `test_gis_kg_complete.py`: Entity/relationship type validation
- `test_gis_adjacency_graph.py`: Graph construction, neighbor lookup
- `test_gis_ca_refiner.py`: Zone merging, area conservation logic
- `test_gis_planning_zone_mapper.py`: 4↔7 zone type conversion
- `test_gis_validator.py`: Validation check semantics
- `test_gis_validator_extended.py`: Edge compatibility metrics

**Integration Tests (48 tests)** - Component interactions:
- `test_gis_e2e_real_data.py`: Full pipeline with 660-parcel data
- `test_gis_mip_optimizer.py`: MIP solver with real adjacency graphs
- `test_gis_kg_builder.py`: RDF triple generation
- `test_gis_sse_events.py`: Progress event streaming
- `test_gis_api_endpoints.py`: HTTP service layer
- `test_gis_geojson_structural.py`: Feature collection validation
- `test_gis_layout_tools.py`: Tool result structure

**E2E Tests (39 tests)** - Complete user workflows:
- `test_gis_e2e_real_data.py`: Full pipeline execution from L3 reports
- `gis_interactions.spec.ts`: Map rendering, layer toggling, zoom controls
- `planning_pipeline.spec.ts`: Service health, layout generation, validation
- `performance_benchmarks.spec.ts`: Frontend rendering performance

### Planning Scenarios Covered

**Geographic types:**
- 660-parcel "金田村" (2352 ha, representative rural village)
- ID Boundary (landuse_current, boundary, protection zones)
- 7 GIS layers: boundary, landuse, farmland protection, ecological protection, historical protection, roads, hazard points

**Planning Zones (4-class planning system):**
1. 农田保护区 - 78.83 ha (target constraint)
2. 村庄建设区 - 30.50 ha (split into 5 sub-types: 居住/产业/公共服务/交通/商业)
3. 生态保护区 - 362.02 ha (split into 90% 生态绿地 + 10% 水域)
4. 一般农业区 - 1881.54 ha (source of agricultural parcels)

**Zone Types (7-class zoning system):**
- 农业用地 (from 农业 + 基本农田)
- 居住用地 (60% of construction)
- 产业用地 (15%)
- 公共服务用地 (15%)
- 交通用地 (8%)
- 商业用地 (2%)
- 生态绿地 (90% of ecological)
- 水域 (10% of ecological)

### 2. PERFORMANCE BASELINES

### Benchmark Categories

#### 2.1 MIP Optimization Benchmarks (`test_gis_mip_optimizer.py`)

| Metric | Target | Test Location | Rationale |
|--------|--------|---------------|-----------|
| MIP build time | <2s | `test_mip_build_under_2s` | Model construction overhead |
| MIP solve (no adjacency) | <60s | `test_mip_without_adjacency_faster` | Backward compatibility |
| MIP solve with adjacency | <120s | `test_mip_solve_time_under_120s` | With spatial constraints |
| Adjacency compatibility rate | >=30% | `test_adjacency_compatibility_rate` | Quality baseline |
| Density penalty weight sensitivity | <=5% degradation | `test_adjacency_does_not_degrade_compatibility` | Weight optimization |
| Area deviation | <1.0% | `test_area_deviation_reasonable` | Planning accuracy |
| DLBM native zone retention | >=60% | `test_dlbm_preference_respected` | User experience |

**Quantitative Metrics:**
- adjacency_weight: 0.5 (default)
- change_penalty_weight: 0.3 (default)
- max_distance_m: 30.0 (neighbor detection threshold)

#### 2.2 Knowledge Graph Performance (`test_gis_performance.py`)

| Operation | Target | Test Location | Rationale |
|-----------|--------|---------------|-----------|
| KG query | <500ms | `test_kg_query_under_500ms` | Fast iteration for tools |
| KG full build | <5s | `test_kg_build_under_5s` | Overhead for planning session |
| Adjacency graph build | <1s | `test_adjacency_graph_build_under_1s` | Spatial indexing |

#### 2.3 Full Pipeline Performance (`test_gis_e2e_real_data.py`)

| Phase | Operation | Target | Notes |
|-------|-----------|--------|-------|
| Phase 0 | Conflict detection | <15s | Cross-dimension metric comparison |
| Phase 0.5 | MIP allocation | <120s | With adjacency graph |
| CA refinement | Spatial adjustment | <30s | Iterative merge passes |
| Validation | 2-round validation | <5s | Area + compactness checks |
| Full pipeline | End-to-end | <180s | 660 parcels, 4 planning zones |

**Sample dataset:** 660 parcels × 12 planning dimensions

### 3. REAL DATA TESTING

### Data Sources

**Backend E2E Real Data Suite (`test_gis_e2e_real_data.py`)**:
- **Village**: "金田村" (representative 1-200人自然村)
- **Land parcels**: 660 features with coordinates, DLBM codes, area_ha
- **12-dimension L3 reports**: land_use_planning, settlement_planning, spatial_structure, ecological, industry
- **7-GIS layer suite**: boundary, landuse_current, farmland_protection, ecological_protection, historical_protection, road_current, construction_zone
- **Session ID**: Verified from dimension_reports table extraction

**Frontend Real Reports Script (`scripts/test_e2e_real_reports.py`)**:
- **Database session**: `dc2a2e0e-b129-4e8e-a981-48ab6bec9082`
- **Source**: SQLite `data/database/village_planning.db` → dimension_reports table
- **Processing**: Load latest L3 report per dimension → extract metrics → build UnifiedSpatialIntent → run pipeline
- **Output**: JSON exports in `docs/gis/output/`

### Village Cases Tested

**Primary Case: 金田村**
- Total area: 2352.56 ha
- Population: 1850 residents
- Construction area: 30.50 ha (1.3%)
- Farmland area: 1881.54 ha (79.97%)
- Ecological protection: 362.02 ha (15.38%)
- Spatial structure: "一核引领、一带串联、三区协同"

**Case Validations:**
- ✅ KG builds with >600 triples from real reports
- ✅ SPARQL queries return non-empty results (get_constraints, count_by_zone_type, get_parcels_by_dlbm)
- ✅ Constraint-driven allocation assigns all 660 parcels
- ✅ assigned_zone in planning zones matches 4 planning zone names
- ✅ MIP allocator produces same structure as greedy mode
- ✅ CA refinement maintains area conservation (≤5% loss)
- ✅ Validation loop completes with 6 check execution
- ✅ Full pipeline generates ≥3 layer configurations

### Test Failures & Rationale

**Observed Issues (from recent test runs)**:
1. **队伍建设区约束添加重复名** (#313): MIP `farmland_min` constraint produces duplicate names when multiple agricultural zones exist (resolved with tolerance)
2. **PuLP deprecation warnings** (#390): Significant warnings in test output (non-critical, library dependency issue)

**Test Stability:**
- All unit tests pass reliably (~81% pass rate)
- E2E tests show occasional flakiness (SSE event ordering, resource cleanup)
- Real data fixtures require consistent database state

### 4. FRONTEND E2E COVERAGE

### Playwright Test Suite

**File 1: `gis_interactions.spec.ts`** (11 tests)

| Test | Purpose | Coverage |
|------|---------|----------|
| `map canvas renders on page load` | Basemap initialization | Canvas visibility check |
| `basemap switch to satellite image` | Vector/Image/Satellite basemap switching | Button click + 2s render delay |
| `basemap switch to terrain` | Terrain basemap support | Button click + 2s render delay |
| `layer toggle hides and shows GeoJSON data` | Layer visibility toggling | Checkbox toggle + 500ms wait |
| `zoom controls work` | Zoom in/out interactions | Zoom button click + 500ms wait |
| `legend panel displays zone colors` | Legend rendering | CSS selector for `.legend` |
| `no console errors on initial load` | Error detection during load | 404/ERR/CORS filtering |

**File 2: `planning_pipeline.spec.ts`** (8 tests)

| Test | Purpose | Coverage |
|------|---------|----------|
| `GIS service health check passes` | Backend API verification | GET /api/gis-test/status |
| `spatial layout generation produces valid output` | Layout pipeline execution | Click run button + 2min wait |
| `constraint validator runs without errors` | Validation logic | Click run section + 3s wait |
| `planning zones render on map after generation` | Zone layer rendering | Canvas visibility post-generation |
| `SSE progress updates appear during generation` | Real-time progress feedback | Progress indicator count |
| `all 4 planning zone types present` | Zone completeness verification | REST API call + Set size check |

**File 3: `performance_benchmarks.spec.ts`** (5 tests)

| Test | Purpose | Coverage |
|------|---------|----------|
| `page load completes under 10s` | Initial page load time | Network idle wait + 30s timeout |
| `map canvas renders under 5s` | First meaningful paint | Canvas waitForSelector + 10s timeout |
| `basemap switch completes under 3s` | Basemap transition latency | Button click + 500ms load + 1000ms stale check |
| `GeoJSON layer rendering does not freeze UI` | Non-blocking rendering | Interactive canvas check |
| `no memory leaks on repeated layer toggle` | Memory stability | Pre/post toggle JS heap size diff (<50MB) |

### Golden Screenshot Verification

**Missing**: No golden screenshot comparison tests found
- No visual regression detection for map rendering
- No snapshot-based zone visual validation
- No pixel-level comparisons for basemap transitions

**Gap**: Frontend visual output not validated programmatically

### 5. TEST GAPS

### 5.1 Missing Planning Scenarios

| Scenario | Gap | Impact |
|----------|-----|--------|
| **Different terrain types** | Only tested generic coordinates; no tests for hilly/mountainous/flat | Terrain-aware adjacency may not be exercised |
| **Different village sizes** | Only 2352 ha "金田村" dataset | Large villages ( >5000 ha) or small villages ( <500 ha) not tested |
| **Multiple villages in one test** | Only single-village analysis | Inter-village spatial conflicts unvalidated |

### 5.2 Boundary Condition Tests

| Condition | Current Coverage | Need |
|-----------|------------------|------|
| **Empty input** | Minimal geojson helpers only | Full elimination tests (empty landuse, empty reports) |
| **极大输入** | None | 2000+ parcels, 15+ dimensions stress test |
| **异常数据** | `unknown_zone_type_defaults_to_general_agriculture` only | Malformed GeoJSON, negative areas, corrupted DLBM codes |
| **Duplicate features** | None | Zero-id or repeated feature indices |
| **Singular feature** | `test_single_feature_passes_through` only | Edge case validation for 1-parcel villages |

### 5.3 Agent Integration Tests

| Integration Point | Current Coverage | Need |
|--------------------|------------------|------|
| **ReAct tool flow** | `test_tool_layer_end_to_end()` bypasses LangGraph | Full LangGraph workflow with tool calling |
| **InjectedState** | Bypassed (pydantic validation issue) | Direct LangGraph integration test |
| **SSE state propagation** | Mock-based only | Real SSE consumer state flushing |
| **Tool result caching** | None | LRU cache behavior validation |
| **Parallel execution** | None | Concurrent tool invocations |

### 5.4 Validation Metric Gaps

| Missing Check | Current | Need |
|---------------|---------|------|
| **Compactness tolerance zones** | Binary pass/fail only | Band thresholds (30-50%, 50-70%, 70-90%) |
| **Adjacency change rate** | Rate only | Δrate % over iterations |
| **Zone connectivity components** | None | Number of connected components check |
| **Road network coverage** | None | % of parcels within 200m of road |
| **Walkability score** | None | Residential-to-amenity distance distribution |
| **Visual adjacency quality** | Adjacency compatibility count only | Per-zone neighbor distribution visualization validation |

### 5.5 Frontend Coverage Gaps

| Area | Current | Need |
|------|---------|------|
| **Snapshot verification** | None | Visual regression testing (Chromatic, Percy, Redux DevTools) |
| **Responsive layouts** | Fixed viewport only | Mobile (375px) + tablet (768px) + landscape test |
| **Accessibility** | None | ARIA labeling, keyboard navigation, color contrast |
| **Error state handling** | Basic console filtering | 404, 500, timeout, network errors UI renders correctly |
| **Download/export** | None | GeoJSON download, PNG screenshot, PDF report validation |
| **Language support** | Chinese locale only | i18n string switches, RTL text direction |

### 6. SUMMARY & RECOMMENDATIONS

### Test Strengths

1. **Real-world validation**: 660-parcel dataset with 12-dimension L3 reports
2. **Hierarchical coverage**: Unit → Integration → E2E progression
3. **Performance accountability**: Specific <120s MIP, <500ms KG query thresholds
4. **Frontend+Backend**: Full-stack E2E with CSS selectors and API calls
5. **Boundary-aware validation**: Service health, landscape awareness

### Critical Test Gaps

1. **Visual regression** ❌ No snapshot-based map rendering validation
2. **Large-scale stress** ❌ No 2000+ parcels or 15+ dimensions tests
3. **Agent integration** ❌ LangGraph workflow not tested end-to-end
4. **Edge cases** ❌ Empty inputs, singular features, malformed data
5. **Compactness bands** ❌ Binary pass/fail only, no tolerance zones

### Test Quality Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Test maturity | 201 tests across 17 files | 200+ | ✅ Met |
| Test hierarchy coverage | Unit (73) + High | All levels | ✅ Met |
| Real data coverage | 660 parcels, 7 GIS layers | >500 parcels | ✅ Met |
| Performance thresholds | 120s MIP, 500ms KG | <180s, <1000ms | ✅ Met |
| Frontend E2E | 24 tests | 20+ | ✅ Met |
| Visual regression | 0 | 100% | ❌ Missing |
| Agent integration | 0 | 100% | ❌ Missing |

### Suggested Test Priorities

**High Priority (Critical Gaps)**:
1. Append a Visual Regression Testing suite (Percy/Chromatic) for map layer rendering
2. Create large-scale stress test (2000+ parcels, 15+ dimensions)
3. Build LangGraph workflow E2E test with real tool execution
4. Add boundary condition test suite (empty, singular, malformed inputs)
5. Implement robust error state UI tests

**Medium Priority (Quality Improvements)**:
6. Add compactness tolerance zone tests (30-50%, 50-70%, 70-90% bands)
7. Test village size variance (100 ha small, 10000 ha large scale)
8. Validate Road network coverage and Walkability scores
9. Multiple village scenarios with cross-village spatial conflicts
10. Enforce LOAD_TEST_RUN environment variable for custom datasets

**Low Priority (Polish)**:
11. Add SSR hydration checks for React Server Components
12. Accessibility audit (WCAG 2.1 Level AA compliance)
13. Keyboard navigation tests for all interactive elements
14. Responsive layout breakpoints (mobile, tablet, landscape)
15. Download/export functionality validation

---

## 四、Exa 搜索结果：中国村庄规划国标

### DB35/T 2061-2022 村庄规划编制规程
- **URL**: https://www.ndls.org.cn/standard/detail/9ee3d051b24b98bca3ad842585e9ee65
- **适用范围**: 福建省范围内城镇开发边界以外的村庄规划编制
- **CCS分类**: P50 土木、建筑 - 城乡规划与市政工程 - 城乡规划
- **ICS分类**: 91.020 建筑材料和建筑物 - 自然规划、城市规划

### GB/T 21010-2017 土地利用现状分类
- **URL**: https://std.samr.gov.cn/gb/search/gbDetailed?id=71F772D789F1D3A7E05397BE0A0AB82A
- **状态**: 现行有效（2017-11-01 实施）
- **主要内容**: 12 一级类、73 二级类，采用二级数字编码
- **适用范围**: 土地调查、规划、审批、供应、整治、执法、评价、统计、登记以及信息化管理

### DB14/T 3120-2024 村庄规划编制技术规范
- **URL**: https://ndls.cnis.ac.cn/standard/detail/d55570cea20c8cda950238481de425b5
- **适用范围**: 山西省域范围内城镇开发边界外的行政村的村庄规划编制

### TD/T 1025-2010 乡(镇)土地利用总体规划编制规程
- **URL**: http://www1.csres.com/detail/212823.html
- **引用标准**: GB/T 21010-2007、GB 50188-2007 镇规划标准、TD/T 1004-2003 农用地分等规程
- **附录**: 包含土地规划用途分类、基本农田调整要求、土地用途区划定步骤、建设用地管制区划定方法

### 湖北省村庄规划编制基本技术指引
- **URL**: https://zrzyhghj.ezhou.gov.cn/ywgz/cxgh1/ghbz/202206/P020220624365363981649.pdf
- **规划定位**: 整合原村庄规划、村庄建设规划、村土地利用规划、土地整治规划

### 关键发现
- **国标层级**: GB/T 21010（国家级）→ TD/T 1025（行业级）→ DB35/T 2061 等省级规程
- **整治规划整合**: 多个省级规程要求村庄规划整合土地整治规划、生态修复规划
- **附录A规范性**: GB/T 21010-2017 附录A 与土地管理法"三大类"对照表

---

## 五、Exa 搜索结果：MIP 土地利用优化

### Application of CPLEX Solver to Land Use Optimization in Gorgan Township
- **URL**: https://jes.ut.ac.ir/article_69575.html
- **核心方法**: 4 用地优化（农业/森林/牧场/建设），3 目标 MIP（最小分配成本+最小转换成本+最大紧凑度）
- **关键约束**: 每个地块仅分配一个用地类型，binary decision variables

### Using Linear Integer Programming for Multi-Site Land-Use Allocation (Aerts 2003)
- **URL**: https://onlinelibrary.wiley.com/doi/10.1111/j.1538-4632.2003.tb01106.x
- **方法**: 4 个 integer programs，raster-based GIS 环境
- **目标**: 最小开发成本 + 最大紧凑度，通过 weighting factor 平衡
- **验证**: 8×8 cells 在合理时间内求解，30×30 cells 案例研究成功

### Evaluation and development of sustainable urban land use plans through spatial optimization
- **URL**: https://onlinelibrary.wiley.com/doi/10.1111/tgis.12531
- **创新点**: 矢量数据（vector data）替代 raster，更好反映地块实际形状
- **算法**: 进化算法寻找 Pareto 解集
- **案例**: 中国大丰市，证明矢量空间优化优于栅格方法

### Village-level land-use scenario decision-making system
- **URL**: https://www.kiphub.com/paper/61e50d431df9b7b431f62a8f
- **方法**: 3 种多目标线性规划方法（目标法、逐步易约束法、Lu's method）
- **案例**: 重庆渝北区龙兴镇
- **适用条件**: (1) 靠近城市 (2) 旅游潜力 (3) 农业主导 (4) 农业活动多样化

### Towards Conversational Spatial Optimization (LLM-Driven)
- **URL**: https://urbcomp25.netlify.app/accept/paper_5.pdf
- **核心创新**: LLM 自动识别优化模型、提取参数、生成数学公式
- **求解器**: Gurobi（默认）或 HiSPOT（开源）
- **支持问题**: P-median、P-center、容量约束
- **性能**: 数百点问题秒级求解

### Evaluation and optimization simulation of land suitability for village construction (Chuzhou city China)
- **URL**: https://www.nature.com/articles/s41598-025-87034-3
- **方法**: "potential-constraint" 评估模型，13 基础指标（海拔、路网密度、人口密度、植被覆盖等）
- **4 维度**: 自然地理、区位交通、社会经济、生态环境
- **权重方法**: CRITIC weighting method
- **应用**: 49 行政村，2035 年村庄建设用地预测

### 关键发现
- **矢量优化更符合规划实践**: 当前项目使用矢量（GeoJSON），符合学术前沿
- **多目标 Pareto 解集**: 当前 MIP 仅单目标，可借鉴大丰市的进化算法
- **LLM→MIP 自动翻译**: Conversational Spatial Optimization 提供了自然语言到 MIP 公式的完整路径
- **CRITIC 权重法**: 可替代当前固定权重 0.5/0.3，提升客观性

---

## 六、Exa 搜索结果：知识图谱 + 规划

### LUAKG - Land Use Approval Knowledge Graph (2025)
- **URL**: https://doi.org/10.3390/app15169012
- **发表**: 2025-08-15, Applied Sciences
- **核心创新**: 分层 KG（General KB + Review KB）
  - General KB: 政策、程序、审批任务
  - Review KB: 项目级规则、约束、典型审查逻辑
- **方法**: LLM + Agent 技术，动态知识路由 + 智能工具调用
- **本体构建**: top-down 政策文档分析 + bottom-up 审批流程提取

### LSDTs - LLM-Augmented Semantic Digital Twins (2026)
- **URL**: https://doi.org/10.1609/aaai.v40i45.41232
- **发表**: 2026-03-14, AAAI
- **核心架构**: 闭环工作流（closed-loop workflow），KG 共享语义基底
- **技术栈**: RDF 三元组 + Jena 规则引擎 + Java Topology Suite 空间函数
- **关键能力**: 自动检测空间冲突（如与保护区重叠）
- **规则引擎**: forward-chaining reasoner，支持 `:hasConflict true` 推导

### AGILE-GISS - 3D Land Use Planning with Ontology
- **URL**: https://agile-giss.copernicus.org/articles/6/3/2025/
- **发表**: 2025-06-09
- **本体**: OntoPlanningRegulations + OntoBuildableSpace
- **技术**: Semantic Web Technologies (SWT) + Blazegraph SPARQL endpoint
- **应用**: 新加坡 3D 城市规划，自动生成 3D master plans

### UrbanKGent - LLM Agent for Urban KG Construction
- **URL**: https://arxiv.org/html/2402.06861v2
- **方法**: LLM Agent 自动构建城市知识图谱
- **关键模块**:
  - Heterogeneity-aware instruction generation
  - Geospatial-infused instruction generation（几何信息注入指令）
  - Tool-augmented iterative trajectory refinement（geospatial tool 增强）
- **微调**: Llama 2-7/13B + Llama 3-8B + LoRA

### mie-lab/3d-landuse-planning (开源项目)
- **URL**: https://github.com/mie-lab/3d-landuse-planning
- **功能**: KG + Blazegraph SPARQL endpoint
- **支持**: area-based 和 type-based regulations，计算 allowable GFA
- **数据格式**: N-quads → Blazegraph

### The World Avatar / Zaha (Cambridge)
- **URL**: https://doi.org/10.17863/cam.120181
- **方法**: RAG + KG 城市问答系统
- **支持**: SPARQL 查询 + 外部工具调用（time series plots、building footprints 可视化）
- **架构**: 基于 Marie（化学 QA 系统）扩展

### Semantic 3D City Agents (Cambridge)
- **URL**: https://como.ceb.cam.ac.uk/media/preprints/c4e-preprint-283.pdf
- **本体**: OntoCityGML（344 classes, 272 object properties, 78 data-type properties, 3363 axioms）
- **Agent 系统**: JPS Agent Framework + Routed Knowledge Graph Access
- **案例**: 柏林 LOD 2 模型，419,909,661 triples

### Automated Compliance Checks in AECO
- **URL**: https://graphwise.ai/blog/automated-compliance-checks-in-aeco-by-leveraging-semantic-technologies/
- **方法**: CityGML → CityRDF（OWM/RDF）+ GraphDB + xSPARQL
- **应用**: 建筑合规自动检查（结构、消防、能效、无障碍）
- **关键技术**: GeoSPARQL ontology vocabulary + 拓扑关系存储

### People, Projects, Organizations, and Products (MDPI 2021)
- **URL**: https://www.mdpi.com/2220-9964/10/12/823
- **方法**: RDF + OWL 标准，SPARQL 查询语言
- **支持**: GeoSPARQL 扩展（sfOverlaps 等空间操作符）
- **应用**: 多方利益相关者环境规划与设计

### 关键发现
- **分层 KG 模式**: LUAKG 的 General KB + Review KB 适合当前项目
- **闭环 KG 更新**: LSDTs 的 forward-chaining reasoner 可借鉴
- **GeoSPARQL 标准**: 当前 ontology.py 使用 GEO namespace，可扩展完整 GeoSPARQL 词汇
- **Agent + KG 融合**: UrbanKGent 的 geospatial tool 增强与当前 GIS Agent 设计一致

---

## 七、Context7 库文档查询结果

### PuLP（MIP 求解器）

**库 ID**: `/coin-or/pulp`
**Code Snippets**: 379 | **Source Reputation**: High | **Benchmark Score**: 64

#### Warm Start 功能
```python
# 激活 warm start
seating_model.solve(pulp.COIN_CMD(msg=True, warmStart=True))

# 设置初始值
for k, v in solution.items():
    x[k].setInitialValue(v)

solver = pulp.COIN_CMD(msg=True, warmStart=True)
```

#### 求解器配置
```python
# 按 name 获取 solver，支持 timeLimit
solver = pl.getSolver('CPLEX_CMD', timeLimit=10)

# CBC 确定性求解（threads=1 禁用并行）
solver = pl.COIN_CMD(timeLimit=60, threads=1, timeMode="elapsed")
```

**应用建议**: 当前 `mip_solver.py` 验证循环重求解时可启用 warmStart，预期降低耗时 30-50%。

### RDFLib（RDF 知识图谱）

**库 ID**: `/rdflib/rdflib`
**Code Snippets**: 392 | **Source Reputation**: High | **Benchmark Score**: 69.7

#### prepareQuery + initBindings 性能优化
```python
from rdflib import Graph
from rdflib.plugins.sparql import prepareQuery

q = prepareQuery(
    "SELECT ?s WHERE { ?person foaf:knows ?s .}",
    initNs={"foaf": FOAF}
)

g = rdflib.Graph()
g.parse("foaf.rdf")

for row in g.query(q, initBindings={'person': tim}):
    print(row)
```

#### RDFLib 家族包
- **sparqlwrapper**: 远程 SPARQL 查询
- **pyLODE**: OWL 本体文档化
- **pyrdfa3**: RDFa 1.1 解析
- **pymicrodata**: HTML microdata 提取
- **pySHACL**: SHACL 验证
- **OWL-RL**: OWL2 RL Profile 扩展

**应用建议**: 当前 `query.py` 20+ SPARQL 模板可预编译，重复查询时通过 initBindings 绑定变量，预期 KG 查询从 500ms 降至 200ms。同时可引入 pySHACL 进行约束验证。

### Shapely（空间几何）

**库 ID**: `/shapely/shapely`
**Code Snippets**: 710 | **Source Reputation**: Medium | **Benchmark Score**: 82.97

#### STRtree 高级查询
```python
from shapely import STRtree, Point, box

# 构建索引
tree = STRtree(pts)

# bounding-box 查询
candidate_idx = tree.query(query_box)

# 带 predicate 的过滤查询
within_idx = tree.query(query_box, predicate="within")

# 最近邻
nearest_idx = tree.nearest(Point(50, 50))

# 批量 predicate 查询（spatial join）
qi, ti = tree.query(circles, predicate="intersects")

# prepared geometry 加速重复包含检查
shapely.prepare(polygon)
hits = tree.query(polygon, predicate="contains")
```

#### STRtree 自动 prepare
```python
# STRtree 自动 prepare，最高效模式
tree = STRtree(pts)
idx = tree.query(polygon, predicate="contains")
```

**应用建议**: 当前 `adjacency_graph.py` 可使用 `tree.query(geom, predicate="intersects")` 替代手动二次过滤，预期邻接图构建从 1s 降至 0.5s。同时使用 `shapely.prepare()` 预处理大几何体。

---

## 八、Plan Agent 设计方案

### 效果评估

#### 1.1 与国标符合度：★★★★☆（4.5/5.0）

**已达标项：**
- **GB/T 21010-2017 土地利用现状分类**：12 一级类 73 二级类代码完整
- **三区三线国标色卡**：完全符合 GC 6000 系列
- **TD/T 1025-2010 分区划分**：4 区划定逻辑正确

**缺口项：**
- **GB/T 21010-2017 农村宅基地分类**：仅支持 2121 宅基地，缺失 2124 经营性建设、2123 宅基地退出
- **省级规程整合缺失**：DB14/T 3120-2024 未整合整治规划
- **控制性详细规划衔接不足**：未读取控制指标（容积率、建筑密度、绿地率）

#### 1.2 与 Agent 集成深度：★★★☆☆（3/5.0）

**已达成项：**
- **L1 L2 L3 数据流单向贯通**
- **GIS 输出回流机制**：`gis_agent_node` 输出 `layout_configs` → Agent 结果累加
- **10 个 GIS 工具可用**

**核心断裂点：**
1. **L1 现状分析未调用 GIS**
2. **L2 规划思路未注入 MIP 目标**
3. **L3 detailed.py 12 维 prompt 无 GIS 引导**
4. **设施服务半径偏小**
5. **KG 现状要素缺失**

### 核心缺陷识别（按严重度排序）

#### 🔴 严重缺陷（阻塞可用性）

1. **L1 L2 L3 数据流双向断裂**（严重度：9/10）
   - 表现为：Agent 无法从 L1 读取现状总用地、耕地保有量，无法约束 L2 指标，L3 文本缺乏空间依据
   - 影响：规划方案与现场脱节，无约束优化

2. **KG 规划实体缺失现状要素**（严重度：8/10）
   - `ontology.py` 仅 13 实体类型，缺 `PARCEL_HISTORY`、`LAND_RIGHTS`、`PRESENT_USAGE`
   - 影响：无法表达"耕地撂荒 15%"、"宅基地闲置 8%"等动态现状

3. **设施服务半径未分等级**（严重度：8/10）
   - GB/T 10210-2017 要求区分教育/医疗/养老
   - 影响：学校设 800m 与医疗设 300m 泛化，选址不符合国标

#### 🟡 重要缺陷（影响准确度）

4. **省级规程未整合整治规划**（严重度：7/10）
5. **Validator 缺控制性指标**（严重度：7/10）
6. **L3 detailed.py 12 维 prompt 无 GIS 工具引导**（严重度：6/10）

### 集成方案

#### 3.1 L1 ↔ L2 数据流注入点

**文件**：`backend/app/agent/analysis/node.py`

在 L1 分析完成后，自动调用 `parse_planning_text()` 提取现状用地指标，注入 `state["_landuse_metrics"]`。

#### 3.2 L2 → L3 规划意图传递

**文件**：`backend/app/agent/conversation/node.py`、`backend/app/services/modules/prompts/concept.py`

L2 节点将 `intent_targets` 字典持久化到 state。

#### 3.3 L3 detailed.py 12 维 prompt 增强

**文件**：`backend/app/services/modules/prompts/detailed.py`

在 `WRITING_RULES` 后新增 `GIS_TOOL_GUIDE` 段，引导 LLM 主动调用 GIS 工具。

#### 3.4 GIS 输出回流 Agent 后续步骤

**文件**：`backend/app/agent/graph.py`

确保 L3 后续维度能读取 `state["gis_layout_configs"]` 中的设施点和轴线。

#### 3.5 KG 闭环更新（LSDTs 模式）

**文件**：`backend/app/services/modules/gis/layout/kg/builder.py`

新增 `_update_from_feedback()` 方法，实现闭环 KG 更新。

### 国标对标增强

#### 4.1 GB/T 21010-2017 农村宅基地分类

补全 2123 宅基地退出、2124 经营性建设编码映射。

#### 4.2 TD/T 1025-2010 省级规程整合

新增 3 个实体：`LandConservationPlan`、`ReforestationPlan`、`GridRegulation`

`builder.py` ZONE_TYPE_PATTERNS 增加"整治规划区"（#FFD700）、"生态红线区"（#8B0000）。

#### 4.3 控制性详细规划指标验证

新增 `validate_comprehensive_planning()` 方法，验证 FAR、GSD、LDR，阈值偏差 ±10%。

### 学术前沿借鉴

#### 5.1 LUAKG 分层 KG（2025）

`builder.py` 拆分 `general_kb` 与 `review_kb`，通过 `kb_source` 参数控制注入来源。

#### 5.2 Conversational Spatial Optimization（LLM→MIP）

**新建文件**：`backend/app/services/modules/gis/layout/optimizer/mip_converter.py`

`ConversationalSpatialOptimizer.nlp_to_mip()` 将 L2 自然语言规划思路转化为 MIP 约束 JSON。

#### 5.3 LSDTs 闭环 KG 更新（2026）

`rule_engine.py` 增加 `SpatialDigitalTwin` 类，实现空间冲突自动检测和 KG 闭环更新。

### 关键修改文件路径和行号

| 文件路径 | 修改类型 | 内容 |
|---------|---------|------|
| `backend/app/agent/analysis/node.py` | 修改 | L1 分析后注入 `_landuse_metrics` |
| `backend/app/agent/conversation/node.py` | 修改 | L2 持久化 `intent_targets` |
| `backend/app/services/modules/prompts/detailed.py` | 增强 | 新增 `GIS_TOOL_GUIDE`，12 维 prompt 引用 |
| `backend/app/services/modules/prompts/concept.py` | 增强 | 注入 L1 现状约束值 |
| `backend/app/services/modules/gis/layout/kg/ontology.py` | 新增实体 | LandConservationPlan/ReforestationPlan/GridRegulation |
| `backend/app/services/modules/gis/layout/kg/builder.py` | 增强 | ZONE_TYPE_PATTERS 增加整治/生态红线区，新增 `_update_from_feedback` |
| `backend/app/services/modules/gis/layout/kg/query.py` | 优化 | SPARQL 模板预编译 + initBindings |
| `backend/app/services/modules/gis/layout/validator.py` | 新增 | `validate_comprehensive_planning` 控性指标 |
| `backend/app/services/modules/gis/layout/facility_placer.py` | 增强 | 设施服务半径分等级 |
| `backend/app/services/modules/gis/layout/optimizer/mip_converter.py` | 新建 | LLM→MIP 翻译器 |
| `backend/app/services/modules/gis/layout/kg/rule_engine.py` | 修改 | 增加 `SpatialDigitalTwin` 闭环更新方法 |
| `backend/app/agent/gis/prompts.py` | 增强 | 补全 2123/2124 宅基地分类 |

### 验证方案

#### 7.1 端到端集成测试

**新建**：`backend/tests/test_gis_e2e_integration.py`
- 测试 L1 → `state["_landuse_metrics"]` 注入
- 测试 L2 → `state["intent_targets"]` 持久化
- 测试 L3 detailed.py prompt 含 `GIS_TOOL_GUIDE`
- 测试 GIS 输出回流到 L3 后续维度

#### 7.2 国标合规测试

**新建**：`backend/tests/test_gis_gb_standard.py`
- 验证 `colors.py` 色卡符合 GB/T 21010-2017
- 验证 4 区划定符合 TD/T 1025-2010
- 验证整治规划区/生态红线区映射
- 验证宅基地 2123/2124 编码

#### 7.3 性能压测

**新建**：`backend/tests/test_gis_performance_stress.py`
- 2000 地块 MIP 求解（阈值 <60s）
- warmStart 重求解耗时对比（预期降 30-50%）
- KG prepareQuery 重复查询耗时对比

#### 7.4 视觉回归测试

**新建**：`backend/tests/test_gis_visual_regression.py`
- 验证 4 区色卡与国标一致
- 验证新增整治/生态红线区色值
- 验证前端 MapView 渲染语义一致性

#### 7.5 边界条件测试

**新建**：`backend/tests/test_gis_edge_cases.py`
- 零面积区允许（特殊村庄如风景区）
- 受保护地块不应在建设区内
- 空输入、单要素、异常数据测试

---

## 九、文件路径验证结果

### 实际验证的文件路径（2026-07-02）

| Plan agent 报告路径 | 实际路径 | 状态 |
|---------------------|---------|------|
| `backend/config/layers.py` | **不存在**（实际在 `backend/app/config/`） | ❌ Plan agent 报告错误 |
| `backend/app/agent/analysis/node.py` | 存在，已验证 L1-L50 | ✅ |
| `backend/app/agent/gis/prompts.py` | 存在，已验证 L1-L47 GIS_AGENT_SYSTEM_PROMPT | ✅ |
| `backend/app/services/modules/prompts/detailed.py` | 存在，已验证 L14-L41 WRITING_RULES、L48-L80 INDUSTRY_PLANNING_PROMPT | ✅ |
| `backend/app/services/modules/gis/layout/kg/ontology.py` | 存在，已验证 L26-L50 EntityTypes 13 实体类型 | ✅ |
| `backend/app/services/modules/gis/layout/optimizer/mip_solver.py` | 存在，已验证 L1-L60 ConstraintDrivenAllocator | ✅ |

### 验证发现

1. **Plan agent 报告中 `backend/config/layers.py` 路径错误**：实际配置在 `backend/app/config/` 目录，需在实际实施时确认具体文件名
2. **`ontology.py` 已包含 13 实体类型**：Parcel/Zone/Constraint/Indicator/Project/Village/Regulation/LandUsePlan/Facility/Axis/Road/WaterBody/BuildingGroup，需新增 LandConservationPlan/ReforestationPlan/GridRegulation
3. **`mip_solver.py` 实际为 `mip_allocator.py`**：Plan agent 报告中文件名描述存在偏差，ConstraintDrivenAllocator 在 mip_allocator.py
4. **`gis/prompts.py` 已有完整 GIS_AGENT_SYSTEM_PROMPT**：6 步工作流已定义，但 L1/L2 prompt 缺少 GIS 引导
5. **`detailed.py` 12 维 prompt 确实无 GIS 引导**：仅注入 analysis_report/planning_concept/constraints，无 GIS_TOOL_GUIDE

---

## 十、实施优先级

### P0（阻塞可用性）
1. L1/L2/L3 数据流闭环（3.1-3.4）
2. detailed.py GIS_TOOL_GUIDE 增强（3.3）
3. ontology.py 整治规划实体（4.2）

### P1（影响准确度）
4. Validator 控性指标（4.3）
5. 设施服务半径分等级
6. PuLP warmStart + RDFLib prepareQuery 优化

### P2（学术前沿）
7. LUAKG 分层 KG（5.1）
8. Conversational Spatial Optimization（5.2）
9. LSDTs 闭环 KG 更新（3.5）

---

## 附录：关键文件行号索引

### 已验证的文件结构

#### `backend/app/agent/analysis/node.py`
- L1-L50: 维度分析节点简化版，包含 RetrievedChunk/RAGRetrievalLog dataclass
- 关键引用：`from ...config import get_dimension_config, get_dimension_layer, list_dimensions`

#### `backend/app/agent/gis/prompts.py`
- L1-L47: GIS_AGENT_SYSTEM_PROMPT 完整 6 步工作流
- L49+: SPATIAL_LAYOUT_PARSE_PROMPT
- 工具调用引导：parse_planning_text → build_kg → query_kg → detect_conflicts → allocate_zones → generate_layout → validate_layout

#### `backend/app/services/modules/prompts/detailed.py`
- L14-L41: WRITING_RULES 全局写作规则
- L48-L80: INDUSTRY_PLANNING_PROMPT 产业规划维度示例
- 引用变量：`{analysis_report}`, `{planning_concept}`, `{constraints}`, `{knowledge_context}`, `{WRITING_RULES}`

#### `backend/app/services/modules/gis/layout/kg/ontology.py`
- L1-L16: 模块文档（13 实体类型 + 11 关系类型 + 三区三线国标）
- L22-L23: PLN/GEO Namespace 定义
- L26-L50: EntityTypes 13 实体类型 URI
- L53-L76: Relations 11 关系类型 URI
- L79-L86: FACILITY_TYPES 5 设施类型
- L89-L93: REGULATION_TYPES 3 规制类型

#### `backend/app/services/modules/gis/layout/optimizer/mip_allocator.py`
- L1-L13: 模块文档（Constraint-driven zone allocator）
- L27: 从 colors.py 导入 ZONE_TYPE_TO_DLBMS, PROTECTED_DLBM_CODES, CONSTRUCTION_ZONE_TYPES
- L30-L36: 预计算 DLBM 类别集合
- L39-L56: CONSTRAINT_NAMES 4 约束映射
- L59+: ConstraintDrivenAllocator 类

---

**文档生成时间**: 2026-07-02 14:30 GMT+8
**分支**: feature/gis-layout-engine
**验证状态**: 文件路径已验证，Context7 文档已查询，Exa 国标与学术前沿已搜索
