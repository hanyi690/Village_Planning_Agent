# 稳定真实运行修复计划

## 设计边界

- `development_goals=36` 是当前需求设计，保持原样，不增加最小长度校验或无意义重试。
- 只使用真实 MiniMax 数据做最终验收，不输出或记录任何 API key。
- Appendix 5 分类码保持闭集，结构化输出必须是严格的 Pydantic 列表契约。
- Grounding 保留 KG/上传数据的几何与 BSM 归属；等价候选才聚合，不能按同名盲目合并。
- LLM fallback 使用独立预算、并发上限和单次超时；耗尽后走已有确定性 best-effort。
- LangGraph/运行时的诊断或恢复不得丢失已成功生成的 delivery artifact refs。

## 修复任务

1. 分类器：将聚合分类拆成小批次，使用严格列表响应模型，缩小输出契约，保留有界 Instructor/Pydantic 重试并记录失败尝试。
2. 语义修复：把 `classification_decision_required` 从真正的 source semantic errors 中分流，先运行分类决策，再决定是否回 L3。
3. 运行时交付：在 reconcile/diagnostic/end 状态合并并保留已成功写入的交付 artifact refs，并补充回归测试。
4. Grounding：对等价的 role/name/hint/candidate fingerprint 分组处理，减少重复 LLM 调用，同时保持每个事实的空间归属与 best-effort 语义。
5. 完成任务级审查、全量核心测试，再使用真实 MiniMax 执行完整流程，审查日志、输出长度、分类重试、Grounding 数量和渲染产物。

## Context7 依据

- Instructor：使用严格 Pydantic response model、有限验证重试，并在失败时检查 `InstructorRetryException.failed_attempts`；不接受含义模糊的 `list | str` 输出契约。
- LangGraph：checkpointer/thread state 应持久化成功节点写入；失败节点重跑时，已经成功的 sibling writes 和 artifact refs 必须保留。
