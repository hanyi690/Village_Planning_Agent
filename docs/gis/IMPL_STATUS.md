





# GIS 系统 — 实现状态与差距分析

> 审计日期: 2026-07-13 | 对比基线: `docs/gis/DESIGN_GOALS.md` | 分支: `feature/gis-layout-engine`

## 1. 总览

| 状态          | 数量 | 说明                       |
| ------------- | ---- | -------------------------- |
| ✅ 已实现     | 18   | 核心流水线 + 编码 + 数据源 |
| ⚠️ 部分实现 | 4    | 有基础但缺标准字段/格式    |
| ❌ 未实现     | 3    | Phase 2/3 规划中           |

**测试**: 164 passed / ~200 total（e2e 测试因引擎 API 变更待迁移）

---

## 2. 逐模块评估

### 2.1 数据获取 ✅

| 功能                  | 状态 | 文件                                   |
| --------------------- | :--: | -------------------------------------- |
| 天地图 WFS 自动获取   |  ✅  | `data/fetcher.py` (763行)            |
| OSM 村级道路补充      |  ✅  | `providers/osm/provider.py`          |
| 高德 POI 搜索         |  ✅  | `providers/amap/provider.py` (999行) |
| 高德优先 + 天地图回退 |  ✅  | `providers/poi.py` (285行)           |
| GDB 12 层字段标准定义 |  ✅  | `data/gdb_schema.py` (509行)         |
| 金田村测试数据加载    |  ✅  | `tests/fixtures/gis_e2e.py`          |

### 2.2 编码系统 ✅

| 功能                               | 文件                         |
| ---------------------------------- | ---------------------------- |
| DLBM/GHYTBM → 8 功能分区 (83条)   | `zone_schema/encodings.py` |
| DLBM → 4 规划分区 (55条)          | `zone_schema/encodings.py` |
| GHFLBM → zone_type (11条)         | `zone_schema/encodings.py` |
| V/N/E 住建部分类 (33条)            | `zone_schema/code_sets.py` |
| SDDLBM → YDYHFLDM 基数转换 (41条) | `zone_schema/code_sets.py` |
| GB/T 21010 标准配色 (8类)          | `zone_schema/colors.py`    |
| 金田村实测 660 地块 100% 覆盖      | 已验证                       |

### 2.3 PARSE（意图解析） ✅

| 功能                                     | 状态 | 位置                                   |
| ---------------------------------------- | :--: | -------------------------------------- |
| LLM 解析规划报告 → UnifiedSpatialIntent |  ✅  | `tools/gis/parse.py`                 |
| 默认意图兜底（无 LLM 时）                |  ✅  | `_build_default_intent()`            |
| 土地利用提示注入（top 10 DLBM）          |  ✅  | `_build_landuse_hint()`              |
| Async 解析变体（API routes 用）          |  ❌  | 旧`_aparse_reports_to_intent` 已移除 |

**差距**: 无。LLM 温度 0.2 的 Intent 提取可靠性在 12 维度金田村报告中已验证。

### 2.4 KG（知识图谱） ✅

| 功能                              | 状态 | 位置                                               |
| --------------------------------- | :--: | -------------------------------------------------- |
| RDF 图谱构建 (PlanningKG, 1046行) |  ✅  | `kg/builder.py`                                  |
| 从报告构建 + 从 Intent 构建       |  ✅  | `build_from_reports()` / `build_from_intent()` |
| 9 个 SPARQL 查询模板              |  ✅  | `kg/query.py`                                    |
| 约束自动提取 (建设/农田/生态)     |  ✅  | 内嵌于 builder                                     |
| Turtle 序列化/反序列化            |  ✅  | `to_turtle()` / `from_turtle()`                |
| 邻接图构建 (30m 阈值)             |  ✅  | `get_adjacency_map()`                            |

**差距**: SPARQL 模板数量（设计 12 个，实现 9 个）——缺少 3 个高级查询模板（阶段统计、设施覆盖率、分区兼容性矩阵），但当前工作流不依赖它们。

### 2.5 CONFLICT（冲突检测） ✅

| 功能                                     | 状态 | 位置                                              |
| ---------------------------------------- | :--: | ------------------------------------------------- |
| 三类冲突检测 (metric/constraint/spatial) |  ✅  | `conflict/detector.py` (355行)                  |
| 基于语义注册表的跨维度对比               |  ✅  | 使用`parsing.semantics.CROSS_DIMENSION_METRICS` |
| 自动消解 (dimension priority-based)      |  ✅  | `conflict/resolver.py` (299行)                  |
| 5% 相对差异阈值                          |  ✅  | 可配置                                            |

**差距**: 无。冲突检测 + 消解完整工作链已验证。

### 2.6 ALLOCATE（MIP 分区分配） ⚠️

