# Wave N — Flash LLM Summary + 死代码清理 + P1-P5 PARTIAL 点全修复

> 分支：`refactor/phase1-planning-context`
> 状态：awaiting_review（全部任务完成，1307 passed / 0 failures）
> 日期：2026-08-05

## 目标

在 Wave M2 全链贯通的基础上，消除上一波遗留的 5 个 PARTIAL 点，并用 Flash LLM 提升结构化摘要质量、清理 EXPLORE 死代码。

## 任务清单（TDD red→green→commit，子代理分批派发）

| # | 任务 | 子代理 commit |
|---|---|---|
| N1 | 死代码清理：删除 `explore/summaries.py`(301) + `bridge_advisor.py`(163) + `test_bridge_advisor.py`(103)；更新 `__init__.py`/`README.md`/`session_kg.py:4` | `2411f4f1` |
| N2 | 重建 `core/instructor_client.py` + 重写 `modules/parsing/summary_generator.py`（Flash LLM 3 层：regex→Instructor→fallback）+ `test_summary_generator.py` | `2098fc91` |
| N3 | P1 SELECT 评分：`selection.py` 拓宽 `rank_candidates` 返回 `ScoredCandidate`、`PlacementDecision` 加 `ranking/selected_score`、`aggregate.py` 用真实 breakdown | `f57e192e` |
| N4 | P4 RECONCILE：`build_coverage_matrix` 语义 ID 匹配（candidate→selection 用 `source_parcels`∩BSM）+ 打乱顺序测试 | `35e3755e` |
| N5 | P3 EXECUTE：validate 生成 `ConstraintAdjustment` + `_validate_node` 映射 legacy shape + `_execute_layout_node` 消费 adjustments（Gap A/B/C 三层闭环） | `c861c218` |
| N6 | P2 PARSE：`llm_patch.py` + `compile_program_async` 激活 LLM patch（REPAIR/REVISE 不再统一 NEEDS_REVIEW） | `d3ff58cf` |
| N7 | P5 HITL：post-L3 链 `human_review_node` interrupt + checkpointer + `post_l3_resume.py` + `human_review_routes.py` API + AgentState 新字段 | `2af39f5f` |
| N8 | 护栏 + 全量测试（主代理） | - |
| N9 | 文档同步（未提交） | - |

## 各任务关键决策

### N2 摘要生成器（3 层 pipeline）
- **Layer 1** regex：`_extract_metrics_regex`（8 种通用数值模式）+ `_extract_dimension_metrics`（4 维度特定规则）+ `_extract_key_points_regex`（###/粗体）+ `_normalize_metric_keys`
- **Layer 2** Instructor：`get_instructor_client()` + `response_model=dim_schema`，`max_tokens=800/temp=0.1/max_retries=3`，后处理（text_summary≤200/key_points≤5/schema fields→metrics 同步）
- **Layer 3** fallback：失败→seed_metrics + regex key_points
- 接口签名不变：`generate_structured_summary(dimension_key, layer, content) -> str`

### N3 P1 SELECT 评分
- 根因：`score_candidates` 算出的分数在 `rank_candidates` 的 `return [s.bsm for s in scored]` 被丢弃
- 修复：`rank_candidates` 返回 `List[ScoredCandidate]`；`PlacementDecision` 新增 `ranking`/`selected_score`
- `road_access`/`service_coverage` 仍为 0.0 stub（从未计算，需外部路网/服务数据，Wave H 已记录 deferred）
- `_SCORE_BREAKDOWN_STUBS` 保留仅用于这两个零 stub 兜底

### N4 P4 RECONCILE 语义 ID
- intervention→spec、spec→candidate：无 join key（schema 缺字段），保留位置对齐并注释
- **candidate→selection 改进**：`next((b for b in selected if b in candidate.source_parcels))` 替代 `selected[i]`
- selection→change→planned：已有 BSM 语义匹配，保留

### N5 P3 EXECUTE 反馈闭环
- **Gap A** `validate/aggregate.py`：对失败 check 合成 `ConstraintAdjustment(constraint_id=check_id, adjustment_type="relax", ...)`
- **Gap B** `_validate_node`：`_delta_ha_from`（adjusted-original）+ 映射 legacy `{zone, action, delta_ha, reason, priority}`；`tools/gis/validate.py` 兼容 dict/对象访问
- **Gap C** `_execute_layout_node`：读 `state.constraint_adjustments`，按 `land_use/planning_zone/zone_id` 匹配 zone target，delta_ha 叠加 area_ha（未匹配安全跳过）

### N6 P2 PARSE LLM patch
- 新增 `compile_program_async`（不破坏同步 `compile_program` 向后兼容）
- `llm_patch.py`：Instructor + Flash，白名单路径（typed_intent.*/project_requirements/spatial_reference_specs，对齐 `merge_node._is_supported_path`），`CompilationPatchList` response_model，`_finalize_patches` 截断 5 条
- `route == "llm_patch"` → 生成+应用 patches；失败/空 → `route = "human_review"` → NEEDS_REVIEW

### N7 P5 HITL
- `GraphInterrupt` 在 `langgraph.errors`；`interrupt`/`Command` 在 `langgraph.types`（LangGraph 1.2.9）
- 带 checkpointer 时 `ainvoke` 不抛异常，返回含 `__interrupt__` 键的 state（`Interrupt.value` 即 payload）；无 checkpointer 才抛
- `gis_agent_entry.py` 双路径兜底：`except GraphInterrupt` + `chain_result.get("__interrupt__")`
- `PlanningContext` 含 `kg_query_fn` 闭包无法 msgpack 序列化 → 图输入剥离 context（存 None），`_resolve_context` 回退 `get_cached_context(session_id)`
- `post_l3_resume.py`：同 checkpointer 重建链，`Command(resume=decisions)` + `astream(stream_mode=["values"], version="v2")`，结果写 `.run-tmp/post_l3/{session_id}/result.json`（`PostL3ResultStore`）+ best-effort 回写主图 AgentState
- API：`GET /api/human-review/{session_id}` + `POST /api/human-review/{session_id}/resolve`，注册于 `api/routes.py`
- AgentState 新增：`post_l3_pending_review`/`post_l3_thread_id`/`post_l3_status`/`post_l3_decisions`（conservative，默认值）

## 验证结果

- **全量：1307 passed / 0 failures**（Wave M2 基线 1280 → 1307）
- 护栏：architecture_invariants + no_advisory_crosswalks + advisory_isolation + legacy_fail_closed + import_graph → 23 passed
- 子图 crosswalk 护栏（bootstrap/execute/validate/reconcile/parse/deliver/ingest）→ 27 passed
- kg→data 边界（bundle_assembly_port + graphify_artifact）→ 6 passed
- advisory_crosswalks violation budget 保持 0

## 遗留（明确不在此波范围）

- `road_access`/`service_coverage` SELECT 评分仍为 0.0 stub（需外部路网/服务设施数据源）
- RECONCILE intervention→spec、spec→candidate 层仍位置匹配（schema 无 ID join key）
- P2 的 `generate_llm_patches` 走真实 Flash 调用需 `GIS_EXPLORE_LLM_ENABLED`/API key（测试已 mock）
- 前端 HITL 交互 UI 未实现（仅后端 interrupt/resume API）
