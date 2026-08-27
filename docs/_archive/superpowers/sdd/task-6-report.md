# Task 6 报告：真实 MiniMax L1 文本兼容 fallback

## 修改范围

本任务只涉及以下三个允许写入的文件：

- `backend/app/domain/assessment/analysis_node.py`
- `backend/tests/core/test_l1_text_provider_fallback.py`
- `docs/superpowers/sdd/2026-08-17-stable-real-run-fixes/task-6-report.md`

没有修改通用 `backend/app/infrastructure/llm/structured.py`，没有新增 provider
调用，也没有执行 commit、reset 或 checkout。

## 实现

- 在 L1 `InstructorRetryException` 路径增加明确记录的 best-effort 文本恢复；
  只有 L1 层且异常确实是 `InstructorRetryException` 时才尝试，其他异常仍走原有
  错误处理。
- 从 `last_completion.choices[0].message.content` 读取字符串内容，兼容 SDK 对象和
  字典形状；恢复逻辑不发起第二次模型请求。
- 仅移除位于内容开头的 `<think>...</think>` 包裹；纯 think、未闭合或其他位置的
  think 标记、空内容、`<failed_attempts>`、Instructor/HTTP 类错误文本都会被拒绝。
- `## observations` 章节只接受严格顺序的
  `entity_type/name/location/relation/description/scale` 六列表头和 Markdown 分隔
  行，最多解析 12 行；每行通过现有 `L1ObservationDraft.model_validate()` 校验。
  解析后从 `report_body` 移除整个 observations 章节；没有表格时返回空观察数组。
- 接受和拒绝都只记录维度键、结果和观察数量，不记录 completion 原文；拒绝时保留
  原始 `InstructorRetryException`，并在外层错误信息中使用不包含 completion 的固定
  诊断文本。

## 离线测试

新增/保留的测试覆盖：

- `<think>` + Markdown 正文 + observations 表格成功恢复；
- 纯 think 被拒绝并重新抛出原始 `InstructorRetryException`；
- 无 observations 表格时正文成功恢复且观察数组为空；
- provider 错误文本不会进入 fallback 日志；
- 协议错误标记和 `InstructorRetryException` 文本被拒绝。

运行结果：

```text
python -m pytest -q backend/tests/core/test_l1_text_provider_fallback.py -o addopts=
5 passed in 2.27s

python -m pytest -q backend/tests/core/test_l1_text_provider_fallback.py backend/tests/core/test_l1_source_fact_contract.py backend/tests/core/test_l1_report_resolution_diag.py backend/tests/core/test_l1_kg_enrichment_replay.py -o addopts=
14 passed in 6.90s

python -m pytest -q backend/tests/core/test_structured_output_runner.py -o addopts=
24 passed in 3.55s
```

`git diff --check` 对本任务实现和测试文件通过。测试均为离线测试，没有真实
MiniMax 或其他网络 provider 调用。工作区原有的其它修改保持不变，未被 reset、
checkout、提交或纳入本任务实现。

