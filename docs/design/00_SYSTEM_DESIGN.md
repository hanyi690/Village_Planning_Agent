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
L2                  → L2DecisionSet
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

阶段只有在以下条件全部满足时才完成：目标边界落实、公开 facade 可调用、typed artifact 真实生成、artifact 可重载、失败和 gap 可表达、迭代可恢复、下游可以消费、契约和集成测试通过。

