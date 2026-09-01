# Document Cleanup Manifest

> Status: CURRENT
>
> 本清单记录 active design surface 的收敛结果，不把“计划删除”写成“已经删除”。

## 本轮已移除

- <code>design/09_MODULE_IMPLEMENTATION_SPEC.md</code>：退役。其内容跨越 Evidence、World
  Model、GROUND、执行、渲染和迁移状态，形成第二套模块权威。
- <code>07</code> 中的迁移前基线、provider 采集专项、GROUND 重复设计和外部调研摘要。
- <code>10</code> 中逐模块重复字段、provider/parcel 实现细节和超出跨模块职责的旧段落。
- <code>00</code> 中绑定金田村具体文件名的准入白名单式表述；总体设计只保留通用准入规则。
- <code>05_MIGRATION</code> 中逐 session id、临时 digest 和长运行日志（由当前可重复证据摘要替代）。
- 原 <code>acceptance/01_data.md</code> 至 <code>13_deliver.md</code>：由带
  <code>_acceptance</code> 后缀的 P0/P1/P2 卡片替代；旧卡中的设计段落归入模块 owner。
- 原先合写在 <code>05_PROJECTION_AND_GROUND.md</code> 的两类 Ground：已拆分为独立 owner。
- <code>design/three-provider-external-evidence-capability-matrix.md</code>：退役。其 provider
  三态、坐标说明和采集目录与新的 Evidence taxonomy、DATA admission 及 historical plan
  重复；有效的 provider 状态与 authority 规则已经归入 <code>04_EVIDENCE.md</code>。

## 内容归属

| 内容 | 归入 |
|---|---|
| assertion/entity/representation/commit/rebase | <code>07</code> |
| Evidence provider 状态、融合、充分性、gap | <code>04</code> |
| L1 observation/fact/final product | <code>01</code> |
| Target Projection | <code>05_PROJECTION_AND_GROUND.md</code> |
| L1 mention/entity 接地 | <code>L1_GROUND_EXECUTABLE_DESIGN.md</code> |
| 规划执行接地 | <code>PLANNING_GROUND_EXECUTABLE_DESIGN.md</code> |
| DATA admission/capability | <code>DATA_EXECUTABLE_DESIGN.md</code> |
| Gate、写入权、增量协议、HUMAN | <code>10</code> |
| 当前实现差距和运行验证摘要 | <code>05_MIGRATION</code> |
| P0/P1/P2 当前判定 | <code>acceptance/</code> |

## Active design surface

~~~text
00_SYSTEM_DESIGN.md
EXECUTABLE_DESIGN_STANDARD.md
DATA_EXECUTABLE_DESIGN.md
01_CONTRACTS_AND_INVARIANTS.md
02_PLANNING_COGNITION.md
03_PLANNING_INTENT.md
04_EVIDENCE.md
05_PROJECTION_AND_GROUND.md
L1_GROUND_EXECUTABLE_DESIGN.md
PLANNING_GROUND_EXECUTABLE_DESIGN.md
06_SELECT_EXECUTE_AND_CODE.md
07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md
08_COGNITIVE_WORLD_MODEL_MIGRATION.md
10_MODULE_LEVEL_EXECUTABLE_DESIGN.md
05_MIGRATION.md
DOCUMENTATION_AUTHORITY.md
README.md
acceptance/README.md + *_acceptance.md
~~~

编号 <code>09</code> 保持空缺，避免旧链接误指向一份新但不同含义的文档。

## Historical/non-authoritative material

<code>docs/audits/</code>、<code>docs/superpowers/</code>、<code>docs/reports-weekly/</code> 和
临时分析输出即使仍在工作树中，也不属于 active design，不得作为 workflow 输入或完成度
证明。是否物理删除由单独的仓库清理任务决定；本轮不擅自删除用户未提交的历史材料。

## 维护规则

1. 删除或移动文档前先更新 authority map；
2. cleanup manifest 只记录实际动作；
3. 旧内容若仍有有效规则，先归入唯一 owner，再删除重复副本；
4. 不从历史计划恢复已退役的实现边界；
5. 不把一次运行产生的 session id、临时路径或 digest 固化进目标设计。
