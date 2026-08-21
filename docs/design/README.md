# 设计文档（唯一总体入口 + 模块专题）

> 总体设计只维护一份：[00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)。实现事实以
> `backend/app/`、`frontend/src/` 和可重复的测试/运行结果为准；状态证据以
> [10_IMPLEMENTATION_STATUS_CURRENT_20260818.md](10_IMPLEMENTATION_STATUS_CURRENT_20260818.md)、
> [27_IMPLEMENTATION_VS_DESIGN.md](27_IMPLEMENTATION_VS_DESIGN.md) 和
> [RELATION_AWARE_MODIFICATION_LEDGER.md](RELATION_AWARE_MODIFICATION_LEDGER.md) 为准。
> 旧版蓝图和重复盘点已移至 `docs/_archive/design/`，不再作为当前入口。

## 当前维护文档

| 文档 | 内容 | 状态 |
|---|---|---|
| [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md) | 总体设计、阶段边界、来源绑定规则和完成门槛 | CURRENT DESIGN |
| [10_IMPLEMENTATION_STATUS_CURRENT_20260818.md](10_IMPLEMENTATION_STATUS_CURRENT_20260818.md) | 最新状态、证据和验收缺口 | CURRENT |
| [27_IMPLEMENTATION_VS_DESIGN.md](27_IMPLEMENTATION_VS_DESIGN.md) | 设计与实现差异 | CURRENT |
| [RELATION_AWARE_MODIFICATION_LEDGER.md](RELATION_AWARE_MODIFICATION_LEDGER.md) | 关系感知空间规划的契约/生产者/消费者/验收台账 | CURRENT |
| [modules/spatial-execution/29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md](modules/spatial-execution/29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md) | 空间规划实现差距审计 | CURRENT / PARTIAL |
| [modules/spatial-execution/30_GIS_FACT_COLLECTION_BINDING_GAP_AUDIT.md](modules/spatial-execution/30_GIS_FACT_COLLECTION_BINDING_GAP_AUDIT.md) | GIS 事实、L1 事实和规划目标绑定审计 | CURRENT |

## 模块专题

| 模块 | 入口 | 对应实现 |
|---|---|---|
| 认知层 | [cognition](modules/cognition/README.md) | `domain/{assessment,objectives,program}`、`workflow/layers/` |
| EXPLORE / 证据检索 | [explore](modules/explore/README.md) | `evidence/`、`infrastructure/rag/` |
| KG / 地名解析 | [kg-place](modules/kg-place/README.md) | `infrastructure/kg/`、`spatial/grounding/` |
| 空间决策链 | [spatial-execution](modules/spatial-execution/README.md) | `workflow/stages/`、`domain/{ground,allocation,materialization}`、`spatial/` |
| 校验 / 反馈 | [validation](modules/validation/README.md) | `domain/validation/` |
| 成果交付 | [delivery](modules/delivery/README.md) | `domain/delivery/`、`infrastructure/{rendering,export}/` |
| 持久化 | [persistence](modules/persistence/README.md) | `database/`、`infrastructure/{artifacts,events}/` |
| LLM 工具绑定 | [llm-tools](modules/llm-tools/README.md) | `infrastructure/llm/` |

专题设计只回答本模块的边界、契约和决策，不重新定义总体主链或完成度。阶段实现事实和
API 细节优先看 [当前架构实现](../architecture/README.md)。

## 状态标记

- `CURRENT`：当前生产路径存在，并有代码或可重复测试证据。
- `PARTIAL`：有可运行片段，但闭环、边界、真实数据或验收仍不完整。
- `GAP`：设计要求存在，但当前生产路径没有实现，或已知接线断裂。
- `TARGET`：目标设计；不能用于证明功能已完成。
- `CLONE_ONLY`：隔离重放或克隆分支证据，不能替代默认 live 验收。
- `HISTORICAL`：带日期的历史事实，只用于解释当时的状态。

“文件存在”“单元测试通过”“能生成空集合或复制现状图”都不足以单独标记 `CURRENT`。
涉及地图、规划结果或恢复的能力，还必须检查实际产物、来源引用、版本一致性和失败路径。

## 维护规则

- 总体设计只修改 [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)，不要新增根目录编号文档。
- 新增或修改模块设计写进对应 `modules/<模块>/`，不要复制总体主链。
- 设计改动与实现不符时，在 [27_IMPLEMENTATION_VS_DESIGN.md](27_IMPLEMENTATION_VS_DESIGN.md)
  或对应专题台账登记差异。
- 历史审计、迁移计划、迭代日志、PPT 等统一放在 `docs/_archive/`，不作为当前设计。
