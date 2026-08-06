# 村庄规划智能系统：总体设计（North Star）

> **状态：TARGET DESIGN** · 本文档定义目标架构。当前实现状态见 [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md)。

## 0. 设计结论

系统不是“文本 Agent 生成报告，再由 GIS Agent 接管”的串联流程，而是一个由规划阶段子图、空间决策子图和证据探索能力组成的闭环系统。

核心原则只有一句话：

> 每一个阶段只生产一种权威产物；后续阶段通过类型化契约消费它；失败沿产生原因返回，而不是回到一个巨大的总路由器。

## 1. 目标图结构

```mermaid
flowchart TD
    Start["START"] --> Bootstrap["BOOTSTRAP\nSessionPlanningContext"]
    Bootstrap --> L1["L1 OBSERVE\n现状事实与问题"]
    L1 --> G1{"L1 Evidence Gate"}
    G1 -->|通过| L2["L2 STRATEGIZE\n目标与策略"]
    G1 -->|缺证据| Explore["EXPLORE\n事实与证据探索"]
    Explore -->|EvidenceBundle| G1
    L2 --> G2{"L2 Consistency Gate"}
    G2 -->|通过| L3["L3 PLAN\n详细规划意图"]
    G2 -->|缺事实| Explore
    G2 -->|事实不一致| L1
    L3 --> G3{"L3 Program Gate"}
    G3 -->|缺信息| Explore
    G3 -->|意图不完整| L3
    G3 -->|通过| Parse["PARSE\nIntent Compiler"]
    Parse --> PG{"Parse Gate"}
    PG -->|修复 / 局部纠正| Parse
    PG -->|缺少规划内容| L3
    PG -->|通过| Ground["GROUND\n空间引用接地"]
    Ground --> GG{"Grounding Gate"}
    GG -->|通过| Select["SELECT\n候选评估与选址"]
    GG -->|实体歧义| Explore
    GG -->|意图错误| L3
    Select --> SG{"Selection Gate"}
    SG -->|通过| Execute["EXECUTE\n布局算法与图层生成"]
    SG -->|候选不足| Ground
    SG -->|目标不可实施| L3
    Execute --> Validate["VALIDATE\n规则、几何与一致性"]
    Validate --> VG{"Validation Router"}
    VG -->|执行缺陷| Execute
    VG -->|选址缺陷| Select
    VG -->|空间解析缺陷| Ground
    VG -->|规划意图缺陷| L3
    VG -->|通过| Reconcile["RECONCILE\nIntent ↔ PlannedState"]
    Reconcile --> Delivery{"Delivery Gate"}
    Delivery -->|通过| Output["EXPORT / RENDER / REPORT"]
    Delivery -->|失败| Validate
```

EXPLORE 是横向能力，不是固定的“L3 后桥接节点”。L1、L2、L3、GROUND 和 VALIDATE 都可以提交
`ExplorationRequest`。EXPLORE 的检索范围覆盖整个 session：`BaseFacts`、`DerivedRelations`、
VillageBundle、各层 AnalysisReport、`【INSTRUCTION】`、typed artifacts、既有 EvidenceBundle、
用户修订记录和允许的外部来源。KG 只是其中一个来源，不是 EXPLORE 的全部输入。

L1/L2/L3 都可以消费空间认知，但不直接持有 KG 实例或维护维度专属 KG 查询；它们按
`stage + dimension_key + query_purpose + evidence_gap` 提交请求，由 EXPLORE 返回带 provenance 的
`EvidenceBundle`。EXPLORE 只返回事实、证据和空间认知，不返回最终候选地块，也不直接改变规划意图。

Bootstrap 可以在 L1 前准备 KG、Bundle 和 artifact 的 evidence index，但该动作不代表探索完成。
实际证据是否充分由各阶段 Gate 判断；worker 和 Gate 按问题、维度及 EvidenceGap 发起增量检索。
因此系统中不存在“一次预设搜索即可满足 L1/L2/L3”的假设。

## 2. 三类权威产物

| 产物                        | 生产者                 | 消费者                        | 语义                                                    |
| --------------------------- | ---------------------- | ----------------------------- | ------------------------------------------------------- |
| `L1Snapshot`              | L1 子图                | L2、L3、Explore               | 已核验的现状事实、约束、问题和证据缺口                  |
| `L2Strategy`              | L2 子图                | L3、Select、Explore           | 目标、定位、策略和策略冲突                              |
| `PlanningProgram`         | L3 子图                | PARSE、L2、Explore            | 项目、设施、道路、保护修复等规划干预及其依赖            |
| `IntentCompilationResult` | PARSE / IntentCompiler | Ground、Select、Execute       | 从 PlanningProgram 编译得到的类型化目标、约束和空间引用 |
| `GroundingResult`         | Ground 子图            | Select                        | 空间引用对应的实体、候选及查询证据                      |
| `SiteSelectionDecision`   | Select 子图            | Execute                       | 经过硬约束、评分和冲突分配后的最终选址决定              |
| `PlannedState`            | Execute 子图           | Validate、Reconcile、Delivery | 实际生成的规划图层和派生关系                            |

