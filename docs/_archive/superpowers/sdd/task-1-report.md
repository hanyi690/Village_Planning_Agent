# Task 1 报告：分类生成器稳定性修复

## 修改文件

- `backend/app/domain/program/classification_generator.py`
  - 将 Instructor 响应收紧为 Pydantic 对象契约：`results` 必须是 `_ClassificationResultItem` 列表；item 和 wrapper 均使用 `extra="forbid"` 与 `strict=True`，不再接受 `list | str`、嵌套 JSON 字符串、字符串/布尔 index 或主动抽取尾随字符后的 JSON。
  - 将分类请求拆为每批最多 6 个目标；每批必须返回完整的 1..N index 集合后才应用，避免大批次上下文和部分结果混用。
  - 将模型输出压缩为 `index`、`selected_code` 和可选短 `rationale`；`candidate_codes` 在服务端收敛为 `[selected_code]`，满足下游 `ClassificationDecision` 契约。
  - 保留 Appendix 5（`classification_code_names("appendix5")`）闭集检查，非法编码、重复/越界/缺失 index 都进入有限重试路径。
  - 保留有限重试：每次共享 structured call 使用 `max_retries=1`，分类批次外层最多 3 次；失败后记录截断诊断并跳过该批次，不引入无界循环。
  - 未修改 `development_goals=36` 相关设计或语义。
- `backend/tests/core/test_l3_classification_generator.py`
  - 更新离线 fake structured LLM 以记录调用和 prompt 批次。
  - 增加/更新批次拆分、验证反馈重试、尾随字符拒绝、嵌套字符串拒绝、字符串/布尔 index 拒绝、失败闭合、中间批失败后继续和 Appendix 5 非法编码拒绝测试。
- `docs/superpowers/sdd/2026-08-17-stable-real-run-fixes/task-1-report.md`
  - 本任务要求的报告文件。

## 测试结果

运行命令：

```text
python -m pytest -q backend/tests/core/test_l3_classification_generator.py -o addopts=
```

结果：`9 passed in 2.14s`。测试使用 fake structured LLM，没有真实网络调用。

另运行：

```text
git diff --check -- backend/app/domain/program/classification_generator.py backend/tests/core/test_l3_classification_generator.py
```

结果：无 diff 格式错误。工作树中的其他既有修改未被 reset、checkout、提交或纳入本任务变更。

## 风险与限制

- 结构化响应现在严格拒绝 provider 返回的裸字符串、嵌套字符串和额外字段；如果生产 provider 无法稳定遵守 function-calling/Pydantic schema，该批次会在最多 3 次外层尝试后失败，需要上层继续走人工/恢复路径。
- 每批失败时该批不会产生部分分类决策；因此多批输入可能得到部分结果，最终是否继续由上层完整目标校验决定。这是故意的 fail-closed 行为。
- 为保持输出紧凑，模型不再返回候选编码列表，服务端将 `candidate_codes` 设为包含最终选择的单元素列表；如果后续产品需要展示多个备选项，需要单独扩展契约和审计语义。
- 测试覆盖的是离线 schema、批次和闭集逻辑，没有验证真实 provider 的 function-calling 兼容性、延迟或 token 使用；本任务明确禁止真实网络验证。
- 当前仓库存在其他代理/用户的脏工作树修改，本任务未创建 commit，也未触碰授权范围之外的实现文件。
- 严格类型回归依赖 Pydantic 的 `strict=True` 行为；若未来替换响应模型或 provider 适配器，必须继续保留该配置并维持字符串/布尔 index 的拒绝测试。
