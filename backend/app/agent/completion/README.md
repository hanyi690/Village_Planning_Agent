# agent/completion 子包（层级完成检测）

> reducer 合并并行结果后检测层级完成，处理 step_mode 审批暂停（interrupt）/ 自动推进（continuous），触发 SSE、KG enrichment、bundle 快照。
> **Updated: 2026-08-02**

---

## 一、定位

主图 `layer_completion_check` 节点。在 `Send` 分发的一组维度全部完成后运行，负责：
1. **层级完成判定**（`set(completed) == set(total_dims)`）；
2. **step_mode 审批**：`interrupt()` 挂起等待人工审核（approve/reject），恢复后决定推进 / 修订；
3. **auto 模式**：直接推进下一层；
4. **边界钩子**：`layer_completed` / `layer_started` SSE、KG 多级富化（enrichment）、版本化 bundle 快照。

---

## 二、目录结构

```
completion/
├── __init__.py    # 导出 layer_completion_check
└── node.py        # ★ 315 行实现 + _snapshot_bundle + _maybe_extract_bindings
```

---

## 三、逻辑分支

```
layer_completion_check(state)
├─ is_revision 分支：
│    兜底写入 pending_reports（dedup by report_id，bulk_save 内部按 version 去重）
│    修订完成判定（revision_completed_dims ∪ target == impact_tree 全维度）
│      → SSE cascade_complete + bundle 快照 + 清空修订状态（is_revision=False）
├─ phase == completed / layer None → no-op
├─ 层未完成 → no-op
└─ 层完成：
    step_mode=True：
      interrupt({layer, phase, reason:"step_mode_awaiting_review"})   ← 必须先于任何 SSE
      恢复后 action：
        approve → layer_complete SSE + KG enrichment + 快照 → 推进 next_phase（或 completed）
        reject  → layer_complete SSE + 快照 → 设置 need_revision / revision_target_dimensions /
                  revision_feedback（进入级联修订）
    auto 模式：
      layer_complete SSE + KG enrichment + 快照 → 自动推进（或 completed）
```

> **关键**：`interrupt()` 会重放整个节点，因此 SSE 副作用必须放在 interrupt **之后**，否则事件会触发两次（代码注释明确警告）。

---

## 四、边界钩子

| 钩子 | 行为 |
|---|---|
| `_maybe_extract_bindings(session_id, layer)` | **KG 多级富化**：`ReportStore.get_layer_reports` → `kg.enrichment.run_wave(wave=layer)`（L1 村名绑定 / L2/L3 实体注解 + 关系注记），经 `tools.access.shared.resolve_bundle` 取 bundle；非致命 |
| `_snapshot_bundle(session_id, trigger_reason)` | 层边界持久化版本化 session bundle 快照（`services.session_bundle`）；非致命 |

---

## 五、输入输出契约

```
输入:  state（phase / completed_dimensions / is_revision / revision_* / step_mode /
       pending_reports / layer_char_counts）

输出:
  自动推进:  {phase: next_phase, previous_layer: layer, pending_reports: []}
  L3 完成:   {phase: "completed", pending_reports: []}
  修订完成:  {is_revision: False, need_revision: False, revision_feedback: None,
              revision_impact_tree: None, last_revised_dimensions, pending_reports: []}
  reject:    {need_revision: True, is_revision: True, revision_target_dimensions,
              human_feedback, revision_feedback, revision_images, pending_reports: []}
```

SSE 事件：`layer_completed` / `layer_started` / `cascade_complete`（经 `SSEPublisher`）。

---

## 六、相关文档

- `../README.md` — 主图与编排
- `app/modules/kg/README.md` — KG enrichment（多级增强）
- `app/services/session_bundle.py` — 版本化快照
- `app/services/report_store.py` — 报告存储
