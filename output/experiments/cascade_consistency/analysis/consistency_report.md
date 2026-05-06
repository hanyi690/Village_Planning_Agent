# 级联一致性检验实验报告

生成时间: 2026-05-05T16:11:29.982710

## 实验数据汇总

| 指标 | 场景一 (规划定位) | 场景二 (自然环境) |
|------|------------------|------------------|
| 目标层级 | Layer 2 | Layer 1 |
| 目标维度 | planning_positioning | natural_environment |
| 受影响下游维度数 | 15 | 17 |
| 修复波次数量 | 2 | 2 |
| 语义一致性达标率 | 0.0% | 0.0% |
| SSE 事件数量 | 2 | 2 |
| 修复耗时(秒) | 5e-06 | 4e-06 |

## 分析结论

- scenario1 (Layer 2 → Layer 2/3) 相对简单
- scenario2 (Layer 1 → Layer 2 → Layer 3) 更复杂
- 跨层传播可能产生更大的语义漂移风险

## 影响树结构

### scenario1

```json
{
  "0": [
    "planning_positioning"
  ],
  "1": [
    "industry",
    "spatial_structure",
    "land_use_planning",
    "development_goals",
    "planning_strategies"
  ],
  "2": [
    "settlement_planning",
    "traffic_planning",
    "public_service",
    "infrastructure_planning",
    "ecological",
    "disaster_prevention",
    "heritage",
    "landscape",
    "project_bank"
  ]
}
```

### scenario2

```json
{
  "0": [
    "natural_environment"
  ],
  "1": [
    "resource_endowment",
    "spatial_structure",
    "land_use_planning",
    "infrastructure_planning",
    "ecological",
    "disaster_prevention",
    "planning_strategies"
  ],
  "2": [
    "industry",
    "settlement_planning",
    "traffic_planning",
    "public_service",
    "heritage",
    "landscape",
    "planning_positioning",
    "project_bank",
    "development_goals"
  ]
}
```
