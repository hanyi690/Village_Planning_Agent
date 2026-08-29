# 金田村三 Provider 外源观测与本地 GIS 对比

日期：2026-08-28  
范围：金田村项目边界及必要的梅州市内扩展；本报告不把梅州市内同名结果自动绑定到金田村。  
方法：只读取本地缓存、运行日志、统一 normalized 产物和 `data/gis/jintian/current`，未发起网络请求。

## 结论

三家地图返回的不是同一种数据产品，不能用返回条数直接排序可信度。应把它们视为带 provider、接口、请求范围、坐标契约和时间的结构化外源观测；本地 GIS 仍负责项目内几何权威。

- 高德：两阶段完整缓存已迁移到统一格式。L1 对目标地名的结构化检索最适合做名称、类型和近似点观测，但跨县/跨市同名结果很多，必须二次范围判定。
- 天地图：行政阶段和 L1 均完成，返回量大、WFS/逆地理能力丰富，但泛名检索产生大量行政外和重复通用名称；数量多不代表实体识别更准。
- 腾讯：仅完成行政阶段的一部分。共记录 284 个请求事件、361 次尝试、284 个 raw 响应；因每日配额耗尽产生 77 个明确 failed，腾讯 L1 未开始，不能与另外两家的 L1 做完整比较。
- 本地 GIS：道路 131 个线 feature 没有名称字段，水域 48 个面 feature 只有 `DLBM=3100/DLMC=水域` 等源属性，短注记 34 个点和灾害点 40 个，是几何和项目范围的主要权威，但缺少很多现实地名语义。

## 采集状态对比

| Provider | 阶段 | 请求事件 | 成功非空 | missing | failed | 记录数 | retained/本地候选 |
|---|---|---:|---:|---:|---:|---:|---:|
| amap | 01_admin_scope | 72 | 51 | 5 | 16 | 538 | 122 |
| amap | 02_l1_place_names | 186 | 177 | 9 | 0 | 2955 | 199 |
| tianditu | 01_admin_scope | 254 | 251 | 3 | 0 | 1169 | 333 |
| tianditu | 02_l1_place_names | 99 | 77 | 22 | 0 | 6600 | 41 |
| tencent | 01_admin_scope | 284 | 66 | 141 | 77 | 299 | — |
| tencent | 02_l1_place_names | 0 | 0 | 0 | 0 | 0 | — |

腾讯行政 run 的详细中断记录见 [manifest](../../output/map_validation/tencent/01_admin_scope/runs/20260828T114116Z/manifest.json)。其中 77 个 failed 的 provider 状态均为 121（每日配额耗尽）；这不是 missing，也不是“腾讯没有数据”。

## 与本地 GIS 的对照

| 本地源 | 数量/现状 | 外源能补什么 | 外源不能替代什么 |
|---|---:|---|---|
| `boundary.geojson` | 1 MultiPolygon | 行政编码、地址层级、边界附近观测 | 本地项目边界本身的权威几何 |
| `road.geojson` | 131 MultiLineString；道路名称字段为空 | AMap/Tianditu/Tencent 逆地理和路线步骤提供道路名观测 | 不能把 POI 点或路线 polyline 当完整道路；需本地线段聚合 |
| `landuse.geojson` | 660 MultiPolygon；其中水域 48 | 水系名称、附近道路和设施关系 | 不能把任意水面直接命名成金田河/石窟河 |
| `annotation.geojson` | 34 Point；短注记如停、站、广、祠、水、电 | 外源 POI/地址/逆地理可帮助解释短注记 | 不能凭同名 POI 覆盖本地 BSM 或短注记语义 |
| `geological_hazard_points.geojson` | 40 Point；包含自然村/小地名文本 | L1 地名响应可提供独立名称和近似点 | 不能因为外源返回点就改写灾害点事实 |

### 目标地名的可用性

