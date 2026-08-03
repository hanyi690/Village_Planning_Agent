# 各 Provider 实际数据能力汇总（基于金田村实测）

> 测试环境：梅州市平远县泗水镇金田村 (bbox 116.00,24.77 ~ 116.10,24.87)
> 实测日期：2026-08-01
> 测试脚本：`backend/scripts/test_*_jintian.py`

---

## 总览表

| Provider | 数据维度 | 真实命中 | 本村内命中 | Bundle 注入 | 坐标系 | 备注 |
|----------|---------|---------|-----------|-----------|--------|------|
| **本地 annotation.geojson** | 村名/设施 | 34 | 34 | 34 (local) | WGS84 | **地基** |
| **本地 landuse.parcels** | 地块 | 660 | 660 | 660 (local) | WGS84 | **地基** |
| **本地 roads_current** | 道路 | 131 | 131 | 131 (local) | WGS84 | **地基** |
| **本地 water_bodies (DLBM=31xx)** | 水域 | 48 | 48 | 48 (local) | WGS84 | **地基** |
| **AMap (高德)** | 设施+道路名+水库 | ≥40 | 9 POI | **19 注入** | GCJ02→WGS84 | ✅ |
| **百度 (Baidu)** | 设施+设施+水库+路 | ~80 | 11 POI | **0 注入** | BD09 | ⚠️ 需查 AK |
| **腾讯 (Tencent)** | 行政村+自然村 | ~30+ | 12 POI | **0 注入** | GCJ02→WGS84 | ✅ |
| **天地图 WFS HYDA/HYDL/LRDL** | 水系面/线/公路 | 15 | 15 | **13 注入** | ≈WGS84 | ✅ |
| **OSM Overpass** | (无数据) | **0** | 0 | 0 | WGS84 | ❌ 中国乡村 0 覆盖 |

---

## 1. AMap (高德地图)

### 实际能力
- **API 端点**: `v3/place/text`, `v3/place/around`, `v3/place/bytype`, `v3/geocode/geo`
- **坐标系**: **GCJ02 (火星坐标系)** — provider 内部 `gcj02_to_wgs84` 调用**实测无效**，需 pipeline Stage 2 显式归一化
- **覆盖类型**:
  - 设施 POI (学校/医院/公交/政府机构): typecode 141200/090100/150700/130106
  - 道路交叉口名: typecode 190000
  - 周边"村"搜索: keyword="村"
  - 水库名: keyword="水库"

### 实测数据 (金田村 bbox, radius=8000m)
| 类别 | 样本 | 数量 |
|------|------|------|
| 行政村 (12) | 大畲/梅畲/上丰/木联/符坑/文贵/上举/白岭/成文/大新/灵水/泗水 | 12 |
| 学校 | 泗水镇中心幼儿园/上举中心小学/东石实验幼儿园 | 3 |
| 医院 | 平远县泗水卫生院/平远县上举卫生院 | 2 |
| 公交站 | 泗水小学站/大畲坳站/白岭村站 | 4 |
| 道路交叉口 | 038县道与123乡道交叉口/122乡道与124乡道交叉口/石牙背 | 25 |
| 水库 | 长潭水库/刁坑水库等 (但**实测跨县错配**到丰顺县) | 3 |

### 关键限制
- **citylimit 失效**: 12 个自然村搜索，9/12 跨县错配（搜"田坑"返回"广东省梅州市大埔县田坑"，非本村）
- **geocode 返回乡镇中心**: 不是真实自然村位置（如 "金田村委会" geocode 实际返 24.7527, 116.0244 是泗水镇中心）

---

## 2. 百度 (Baidu Maps)

### 实际能力
- **API 端点**: `place/v3/region` (区县级 + region_limit), `place/v2/search`, `geocoding/v3`
- **坐标系**: **BD09 (百度坐标系)** — 设置 `coord_type=1` 后**实测仍偏差 1000m+**（百度 geocoding 返回的是 "中心点" 而非真实位置）
- **覆盖类型**: 行政区划+POI+地理编码
- **核心优势**: `address` 字段**最精准**（含"泗水镇"、"广东省梅州市平远县"），是 4 个 provider 中防误连判断的**唯一可靠**字段

### 实测数据 (新 key: `vzBUZIivOA6SoB9yxEhj07GnJ2VkwJpG`)
| 类别 | 实测样本 | 数量 |
|------|---------|------|
| 行政村 (query=村, region_limit) | 角坑村/黄畲村/热水村/古丁村/邹坊村 等 | 20 (total=131) |
| 学校 | 平远中学/八尺中学/特殊教育学校 等 | 20 |
| 医院 | 平远县热柘镇卫生院/河头镇卫生院 等 | 19 |
| 公交站 | 平远老车站/汽车总站 等 | 20 |
| 水库 | 富石水库/锅叾水库/刁坑水库 等 | 20 |
| 道路 | 松柏塘路/官汕一路/平城北路 | 20 |
| 4 邻村 | 八社/符坑/文贵 真实本村内 | 3/4 (上举跨镇) |
| 12 自然村 × region search | 11/12 命中，**0 个本村内** | 跨县错配 |

