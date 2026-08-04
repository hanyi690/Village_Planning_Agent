# 成果、合规与交付门槛

## 1. 交付原则

交付对象是一个由 `PlannedState` 派生的成果包，而不是由多个节点各自拼出的文件集合。

```text
PlannedState
  → layer registry
  → geometry / attribute validation
  → statistics and balance tables
  → control rules
  → GDB / GeoJSON / map / report
```

## 2. 一图一表一规则

| 成果 | 来源 | 必须携带 |
|---|---|---|
| 一图 | PlannedState + render config | 图层版本、符号规则、空间参考 |
| 一表 | PlannedState aggregation | 统计口径、输入版本、校验结果 |
| 一规则 | schema encodings + planning constraints | 规则来源、适用范围、冲突处理 |

所有输出都必须记录 `artifact_ref`、`context_version` 和 `provenance`。

## 3. Delivery Gate

Delivery Gate 至少检查：

- 必需图层是否完整。
- 图形是否合法、坐标系是否一致。
- 属性编码是否满足 schema 和数据库规范。
- 统计表是否可由 PlannedState 重算。
- 文本、图、表、规则是否一致。
- 所有规划对象是否能追溯到 L3 intent 和 placement decision。

任何 blocking issue 都只输出诊断包，不输出“看似完成”的正式成果。

## 4. 输出适配器

输出适配器可以包括：

- GDB package
- GeoJSON package
- HTML / PNG map
- Markdown / DOCX report
- provenance manifest
- validation report

适配器不修改 PlannedState；需要修订必须回到对应阶段子图。

## 5. 数据库交付

数据库图层、字段和编码以 `modules/schema` 的 registry 为准。渲染层和报告层不得各自维护第二套字段映射。