| 功能                       | 状态 | 位置                                                          |
| -------------------------- | :--: | ------------------------------------------------------------- |
| PuLP MILP 求解器           |  ✅  | `optimizer/mip_allocator.py` (453行)                        |
| 保护地块硬约束（变量锁定） |  ✅  | MIP 路径 + greedy 回退均实现                                  |
| 约束松弛变量（slack）      |  ✅  | 非保护地块面积偏差最小化                                      |
| Greedy 回退模式            |  ✅  | PuLP 不可用时自动切换                                         |
| CA 细化器                  |  ✅  | `optimizer/ca_refiner.py` (239行)                           |
| 邻接图构建                 |  ✅  | `optimizer/adjacency_graph.py` (205行)                      |
| **道路网络分割**     |  ❌  | GenPlanner 有此功能，我们的 MIP 不做道路分割                  |
| **Voronoi 几何细化** |  ❌  | GenPlanner 的`features2terr_zones2blocks` 包含 Voronoi 分割 |

**差距**: MIP 核心功能完整，但输出是地块级重分类（不改变几何），缺少道路分割和 Voronoi 微调来生成更自然的区块边界。这是 Phase 2 的优先级最高项。

### 2.7 GENERATE（布局生成） ⚠️

| 功能                                      | 状态 | 位置                                  |
| ----------------------------------------- | :--: | ------------------------------------- |
| DLBM 重分类 → function_zone 图层         |  ✅  | `layout/zone_generator.py` (698行)  |
| 设施选址（4 策略：保留/新建/改扩建/迁建） |  ✅  | `layout/facility_placer.py` (445行) |
| 轴生成（一核一带三区）                    |  ✅  | `layout/axis_builder.py` (313行)    |
| 规划分区图层生成                          |  ✅  | `tools/gis/generate.py`             |
| **道路网络生成**                    |  ❌  | Phase 2                               |
| **建筑体量生成**                    |  ❌  | 不在村级规划范围内                    |

**差距**: 功能完整。与外部方案对比：PlanX-Settlement 的 9 阶段 pipeline 包含 building footprint placement / parking generation 等城市级功能，村级规划不需要。GenPlanner 的道路分割属于 ALLOCATE 步骤的输出约束，非 GENERATE 步骤。

### 2.8 VALIDATE（布局验证） ✅

| 功能                                        | 状态 | 位置                                         |
| ------------------------------------------- | :--: | -------------------------------------------- |
| 8 项空间检查                                |  ✅  | `validation/layout_validator.py` (738行)   |
| 面积约束 (construction/farmland/ecological) |  ✅  |                                              |
| 分区完整性 (4种必有3种)                     |  ✅  |                                              |
| 地块重叠检测                                |  ✅  |                                              |
| 保护地块占用检测                            |  ✅  |                                              |
| 最小面积检查                                |  ✅  |                                              |
| GeoJSON 结构验证                            |  ✅  |                                              |
| 邻接兼容性检查                              |  ✅  |                                              |
| 最多 3 轮验证-重试（damping=0.2）           |  ✅  | 由 LAYOUT Agent ReAct 内循环实现             |
| 设施选址验证                                |  ✅  | `validation/facility_validator.py` (837行) |

**差距**: 无。8 项检查全部实现并测试覆盖。

### 2.9 EXPORT（GDB 输出） ❌

| 功能                                   | 状态 | 位置                                                                          |
| -------------------------------------- | :--: | ----------------------------------------------------------------------------- |
| GeoJSON 文件写出                       |  ✅  | `tools/gis/export.py`                                                       |
| 基础目录结构 (current/planned/tables/) |  ✅  |                                                                               |
| 用地平衡表 JSON                        |  ✅  | `_compute_land_balance()`                                                   |
| **12 层完整输出**                | ⚠️ | 当前输出 7/12 层（缺少 admin_line / historical / hazard / road / annotation） |
| **GDB 标准字段**                 | ⚠️ | 输出字段不完全匹配`gdb_schema.py` 定义                                      |
| **Excel 用地平衡表**             |  ❌  | 当前仅 JSON，需要`openpyxl` 输出标准表格                                    |
| **ArcGIS .gdb 格式**             |  ❌  | 当前仅 GeoJSON，需要 Arcpy 或 GDAL FileGDB driver                             |

**差距**: 这是当前最大的功能缺口。需要：

1. 补全 12 层输出（从 GIS data 中提取已有图层 + 生成缺失图层）
2. 对齐字段名到 `GDB_LAYER_REGISTRY` 定义
3. Excel 用地平衡表（模板参照金田村输出标准）

### 2.10 RENDER（前端渲染） ⚠️