### 关键限制
- **自然村搜索不可信**: 11/12 hit 全部跨县
- **坐标精度低**: geocode 返回"中心点"，偏差 1000m+
- **Bundle 注入为 0**: 需要进一步排查（疑似 signature/timestamp 问题）

---

## 3. 腾讯 (Tencent Maps)

### 实际能力
- **API 端点**: `ws/place/v1/search` (新), `ws/geocoder/v1`
- **坐标系**: **GCJ02** — 设置 `coord_type=wgs84` 后**实测偏差 400-1900m**（搜索结果与文档不符，需在 pipeline Stage 2 显式转换）
- **核心参数**: `keyword` + `boundary` (格式 `region(adcode,0)` 或 `nearby(lat,lng,radius,1)`)
- **覆盖类型**: 行政区划+自然村+设施

### 实测数据 (新 key: `7NMBZ-TX4L7-QFHXG-HLJGK-K5OGO-JQBDL`)
| 类别 | 实测样本 | 数量 |
|------|---------|------|
| 行政村 (query=村) | 东兴村/梅东村/儒地村/下丰村/小柘村 等 | 20 |
| 12 自然村 × region search | 10/12 命中 | **5/12 本村内 (园寨 0.6km/清明 3.3km/长塘 2.7km + 田坑/分水)** |
| 4 邻村 | 八社/符坑/文贵 真实本村内 | 3/4 |
| 学校 | 泗水镇泗水中学/广福学校/桂岭学校/铁民中学 | 20+ |
| 设施 | 综合 | 60+ |

### 关键优势
- **唯一能拿金田本村内自然村坐标的源**: 5/12 本村内（vs 百度 0/12, 高德 0/12）

### 关键限制
- **`region` 参数**: 必须用 12 位 township code `441426110000` 才能精确到镇
- **周边搜索半径上限 1000m**（不是 5000m）

---

## 4. 天地图 (Tianditu) WFS

### 实际能力
- **API 端点**: `https://gisserver.tianditu.gov.cn/TDTService/wfs`
- **坐标系**: **CGCS2000 ≈ WGS84** (实测偏差 4-8m，可忽略)
- **核心图层** (1:100万国家级矢量):
  - `TDTService:HYDA` 水系面 (Polygon)
  - `TDTService:HYDL` 水系线 (LineString)
  - `TDTService:LRDL` 公路 (LineString)
  - `TDTService:LRRL` 铁路 (LineString)
  - `TDTService:RESA` 居民地面 (Polygon)
  - `TDTService:RESP` 居民地点 (Point)

### 实测数据 (金田村 bbox)
| 图层 | 名称 | 数量 | 含名字 |
|------|------|------|--------|
| HYDA | 长潭水库 | **1** | ✅ "长潭水库" |
| HYDL | 中山河 + 其他 | **7** | ✅ "中山河" 等 |
| LRDL | Y161 铁坑-西山 等 | **7** | ✅ "Y161 铁坑-西山" |
| LRRL | (无铁路) | **0** | — |
| RESA | (1:100万无村级) | **0** | ❌ |
| RESP | (1:100万无村级) | **0** | ❌ |

### Bundle 注入
- `water_bodies`: +1 (天地图 HYDA 长潭水库) → 共 49
- `roads_current`: +12 (天地图 LRDL) → 共 143

### 关键优势
- **几何权威性最高**（国家级矢量，含精确边界）
- **含名字字段** (NAME)
- **坐标系无需转换** (CGCS2000 ≈ WGS84)

### 关键限制
- **1:100万比例尺无村级** (RESP/RESA 为空)
- **bbox 必须 ≥ 乡镇级** (村级太小会返回 0)

---

## 5. OSM (OpenStreetMap) Overpass

### 实际能力
- **API 端点**: `https://overpass.kumi.systems/api/interpreter` (国内镜像)
- **坐标系**: WGS84 (无需转换)
- **核心查询**: Overpass QL (`[out:json];node["place"="village"](bbox);out;`)

### 实测数据 (金田村 bbox 24.77,116.00,24.87,116.10)
| 查询 | 命中数 |
|------|--------|
| `node[place=village]` | **0** |
| `node[amenity~school|hospital|clinic]` | **0** |
| `relation[boundary=administrative][admin_level=8]` (township) | **0** |
| `relation[boundary=administrative][admin_level=10]` (village) | **0** |
| `way[highway~residential|tertiary]` | **0** |
| `way[natural=water]` | **0** |
| Nominatim geocode "金田村" | **0** |

