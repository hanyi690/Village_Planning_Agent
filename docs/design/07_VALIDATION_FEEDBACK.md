# 校验、级联修订与人工审查

> **Evaluator Gate 保证布局质量，级联修订保证文本一致性，interrupt() 实现人工审查。**
> 对应 `00_SYSTEM_DESIGN` 第五部分（闭环反馈）展开。

---

## 1. 三层校验体系

```
┌─────────────────────────────────────────────────────────┐
│  层1: EXECUTE Evaluator Gate (空间布局校验)              │
│  layout/facility/axis/road -> validate (max 3 retry)    │
│  粒度: 图斑级 | 触发: 自动 | 反馈: constraint_adjustments│
├─────────────────────────────────────────────────────────┤
│  层2: 级联修订 (文本维度一致性)                          │
│  feedback -> impact_tree -> Wave 0..N 重算              │
│  粒度: 维度级 | 触发: 人工反馈 | 反馈: 重置完成状态      │
├─────────────────────────────────────────────────────────┤
│  层3: 人工审查 (layer_completion_check interrupt)        │
│  step_mode -> pause -> approve/reject                   │
│  粒度: 层级 | 触发: 每层完成 | 反馈: advance/revision   │
└─────────────────────────────────────────────────────────┘
```

---

## 2. EXECUTE Evaluator Gate

### 2.1 路由逻辑

`layout_pipeline.py:333` `_route_after_validation`（legacy 层）+ `execute/agent.py:357` `_route_after_validate`（子图内）：

```python
def _route_after_validate(state) -> Literal["pass", "retry"]:
    result = state.validation_result or {}
    if result.get("passed", False):
        return "pass"
    if state.validation_round >= 3:
        logger.warning("validation exceeded 3 rounds - using best result")
        return "pass"
    return "retry"
```

### 2.2 重试回路

```
execute_layout ──> validate ──(fail, round<3)──> retry
                      │                          │
                      │                    constraint_adjustments
                      │                          │
                      │                    ┌─────┘
                      │                    ▼
                      │              execute_layout (调整 target_map)
                      │                    │
                      │              ... validate (round+1)
                      │
                      ├──(pass)──────> write_l4 ──> END
                      └──(fail, round>=3)──> pass (最优) ──> write_l4 ──> END
```

`validate` 节点（execute/agent.py:298）调用 `LayoutValidator.validate`，产出：
- `passed`: bool
- `status`: "pass" / "warn" / "fail"
- `violations`: List[{check, message}]
- `constraint_adjustments`: List[{zone, action, delta_ha, reason, priority}]

`constraint_adjustments` 反馈到 `execute_layout`：
```python
# execute/agent.py:102-111
if state.constraint_adjustments:
    for adj in state.constraint_adjustments:
        zone = adj.get("zone", "")
        delta = adj.get("delta_ha", 0)
        if zone in target_map and delta:
            target_map[zone] = round(target_map[zone] + delta, 2)
```

---

## 3. 级联修订

### 3.1 触发条件

人工反馈（reject）或 `need_revision=True` + `feedback` 存在时触发：

```
layer_completion_check (reject)
  -> need_revision=True, revision_target_dimensions=[dim_keys], revision_feedback=text
  -> after_conversation 检测 need_revision
  -> 计算影响树
  -> 分发 Wave 0
```

### 3.2 影响树计算

`routing.py:50-104` `after_conversation` 中：

```python
# routing.py:63-74
final_tree = state.get("revision_impact_tree")
if not final_tree:
    downstream_tree: Dict[int, List[str]] = {}
    for target_dim in target_dims:
        tree = get_impact_tree_compat(target_dim)  # dependency.py:149
        for wave, dims in tree.items():
            downstream_tree.setdefault(wave, []).extend(dims)

    wave0_dims = list(set(target_dims))
    final_tree = {0: wave0_dims}
    for wave in sorted(downstream_tree.keys()):
        final_tree[wave] = list(set(downstream_tree[wave]))
```

`get_impact_tree_compat`（dependency.py:149）正确计算 Wave 编号：
- 目标维度 Wave = 0
- 下游维度 Wave = max(依赖维度的 Wave) + 1
- 迭代计算直到所有维度 Wave 稳定

### 3.3 Wave 分发

```
Wave 0: 目标维度（直接修订）
  -> Send("analyze_dimension", {is_revision=True, revision_impact_tree=final_tree})

Wave 1..N: 下游维度（依赖 Wave 0 完成）
  -> after_analysis 检查依赖完成
  -> Send("analyze_dimension", {is_revision=True, ...})
```

