# Layer Architecture Research — 2026-07-25

> Exa research validating "Layer as organizing principle + typed features inside" architecture.
> 3 subagents, 305 sources reviewed (125 + 105 + 75).

## 1. GIS 软件 / 空间数据库图层架构 (125 sources)

| Project/System | Layer design key point | Layer-Feature relationship | Cross-layer operation | Relevance | URL |
|---|---|---|---|---|---|
| QGIS (QgsLayerTree) | 树形: Group(容器)+Layer(叶节点指向 QgsMapLayer); 信号向上传播 | Layer 是 typed features 容器; QgsVectorLayer 持有 DataProvider+typed fields | Processing Framework (overlay/intersect/buffer) layer-in/layer-out | High | https://qgis.org/pyqgis/master/core/QgsLayerTreeNode.html |
| QGIS (QgsProject) | Singleton 持有 ID-keyed hash table + LayerTree; addMapLayer 校验 provider+缓存 CRS/extent | 三重存储: ID hash + layer tree + CRS/extent cache | 批量 addMapLayers 单次刷新; 实时 reprojection | High | https://www.pyqgis-engineering.org/pyqgis-core-architecture-data-handling/working-with-qgsproject-and-layer-registry/ |
| ArcGIS / ArcSDE | DBMS 中一个 geometry column = 一个 LAYER; LAYERS 表一行一空间列 (owner/table/col/CRS/type/index) | Layer=空间列; FeatureClass=表+空间列; Feature=行 | Overlay Layers tool (Intersect/Union/Erase), 维度感知输出 | High | https://help.arcgis.com/en/geodatabase/10.0/sdk/arcsde/concepts/geometry/dbschema/dbschema.htm |
| GeoPackage (OGC) | gpkg_contents (data_type="features") + gpkg_geometry_columns (geom col/type/SRID) | Layer=feature table; Feature=row; 几何类型列级约束 | SQL 空间连接 (ST_Intersects), 或 OGR/GDAL pipeline | Med | https://github.com/opengeospatial/geopackage/blob/master/spec/core/2a_features.adoc |
| PostGIS | geometry_columns 视图 (table/schema/col/srid/type/dim); 每个带几何列的表即 layer | Layer=带几何列的表; type modifier `geom geometry(POINT,4326)` 列级强制类型+SRID | SQL ST_Intersects/ST_Union/ST_Intersection 跨表; GDAL 每表视作 layer | High | https://postgis.net/docs/using_postgis_dbmanagement.html |
| GeoTools | 模块化: gt-api(接口)+gt-main(Feature/Filter)+gt-data(DataStore/FeatureSource); MapContent 持有序 Layer 列表 | DataStore=物理源; FeatureSource=读访问; FeatureCollection=typed Feature 可迭代集; FeatureLayer 包装 FeatureSource | Query+Filter (OGC) 空间过滤; FeatureStore 写+事务 | High | https://docs.geotools.org/stable/userguide/welcome/architecture.html |
| GeoServer | Catalog: Workspace->Store->Resource(FeatureType/Coverage)->Layer; Layer 是**发布**单位 | Layer 发布 Resource (FeatureType 属性/类型); 元数据: name/title/abstract/keywords/CRS/bbox/style/CQL | WMS GetMap 多图层; SLD 样式; WFS 要素级; Layer groups | High | https://docs.geoserver.org/main/en/user/data/webadmin/layers/ |
| OGC Abstract Spec (Topic 5) | 九层模型: Real World->...->Feature World; Feature 为基本单元; Feature Collection 分组 | Feature=现实实体抽象(几何+属性+身份); Feature Type=schema; Feature Collection=可查询集 | Feature Collections 支持查询; 持久 Feature 标识符跨集合解析 | Med | https://docs.ogc.org/as/08-126/08-126.pdf |
| GDAL/OGR | ogr2ogr pipeline; Dataset=layer 集合; 每层有 schema (字段定义+几何类型) | Layer=表/命名实体; Feature=行; 支持多几何列 | gdal_vector_pipeline 链式; SQL 方言空间过滤 | Med | https://gdal.org/en/latest/programs/gdal_vector_pipeline.html |

