# Exa 搜索发现 - 外部基准与架构评估

> **Status: Active** | **Type: External Reference**
> **Purpose**: 为系统设计决策提供外部可行性验证与架构评估基准
> **Sources**: exa web search + paper fetch，两部分共 ~380 sources reviewed

---

## Part 1: 文本到空间布局技术可行性（2026-07-23，30+ papers）

验证 3 个关键技术决策：原子操作范式、空间锚定、文本->空间布局主导范式。

### 1.1 搜索策略

| 搜索 | 查询方向 | 论文数 | 深度阅读 |
|---|---|---|---|
| 原子空间操作范式 | LLM 是否输出离散 create/split/merge 操作对 GIS 图层执行 | 10 | 0（无相关命中） |
| 空间锚定 | 自然语言地名 -> 具体 GIS 图斑的解析方法 | 10 | 1 |
| 文本到空间布局 | 2025-2026 年文本->空间布局的主导范式 | 10 | 3 |

### 1.2 发现 1：原子操作（create/split/merge）并非成熟范式

**结论：零命中。** 所有检索到的论文都是关于空间**查询**（NL2SQL），而非空间**编辑**。没有任何已发表系统描述过 LLM 输出离散的 create/split/merge 操作对 GIS 图层执行。这意味着我们的原子操作设计是**新颖的**--风险更高，但差异化也更大。

**设计影响**：原子操作应作为系统的**差异化能力**，而非行业标准。初期目标应优先使用已验证的 Plan-then-Execute 范式（MIP allocate + generate），原子操作作为增量编辑能力保留。

### 1.3 发现 2：主导范式是 "Plan-then-Execute"（意图 -> 优化）

6 个已发表系统均采用相同模式：LLM 从文本提取结构化意图，优化引擎执行空间布局。

