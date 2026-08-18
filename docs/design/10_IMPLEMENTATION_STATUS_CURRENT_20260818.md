# 当前实现状态补充（2026-08-18）

本文是 `10_IMPLEMENTATION_STATUS.md` 历史台账的覆盖页。旧文档中的“当前活动 demo 规划图层为 0”
仍适用于 `fresh-ground-20260817-test3` 和默认旧入口，但不能覆盖最新的 source-aware clone-only
replay28。后续阅读实现状态时，以本文、
[`RELATION_AWARE_MODIFICATION_LEDGER.md`](RELATION_AWARE_MODIFICATION_LEDGER.md) 和
[`29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md`](modules/spatial-execution/29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md)
的时间顺序记录为准。

## 当前可证实状态

| 阶段 | 当前证据 | 状态 |
|---|---:|---|
| TARGET_PROJECTION | 170 typed specs；source-aware stage 已读取 L1 observation/binding | `PARTIAL` |
| GROUND | 42 exact Point、1802 parcel candidate、329 corridor candidate；exact Line=0 | `PARTIAL` |
| SELECT | 16 placed、154 deferred | `PARTIAL` |
| EXECUTE | 16 final features（4 Point + 12 Polygon） | `PARTIAL` |
| VALIDATE/RECONCILE | 0 relation findings；geometry quality invalid/empty/placeholder/duplicate=0 | `CLONE_ONLY` |
| DELIVER | 15 render layers；122 non-baseline planning overlays；orphan=0 | `CLONE_ONLY/PARTIAL` |
| `/map-layers` | 同 run-root CAS descriptor 可解引用并可审计 | `PARTIAL` |
| 默认 live demo | 尚未完成 fresh live graph | `GAP` |
| live second resume | 尚未完成真实 LLM/worker counter delta 证明 | `GAP` |
| road/axis exact Line | 真实 source-feature ID/network binding 尚未供应 | `GAP` |

补充：真实 `data/gis/jintian/current/road.geojson` 的 131 条 `MultiLineString` 已通过
`backend/tests/characterization/test_real_source_line_grounding.py` 贯通
`source bundle → KG → spatial adapter → SpatialResolver → GROUND`，可得到
`line/exact_feature/execution_geometry`。因此 exact Line 的剩余问题是规划目标缺少可审计的
source-feature binding，而不是 GROUND 或 KG 不支持线几何。

另修复了一个接口丢失：`RoadTarget` 现在保留 `existing_road_feature_ids` 和 network
`existing_road_segment_ids`，mapper 和 compile 都接受显式的
`source_feature_ids`/`existing_road_feature_ids`/`road_feature_ids` 特征 ID 别名；这只修复审计
ID 的传递，不会从道路文本或数量不一致的源层自动猜测绑定。

## 不应混淆的两组结果

### 旧空图层证据

`fresh-ground-20260817-test3` 有 161 个 candidate，但全部是 `polygon/parcel_set`，exact Point、
exact Line、exact feature 均为 0；161 个 hard constraints 全部失败，SELECT=0，EXECUTE workers=0，
因此没有规划交付图层。

### 新 source-aware clone-only 证据

replay28 从 clean main cursor 和 v3 source bundle 完成
`TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`。它证明
设施 Point 和 polygon overlay 已可以贯通主链，但不是默认 live 完成态：exact Line=0、154 个目标
仍 deferred、delivery status=partial，且 clone-only artifact 不能代替默认入口的 live acceptance。

`actual_change_count=0` 是相对 baseline 的变化字段，不代表规划 feature 为零；当前应使用
`planning_overlay_feature_count=122`、`selected_count=16` 和 `materialized_feature_count=1979`
区分规划结果、选中目标和所有物化 feature。

## 阶段边界

- GROUND 只召回 typed candidate；权威 Point/Line WKT 才能成为 `exact_feature`，BSM union 只能是
  parcel/corridor candidate。
- SELECT 负责 hard/soft relation、容量、保护约束和网络可行性；`violated` 终止组合，
  `pending/unknown/deferred` 进入 partial/deferred ledger。
- EXECUTE 只物化 SELECT 已选 candidate 的 source-backed geometry；缺 source ID/geometry 时
  deferred，不生成 centroid、representative point、入口点或两点连线。

## 下一验收门槛

1. 用 source-aware bundle/KG 从 GROUND 之前 fresh replay，证明至少一个 road/axis exact Line。
2. 运行低内存 clone preflight，记录每阶段 yield、artifact digest 和 `/map-layers` 返回。
3. 第二次 resume 证明 scenario/final-validation fingerprint 不变且 LLM/worker 增量为零。
4. 默认入口和旧 test3 的空结果都必须保持 fail-closed；不能以放宽硬约束或 baseline 复制“修复”。

## 已知测试维护项

`backend/tests/core/test_final_relation_validation.py` 以及部分 network/service core fixtures
仍按旧契约构造 `ScenarioFeature`，缺少现在必填的 `relation_ids`，因此会在 fixture 构造阶段
失败。生产契约不应为此改回可空 lineage；下一次可写测试上下文应给每个 fixture 补稳定的
`relation_ids`（例如 `relation:near-zone-facility`），再重新运行 final-validation/network 回归。