| 目标类型 | 高德观察 | 天地图观察 | 腾讯当前阶段 | 本地 GIS 对齐结论 |
|---|---|---|---|---|
| `122乡道` | L1 中有多条结构化返回；可作为道路名约束 | L1 有返回但泛名噪声需过滤 | 未进入 L1 | 本地 131 条线需按方向、连续性和关系聚合，不选单线 |
| `石窟河` | L1 有名称观测 | L1 有名称观测 | 行政阶段未形成可比 L1 | 本地水域面只能形成候选水系集合，不能单面命名 |
| `金田河/公王河` | 名称和别名可进入关系证据 | 名称可能被泛名结果淹没 | 未完成 | 用文本关系 + 连通水域成员聚合，保留名称冲突 |
| `公王下/长塘仔/马头段` | 可用于输入提示、地理编码和 POI 探测 | 可用于地名搜索，但需要项目范围筛选 | 未完成 | 代表点与居民地/道路相关几何分离 |

## L1 名称阶段的覆盖解释

L1 输入共有 33 个 place-like 名称。高德执行了名称级结构化检索；天地图执行了地名/多边形/地址组合；腾讯 L1 未开始。名称级接口成功返回，只能证明 provider 对该 query 产生了观测，不等于本地实体已确认。

天地图的 `normalized_record_count` 明显高于高德，但其 `outside_meizhou` 和通用名结果也明显更多；高德的 retained 数量较小不是召回不足的直接证明，而是范围和质量筛选更早收紧的结果。腾讯行政阶段的 299 个可解析 data 记录来自 66 个非空请求，仍是未完成的局部样本。

## 未来架构判断

外源检索不应只是把一段文本塞给 LLM，也不应越过 Data 层直接写入 KG/GROUND。最合适的是三层对象：

```text
Provider API / local cache
        ↓
ExternalObservationSnapshot  (Data: 原始响应、状态、坐标、范围、请求谱系)
        ↓ deterministic projection
ExternalCandidateEvidence    (Evidence: 名称/类型/点位/道路/路线/行政关系)
        ↓ bounded cognition + local spatial blocking
EntitySupportProposal        (Cognition: 支持、别名、冲突、待核)
        ↓ commit only after validation
WorldModel entity/representation support
        ↓
GROUND 只绑定已存在的本地或已提交 representation，不创建 API 几何
```

行政阶段和 L1 阶段都应是高质量的外源观测证据，但不能直接等同于本地 GIS 的几何可信度：行政阶段对‘provider 返回的行政层级’可以给高 observation confidence；L1 对‘provider 返回了这个名字、类型和点’可以给高 observation confidence。二者对‘它就是本地哪个 WorldEntity、它的完整道路/河流几何是什么’只能给独立的 binding confidence，通常需要本地空间、文档关系和跨 provider 一致性共同提高。

因此未来不使用单一 confidence，而使用至少三个轴：

1. `acquisition_confidence`：请求是否成功、响应是否完整、坐标是否符合契约、是否可复现；
2. `semantic_observation_confidence`：provider 对名称/类型/行政关系的明确程度；
3. `entity_binding_confidence`：与本地 Source Record、bundle 几何、KG 关系和其他 provider 的匹配程度。

`geometry_authority` 另行记录：本地 bundle/官方规划矢量可以是 geometry authority；API POI、逆地理最近点和路线 polyline 默认只是 `point_observation` 或 `route_observation`，不能升级成完整几何。

详细的目标架构已同步到 `07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md` 的外源融合章节。

## 证据边界与未决项

- `missing` 只表示本次公开接口成功但没有记录，不能证明地点不存在。
- 腾讯的 77 个 quota failed 必须保留为 failed；恢复额度后的重试应由显式采集计划触发，不能在报告生成时自动重放。
- 三家 provider 的 ID 不可直接互认；跨 provider 一致性只能作为支持特征，不能当作同一实体主键。
- 高德底图可见但公开 API 不返回的标签仍然只能作为 `BasemapLabelObservation`，没有公开几何时不进入 WorldEntity geometry。
- 本报告的数量是采集产物统计，不是金田村现实对象数量。

## 产物

- [机器可读对比 JSON](../../output/map_validation/three_provider_local_gis_comparison.json)
- [腾讯未完成行政 manifest](../../output/map_validation/tencent/01_admin_scope/runs/20260828T114116Z/manifest.json)