### 结论: **OSM 在金田 bbox 内 0 数据**

### 根因
- 中国乡村数据由民间志愿者贡献，**覆盖率极低**
- 金田村这种小村庄几乎肯定没有被绘制

---

## 6. 本地数据 (data/gis/jintian/)

### 已加载内容
| 类型 | 文件 | 数量 |
|------|------|------|
| 现状注记 | `current/annotation.geojson` | **34 个 Point** (4 邻村 + 30 设施代号) |
| 现状地块 | `current/landuse.geojson` | **660 个 Polygon** |
| 现状道路 | `current/road.geojson` | **131 个 LineString** |
| 规划注记 | `planned/annotation.geojson` | 71 |
| 规划地块 | `planned/landuse.geojson` | 582 |
| 规划道路 | `planned/road.geojson` | 170 |
| 行政边界 | `boundary.geojson` | 1 |
| 行政界线 | `admin_boundary_line.geojson` | 561 |
| 水域 (DLBM=31xx) | landuse.geojson 派生 | 48 |
| 各类保护/控制 | 多个文件 | 280+ |

### 邻村 (4 个, 本地已有)
- 八社村 (116.0473, 24.8504)
- 上举村 (115.9964, 24.8126)
- 符坑村 (116.0155, 24.8022)
- 文贵村 (116.0487, 24.8048)

### 金田村 12 位 adcode (本机查得)
```
441426110202 = 广东省 / 梅州市 / 平远县 / 泗水镇 / 金田
```

---

## 7. Bundle 注入实测汇总 (scripts/_smoke_v98.py)

```
=== metadata ===
province: 广东省 ✓
city: 梅州市 ✓
county: 平远县 ✓
township: 泗水镇 ✓
adcode_12: 441426110000 ✓

=== annotations_current (34 + 19 = 53) ===
  local: 34
  amap_poi: 19
    - 泗水镇金田村退役军人服务站
    - 金田村委会
    - 八社村退役军人服务站 / 八社村村委会
    - 泗水镇文贵村退役军人服务站 / 文贵村委会
    - 符坑村村委会 / 人社综合服务窗口(符坑村党群服务中心) / 符坑村退役军人服务站
    - 石窟河 / 长潭水库 / 牙子寨 / 142乡道 / 118乡道与122乡道交叉口 / 青山岌顶
    - 瓜窝山 / 118乡道 / 猴哥寨 / 长潭水库
  baidu_v3: 0 (集成未生效)
  tencent_map: 0 (集成未生效)
  tianditu_wfs: 0 (注入到 annotations_current)

=== water_bodies (48 + 1 = 49) ===
  local: 48
  tianditu_wfs: 1 (长潭水库)

=== roads_current (131 + 12 = 143) ===
  local: 131
  tianditu_wfs: 12 (Y161 铁坑-西山 等)

=== _external sub-key 数: 0 (符合规范) ===
```

---

## 8. 关键结论与建议

### 8.1 哪些数据本地已经够用，不需要外部增强？

| 数据类型 | 本地有 | 外部补强价值 |
|---------|--------|------------|
| 道路几何 | 131 条 (current) | ❌ 不需要 |
| 水域几何 | 48 条 (DLBM) | ⚠️ 天地图水库 Polygon 可补 (有名字) |
| 行政边界 | 1+561 | ❌ 不需要 |
| 邻村 POI | 4 个 (八社/上举/符坑/文贵) | ❌ 不需要 |
| 设施代号 | 30 个 ("小/校/医") | ✅ 真实名 (学校名/医院名) |

### 8.2 哪些数据本地完全缺失，外部能补？

| 数据类型 | 本地 | 外部能补 | 哪个 provider |
|---------|------|---------|--------------|
| **行政村村委会名字** (本村 + 周边) | ❌ | ✅ | **高德 P5a** (本镇 12 个) |
| **自然村本村坐标** | ❌ | ⚠️ | **腾讯** (5/12 命中) |
| **设施真实名** | ❌ | ✅ | **高德/腾讯** (学校/医院) |
| **公交站名** | ❌ | ✅ | **高德 P4** |
| **水库名** | ❌ | ✅ | **天地图 HYDA** |
| **道路名 (含交叉口名)** | ❌ | ✅ | **天地图 LRDL** |
| **周边行政村村委会位置** | ❌ | ✅ | **高德 + 腾讯 + 百度** (3 源去重) |
| **邻村精确归属判断** | ⚠️ 仅有坐标 | ✅ | **百度 address 字段** (最精准) |

