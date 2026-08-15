# `src/features`

Feature-oriented frontend modules. Each feature owns its API adapters, state,
components, hooks, and local types; shared UI primitives and application wiring
stay outside the feature boundary.

| Feature | 职责 | README |
|---|---|---|
| `planning/` | 主规划工作台：会话 API/SSE、Zustand store、聊天/报告/GIS/HITL/交付 UI | [planning/README.md](planning/README.md) |
| `gis-test/` | 开发期 GIS 能力验证客户端（`/api/dev/gis/*`），非生产规划入口 | [gis-test/README.md](gis-test/README.md) |
| `compliance/` | 土地平衡/合规评估面板 | [compliance/README.md](compliance/README.md) |
| `evaluation/` | 质量评估面板（忠实度/引用/深度） | [evaluation/README.md](evaluation/README.md) |
| `suitability/` | 适宜性评估面板 | [suitability/README.md](suitability/README.md) |

新工作流行为应加进所属 feature，而不是扩展一个没有领域契约的全局 store。