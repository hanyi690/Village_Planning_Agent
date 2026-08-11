# 后端状态与交付边界

## 权威状态

| 数据 | Owner | 持久位置 | 对外公开 |
|---|---|---|---|
| 阶段、Gate、HITL、重试 | LangGraph `AgentState` | checkpoint | 仅经 `SessionProjection` |
| 阶段业务结果 | 对应阶段 contract | Artifact Store | 默认不公开 |
| EXECUTE 结果 | `ExecutionOutcome`、`ParcelChangeSet`、`PlannedState`、`DeferralLedger` | Artifact Store | 经交付投影公开 |
| 完整期末空间状态 | `DeliverySpatialSnapshot` | Artifact Store + layer files | 经 `MapLayerCollection` 公开 |
| 交付结论 | `DeliveryManifest` | Artifact Store | 经 `DeliveryProjection` 公开 |
| 事件历史 | session event log | 数据库/持久事件存储 | 经 SSE 和 sync 公开 |

`AgentState` 只允许承载图控制字段和 artifact refs。GeoJSON、完整 Pydantic
contract、导出结果和渲染文件清单不得成为新的 checkpoint 字段。现有
`specs`、`land_design_briefs`、`layout_configs`、`action_results`、`export_result`、
`render_artifacts` 已从父图状态移除并改由阶段 artifact 传递。新 API 不读取这些
历史 payload 字段。

EXECUTE 的 `execution_errors`、`l4_write_result`、
`execution_outcome_target_coverage` 也不再进入 checkpoint；三者合并写入
`ExecutionDiagnostics` artifact。主图仅通过 `fatal_error` 决定是否进入诊断终态。

## DELIVER 不变量

```text
ParcelChangeSet + current source layers
  -> DeliverySpatialSnapshot
     -> renderer
     -> exporter
     -> land balance
     -> DeliveryManifest
```

DELIVER 后的空间消费者必须使用同一个 snapshot checksum。禁止从
`PlannedState`、`allocated_geojson` 或原始 `gis_data` 重新构造另一份期末用地。
`/api/v1/.../map-layers` 已执行该边界；旧 `/render-layers` 不是稳定契约。

`agent/deliver/spatial_products.py` 是 snapshot、render layers 与 export package
的单一 application service。Snapshot 构建失败时不执行空间渲染或导出，土地平衡
以空期末集合失败关闭，最终成果进入 `diagnostic_only`，不允许历史状态回退。

## 分类边界

正式执行链只接受 `ClassificationDecision`。KG、地块 `dlbm`、目标名称、设施
类型和 advisory crosswalk 都不得生成规划编码。Worker 的规范数据流为：

```text
ClassificationDecision -> GeometryOperation -> ParcelChange
```

架构测试会扫描 Agent、KG 和正式输出目录，禁止导入 advisory crosswalk 或引用
历史跨体系映射名称。