Markdown 报告、SSE 事件和 UI 展示都是这些产物的视图，不是新的事实源。

## 3. Agent 与确定性子图边界

| 能力                   | 目标形态                                  | 允许做什么                                                                             | 不允许做什么                       |
| ---------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------- |
| EXPLORE                | session evidence service / 工具调用 Agent | 按阶段和维度检索 KG、Bundle、报告、typed artifacts、RAG 和外部资料，整理证据与空间认知 | 生成候选 BSM、修改意图、选最终位置 |
| L1/L2/L3 分析          | 专业分析 Agent                            | 解释事实、推导策略、生成规划文本草案                                                   | 绕过 Gate 直接写空间成果           |
| PARSE / IntentCompiler | 类型化编译节点                            | 文本转 Target、Constraint、`SpatialReferenceSpec`                                    | 查询地块或决定最终选址             |
| GROUND                 | 确定性子图，可含歧义处理节点              | 实体解析、KG 候选、几何精化                                                            | 评价候选优劣                       |
| SELECT                 | 混合决策子图                              | 硬过滤、评分、可选模型排序、冲突分配                                                   | 直接生成坐标或绕过约束             |
| EXECUTE                | 算法 Worker 子图                          | MIP、设施、道路、分区和图层生成                                                        | 静默改变规划意图                   |
| VALIDATE               | Evaluator 子图                            | 规则、几何、拓扑、文本/成果一致性校验                                                  | 把失败吞掉后继续交付               |

## 4. 依赖方向

```text
Schema contracts
    ↑
Data adapters / repositories
    ↑
Spatial query and geometry services
    ↑
KG semantic services
    ↑
Planning domain services (intent / grounding / selection / execution)
    ↑
Application subgraphs and API routes
```

应用层可以调用领域层；领域层不能反向导入 Agent、Service、API 或 UI。`tools` 只能是外部能力适配器，不能成为规划算法的第二实现。

## 5. 名称约定

规划阶段 L1/L2/L3 与知识图谱生命周期不再共用相同编号。KG 内部使用以下名称：

| KG 名称              | 内容                           |
| -------------------- | ------------------------------ |
| `BaseFacts`        | 现状实体、几何、编码和来源     |
| `DerivedRelations` | 预计算空间关系、约束和认知摘要 |
| `IntentGraph`      | 当前规划周期内的类型化意图实体 |
| `PlannedState`     | 执行后产生的规划成果实体       |

## 6. 当前实现边界

上图是目标设计，不是当前代码的逐节点描述。当前主图已经拆出独立的 L1/L2/L3 worker、层级 aggregate
和 post-L3 链；post-L3 链由 `gis_agent_node` 调用，当前运行顺序为：

```text
PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

当前 EXECUTE 已重构为多 worker 子图：`route_tasks → prepare_inputs → project_worker → zone_worker → [facility_worker ‖ axis_worker] → road_worker → merge_worker_results → geometry_materialize → planned_state_builder → execution_review`。道路规划器位于 `app/modules/spatial_ops/road/`
（确定性 staged pipeline）；旧的 `spatial_ops.road_planner` 简化 fallback 已删除，
`services/modules` 目录已清除。分区求解经 `ZoneAllocatorPort`（PuLP MIP）处理空候选 zone，失败显式 unresolved。
`ExecutionPlan`、统一 WorkerResult 契约和 RoadPlannerPort 收敛仍属后续工作。

因此当前真实 session 可以验证报告、`【INSTRUCTION】`、部分 typed aggregate 和 post-L3 节点，但不能据此
宣称“现状报告 + GIS → 合理项目定位、规划分区、道路和地块重组”已经端到端可用。

实现状态以 [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md) 为准；目录迁移和重复实现清理记录在
[09_INTEGRATION_BREAKPOINTS.md](09_INTEGRATION_BREAKPOINTS.md)。

## 7. 相关文档

- [01_LAYERED_ARCHITECTURE.md](01_LAYERED_ARCHITECTURE.md)：模块层和依赖规则
- [02_DATA_PERSISTENCE.md](02_DATA_PERSISTENCE.md)：上下文、产物和版本持久化
- [03_KG_SEMANTIC_BRIDGE.md](03_KG_SEMANTIC_BRIDGE.md)：KG 四类数据边界
- [04_PLANNING_PIPELINE.md](04_PLANNING_PIPELINE.md)：L1/L2/L3 及空间子图
- [05_EXPLORE_BRIDGE.md](05_EXPLORE_BRIDGE.md)：EXPLORE 证据探索能力
- [06_PARSE_EXECUTE.md](06_PARSE_EXECUTE.md)：PARSE、GROUND、SELECT、EXECUTE 契约
- [07_VALIDATION_FEEDBACK.md](07_VALIDATION_FEEDBACK.md)：Gate 与定向反馈
- [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md)：当前代码与目标态差距