**Key findings**: (1) Layer-Feature 普遍是"typed features 容器"; (2) 图层树形组织; (3) 跨图层运算 layer-in/layer-out; (4) 图层元数据标准化 (CRS/几何类型/字段/bbox); (5) 图层贯穿输入->分析->输出->渲染。

## 2. 类型化与图层共存工程实践 (105 sources)

| Framework/Practice | Typing approach | How layer is preserved | Dynamic/unknown layer | Similarity | URL |
|---|---|---|---|---|---|
| Overture Maps Schema | Pydantic `OvertureFeature[ThemeT, TypeT]` 泛型; GeometryTypeConstraint; @no_extra_fields | `theme` 显式"analogous to layer"; S3 按 theme/type 分区 | `ext` 前缀用户扩展; setuptools entry points 发现; JSON Schema 兜底 | High | https://github.com/OvertureMaps/schema/blob/main/SCHEMA_CONVENTIONS.md |
| geojson-pydantic | `Feature[GeometryType, PropertiesType]` Pydantic Generic; FeatureCollection typed wrapper | FeatureCollection 是 layer 容器; iter/length 方法 | 默认 `Feature[Geometry, Dict]` 无类型兜底; type-discriminated Geometry union | High | https://developmentseed.org/geojson-pydantic/intro/ |
| GeoPandas GeoDataFrame | 列式 typing (pandas dtypes); 单活动几何列 (GeoSeries) | GeoDataFrame IS the layer; 空间方法作用于活动几何列 | Schema-on-read; 纯列式无 feature 级 schema | Med | https://docs.geopandas.org/en/stable/docs/user_guide/data_structures.html |
| OGC API Features Part 3 | JSON Schema per collection; 逻辑 schema 独立于格式 | Collection=layer; `/collections/{id}`; 同 collection 共享 schema | Schema-on-read; 逻辑 schema 发布在 collection 级 | Med | https://docs.ogc.org/is/23-058r2/23-058r2.html |
| pygeoapi | 插件式; BaseProvider 契约; formatter 插件 | Provider=layer; 插件注册表映射 | 配置驱动动态加载; 外部插件包 | Med | https://docs.pygeoapi.io/en/stable/plugins.html |
| pynspd (Russian NSPD) | 自动生成 per-layer Pydantic 类 (codegen); `BaseFeature[Geometry, Properties]` | layer ID 嵌入类名 (`Layer37578Feature`); `layer_meta: LayerNode` 嵌入每个 feature 类 | `by_title()` 返回无类型 NspdFeature; `.cast()` 自动检测/手动指定 | High | https://github.com/yazmolod/pynspd/blob/main/scripts/autogeneration.py |
| PostGIS+FastAPI+Pydantic | Pydantic v2 几何 validator (入口); PostGIS 几何列 (存储); CRS 边界规范化 | Layer=PostGIS 表+几何列; GIST 索引 | 单几何列处理所有类型; JSONB 灵活属性; API 边界校验 | Med | https://www.geospatial-api.com/core-geospatial-api-architecture-with-fastapi-postgis/ |
| datamodel-code-generator | 运行时 Pydantic 模型生成 (JSON Schema/OpenAPI) | 非原生 layer; per-schema 非 per-layer | 动态模型生成+缓存; 支持循环引用/嵌套 | Med | https://datamodel-code-generator.koxudaxi.dev/dynamic-model-generation/ |
| django-ninja-spatial | Pydantic GeoJSON schemas (PointField/PolygonField); type-discriminated Geometry union | Layer=Django model+GeoDjango field; ModelSchema 自省几何列 | GeometryField 接受任何类型; typed fields 拒绝错类型 | Med | https://pypi.org/project/django-ninja-spatial/0.9.0/ |