### 8.3 哪些 provider 在金田村场景贡献最大？

**排名** (基于实测):
1. **本地数据** (地基，所有 POI/几何的权威源)
2. **高德 AMap** (行政村 12 + 设施 9 + 道路名 25 = 46+ features)
3. **天地图 WFS** (水系 1 + 公路 12 = 13 features)
4. **腾讯** (行政村 ~30 + 自然村 5 本村内)
5. **百度** (行政村 20 + 设施 79, 但**坐标精度低 + 防误连**强)
6. **OSM** (0 数据，**跳过**)

### 8.4 坐标系统一性

| Provider | 默认返回 | 实际偏差 (vs 已知 WGS84 真值) | 解决方案 |
|----------|---------|------------------------------|---------|
| 高德 AMap | GCJ02 | 388-1562m | **Pipeline Stage 2 显式 `gcj02_to_wgs84`** |
| 百度 | BD09 | 661-1201m | Pipeline Stage 2 标 BD09 (百度 geocoding 本来就精度低) |
| 腾讯 | GCJ02 | 578-1874m | **Pipeline Stage 2 显式 `gcj02_to_wgs84`** |
| 天地图 | CGCS2000 ≈ WGS84 | 4-8m | **无需转换** |
| OSM | WGS84 | 0m | **无需转换** |

### 8.5 防误连规则

```
本村内 = 外部 POI 的 address/district/township 含 "泗水镇" 或 township="金田村"
外村 = 不在 township="泗水镇" 范围 (如 上举村 实际在上举镇)
```

百度 address 字段防误连最精准:
- "广东省梅州市平远县八社村" → 泗水镇 → 本村
- "广东省梅州市平远县上举镇" → 上举镇 → 外村
- "广东省梅州市平远县118乡道南200米" → 平远县泗水镇 → 本村

### 8.6 推荐的下一步

1. **启用百度和腾讯** (当前 catalog 集成只跑了高德 + 天地图)
2. **修复百度 baidu_v3 注入为 0** (疑似 API 调用参数)
3. **修复腾讯 tencent_map 注入为 0** (同上)
4. **添加自然村本村坐标替换机制** (bridge_advisor 用腾讯 T6 5/12 命中替换 KG cluster centroid)

---

## 9. 实测 Probe 脚本列表

| 脚本 | 功能 | 输出 JSON |
|------|------|----------|
| `scripts/test_amap_village_anchor.py` | 高德 11 路径探测 | `_amap_probe_stdout.txt` |
| `scripts/test_baidu_village_jintian.py` | 百度 11 路径探测 | `_baidu_probe_jintian.json` |
| `scripts/test_tencent_map_jintian.py` | 腾讯 10 路径探测 | `_tencent_map_probe_jintian.json` |
| `scripts/test_tianditu_wfs_jintian.py` | 天地图 WFS 6 layer 探测 | `_tianditu_wfs_probe_jintian.json` |
| `scripts/test_osm_overpass_jintian.py` | OSM Overpass 6 query 探测 | `_osm_probe_jintian.json` |
| `scripts/test_coord_system_validation.py` | 5 provider 坐标系验证 | `_coord_validation.json` |
| `scripts/test_baidu_tencent_internal_jintian.py` | 百度+腾讯内部归属详细 | `_baidu_tencent_internal.json` |
| `scripts/_smoke_v98.py` | 完整 bundle 注入 smoke test | stdout |

---

## 10. 最终方案 v9.8 决策总结

| 决策 | 选择 | 原因 |
|------|------|------|
| 注入 sub-key | **复用现有** (annotations_current 等) | 0 schema 变更, 下游自动识别 |
| sub-key 是否新增 `_external` | **不新增** | 防止双 bucket 混乱 |
| 跨源去重维度 | **(name_norm, lon_3, lat_3, category)** | 不做 fuzzy, 严格匹配 |
| 去重优先级 | **天地图 > 百度 > 腾讯 > AMap > OSM** | 国家级矢量 + address 字段优先 |
| 坐标归一化 | **Pipeline Stage 2 显式处理** | provider 内部转换实测无效 |
| 防误连时机 | **enrichment 阶段 (基于 address/district)** | 比 bridge_advisor 后置更早 |
| 12 位 adcode 来源 | **本地 CSV 查询** (AdminCodeService) | 不依赖 metadata 预填 |
| Pipeline 钩入位置 | **load_village_bundle() 末尾, Step 4b 之后** | 不影响本地数据加载 |
| OSM 是否纳入 | **否** | 金田 bbox 0 数据, 跳过 |

---

> 文档生成时间: 2026-08-02
> 实测依据: scripts/_smoke_v98.py + 7 个 probe 脚本