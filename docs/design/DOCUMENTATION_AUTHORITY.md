# Documentation Authority

> Status: CURRENT
>
> 本文件只解决“发生冲突时谁是 owner”。设计、现状、迁移和历史证据必须分开。

## Canonical owners

| Scope | Canonical owner | 内容 |
|---|---|---|
| 文档治理 | <code>design/DOCUMENTATION_AUTHORITY.md</code> | owner、保留和冲突规则 |
| 可执行设计标准 | <code>design/EXECUTABLE_DESIGN_STANDARD.md</code> | 16 个必答章节、成熟度和证据规则 |
| 总体目标 | <code>design/00_SYSTEM_DESIGN.md</code> | 业务主链、阶段目标、总不变量 |
| DATA | <code>design/DATA_EXECUTABLE_DESIGN.md</code> | DATA MVP 真实输入闭包、当前实现地图、capability、admission、resource/representation、DataGap 与兼容边界 |
| L1 | <code>design/01_CONTRACTS_AND_INVARIANTS.md</code> | observation、fact、mention、L1 product |
| L2 | <code>design/02_PLANNING_COGNITION.md</code> | cognition strategy |
| L3 | <code>design/03_PLANNING_INTENT.md</code> | claims、program、intent |
| Evidence | <code>design/04_EVIDENCE.md</code> | requirement、acquisition、reasoning、gap |
| Target Projection | <code>design/05_PROJECTION_AND_GROUND.md</code> | L3 claim admission 与 typed grounding request |
| L1-GROUND | <code>design/L1_GROUND_EXECUTABLE_DESIGN.md</code> | mention-to-entity/scope binding、proposal、终态 |
| Planning Ground | <code>design/PLANNING_GROUND_EXECUTABLE_DESIGN.md</code> | representation/resource/geometry/CRS/capability 与候选闭集 |
| SELECT/EXECUTE/交付 | <code>design/06_SELECT_EXECUTE_AND_CODE.md</code> | solver、approval、materialization、delivery |
| Cognition/World Model | <code>design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md</code> | assertion、entity、representation、commit、rebase |
| Cognition 实施顺序 | <code>design/08_COGNITIVE_WORLD_MODEL_MIGRATION.md</code> | 专项迁移步骤，不证明完成 |
| 跨模块协议 | <code>design/10_MODULE_LEVEL_EXECUTABLE_DESIGN.md</code> | 产品流、唯一 Gate、写入权、增量执行、HUMAN |
| 迁移完成度 | <code>design/05_MIGRATION.md</code> | 唯一 current-to-target ledger |
| 成熟度验收 | <code>design/acceptance/</code> | P0/P1/P2 当前证据；不定义模块设计 |
| 当前代码行为 | <code>architecture/CURRENT_RUNTIME.md</code> | observed code/runtime facts |
| API/state | <code>architecture/API_AND_STATE.md</code> | HTTP/SSE/state projection |
| 运行与发布 | <code>architecture/OPERATIONS.md</code> | start、diagnostics、release checks |
| 字段级契约 | Pydantic/OpenAPI/tests | schema、validator、external contract |
| 决策历史 | <code>adr/</code> | 已接受的历史约束 |

## Conflict precedence

同一问题按下列顺序处理：

1. 可重载 artifact、运行输出和当前代码决定“现在实际怎样”；
2. Pydantic/OpenAPI 决定当前字段；
3. 对应 design owner 决定“目标应该怎样”；
4. <code>05_MIGRATION.md</code> 记录两者差距；
5. audit、plan、weekly report 和历史会话只提供背景，不覆盖以上 owner。

目标设计与当前代码不同不是文档冲突；只有把 TARGET 写成 IMPLEMENTED/CURRENT 才是错误。

## Operating rules

1. 每个规则只有一个 owner；其他文档使用链接和摘要。
2. <code>passed=True</code>、pending、partial、HUMAN 和 diagnostic 的跨阶段语义只由
   <code>10</code> 定义。
3. current/assertion/intent/planned 的写入权和视图权限由 <code>07</code> 定义。
4. provider 状态、coverage/sufficiency 和 gap 由 <code>04</code> 定义。
5. L1 mention 终态只由 <code>L1_GROUND_EXECUTABLE_DESIGN</code> 定义；执行候选 Gate 只由
   <code>PLANNING_GROUND_EXECUTABLE_DESIGN</code> 定义。
6. 验收卡只判成熟度和引用证据，不复制模块设计。
7. 实施计划不得写成现状；一次运行记录不得粘贴进目标设计。
8. 新 design file 只有在 authority map 先分配了不重叠 scope 后才允许创建。

## Supporting material

- <code>docs/contracts/</code>：生成或 contract-adjacent artifact；
- <code>docs/reference/</code>：稳定术语和领域资料；
- <code>docs/guides/</code>、<code>docs/frontend/</code>：任务指南；
- <code>docs/audits/</code>：一次性证据，不是规范；
- <code>docs/superpowers/</code>、<code>docs/reports-weekly/</code>：若保留，仅为 HISTORICAL，
  不属于 active design surface。

## Retired owner

<code>design/09_MODULE_IMPLEMENTATION_SPEC.md</code> 已退役。它混合了 provider cache、GIS
identity、GROUND、执行/渲染、LLM 表格和阶段差距，导致和当前模块 owners 重复。
有效规则已归入对应 owner；迁移证据归 <code>05_MIGRATION.md</code>。
