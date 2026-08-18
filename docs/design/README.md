# 设计文档（按模块组织）

> 设计文档回答“系统应该怎样设计”。实现事实以 `backend/app/`、`frontend/src/` 与
> [27_IMPLEMENTATION_VS_DESIGN.md](27_IMPLEMENTATION_VS_DESIGN.md) 为准；完成度以
> [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md) 为准。
> 状态标记：`TARGET`=目标设计（不代表已实现）；`CURRENT`=以代码为准的现状；`HISTORICAL`=历史证据（在 `_archive/`）。

## 跨模块设计（根目录）

| 文档 | 内容 | 状态 |
|---|---|---|
| [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md) | 总体设计（North Star）：目标图结构、三类权威产物、依赖方向 | TARGET |
| [01_LAYERED_ARCHITECTURE.md](01_LAYERED_ARCHITECTURE.md) | 分层架构与模块边界规则 | TARGET |
| [14_BACKEND_MODULE_BLUEPRINT.md](14_BACKEND_MODULE_BLUEPRINT.md) | 后端模块蓝图：目标模块、阶段契约、完成定义 | TARGET |
| [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md) | 实现状态台账（CURRENT/PARTIAL/GAP） | CURRENT + HISTORICAL |
| [24_MODULE_OUTPUT_INVENTORY.md](24_MODULE_OUTPUT_INVENTORY.md) | 模块实现与结构性产出盘点（以代码为准） | CURRENT |
| [25_VALIDATION_INVENTORY.md](25_VALIDATION_INVENTORY.md) | 校验点盘点（死校验风险分级） | CURRENT |
| [27_IMPLEMENTATION_VS_DESIGN.md](27_IMPLEMENTATION_VS_DESIGN.md) | 设计 vs 实现差异台账（以代码为准） | CURRENT |

## 按模块的专题设计（`modules/`）

| 模块 | 设计文档 | 对应实现 |
|---|---|---|
| [cognition](modules/cognition/README.md)（L1/L2/L3 认知层） | 04 规划管线、11 EXPLORE-KG 富化 | `domain/{assessment,objectives,program}`、`workflow/layers/` |
| [explore](modules/explore/README.md)（EXPLORE/证据检索） | 05 EXPLORE 桥、23 检索体系重构 | `evidence/`、`infrastructure/rag/` |
| [kg-place](modules/kg-place/README.md)（KG/地名解析） | 03 KG 语义桥、12 地名解析 | `infrastructure/kg/`、`spatial/grounding/` |
| [spatial-execution](modules/spatial-execution/README.md)（空间决策链） | 06 阶段边界、28 关系感知规划生成 | `workflow/stages/`、`domain/{ground,allocation,materialization}`、`spatial/` |
| [validation](modules/validation/README.md)（校验/反馈/自动迭代） | 07、13、26 | `domain/validation/` |
| [delivery](modules/delivery/README.md)（成果/合规/交付） | 08 | `domain/delivery/`、`infrastructure/{rendering,export}/` |
| [persistence](modules/persistence/README.md)（持久化） | 02 | `database/`、`infrastructure/{artifacts,events}/` |
| [llm-tools](modules/llm-tools/README.md)（LLM 工具绑定） | 17 | `infrastructure/llm/` |

## 维护规则

- 新增/修改模块设计 → 写进对应 `modules/<模块>/`，不要新增根目录编号文档。
- 设计改动与实现不符时，先在 [27_IMPLEMENTATION_VS_DESIGN.md](27_IMPLEMENTATION_VS_DESIGN.md) 登记差异。
- 历史审计、迁移计划、迭代日志、PPT 等已归档到 `docs/_archive/`，不作为当前设计。
