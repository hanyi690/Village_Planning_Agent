# 自动迭代与多模态规划设计

> 本文是设计规范，描述目标行为和边界；不等同于当前实现。
> 当前实现状态以 `10_IMPLEMENTATION_STATUS.md` 和 `docs/architecture/` 为准。

## 1. 设计目的

本项目不是一次性文本生成器，而是一个以 GIS 产物为中心的规划闭环。系统必须能：

1. 根据自己的校验产出自动修正可确定的问题；
2. 在不确定时保留 unresolved/HUMAN/partial 语义；
3. 使用图片、扫描件、规划图、遥感图和现场照片作为可审计证据；
4. 将视觉发现接入同一套 TARGET_PROJECTION/GROUND/SELECT/EXECUTE/VALIDATE/DELIVER 闭环；
5. 保留每轮修复的输入、调整、空间差异和交付 checksum。

自动迭代不是无限重试，也不是让 LLM 自由重写规划；多模态也不是向 L1 随意附加
几张图片。两者都必须服从 typed artifact、确定性 GIS 校验和现有 revision 机制。

## 2. 设计依据

GeoContra 将 GIS 任务表示为包含 CRS、字段、空间关系、拓扑和指标约束的可执行
契约，并将静态、运行时和语义验证结果用于有界修复循环。
[GeoContra](https://arxiv.org/html/2605.00782)

MiniMax 官方 OpenAI-compatible 接口支持同一消息中的 `text` 与 `image_url`，图片
可使用 URL 或 Base64 Data URL，并提供 detail 与大小限制。
[MiniMax multimodal API](https://platform.minimax.io/docs/api-reference/text-chat-openai)

多模态内容处理通常先做 OCR/版面分析和证据定位，再将字段绑定到页码和区域框，
并保留人工校验与 provenance。
[Microsoft multimodal content processing](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/idea/multi-modal-content-processing)

GeoAI 的可用形式是视觉感知、地理记忆、确定性空间工具和人工审查的组合；视觉模型
输出是建议/证据，不是自动法定图层。
[GeoAI Agency Primitives](https://arxiv.org/html/2604.01869)

## 3. 当前实现事实与差距

以下是代码审查得到的当前事实，不是目标描述：

| 能力 | 当前实现 | 状态 |
|---|---|---|
| 自动校验 | `backend/app/agent/validate/` 有确定性 checks、`ValidationReport`、责任阶段和 gate | PARTIAL |
| 自动回退 | 阶段路由已有 EXECUTE/SELECT/GROUND 等定向反馈，统一 adjustment executor 仍待完成 | PARTIAL |
| 自动调整 | `ValidationReport.adjustments` 已存在，但各 worker 消费不完整 | PARTIAL |
| 无进展保护 | `issue_fingerprint`、`gate_progress_metadata` 会识别重复问题 | CURRENT / 语义不足 |
| 自动修复闭环 | 同一问题通常转 HUMAN 或重复阶段，尚未统一执行 adjustment | GAP |
| 修订 | `revision_impact_tree`、artifact revision/checksum、目标投影修订已有基础 | PARTIAL |
| 图片 API | `ImageData`、`images` 字段存在 | PARTIAL |
| 图片 State | `image_ids` 存在 | PARTIAL |
| 图片 LLM 输入 | L1 主要仍发送文本，只记录 `has_images` | GAP |
| 图片 artifact | 没有统一媒体登记、hash、区域和版本链 | GAP |
| OCR/版面/图例证据 | 没有统一的 ImageEvidence 索引 | GAP |
| 多阶段视觉消费 | L2/L3/TARGET_PROJECTION/GROUND/SELECT/VALIDATE/DELIVER 未形成正式输入 | GAP |
| 视觉触发迭代 | 图片问题不能稳定绑定 target 并进入 adjustments | GAP |

因此当前不能宣称已经具备自动规划修复或完整多模态规划。

## 4. 自动迭代设计

### 4.1 复用现有契约

不新增平行的 `RepairAction`、`RepairPlan`、`ValidationIssue` 体系。复用并增强：

- `ValidationReport.checks`：实际值、期望值、检查证据和受影响目标；
- `ValidationReport.issues_by_stage`：责任阶段和问题归类；
- `ValidationReport.adjustments`：确定性修复动作及参数；
- `GateDecision.feedback_route`：最早受影响阶段；
- `retry_counts`：阶段/迭代预算；
- `revision_impact_tree`：受影响维度和下游阶段；
- `ArtifactRef` revision/checksum：父版本与输入输出身份；
- `ExecutionPlan`、`PlannedState`：修复后的权威产物；
- `DeferralLedger`：无法证明的目标。

只增加一个内部编排入口：

```text
apply_validation_adjustments(state, validation_report)
```

它校验 adjustment 的 stage、target、evidence 和参数，将其写入现有阶段输入，更新
retry/revision 信息，并让现有 worker 消费；不在 state 中保存完整业务对象。

### 4.2 自动循环

```text
EXECUTE
  → VALIDATE
  → 诊断 issues/checks
  → 读取 adjustments
  → 校验 target/stage/evidence
  → 从最早受影响阶段重算
  → VALIDATE
  → RECONCILE → DELIVER
```

每轮写入现有 stage audit/provenance：iteration index、issue fingerprint、父
checksum、adjustments、受影响目标、检查前后结果和新产物 checksum。

### 4.3 自动修复边界

| 问题 | 自动调整 | 回到 |
|---|---|---|
| 面积不闭合 | footprint 调整、保留余地、重算 | EXECUTE |
| 候选违反硬约束 | 排除具体 BSM、重新评分 | SELECT |
| 有新证据的空候选 | 目标级重读候选 | GROUND |
| 规划分类缺失 | 同一编码体系闭集决策 | TARGET_PROJECTION/EXECUTE |
| 设施缓冲/面积错误 | 米制 CRS 确定性重算 | EXECUTE |
| 道路/轴线无效 | 使用已确认锚点重建 | EXECUTE |

禁止：补猜坐标、跨体系映射、默认 `0701`、扩大无证据候选池、修改现状源图层、
用 LLM 自由文本覆盖 PlannedState。

### 4.4 收敛

默认每阶段最多两轮自动修复。相同 fingerprint 且输入 checksum 未变化时停止；
检测到修复来回振荡时回滚上一稳定 revision。剩余问题必须进入 HUMAN、DeferralLedger
或真实 `partial/diagnostic_only`，不得为了 PASS 降低门槛。

## 5. 多模态证据设计

### 5.1 统一媒体链

```text
图片/扫描件/规划图/遥感图/现场照片
  → ImageArtifact
  → OCR/布局/图例/图像理解
  → ImageEvidence / VisualFact / MapObservation
  → L1/L2/L3
  → TARGET_PROJECTION/GROUND/SELECT
  → EXECUTE 后 VisualReview
  → VALIDATE/adjustments
  → RECONCILE/DELIVER
```

State 只保存 artifact ref 和 checksum，完整图片保存在 artifact store。

### 5.2 复用 artifact 体系的媒体记录

`ImageArtifact` 至少包含：`artifact_ref`、sha256、存储路径、MIME、尺寸、来源、
文件名、父文档、页码、CRS、bbox、采集时间和预处理 ref。

`ImageEvidence` 至少包含：`evidence_id`、图片 ref、页码/区域框、OCR 文本、caption、
视觉要素、图例、检测标签、置信度、空间/时间状态、review 状态和 provenance。

`VisualFact` 保存维度、事实类型、主谓宾、证据 refs、置信度和是否需要 HUMAN。
`VisualReview` 绑定 `target_id`、规划状态、证据 refs、问题和现有 validation
adjustments；这些是 artifact payload 类型，不是新的 State 平行存储。

### 5.3 各阶段职责

- **L1**：每个维度独立 prompt/schema，只接收相关图片或裁剪图；事实必须引用
  `evidence_id`，不得直接产生坐标、BSM 或 CandidateSite。
- **L2**：结合视觉事实、时间差、区域关系和 GIS 摘要解释空间问题，不重复传全量图片。
- **L3**：检查规划目标与现场事实是否冲突，判断新增/改造/保留并保留 evidence refs。
- **TARGET_PROJECTION/GROUND**：`visual_exact_label` 仍需核验；`visual_ambiguous_reference` 和
  `visual_unresolved` 不得生成坐标、BSM 或空间 PASS；只有可靠 CRS/bbox 或 HUMAN
  确认区域才可辅助 grounding。
- **SELECT/EXECUTE**：视觉属性可作为可解释评分证据；几何、面积、拓扑、CRS 和分类
  仍由确定性 GIS/冻结分类决策决定。
- **VALIDATE/DELIVER**：生成规划前后截图、目标地块裁剪图、视觉差异和图例标注，
  形成 `VisualReview` 并进入现有自动迭代。

### 5.4 MiniMax 请求边界

```text
ImageArtifact → 相关性筛选 → crop/resize/detail budget
  → 临时 URL 或受控 Data URL
  → 独立维度 MiniMax text + image_url 请求
  → typed output + evidence_refs
```

日志只保存 artifact ref、hash、维度、detail、token 和耗时；不保存完整 Base64。
图片失败时回退到确定性 OCR/文本证据，不能阻断主流程。图片大小、数量、请求体和
超时预算按 MiniMax 官方限制执行。

## 6. 验收要求

- 代码、设计和状态台账分别标记 `CURRENT/PARTIAL/TARGET/GAP`；
- 图片确实进入相关 MiniMax 请求，日志不泄漏完整媒体；
- 每个视觉事实能追溯到图片 artifact 和区域；
- 视觉事实不直接生成坐标、BSM、编码或空间 PASS；
- validation adjustment 能驱动受影响阶段自动重算；
- 重复问题、循环和预算耗尽都有明确终态；
- 最终交付包含视觉复核、空间产物、revision 和 provenance checksum；
- 图片调用失败可确定性降级；
- 不跨编码体系推断、不修改现状源图层、不用默认编码补齐结果。

## 7. 实施顺序

1. 图片登记进现有 artifact store，生成 ref/hash/元数据；
2. 完成媒体裁剪和 MiniMax `text + image_url` 构造；
3. 先接通一个 L1 维度的真实视觉 evidence 闭环；
4. 扩展 L2/L3 证据消费，禁止视觉事实直接空间落地；
5. 将视觉复核写入 `ValidationReport` 和现有 adjustments；
6. 实现 `apply_validation_adjustments`，先接面积、候选排除、分类缺失；
7. 接通 worker 消费、有限迭代和 checksum/provenance；
8. 完成真实 MiniMax、多模态失败降级和完整交付 E2E。