| 系统 | 会议/年份 | 范式 | 引用 |
|---|---|---|---|
| **UrbanXplain** | SIGSPATIAL 2025 | 文本 -> LLM 分区命令 -> 结构化建筑规格 -> 3D 渲染。可解释推理 + 可追溯性 | [DOI](https://doi.org/10.1145/3748636.3762792) |
| **Text-to-3D City** | CAVW 2026 | Plan-then-Execute：LLM 规划器->结构化城市计划->PCG 执行器 | [DOI](https://doi.org/10.1002/cav.70124) |
| **Co-Layout** | AAAI 2026 | LLM 提取约束->基于网格的整数规划优化，粗到细 | [DOI](https://doi.org/10.1609/aaai.v40i17.38452) |
| **Intelli-Planner** | WWW 2026 | LLM + DRL：LLM 制定目标，RL 优化，多利益相关方评分 | [DOI](https://doi.org/10.1145/3774904.3793019) |
| **Lang2Plan** | 2026 | 多代理：NLP->规划->布局->验证->渲染，反馈循环 | [DOI](https://doi.org/10.1145/3774905.3793111) |
| **Prompt-to-Plan** | ICNWC 2026 | 多代理管线：NLP->规划->布局生成->验证->渲染 | [DOI](https://doi.org/10.1109/icnwc68145.2026.11518170) |

**设计影响**：PARSE（意图提取）+ MIP allocate（优化）+ generate（程序化合成）设计**完全符合** 2025-2026 SOTA，不需要范式转换。UrbanXplain 对"可解释推理/可追溯性"的强调与可解释汇交成果目标一致。

### 1.4 发现 3：空间锚定 - LLM 在推理上优于事实性知识

**"Coordinates from Context: Using LLMs to Ground Complex Location References"**（Masis & O'Connor, UMass Amherst, EACL 2026）

| 发现 | 详情 |
|---|---|
| LLM 弱点 | 在生成准确地理事实性知识（中心坐标）方面表现不佳 |
| LLM 优势 | 在给定事实性知识的情况下进行空间推理表现良好 |
| 混合方法 | 传统 gazetteer 提供候选坐标，LLM 在候选上推理 |
| 效率 | 微调小型 LLM 可达大型模型相当性能 |
| 表示 | 用 bounding box 链接位置，简单且信息丰富 |

**设计影响**：验证当前 Gazetteer + LLM 空间锚定策略。Gazetteer 层（确定性：天地图 + villages-ML -> 候选）+ LLM 推理层（语义：给定候选 + 约束排名），与 EACL 2026 混合方法一致。

### 1.5 相关项目

| 项目 | 描述 |
|---|---|
| PlanX-Settlement | 9 阶段参数化定居点规划管道（QGIS 插件）- 地块/建筑/停车/景观 |
| gisdataagent | Google ADK 驱动 GIS 数据智能体 - DRL 用地优化、WorldModel、NL2SQL 语义路由 |

### 1.6 设计决策总结

| 决策 | 结论 | 外部验证 |
|---|---|---|
| PARSE + MIP allocate 范式 | 坚守。Plan-then-Execute 是 SOTA | 6/6 论文确认 |
| 原子操作（create/split/merge） | 新颖，非标准。初期用于 create（项目落地），其余预留 | 无先例，属差异化 |
| 空间锚定（Gazetteer + LLM） | 坚守。混合方法正确 | EACL 2026 确认 |
| 可解释性/可追溯性 | 坚守。UrbanXplain 列为关键特征 | SIGSPATIAL 2025 确认 |
| 验证反馈循环 | 已有 VALIDATE Evaluator Gate | Prompt-to-Plan 验证代理 |

---

## Part 2: 架构评估四流研究（2026-07-24，~354 sources）

评估 Data/Schema/KG/PARSE 四层实现，对标外部系统。4 个 Exa 子代理并行研究，~354 sources reviewed。

### 2.1 搜索策略

| 流 | 方向 | sources | 评估对象 |
|---|---|---|---|
| 流 1 | 地理空间多源数据访问架构（QGIS/GDAL/Intake/STAC/ODC） | 90 | Data/Schema 分层 |
| 流 2 | 规划知识图谱（本体/RDF/GeoSPARQL/三层架构） | 60 | KG 三层设计 |
| 流 3 | 语义约束->数值优化编译（KG->MIP/CP/SAT） | 60 | ConstraintCompiler |
| 流 4 | 村庄/城市规划自动化系统 | 144 | PARSE/EXECUTE 对标 |

### 2.2 流 1：地理空间数据架构（对标 Data/Schema 分层）

| 系统 | URL | 架构模式 | 借鉴点 | 相关性 |
|---|---|---|---|---|
| **QGIS Data Provider** | https://deepwiki.com/qgis/QGIS/3.1-data-provider-architecture | 抽象 `QgsDataProvider` 基类，向量/栅格子类，URI 层次化，capabilities 查询 | Provider 抽象映射我们 Connection/Source 拆分；**`capabilities()` 应加入 DataResult/Source** | 高 |
| **GDAL/OGR Driver** | https://gdal.org/en/stable/tutorials/vector_driver_tut.html | `GDALDriverManager` 单例注册 + 每驱动 `GDALDriver` + `pfnOpen/Identify/Create` | 运行时驱动注册验证 DriverRegistry；驱动元数据标志等同编码分类 | 高 |
| **GeoServer Catalog** | https://github.com/geoserver/geoserver-cloud | 分层 Catalog/CatalogFacade/Repository，ValidationRules+BusinessRules 装饰器 | **验证"入口编码校验"**；可插拔后端存储对应 Schema/Data 分离 | 高 |
| **Intake** | https://intake.readthedocs.io/en/reader/catalog.html | YAML 目录 driver+args+metadata，Jinja2 模板参数，目录嵌套，direct_access 模式 | YAML 目录受其启发；**应加 Jinja2 模板化 + direct_access 模式** | 高 |
| **STAC** | https://stacspec.org/ | 描述地理空间资产的 JSON 规范（catalog/collection/item），pystac 生态 | 资产级元数据模式启发 DataResult.metadata；**应加 `to_stac()` 序列化器** | 高 |
| **ODC** | https://opendatacube.readthedocs.io/en/stable/about-core-concepts/architecture-guide.html | 索引 DB + 虚拟存储资源 VSR + BandDataSource 延迟加载到 xarray | VSR 对应 DataResult；**两阶段"先构建描述再加载"对应"先 Schema 注入再 Execute"** | 高 |
| **OGC API Features Schemas** | https://docs.ogc.org/is/23-058r2/23-058r2.html | 逻辑模式（格式无关）经 JSON Schema 机器可读，schema 端点 + 配置文件验证 | **逻辑模式 vs 格式特定表示分离直接验证 Schema/Data 分层** | 高 |
| **Geospatial-ETL** | https://www.geospatial-etl.com/mastering-geospatial-data-ingestion-in-python/ | 五阶段：发现->提取->转换->验证->加载，CRS 规范化在转换，Pydantic 验证门 | **"五阶段不可合并"强烈验证我们架构**；应加拓扑/CRS 质量门 | 高 |

**6 个关键发现**：
1. 我们的架构与行业标准一致但更雄心--无系统同时做 schema-first + YAML 目录 + driver/source + 编码校验四件
2. **应加显式 `capabilities` 系统**（QGIS `QgsDataProvider.capabilities()`）
3. 入口校验正确（Intake direct_access + GeoServer ValidationRules 验证）
4. **应丰富 `DataResult`**：加 `spatial_extent`/`crs` 为显式字段（ODC ParsedItem）
5. 应加 YAML Jinja2 模板化（参数化源定义）
6. STAC 互操作重要--应加 `to_stac()` 序列化器

### 2.3 流 2：规划知识图谱（对标 KG 三层设计）

| 项目/论文 | URL | KG 架构 | 借鉴点 | 相关性 |
|---|---|---|---|---|
| **OntoZoning** | https://doi.org/10.1016/j.jum.2023.02.002 | 单层 OWL 本体（6 类）+ Blazegraph，链接 CityGML | **直接示范 PARSE 写入**：use quantum(%) 作约束 EXECUTE 读；TBox/ABox 映射 L1/L3 | 高 |
| **OntoPlanningRegulations** | https://doi.org/10.5192/agile-giss-6-3-2025 | 两 OWL 本体（规则+3D 体量）+ Blazegraph，GeoSPARQL | **L2 蓝图**：预计算 corner plot/residential fringe/width/depth 为 RDFS 三元组 | 高 |
| **PolyRAG** | https://arxiv.org/abs/2407.21276 | 3 层金字塔：Ontology->KG->Raw text，瀑布检索 | **直接支持 3 层**：Ontology=L1, KG=L2, raw=L3；瀑布检索匹配 PARSE写/EXECUTE读 | 高 |
| **3-Layer MAS KG** | https://doi.org/10.1109/aaiml67890.2026.11498098 | 3 层：Reference KG->Observation KG->Evidence KG，LLM 构建 | Reference=L1, Observation=L2, Evidence=L3；LLM 构建类比 PARSE 写入 | 高 |
| **OLG++** | https://arxiv.org/abs/2507.05488 | 属性图 Neo4j，Location/Jurisdiction/Party/DeonticModality，空间约束一等边 | 空间/时间约束一等边（SPATIAL/PROXIMITY_TO/WITHIN）；EXCEPTION/OVERRIDE 映射 L3 | 高 |
| **LUAKG** | https://doi.org/10.3390/app15169012 | 双子图：General KB（政策）+ Review KB（项目规则），Neo4j，200+ 规则 | General=L1, Review=L2；overlay/time/adjacency 工具做合规检查=我们 EXECUTE 读 | 高 |
| **LSDTs** | https://arxiv.org/abs/2508.06799 | RDF+OWL，LLM 提取约束为可执行规则，Jena 前向链合规 | **PARSE 类比**：LLM 从文档提约束为 RDF 事实+规则；**EXECUTE 类比**：前向链评估候选设计 | 高 |
| **ISO 19144 (LCML/LUML)** | https://doi.org/10.3390/land13081202 | 3 部分：LCML/LUML/注册框架，描述符本体 | L1 本体设计：用地分解为原子描述符而非固定标签 | 高 |
| **Stock-KG** | https://doi.org/10.1117/12.3105856 | 类型化多图，PlanningBlock 中心，4 关系 WITHIN/OVERLAPS/ADJACENT/EVALUATES | **L2 空间关系**：4 显式关系类型直接用于邻接约束 | 中 |

**6 个关键发现**：
1. **TBox/ABox 分离是标准**：L1（静态本体+编码）=TBox，L3（易失意图）=ABox
2. **预计算空间关系为独立 L2 层**有先例（OntoPlanningRegulations 预计算 corner plot/width/depth）
3. 3 层架构独立被 PolyRAG/3-layer MAS/公共卫生语义框架验证
4. **邻接/空间约束作为一等边**（Stock-KG, OLG++）验证我们 14 关系类型
5. 约束为可执行规则（LSDTs/OLG++/LUAKG）验证 PARSE写/EXECUTE读管道
6. **Gap：无人把"易失规划意图"作为独立一层**--我们 3 层是新颖贡献

### 2.4 流 3：语义->优化编译（对标 ConstraintCompiler）

| 论文/方法 | URL | 桥接方法 | 借鉴点 | 相关性 |
|---|---|---|---|---|
| **RLP (Relational LP)** | https://doi.org/10.1016/j.artint.2015.06.009 | LogKB（逻辑事实+规则）+ RLP 模板 -> ground LP via 有限 answer-set | Schema=LogKB 纯语义，Data=ground LP 纯数值；**grounding 函数即编译器**，有限且产生有效 LP | 高 |
| **Graph-Grounded Optimization** | https://arxiv.org/abs/2605.12204 | 属性 KG via Cypher 查询 -> 决策变量/约束/目标系数，预物化 vs 每次查询 | Cypher 查询模板定义优化模型结构；**预物化模式**对大而静的 KG 关键 | 高 |
| **Stapel (ontology->AML)** | http://nbn-resolving.de/urn:nbn:de:hbz:466:2-24946 | OWL 本体类 + 派生 -> AML 语句 -> solver，三层 | 本体类定义可复用约束公式类型；AML grounding 替换个体为具体数 | 高 |
| **Scimitar** | https://doi.org/10.1145/3689492.3690051 | 函数式语言 minimize -> 编译器分离 host/solver 语义 -> 标准形 MILP | **归一化管道（重写->展平->标准形）是我们 grounding 管道的直接模板** | 高 |
| **Ontology-to-tools** | https://arxiv.org/abs/2602.03439 | OWL T-Box 公理 -> 编译 MCP 工具接口 -> LLM 用工具强制约束 | **硬约束（形式 T-Box）vs 软约束（注解派生）**=我们保护地块硬锁 vs 面积目标软约束 | 高 |
| **MILP Model Ontology** | https://arxiv.org/abs/2011.06300 | OWL 本体 of MILP 构造（Objective/Constraint LHS/RHS）+ 约束类型树 | **约束类型学（bound/balancing/set covering/logic）直接映射我们约束模板库** | 高 |
| **PSOLA** | https://doi.org/10.1371/journal.pone.0157728 | 知识规则（适宜性/可达性/政策/偏好）+ patch 操作 -> PSO 转移概率 | 规则层与优化算法分离；规则调制转移概率=我们 MIP 约束生成 | 高 |
| **MICE** | https://arxiv.org/abs/1611.08908 | 高级 CP 约束 -> 分解为线性约束 via lemma -> MILP | **线性化 lemma（Deviation/InterDistance/reified）可直接复用为约束编译模板** | 高 |

**5 个关键发现**：
1. **3 层共识**：Schema（本体/KG）-> IR（模板/原型）-> Data（ground 数值模型）（Stapel/RLP/CIR 收敛）
2. **grounding 函数即编译器**：必须有限、产生有效数学规划（RLP answer-set/Cypher/Scimitar 归一化）
3. **约束类型学是可复用资产**（Ofoghi MILP 本体：bound/balancing/set covering/logic）-> 我们模板库
4. **硬 vs 软约束**：T-Box 公理（保护地块硬锁）vs 注解派生（面积目标软约束）完美映射
5. 数据质量浮现：直接查 KG 会暴露缺失属性，文本方法会静默掩盖

### 2.5 流 4：村庄规划自动化系统（对标 PARSE/EXECUTE）

| 系统/论文 | URL | 功能 | 借鉴点 | 相关性 |
|---|---|---|---|---|
| **UrbanXplain** | https://doi.org/10.1145/3748636.3762792 | NL->LLM 分区命令->建筑功能分配->布局+约束 | **直接架构平行**：NL->结构化意图(PARSE)再空间布局(EXECUTE)；可解释推理 | 高 |
| **MapAgent** | https://aclanthology.org/2026.findings-eacl.67/ | 分层多代理地理推理：高层规划器分解->专门 map-tool 代理 | **规划与执行解耦**="高层规划器+专门模块"正是我们 PARSE/EXECUTE | 高 |
| **LLM Participatory Urban Planning** | https://doi.org/10.48550/arxiv.2402.01698 | LLM 代理社区级用地，角色扮演+协作生成+反馈迭代 | 验证 LLM 代理可产出与 RL 相当的用地规划；4 评估指标 | 高 |
| **GeoSage (地智通)** | https://gx.cnr.cn/cnrgx/zongtaiguanzhu/20250813/t20250813_527316883.shtml | MoE 大模型(800GB 知识库)自动生成"一图一表一则一库一说明"+12 指标图 | **最近中文产线对标**；"感知-分析-决策-输出-校验"闭环=我们 PARSE/EXECUTE | 高 |
| **RP-MCE-SOP** | https://www.mdpi.com/2071-1050/11/11/2997 | 理性规划+多准则评价+空间优化(NSGA-II)做县级三区三线 | NSGA-II（非 MIP）但五步框架是 EXECUTE 参考 | 高 |
| **zoning-extraction-pipelines** | https://github.com/JoT8ng/zoning-extraction-pipelines | Claude API 从规章 PDF 提结构化分区数据->CSV+GeoJSON | **直接 PARSE 类比**：非结构化规划文本->结构化 GIS-ready 数据 | 高 |
| **LLM Building Code Compliance** | https://mediatum.ub.ub.tum.de/1840853 | ReAct LLM 代理推理规章文本，增量探索 IFC 模型合规 | ReAct 用于空间规章；"证据驱动推理"=我们执行期约束满足 | 中 |
| **ArcGIS CityEngine** | https://www.esri.com/en-us/arcgis/products/arcgis-cityengine/overview | CGA 形状语法程序化 3D 城市生成，GIS 集成，分区合规可视化 | CGA 规则编码分区约束（高度/退缩）；FAR 自动算；GIS 原生输出 | 中 |
| **MPMAS** | https://www.uni-hohenheim.de/fileadmin/einrichtungen/mp-mas/Manual.pdf | MILP 用地变化模拟（农业林业），农场经济+生物物理 | **直接 MILP 空间用地分配**，7+ 国家实证 | 中 |

**5 个关键发现**：
1. **UrbanXplain 是最接近系统**：NL->结构化分区命令->空间布局，验证 PARSE/EXECUTE 解耦
2. **无系统完全组合三件**（LLM 文本解析 + MIP 空间分配 + GIS-ready 输出）做村庄规划
3. PARSE/EXECUTE 分离有两个验证先例：MapAgent（分层规划器/专门代理）+ UrbanXplain（NL->分区命令再布局）
4. MIP 用地分配学术成熟（MPMAS/RP-MCE-SOP）但未与 LLM 意图解析集成
5. 文本->GIS-ready 结构化数据被 zoning-extraction-pipelines 验证（Claude API->CSV+GeoJSON）

### 2.6 跨流收敛结论

| 维度 | 外部收敛 | 对我们印证 |
|---|---|---|
| Data/Schema 分层 | 无系统同时做四件事；QGIS/GDAL/Intake/STAC/ODC 各做 1-2 件 | 方向正确且更完整，但缺 capabilities/to_stac/YAML 模板/显式 CRS |
| 3 层 KG | TBox/ABox 标准；预计算空间关系独立层有先例；**无人把易失意图独立成层** | L1/L2/L3 是有效贡献，但实现未对齐设计 |
| 语义->数值编译 | 三层共识 Schema->IR->Data；grounding 即编译器 | ConstraintCompiler 符合主流，但**尚未实现** |
| 村庄规划自动化 | UrbanXplain/MapAgent 验证 PARSE/EXECUTE；GeoSage 最近中文对标；**无人组合 LLM+MIP+GIS 汇交** | 差异化定位成立 |

### 2.7 评估结论：实现与设计的鸿沟

设计文档（00_SYSTEM_DESIGN）在国内村庄规划领域领先，问题不在设计，而在**实现与设计的鸿沟**：

| 层 | 鸿沟 | 严重度 |
|---|---|---|
| **Data** | 新 `modules/data/`（DataCatalog+ingest+类型化 bundle）**不在生产路径**；运行时走旧 `gis/data/fetcher.py`+raw dict；三套并行抽象未消除 | 🔴 |
| **Schema** | 已提升到 `modules/schema/`，但 `gis/schema/` 兼容 shim 不存在；7 个新空间类型缺失；文档路径漂移 | 🟡/🔴 |
| **KG** | 违反"类型化模型唯一"契约：`KGInputParcels.from_geojson()`/`add_*(gis_data:Dict)` 收 raw dict；**无 ConstraintCompiler**；读 API 大半缺失；KG 实为"写完即拍平"的 side computation | 🔴 |
| **PARSE** | 结构良好（Think-Format+3 工具+Pydantic），但 `compute_spatial_context(gis_data:Dict)` 收 raw dict；PARSE->KG 经单体 `build_from_intent` 而非粒度写 API；SpatialContext 被困 legacy 文件 | 🟡 |

### 2.8 优化路线（对标外部基准）

| 优先级 | 任务 | 对标 | 验收 |
|---|---|---|---|
| P0 | DataCatalog 上生产 + 删 raw dict 路径 + gis/schema shim + 合并注册表 | Geospatial-ETL 五阶段 | `load_village_bundle` 被 gis_context 调用 |
| P0 | KG 类型化摄入（`build_from_bundle`/`add_parcels`/`add_protection_zones`）+ 删 `from_geojson` | OntoZoning TBox/ABox | KG 签名拒绝 dict |
| P1 | 新建 `kg/constraint_compiler.py` 替代 `tools/gis/kg.py` 拍平 + 补读 API | RLP/Graph-Grounded/Scimitar | MIP 从 MIPModel 取约束 |
| P1 | 7 个新空间类型 + AdminArea 扩展 + ingest registry | 计划 §4.1 | P1 数据集可类型化入库 |
| P1 | `compute_spatial_context(bundle)` + SpatialContext 迁 parse_contracts + 粒度写 API | UrbanXplain/MapAgent | PARSE 输入输出全类型化 |
| P2 | GeoPackage driver + YAML 模板 + `to_stac()` + capabilities() + DataResult 显式字段 | QGIS/Intake/STAC/ODC | sources.yaml 可参数化 |
| P2 | 保护/规划/自然要素类型化入 KG（计划 Phase 1） | OLG++/Stock-KG | KG 入库率 4/29->15+/29 |

**核心判断**：P0 全是"接线/去重/补 shim"，不新增抽象。最大风险不是设计不够，而是新 Data 层和 KG 类型化契约没切入运行时。