| 功能                            | 状态 | 位置                                                                 |
| ------------------------------- | :--: | -------------------------------------------------------------------- |
| GeoJSON → GISLayerConfig 格式  |  ✅  | `tools/gis/render.py`                                              |
| GB/T 21010 配色注入             |  ✅  | `zone_schema/colors.py` + MapRenderer                              |
| 坐标精度压缩 (6 decimal)        |  ✅  | `reduce_coordinate_precision()`                                    |
| 属性白名单（减少 SSE payload）  |  ✅  | `PROPERTIES_WHITELIST`                                             |
| **MapLibre 样式规范注入** |  ❌  | 当前仅注入 feature-level color/stroke，缺少 sprite/glyphs 等样式层级 |

### 2.11 数据工具 ✅

| 工具                       | 位置                       |
| -------------------------- | -------------------------- |
| `fetch_gis_data`         | `tools/gis/data.py`      |
| `search_poi`             | `tools/gis/data.py`      |
| `calculate_gis_coverage` | `tools/gis/analytics.py` |
| `analyze_accessibility`  | `tools/gis/analytics.py` |

## 3. 与外部方案差距矩阵

| 功能维度     | 本项 | GenPlanner | BlocksNet | DRL-UP | 专利 | bxgis | 差距               |
| ------------ | :--: | :--------: | :-------: | :----: | :--: | :---: | ------------------ |
| MILP 分区    |  ✅  |     ✅     |    ❌    |   ❌   |  ❌  |  ❌  | —                 |
| 邻接约束     |  ✅  |     ✅     |    ❌    |   ❌   |  ❌  |  ❌  | —                 |
| KG + SPARQL  |  ✅  |     ❌     |    ❌    |   ❌   |  ❌  |  ❌  | **独有能力** |
| 冲突检测     |  ✅  |     ❌     |    ❌    |   ❌   |  ✅  |  ✅  | —                 |
| 12层输出     | ⚠️ |     ❌     |    ❌    |   ❌   |  ❌  |  ✅  | **最大差距** |
| 用地平衡表   | ⚠️ |     ❌     |    ✅    |   ❌   |  ✅  |  ✅  | 缺少 Excel         |
| 道路网络     |  ❌  |     ✅     |    ❌    |   ✅   |  ❌  |  ❌  | Phase 2            |
| Voronoi 细化 |  ❌  |     ✅     |    ❌    |   ❌   |  ❌  |  ❌  | Phase 2            |
| DRL 优化     |  ❌  |     ❌     |    ❌    |   ✅   |  ❌  |  ❌  | Phase 3            |
| 可达性分析   |  ✅  |     ❌     |    ✅    |   ❌   |  ❌  |  ❌  | —                 |
| GDB 原生格式 |  ❌  |     ❌     |    ❌    |   ❌   |  ❌  |  ✅  | 需 Arcpy           |

## 4. 测试覆盖

| 测试集                           |     状态     | 文件数                                   |
| -------------------------------- | :-----------: | ---------------------------------------- |
| 单元测试 (validator/geojson/MIP) |  ✅ 164 pass  | 8 文件                                   |
| E2E 测试 (金田村真实数据)        |  ⚠️ 待迁移  | 1 文件 (test_gis_e2e_real_data.py)       |
| Agent pipeline 测试              |   ⚠️ 部分   | 1 文件 (test_gis_agent_pipeline.py)      |
| 性能基准 (benchmark)             |  ⚠️ 待更新  | 1 文件 (benchmark_jintian_gis.py)        |
| 集成测试 (parsing↔GIS)          | ⚠️ LLM 依赖 | 1 文件 (test_parsing_gis_integration.py) |

**E2E 测试缺口原因**: `SpatialLayoutEngine` API 变更（从 layout/engine.py 842行 迁移到 gis/engine.py 140行精简版）。测试需要改为直接调用 pipeline tools。

## 5. 优先级路线图

### P0 — 本迭代

- [ ] **export**: 12 层完整输出 + 字段对齐 `gdb_schema.py`
- [ ] **export**: 用地平衡表 JSON（已有）→ 确认字段完整
- [ ] **test**: e2e 测试迁移到 pipeline tools（消除 72 个失败/错误）

### P1 — 下一迭代

- [ ] **export**: Excel 用地平衡表 (`openpyxl`)
- [ ] **allocate**: Voronoi 几何细化（参考 GenPlanner `features2terr_zones2blocks`）
- [ ] **generate**: 道路网络规划生成（参考 GenPlanner 的 road-based splitting）
- [ ] **data**: PostGIS 迁移（>1000 地块场景）

### P2 — 探索

- [ ] **allocate**: DRL 替代 MIP 的对比实验（参考清华 DRL-urban-planning）
- [ ] **generate**: GAN 村庄布局生成（参考 CGAN Rural Plan, FoAR 2025）
- [ ] **export**: ArcGIS .gdb 直接输出（需要 Arcpy 许可）
