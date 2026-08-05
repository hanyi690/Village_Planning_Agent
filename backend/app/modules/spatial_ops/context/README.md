# spatial_ops.context — 空间认知卡片生成

## 职责边界

- 生成 ContextBlock 架构的空间认知卡片，供下游消费（LLM 上下文/空间认知）。
- `compute_context_blocks(bundle, requested, max_token_budget)` 是唯一公开入口。
- 内置 8 类生成器（注册在 `_GENERATORS`）：
  VILLAGE_META（村庄概况）、LANDUSE_DIST（用地分布）、RESIDENTIAL_CLUSTERS
  （居民点聚类锚点）、SPATIAL_RELATIONS（居民点方位关系）、CONSTRAINTS
  （保护约束边界汇总）、FACILITIES（设施锚点）、TERRAIN（地形栅格占位）、
  ZONE_ADJACENCY（分区邻接）。
- 消费方式：下游按 ContextBlockType 过滤、按 priority 排序、按 token 预算截断。

## 输入输出契约

- 输入：`VillageBundle`（直接类型化属性访问，如 `p.dlbm/p.geometry`），
  可选 `requested` 块类型列表与 `max_token_budget`（默认 1500）。
- 输出：`List[ContextBlock]`，已按 priority 升序排序并按 CJK 感知 token
  估算截断；单块 `to_markdown()` 供提示词拼接。
- 生成器失败不中断：单个块失败记 warning 并跳过。

## 依赖方向

- 依赖 `app.modules.schema.contracts.context_contracts` 与
  `app.modules.schema.types.canonical`（VillageBundle）。
- 复用 `app.modules.spatial_ops.geometry` 与
  `app.modules.spatial_ops.geometry.relations` 的纯函数。
- 不依赖 agent / services / api 层。

## 禁止行为

- 禁止直接遍历 bundle 原始 GeoJSON dict（须类型化属性访问）。
- 禁止在 generator 中修改 bundle。
- 禁止生成器相互依赖（SPATIAL_RELATIONS 内部自聚类，不依赖外部块顺序）。
- 禁止超过 token 预算输出（必须截断）。
