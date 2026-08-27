# Current architecture

> Status: CURRENT
> Authority: Navigation for implementation behavior evidenced by the current worktree; canonical documentation ownership is defined in `../design/DOCUMENTATION_AUTHORITY.md`.

- [CURRENT_RUNTIME.md](CURRENT_RUNTIME.md)：启动入口、四段工作流、L1/L2/L3、空间链、检索、artifact 和已知边界。
- [API_AND_STATE.md](API_AND_STATE.md)：HTTP/SSE、WorkflowState、artifact refs、resume 和 delivery projection 的 owner。
- [OPERATIONS.md](OPERATIONS.md)：本地启动、配置类别、RAG/embedding 健康、退化运行和测试。
- [生成契约](../contracts/)：OpenAPI 与 SSE 的字段级外部契约。
- [后端代码级 README](../../backend/app/README.md)：各包当前职责；实现细节以代码和测试为准。
- [文档权威边界](../design/DOCUMENTATION_AUTHORITY.md)、[目标系统设计](../design/00_SYSTEM_DESIGN.md) 与 [迁移清单](../design/05_MIGRATION.md)。

本目录不维护目标蓝图、日期状态台账或复制的 endpoint schema。每一项 `CURRENT` 结论必须能回到代码路径或可重复命令；未达到目标的部分统一标为 `PARTIAL`/`GAP` 并链接迁移文档。
