# 00 业务流程总设计

> Status: TARGET。目标设计按业务阶段组织；当前实现以 `docs/architecture/` 为观察依据，迁移状态以本目录的迁移章节为准。

## 1. 唯一业务主链

```text
SessionDataSnapshot
  → L1 现状事实
  → L2 规划认知
  → L3 规划意图
  → TARGET_PROJECTION 目标编译
  → GROUND 空间接地
  → SELECT 方案求解与审批
  → EXECUTE 执行与物化
  → VALIDATE → RECONCILE → DELIVER
```

Evidence 是横向能力；它可以被 L1、L2、L3、TARGET_PROJECTION、GROUND 和 SELECT 使用。

## 2. 阶段不是单向函数

每个阶段都是一个可恢复的受控子图：

```text
prepare_context → retrieve → llm_reason → parse → validate
       ↑                                      ↓
       └──── resolve_gap / bounded_retry ─────┘
                         ↓
                    persist_artifact
```

阶段内部允许迭代，阶段之间只允许声明式反馈：

```text
L1/L2/L3/GROUND/SELECT → Evidence：补充证据
GROUND → GROUND：已解决对象辅助未解决定位
SELECT → GROUND：候选空间不足
VALIDATE → L3/GROUND/SELECT/EXECUTE：按责任阶段修复
```

每轮必须有预算、输入 digest、输出 digest、失败原因和终止条件。

## 3. 阶段权威产物

```text
L1                  → L1Snapshot
L2                  → L2Strategy（包含各维度 L2DecisionSet）
L3                  → PlanningProgram
TARGET_PROJECTION   → AdmittedTargetSet / GroundingRequest
GROUND              → GroundedPlanningProblem
SELECT              → ScenarioSet / ApprovedExecutionInput
EXECUTE             → ExecutionPlan / ExecutionResult / PlannedState
VALIDATE            → ValidationCertificate
RECONCILE           → FinalManifest
DELIVER             → DeliveryManifest
```

## 4. 共同完成条件

阶段只有在以下条件全部满足时才完成：目标边界落实、公开 facade 可调用、typed artifact 真实生成、artifact 可重载、失败和 gap 可表达、迭代可恢复、下游可以消费、契约、编译和运行探针通过。

## 5. 增量迁移目标

实现必须沿本文件的业务主链逐阶段推进。每阶段都必须完成目标目录、facade、真实 artifact、可恢复迭代和下游适配，才能进入下一阶段。阶段映射和迁移出口记录在 `05_MIGRATION.md`，目标文件树记录在 `06_SELECT_EXECUTE_AND_CODE.md`。

## 6. 跨阶段专项设计

本文件刻意保持业务主链总览，不承担 GIS 来源模型、实体身份、多空间表示、Session KG、检索和接地算法的详细定义。相关权威设计见 `07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md`，实施顺序、双轨切换和退出门槛见 `08_COGNITIVE_WORLD_MODEL_MIGRATION.md`；实际完成状态仍只记录在 `05_MIGRATION.md`。

Context Runtime 和 Structured Runtime 是所有业务阶段共用的基础设施，不能由 L1/L2/L3 或 GROUND 各自实现第二套上下文、prompt 截断或结构化解析。模块级职责、产品表、依赖树、LLM 表格协议、Evidence gap 调度和逐模块验收见 `10_MODULE_LEVEL_EXECUTABLE_DESIGN.md`；本文件仍只保留主链总览。