**Key findings**: (1) **两级类型系统**--泛型基类参数化 (layer_id, geometry_type, properties_type), layer 编码为类型参数或嵌入元数据, 不被消解; (2) **优雅降级**--默认无类型模式 (`Feature[Geometry, Dict]`) 接受任何数据, 可选 .cast()/显式参数化; (3) **Overture Maps** 是最接近的工业级参考 (theme=layer + Pydantic 泛型 + GeometryTypeConstraint + ext 扩展), 选 Pydantic 而非 JSON Schema 验证我们的方向; (4) **pynspd** 把 layer_meta 嵌入每个 feature 类, 是动态图层最强方案; (5) 统一 GeoJSON vs per-type 表是 extensibility vs strict typing 的权衡, 我们的"图层容器+内部 typed features"是中间路径。

## 3. 国土空间规划图层分层标准 (75 sources)

| Standard/Spec | Layer stratification | Current/planned separation | Encoding-to-layer | Corroboration | URL |
|---|---|---|---|---|---|
| 市级国土空间总体规划数据库规范 (自然资办发〔2021〕31号) | 基础地理(100)+分析评价(208)+国土空间规划信息(209); 必选: 行政区/生态保护重要性/基期现状用地/三条控制线/主体功能分区 | **严格分离**: 209001=基期年现状, 209002=目标年规划 (顶层划分) | 10位层次码: 专业(2)+业务(2)+类(6); DLBM/GHFLBM 属性字段 | High | https://www.fqghj.net/show.aspx?nid=5796&tid=163 |
| DB14/T 2979-2024 村庄规划数据库规范 (山西) | 村域+村庄域; 村级行政区/控制线/现状用地/目标年规划用地/规划分区/规划栅格; 必选 CZJSBJ | **严格分离**: 209001(含 XZYD 现状用地) vs 209002(含 GHDLTB 规划地类图斑); 两套属性表 | 2090010100=现状用地, 2090020610=村域规划分区 | High | https://www.ndls.org.cn/standard/detail/ea503c5a77aa9ac0fc749d933728b42a |
| 云南省多规合一村庄规划数据库标准 (2021) | 基础地理+空间规划; 行政区/基期现状用地/永久基本农田/生态红线/村庄建设边界/规划地类图斑/规划设施; GDB 必选 | **严格分离**: 209001(含 2090010100 基期现状用地) vs 209002(含 2090020210 规划地类图斑) | 10位码同国标; JQXZYD vs GHDLTB | High | https://dnr.yn.gov.cn/uploadfile/s58/2024/1107/20241107030813898.pdf |
| 广东省村庄规划数据库建设要求 (2019) | 四核心层: GHCFW/QMDLTB/TDYT/JSYDGZQ; GDB+CGCS2000+3度高斯-克吕格 | **隐式分离**: QMDLTB 同层混 DLBM(现状)+QMDLBM(期末)+GHFLBM+GHYTBM (过渡例外) | 多编码字段同表; 10位码 | Medium | https://www.docin.com/p-2395334185.html |
| 贵州省村庄规划成果汇交要求 (2023修订) | 村级行政区/现状建设用地/永久基本农田/生态红线/城镇边界/村庄建设边界/村庄建设用地调整/宅基地/规划设施/规划用地布局/管控类 | **分离**: 现状建设用地 vs 规划用地布局; 村庄建设用地调整层处理过渡 | 标准码; 调整代码/管控要求代码 | High | https://www.2b34.com/blog/183836.html |
| GB/T 21010-2017 土地利用现状分类 | 12一级73二级; 三调基准; 非图层标准, 编码被引用 | N/A (分类标准) | 2级数字码: 0101=水田 | Medium | https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=224BF9DA69F053DA22AC758AAAADEEAA |
| 自然资发〔2023〕234号 用地用海分类指南 | 统一 survey/planning/use-control 分类; 24一级113二级140三级; 替代旧 GB 50137+GB/T 21010 | **统一分类**: survey 和 planning 用同一编码, 靠 context (209001/209002) 区分 | 3级码: 0701=城镇住宅用地; 附录B 城镇村工矿 | High | https://www.guoturen.com/wenku-11572.html |
| 省级国土空间规划数据库标准 (试行) | 基础地理(100)+分析评价(208)+空间规划(209); 双评价/基期现状/三线/主导功能/综合交通/防灾/能源/整治 | **严格分离**: 209001(基期现状) vs 209002(三线/开发保护/支撑/整治) | 同10位码; GHJQN/GHMBN 元数据 | High | https://www.doczj.com/doc/1a5389196.html |
| DB22/T 3407-2022 村庄规划数据库建设规范 (吉林) | 基础地理+国土空间规划; 现状地类图斑/三区划定/村庄建设边界/规划地类图斑/基础设施/整治/近期项目 | **分离**: 现状地类图斑(XZDLTB) vs 规划地类图斑(GHDLTB) 独立属性表 | 10位码; GHDLTB 用规划用地分类 | High | https://ndls.cnis.ac.cn/standard/detail/02203191831716bfe3ea1d60912fcde2 |
| DB3713/T 289-2023 市县级一张图平台数据库规范 (临沂) | 显式分 现状类要素 vs 规划类要素; 现状: 行政区/地形/路网/地类图斑/用途区/耕地后备; 规划: 规划地类图斑/三区三线/设施/重大工程 | **显式分离**: 表A.1 现状类空间要素分层表 独立于规划层 | 标准码; 三区三线为规划级引用层 | High | https://www.bzchaxun.com/view/6232000013000000.html |
| DB14/T 3433-2025 国土空间专项规划数据库规范 (山西) | 基础地理+现状空间+规划空间+非空间; 专题: 现状分布/项目建设/空间开发/保护控制/整理整治/风险识别/规划实体 | **分离**: 现状空间要素 vs 规划空间要素 顶层类别; GHJQN/GHMBN 元数据 | 标准码; 通用要素+专题要素(LXDM) | High | https://max.book118.com/html/2026/0714/8016034065010110.shtm |

