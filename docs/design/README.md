# Design documentation

> Status: TARGET
>
> 本目录定义目标语义、所有权、边界和验收规则，不证明能力已经实现。当前代码事实见
> <code>../architecture/CURRENT_RUNTIME.md</code>；目标到当前的差距只见
> <code>05_MIGRATION.md</code>。

## Start here

- [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md)：文档冲突时的 owner map。
- [DOCUMENT_CLEANUP_MANIFEST.md](DOCUMENT_CLEANUP_MANIFEST.md)：本轮收敛和退役内容。
- [EXECUTABLE_DESIGN_STANDARD.md](EXECUTABLE_DESIGN_STANDARD.md)：模块设计 16 节标准、成熟度与证据标签。
- [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)：初期认知闭环、中期规划 MVP 和完整业务主链。
- [DATA_EXECUTABLE_DESIGN.md](DATA_EXECUTABLE_DESIGN.md)：DATA 声明能力、准入状态机与 fail-closed 契约。
- [01_CONTRACTS_AND_INVARIANTS.md](01_CONTRACTS_AND_INVARIANTS.md)：L1 observation、事实接纳、地点工作项和最终产品。
- [L1_IMPLEMENTATION_AND_UPSTREAM_DOWNSTREAM_COMPARISON.md](L1_IMPLEMENTATION_AND_UPSTREAM_DOWNSTREAM_COMPARISON.md)：L1 当前实现、上下游边界与设计差距审计。
- [02_PLANNING_COGNITION.md](02_PLANNING_COGNITION.md)：L2 规划认知。
- [03_PLANNING_INTENT.md](03_PLANNING_INTENT.md)：L3 规划意图。
- [04_EVIDENCE.md](04_EVIDENCE.md)：Evidence 采集、推理、充分性和 gap 调度。
- [05_PROJECTION_AND_GROUND.md](05_PROJECTION_AND_GROUND.md)：Target Projection 编译，不含两类 Ground。
- [L1_GROUND_EXECUTABLE_DESIGN.md](L1_GROUND_EXECUTABLE_DESIGN.md)：mention-to-entity/scope 认知接地。
- [PLANNING_GROUND_EXECUTABLE_DESIGN.md](PLANNING_GROUND_EXECUTABLE_DESIGN.md)：规划用途表示、资源、geometry、CRS 和候选闭集。
- [06_SELECT_EXECUTE_AND_CODE.md](06_SELECT_EXECUTE_AND_CODE.md)：SELECT、EXECUTE 和交付。
- [07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md](07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md)：Cognition/World Model 生命周期与事务。
- [08_COGNITIVE_WORLD_MODEL_MIGRATION.md](08_COGNITIVE_WORLD_MODEL_MIGRATION.md)：Cognition 专项实施顺序；不表示已经完成。
- [10_MODULE_LEVEL_EXECUTABLE_DESIGN.md](10_MODULE_LEVEL_EXECUTABLE_DESIGN.md)：跨模块产品流、唯一 Gate 矩阵、写入权和增量协议。
- [05_MIGRATION.md](05_MIGRATION.md)：唯一迁移状态账本。
- [acceptance/README.md](acceptance/README.md)：P0/P1/P2 成熟度验收卡；不承载模块设计。

## Reading paths

- 初期认知闭环：<code>Standard → DATA → 07 → 04 → 01 → L1-GROUND → 10</code>。
- 中期规划 MVP：<code>00 → 02 → 03 → Target Projection → Planning Ground → 06 → 10</code>。
- 核对当前实现：<code>architecture/CURRENT_RUNTIME → 05_MIGRATION</code>。
- 核对成熟度：<code>acceptance/00_common → 对应模块验收卡</code>。
- 查询字段：以 Pydantic contracts、生成 OpenAPI 和可重复测试为准，设计文档不复制第二份 schema。

## Maintenance

不得在 <code>design/</code> 新建日期状态页、第二套总体蓝图、provider 专项实现日志或重复字段表。
一次性审计只提供证据；若审计结论改变规则，必须回写上述 canonical owner。已退役的
<code>09_MODULE_IMPLEMENTATION_SPEC.md</code> 不再恢复，其有效内容已分别归入
<code>04</code>、Target Projection、两类 Ground、<code>07</code> 和 <code>10</code>。
