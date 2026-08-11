# spatial_ops.evidence

`evidence/` 是空间引用解析前的确定性证据索引与评分层。它把 Gazetteer、L1 typed location facts、VillageBundle POI 和允许的 KG 名称整理为可追踪候选，但不执行最终选址。

## 组件

| 文件 | 职责 |
|---|---|
| `place_evidence_index.py` | 构建版本化地名/实体证据索引并输出解析候选 |
| `evidence_scorer.py` | 对名称、角色、提示和来源做确定性评分 |
| `place_evidence_port.py` | 为 GROUND/SpatialResolver 提供依赖倒置端口 |

## 边界

- 输出必须保留 `entity_ref`、来源、候选分数和 unresolved/ambiguous 原因。
- 该层可以生成候选和证据，不能直接选择地块、写 `PlannedState` 或修改规划意图。
- 精确几何查询通过 `spatial_ops.grounding` / `spatial_ops.index` 完成；不要在这里复制几何算法。
- 版本来自 `PlanningContext`，上下文版本变化后必须重建索引。