`routing.py:85-104` 仅分发 Wave 0：
```python
# 重置受影响维度的完成状态
all_dims = [d for dims in final_tree.values() for d in dims]
new_completed = _reset_dimensions(state.get("completed_dimensions", {}), all_dims)

# 仅分发 Wave 0（目标维度）
return [Send("analyze_dimension", {
    **state, "dimension_key": d,
    "completed_dimensions": new_completed,
    "is_revision": True,
    "revision_impact_tree": final_tree,
    "revision_feedback": feedback,
    "revision_completed_dims": {},
}) for d in wave0_dims]
```

### 3.4 修订后路由（after_analysis）

`routing.py:129-236` 处理修订波次推进：

```python
# routing.py:184-226
ready_dims = []
for dim_key in all_revision_dims:
    if dim_key in revision_completed:
        continue  # 已修订完成

    # 检查同层依赖 + 跨层依赖
    same_layer_ok = all(dep in all_completed for dep in same_layer_deps)
    cross_layer_ok = all(dep in all_completed for dep in cross_layer_deps)

    if same_layer_ok and cross_layer_ok:
        ready_dims.append(dim_key)

if ready_dims:
    return [Send("analyze_dimension", {...}) for d in ready_dims]
```

### 3.5 级联修订流程图

```
用户反馈 (reject + feedback + target_dims)
    │
    ▼
after_conversation
    │
    ├── 计算/读取 impact_tree (get_impact_tree_compat)
    │   Wave 0: [target_dim_A, target_dim_B]
    │   Wave 1: [downstream_C (dep A), downstream_D (dep B)]
    │   Wave 2: [downstream_E (dep C, D)]
    │
    ├── _reset_dimensions: 重置 all_dims 的 completed 状态
    │
    └── Send Wave 0 -> analyze_dimension (is_revision=True)
            │
            ▼
        after_analysis (is_revision=True)
            │
            ├── 检查 revision_completed: C 的依赖 A 完成? -> ready
            ├── Send C -> analyze_dimension
            │
            ├── D 的依赖 B 完成? -> ready
            ├── Send D -> analyze_dimension
            │
            ▼
        after_analysis
            │
            ├── E 的依赖 C, D 都完成? -> ready
            ├── Send E -> analyze_dimension
            │
            ▼
        layer_completion_check (is_revision=True)
            │
            ├── all_completed == all_dims? -> cascade_complete SSE
            │   return {is_revision: False, need_revision: False}
            │
            └── 否 -> 等待
```

### 3.6 影响树示例

假设用户反馈修改 `resource_endowment`（L2 Wave 1）：

```
get_impact_tree_compat("resource_endowment") 返回:

  Wave 0: [resource_endowment]          (目标维度)
  Wave 1: [planning_positioning]        (dep resource_endowment)
  Wave 2: [development_goals]           (dep resource_endowment, planning_positioning)
  Wave 3: [planning_strategies]         (dep 前3个L2维度)
  Wave 1: [land_use_planning]           (L3, phase_dep resource_endowment)
  Wave 1: [spatial_structure]           (L3, phase_dep resource_endowment)
  Wave 2: [project_bank]                (L3, dep land_use_planning + traffic_planning)
  ...
```

> Wave 编号基于 `max(依赖维度的 Wave) + 1`，非简单 BFS 层级。如 `project_bank` 依赖 industry(Wave 1) 和 traffic_planning(Wave 2)，则 project_bank 在 Wave 3。

---

## 4. 跨层提前分发

`routing.py:262-287` 实现 continuous mode 下的跨层提前分发：

```python
# routing.py:262-287
cross_ready = []
next_layer = layer + 1
if next_layer <= 3 and not step_mode:
    next_dims = list_dimensions(next_layer)
    for dim in next_dims:
        if dim.key in next_completed:
            continue
        # 同层依赖已完成
        if not all(dep in next_completed for dep in dim.depends_on):
            continue
        # 跨层依赖（layer_depends_on）已完成
        cross_deps = list(getattr(dim, 'layer_depends_on', []) or [])
        if not all(dep in completed for dep in cross_deps):
            continue
        # 阶段依赖（phase_depends_on）的前层已完成
        phase_deps = list(getattr(dim, 'phase_depends_on', []) or [])
        if not all(dep in prev_completed for dep in phase_deps):
            continue
        cross_ready.append(dim.key)
```

**效果**：L2 某维度完成且其 L3 下游的跨层依赖就绪时，L3 维度可提前启动，不必等 L2 全部完成。

---

## 5. 人工审查

### 5.1 layer_completion_check + interrupt()

`completion/node.py:20` 使用 LangGraph `interrupt()` 实现 step_mode 暂停：

