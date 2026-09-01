# 00 业务流程总设计

> Status: TARGET。目标设计按业务阶段组织；当前实现以 `docs/architecture/` 为观察依据，迁移状态以本目录的迁移章节为准。

本总设计只保留业务主链和不变量。模块级输入/输出表、无名地块与大地块实体
规则、DATA/KG/EVIDENCE 解耦、LLM 表格预算、Evidence Gap 即时调度，以及
GROUND→SELECT→EXECUTE 的资源协议，统一详见独立基线
[`10_MODULE_LEVEL_EXECUTABLE_DESIGN.md`](10_MODULE_LEVEL_EXECUTABLE_DESIGN.md)。

目标领域名称统一为 Cognition / World Model。KG 只是当前可选的存储、索引或投影实现，不能
成为第二套领域权威。业务代码通过 <code>CurrentWorldQueryPort</code> 与
<code>WorldModelCommitPort</code> 访问 immutable World Model snapshot；当前
<code>WorldModelKGStore</code> 是实现适配器，不定义 assertion/decision/commit 语义。

## 1. 唯一业务主链

```text
SessionDataSnapshot
  → Cognition / World Model 世界认知快照 v0
  → EVIDENCE_BOOTSTRAP / 即时缺口调度
  → L1 observation
  → L1-GROUND mention/entity/scope 认知接地
  → Cognition validation / World Model commit v1
  → binding revalidation / L1 final view
  → L2 规划认知
  → L3 规划意图
  → TARGET_PROJECTION 目标编译
  → Planning Ground 可执行空间接地
  → SELECT 方案求解与审批
  → EXECUTE 执行与物化
  → VALIDATE → RECONCILE → DELIVER
```

Evidence 是横向能力；它可以被 L1、L1-GROUND、L2、L3、Target Projection、Planning Ground
和 SELECT 使用。
初期首先完成到 L1 final view 的认知闭环；中期再完成 L2 到 DELIVER 的规划 MVP。两个闭环
使用同一套 artifact、Gate、版本和恢复协议，但验收进度不得混为一个“系统完成度”。

现状输入和规划输出是两个不可逆的命名空间。只有经过来源准入、同时满足
`input_role=current_evidence` 与 `status=admitted` 的资源，才能构成
`SessionDataSnapshot` 并投影到 KG 的 current-world。任务说明和约束属于控制输入，
不是真实世界事实；`reference_plan` 只能进入显式参考通道；`planned_output` 只能由
EXECUTE/DELIVER 产生和读取，永远不得重新进入 DATA、KG current-world、EVIDENCE
现状检索或 GROUND/SELECT 候选池。文件名、图层名、字段值和“看起来像现状”都不能
代替准入决定；角色缺失或冲突时必须隔离并阻断，而不是猜测放行。

现状报告、既有规划成果和本次任务说明必须分别走 current、reference/planned 和 control
通道。具体项目文件只属于验收样本，不在总体设计中列白名单；准入由内容角色、来源声明和
确定性 policy 决定。

## 1.1 系统优化目标

本系统的目标不是最大化 `PASS` 数、候选数、图层数或渲染完整度，而是在真实输入和
有限证据下，生成可追溯、可执行、可校验的规划空间变更。优化目标采用不可互换的
词典序：

1. 事实、来源、身份和版本闭包；
2. 本地资源、CRS、几何有效性与操作可执行性；
3. 规划约束、服务需求、空间覆盖和方案效用；
4. 不确定性显式化、恢复路径、解释与审计；
5. 缓存复用、外部调用和计算成本。

前一层硬门禁未通过时，后一层软评分不得补偿。未知必须保持未知；无法生成可信规划
图层时，显式输出 gap、HUMAN_REQUIRED 或 diagnostic-only，比伪造“完整方案”更接近
系统目标。

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
DATA                → SessionDataSnapshot / DataResourceCatalog
World Model bootstrap → SessionWorldModelSnapshot v0
EVIDENCE            → EvidenceStageSnapshot / EvidenceGapLedger / EvidencePacket
L1 observe          → L1ObservationSnapshot / EvidenceObservationSnapshot
L1-GROUND           → L1BindingSnapshot / Cognition proposals
Cognition commit    → L1WorldProjectionSnapshot / SessionWorldModelSnapshot v1
L1 final            → L1FinalProduct / L1ProductManifest
L2                  → L2Strategy（包含各维度 L2DecisionSet）
L3                  → PlanningProgram
TARGET_PROJECTION   → TargetProjectionArtifact / PlanningGroundingRequest
Planning GROUND     → GroundedPlanningProblem
SELECT              → ScenarioSet / SelectionDecisionSet / ApprovedExecutionInput
EXECUTE             → ExecutionPlan / ExecutionResult / PlannedState
VALIDATE            → ValidationCertificate
RECONCILE           → DeliveryReadinessManifest
DELIVER             → DeliveryManifest
```

其中 `PlannedState.features` 是通用点/线/面/multipatch 的规范产物；
`PlannedState.parcels` 仅为显式 BSM 地籍任务保留的兼容投影。后续模块不得把
parcel 或 `landuse_current` 当作所有规划目标的前置条件，详细退出规则见模块级设计。

## 4. 分级完成条件

阶段不再使用单一“全部完成”结论。P0 / Loop Ready 验证认知闭环的边界、artifact、状态、失败、
恢复、重载与限定下游消费；P1 / MVP Ready 验证稳定规划主链；P2 / Production Ready 再验证输入
广度、并发、安全、性能和人工治理。统一定义见
<code>EXECUTABLE_DESIGN_STANDARD.md</code>，当前判定见 <code>acceptance/</code>。

## 5. 增量迁移目标

实现必须沿本文件的业务主链逐阶段推进。每阶段都必须完成目标目录、facade、真实 artifact、可恢复迭代和下游适配，才能进入下一阶段。阶段映射和迁移出口记录在 `05_MIGRATION.md`，目标文件树记录在 `06_SELECT_EXECUTE_AND_CODE.md`。

## 6. 跨阶段专项设计

本文件刻意保持业务主链总览，不承担 GIS 来源模型、实体身份、多空间表示、Session KG、检索和接地算法的详细定义。相关权威设计见 `07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md`，实施顺序、双轨切换和退出门槛见 `08_COGNITIVE_WORLD_MODEL_MIGRATION.md`；实际完成状态仍只记录在 `05_MIGRATION.md`。

Context Runtime 和 Structured Runtime 是所有业务阶段共用的基础设施，不能由 L1/L2/L3 或 GROUND 各自实现第二套上下文、prompt 截断或结构化解析。模块级职责、产品表、依赖树、LLM 表格协议、Evidence gap 调度和逐模块验收见 `10_MODULE_LEVEL_EXECUTABLE_DESIGN.md`；本文件仍只保留主链总览。

输入预处理属于 DATA 边界：GIS 进入空间解析链，非 GIS 文档转换为可寻址的规范文本与媒体
引用。尚不能读取的媒体形成明确 Evidence gap；是否阻塞由对应 requirement 决定，不能一律
忽略，也不能一律阻塞整条主链。