**Key findings**: (1) **必选核心层**: GHCFW/QMDLTB/TDYT/JSYDGZQ; (2) **三区三线是引用层** (中央审批成果, 村庄级不重新创建); (3) **用地用海分类** (自然资发234号) 统一了 survey/planning 编码; (4) **现状/规划分离是强制**: 每个国家/省级标准都严格分 209001(基期现状) vs 209002(目标年规划), 广东 QMDLTB 混合是过渡例外非规范; (5) **10位层次码** (专业+业务+分类) 通用。

## 4. 三方汇聚：对当前设计的验证与补充

### 验证 (设计方向正确)
1. **图层为容器 + 要素强类型化** = QGIS/ArcGIS/PostGIS/GeoServer/GeoTools 通用模式 (subagent 1)
2. **现状/规划分离** = 国家标准强制 (209001/209002 顶层划分) (subagent 2) — 我们的 `current_landuse`/`planned_landuse` 分离是 mandated, 非可选
3. **两级类型系统保留图层** = Overture/pynspd/geojson-pydantic 工业实践 (subagent 3) — 我们的 layer_type+几何基类+语义子类与之对齐

### 可补充 (基于 Exa 发现)
1. **GISMetadata 加 layer_tree 字段** — QGIS/GeoServer 都有图层树; 列出所有图层 (核心+extra) 的 name/source/geometry_kind/feature_count, 让分析工具"发现"图层而非硬编码
2. **layer 身份嵌入 feature** — pynspd 把 layer_meta 嵌入每个 feature 类; 我们的 SpatialFeature 可加 `layer_type: str` 字段, 确保 feature 不脱离图层身份
3. **三区三线标注引用层** — Exa 确认三区三线是中央审批成果引用层, 村庄级不重新创建; layer_registry 的 farmland_protection/ecological_protection/urban_dev_boundary 标注 `is_reference_layer=True`
4. **动态图层优雅降级路径** — geojson-pydantic `Feature[Geometry, Dict]` 默认无类型 + .cast(); 我们的 ingest_inference 应明确"完全未知"时降级到继承 Point/Line/PolygonFeature + 保留 raw properties dict
5. **FeatureCollection 抽象统一图层访问** — geojson-pydantic 用 FeatureCollection 作 layer 容器; 我们可加 `bundle.get_layer(layer_type)` 统一核心字段与 extra_layers 访问
6. **ysdm 前缀区分现状/规划** — 209001/209002 是国标前缀; SpatialFeature.ysdm 可用前缀作现状/规划分离的元数据级保障