```python
# completion/node.py:144-158
if step_mode:
    # CRITICAL: interrupt() BEFORE any SSE side effects
    # On resume, entire node re-executes, so events before interrupt() would fire twice
    resume_data = interrupt({
        "layer": layer,
        "phase": phase,
        "layer_name": get_layer_name(layer),
        "reason": "step_mode_awaiting_review",
    })
    action = resume_data.get("action", "approve")
```

### 5.2 审查动作

| 模式 | action | 效果 |
|------|--------|------|
| step_mode | approve | 推进到下一层（send layer_completed + layer_started） |
| step_mode | reject | 启动级联修订（need_revision=True, revision_target_dimensions） |
| auto | - | 自动推进（send layer_completed + layer_started） |

```python
# completion/node.py:169-220
if action == "approve":
    SSEPublisher.send_layer_complete(...)
    if layer < 3:
        next_phase = get_next_phase(phase)
        SSEPublisher.send_layer_start(...)
        return {"phase": next_phase, "pending_reports": []}
    return {"phase": "completed", "pending_reports": []}

elif action == "reject":
    SSEPublisher.send_layer_complete(...)
    return {
        "need_revision": True,
        "is_revision": True,
        "revision_target_dimensions": resume_data.get("dimensions", []),
        "human_feedback": resume_data.get("feedback", ""),
        "revision_feedback": resume_data.get("feedback", ""),
        "revision_images": resume_data.get("images", []),
    }
```

### 5.3 修订完成检测

`completion/node.py:52-106` 检测级联修订是否全部完成：

```python
if state.get("is_revision"):
    impact_tree = state.get("revision_impact_tree", {})
    completed = state.get("revision_completed_dims", {})
    all_completed = [d for dims in completed.values() for d in dims]
    all_dims = [d for dims in impact_tree.values() for d in dims]
    all_dims.extend(target_dims)

    if set(all_completed) == set(all_dims):
        SSEPublisher.send_event(
            session_id=session_id,
            event_type="cascade_complete",
            revised_dimensions=all_dims,
        )
        return {
            "is_revision": False,
            "need_revision": False,
            "revision_impact_tree": None,
            "last_revised_dimensions": all_dims,
        }
```

---

## 6. SSE 事件

| 事件 | 触发 | 发送者 |
|------|------|--------|
| `layer_started` | 层开始 | completion/node.py:182 |
| `layer_completed` | 层完成 | completion/node.py:171 |
| `pause` | step_mode 暂停 | sse_publisher.py:167 send_layer_paused |
| `resumed` | 审批恢复 | sse_publisher.py:177 send_execution_resumed |
| `dimension_start` | 维度开始 | sse_publisher.py:186 |
| `dimension_complete` | 维度完成 | sse_publisher.py:215 |
| `cascade_complete` | 级联修订完成 | completion/node.py:93 |

---

## 7. 实现状态总览

| 组件 | 状态 | 证据 |
|------|------|------|
| **Evaluator Gate** | | |
| validate 节点 | `[IMPLEMENTED]` | execute/agent.py:298 |
| _route_after_validate (max 3) | `[IMPLEMENTED]` | execute/agent.py:357 |
| _route_after_validation (legacy) | `[IMPLEMENTED]` | layout_pipeline.py:333 |
| constraint_adjustments 反馈 | `[IMPLEMENTED]` | execute/agent.py:102-111 |
| LayoutValidator | `[IMPLEMENTED]` | tools/gis/_validation/layout_validator.py |
| **级联修订** | | |
| after_conversation 修订路由 | `[IMPLEMENTED]` | routing.py:50-104 |
| get_impact_tree_compat | `[IMPLEMENTED]` | dependency.py:149 |
| _reset_dimensions | `[IMPLEMENTED]` | routing.py:315 |
| after_analysis 修订波次推进 | `[IMPLEMENTED]` | routing.py:129-236 |
| 修订完成检测 | `[IMPLEMENTED]` | completion/node.py:52-106 |
| cascade_complete SSE | `[IMPLEMENTED]` | completion/node.py:93 |
| **跨层提前分发** | | |
| cross-layer early dispatch | `[IMPLEMENTED]` | routing.py:262-287 |
| **人工审查** | | |
| interrupt() step_mode | `[IMPLEMENTED]` | completion/node.py:153 |
| approve/reject 动作 | `[IMPLEMENTED]` | completion/node.py:169-220 |
| auto-advance | `[IMPLEMENTED]` | completion/node.py:222-254 |
| **L3 校核轮** | | |
| L3 读 L4 对账 | `[PLANNED]` | I5 改造 |
| after_analysis L3完成->explore | `[PLANNED]` | I6 改造 |
