# Design documentation

> Status: TARGET
> Authority: Navigation for the canonical target-design set. Governance is owned by `DOCUMENTATION_AUTHORITY.md`; observed behavior is owned by `../architecture/CURRENT_RUNTIME.md`; migration status is owned only by `05_MIGRATION.md`.

`design/` 只定义目标语义、所有权、边界和验收规则，不证明能力已经实现。字段级 authority 是 Pydantic、provider response models、生成 OpenAPI 和可重复测试；设计文档不复制 schema 表。

## Start here

- [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md)：文档冲突时的 canonical owner map。
- [DOCUMENT_CLEANUP_MANIFEST.md](DOCUMENT_CLEANUP_MANIFEST.md)：已执行的冗余/历史材料清理记录；不作为设计输入。
- [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)：全链路业务流程、阶段关系、阶段反馈和共同运行规则。
- [01_CONTRACTS_AND_INVARIANTS.md](01_CONTRACTS_AND_INVARIANTS.md)：L1 事实构建、事实类型、契约和结构化输出边界。
- [02_PLANNING_COGNITION.md](02_PLANNING_COGNITION.md)：L2 规划问题、目标、需求、适宜性和策略。
- [03_PLANNING_INTENT.md](03_PLANNING_INTENT.md)：L3 claim、PlanningProgram、lineage 和接地前边界。
- [04_EVIDENCE.md](04_EVIDENCE.md)：Evidence 检索、KG/Bundle 融合、推理、coverage 和 gap 闭合。
- [05_PROJECTION_AND_GROUND.md](05_PROJECTION_AND_GROUND.md)：目标编译和 GROUND 迭代接地子图。
- [06_SELECT_EXECUTE_AND_CODE.md](06_SELECT_EXECUTE_AND_CODE.md)：SELECT、EXECUTE、后处理和目标代码树。
- [07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md](07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md)：Source Data、动态 GIS 语义认知、实体解析、多空间表示、Session KG、实体检索和 GROUND 重构的跨阶段详细设计。
- [08_COGNITIVE_WORLD_MODEL_MIGRATION.md](08_COGNITIVE_WORLD_MODEL_MIGRATION.md)：上述专项设计的增量实施顺序、双轨门禁、测试、回滚和旧路径退出条件；不代表当前完成状态。
- [09_MODULE_IMPLEMENTATION_SPEC.md](09_MODULE_IMPLEMENTATION_SPEC.md)：把缓存外源证据、Data/KG 解耦、GROUND 到 SELECT/EXECUTE 资源协议和 DELIVER 渲染验收落实到各模块。
- [10_MODULE_LEVEL_EXECUTABLE_DESIGN.md](10_MODULE_LEVEL_EXECUTABLE_DESIGN.md)：模块级可执行基线，统一 Context/Structured Runtime、DATA、KG、EVIDENCE、L1/L2/L3、GROUND、SELECT、EXECUTE、DELIVER 的产品、依赖树、LLM 表格协议和验收。
- [05_MIGRATION.md](05_MIGRATION.md)：目标到当前的迁移状态和前后阶段适配记录。

## Reading paths

- 理解目标：`00` → `01` → `02` → `03` → `04` → `05` → `06`。
- 理解通用 GIS 与认知世界模型：先读 `00` 的主链，再读 `07` 的专项设计；准备实施时读 `08`。
- 核对现状：[CURRENT_RUNTIME.md](../architecture/CURRENT_RUNTIME.md) → [API_AND_STATE.md](../architecture/API_AND_STATE.md) → [OPERATIONS.md](../architecture/OPERATIONS.md)。
- 判断差距：先读目标 owner，再只查 `05_MIGRATION.md`；不要从历史计划、报告或会话状态推断完成度。
- 理解决策历史：[ADR](../adr/)；ADR 约束设计，但不替代 current-runtime evidence。

不得在 `design/` 新建日期状态页、第二套总体蓝图或重复契约表。`07` 是经 authority map 明确授权的跨阶段专项 owner，`08` 是其实施计划；新内容必须修改对应 canonical owner，历史与执行材料按 cleanup manifest 处理。
