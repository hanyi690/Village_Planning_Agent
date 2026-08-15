# 落地路线图：侧线模块主链接线与 fail-closed 收尾

> 状态：`ROADMAP / PLAN` · 本文把 [18_EXA_ARCHITECTURE_ALIGNMENT.md](18_EXA_ARCHITECTURE_ALIGNMENT.md)
> 的对齐结论拆成可勾选的按模块落地清单。每项含：目标 / 涉及文件 / 验收标准 / 台账状态引用。
> 完成状态以 [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md) 为准；本文只负责"下一步做什么、怎么验收"。

核心判断：`semantic_repair` / `repair_directives` / `repair_impact` / `terrain` / `global_zone_parcel_allocator` /
`road_candidate_preparation` 六个"正确设计"模块已存在且有测试，但它们与 `select_service` / `zone_worker` /
`RoadGenerator` / `validate→execute` 之间的主链 wiring 是当前唯一的关键缺口；其次是拆除 `grounding.py` 的
几何兜底与补齐 finding lineage。

---

## P0 — 全局 Zone 分配器接入主链（消除 2824 重复 BSM 根因）

**目标**：zone 从"每个 target 独立重分类同一批地块 + 无条件 merge"改为"一次全局求解 + 每 BSM 唯一权威地类"。

- [ ] `workflow/stages/select.py`：把 `allocate_zones_for_select` 替换为
      `DeterministicGlobalZoneParcelAllocator.allocate(problem)`；`Suitability→ZoneCandidateSet` 由
      `terrain_adapter` + `spatial_factors` 产出，禁止空候选全村回退（§18.4.1/18.4.2）。
- [ ] `domain/materialization/zone_worker.py`：只消费 `AuthoritativeZoneParcelAssignment` 生成 parcel change；
      overlay（protection/restoration）走独立图层；写 PlannedState 前按 BSM 二次校验唯一性（§18.4.4）。
- [ ] `domain/allocation/select_gate.py`：`MODEL_INVALID/INFEASIBLE/SOLVER_*` 阻断；
      `PARTIAL` 按 `ZoneAreaBalance` 生成目标级 reallocate/exclude 指令（§18.4.3）。

**验收**：同一 session 内不再出现同一 BSM 被多个 zone 改写为不同地类；`PlannedState` 无重复 BSM；
`sum(x[target,bsm]) <= 1` 在真实结果中成立。

**涉及文件**：`spatial/allocation/global_zone_parcel_allocator.py`、`contracts/spatial/global_zone_allocation_contracts.py`、
`workflow/stages/select.py`、`domain/materialization/zone_worker.py`、`domain/allocation/select_gate.py`。

---

## P0 — VALIDATE 调整被 EXECUTE worker 真正消费（打通自动重规划闭环）

**目标**：让 `rebuild_geometry` / `require_source_evidence` 指令实际驱动 worker，而不是只回 SELECT。

- [ ] `workflow/stages/execute.py`：EXECUTE 前置读取 `repair_directives` / `repair_impact` artifact；
      对 `rebuild_geometry`（topology/continuity/area/road_route_failed）只重派发受影响 target 的 worker task
      并注入 `rebuild_strategy`；对 `require_source_evidence` 不派发并显式 unresolved。
- [ ] `domain/materialization/zone_worker.py` / `road_worker.py`：消费 directive 的
      `exclude_bsms`/`affected_bsms`/`rebuild_strategy` 字段，禁止静默合并。

**验收**：同一 `overlap`/`hard_constraint` finding 触发一轮后 violation 计数下降，而非三轮结果不变
（对应迭代日志 §13.6 的"EXECUTE 三轮不变"）。

**涉及文件**：`workflow/stages/execute.py`、`domain/materialization/zone_worker.py`、
`domain/materialization/road_worker.py`、`domain/validation/repair_directives.py`（已实现）。

---

## P1 — Road Contract 侧线接入主链（现状路提质 vs 新建走廊）

**目标**：区分 `existing_road_intervention` 与 `new_corridor`，产出可审计 planned_road。

- [ ] `spatial/network/road_candidate_preparation.py` 接入真实链：在 Stage 2.6 前调用
      `prepare_road_candidates()`（§16.3/§16.5 已给出接入顺序）。
- [ ] `domain/materialization/road_generator.py`：`ExistingRoadPlanningInput` → 独立 segment-operation
      materializer；`NewCorridorPlanningInput` → 把 DEM/land-friction/hazard 显式映射进 `RoadPlanningConfig`
      （删无 DEM 时的生产级 geometric family fallback，仅测试保留并标非权威）。
- [ ] `domain/ground`：existing action 的 `alignment_refs` 解析为真实 feature/segment id；new action 的
      `connects` 解析为两个带 provenance 的 `RoadEndpointEvidence`，禁止方向 bbox 升级为 confirmed（§16.5.2）。
- [ ] resume 边界：action/kind 错 → L3；地点/road-id 绑定错 → GROUND；成本面变化 → candidate preparation/Stage4（§16.5.5）。

**验收**：`planned_road` 非空且每条线带现状 feature/segment 或双端点 provenance；
`ROAD_EXISTING_BINDING_MISSING` / `ROAD_ENDPOINT_PROVENANCE_MISSING` 稳定 code 不产生伪线。

**涉及文件**：`spatial/network/road_candidate_preparation.py`、`contracts/domain/road_planning.py`、
`domain/materialization/road_generator.py`、`domain/ground/*`。

---

## P1 — SELECT 真实适宜性闭环（DEM + 约束 + 服务覆盖 + 全局分配）

**目标**：SELECT 不再用 grounding confidence 代替适宜性（迭代日志 §13.6 历史缺陷）。

- [ ] `workflow/stages/select.py`：确认 `build_suitability_surface` 已把 `TerrainEvidenceService` +
      `spatial_factors`（road_access/service_coverage/hazard）并入 score，而非沿用 confidence 投影。
- [ ] `domain/suitability/spatial_factors.py`：补齐 farmland/ecological 的实际 overlap 计算
      （当前仅 `source_only` 审计，未算 overlap），输出 `EliminatedCandidate` 稳定原因码。
- [ ] `domain/allocation/select_gate.py`：DEM 缺失但有坡度要求 / constraint index 不可用 /
      所有候选违反硬约束时 fail-closed（对应 GeoBenchX 的 reject 语义）。

**验收**：候选分数有可解释 breakdown（slope/hazard/road_access/service_coverage/hazard_safety），
被过滤候选进入 `EliminatedCandidate` 且带稳定原因码。

**涉及文件**：`domain/suitability/terrain.py`、`terrain_adapter.py`、`spatial_factors.py`、`service.py`、
`workflow/stages/select.py`、`domain/allocation/select_gate.py`。

---

## P2 — 拆除 GROUND 全村几何兜底 + 结构化不确定性

**目标**：地名解析失败保持 typed `unresolved`，不静默扩候选池。

- [ ] `spatial/grounding/grounding.py`：删除 `_resolve_directional`/`_village_center` 的村级质心 + buffer
      兜底；方向词只允许经 resolver 的 BSM-backed 结果；`ground_zone/facility/linear_spatial_preference`
      候选为空时返回 typed `unresolved`。
- [ ] `spatial/grounding/resolver.py`：cluster fallback 收敛为 `resolved/ambiguous/unresolved` 三态，
      不静默扩大候选池。
- [ ] `contracts/spatial/grounding_contracts.py`：给 candidate 增 `uncertainty{radius_m, reason_code}`；
      候选置信度从 {0,0.7,1} 扩为带证据权重的可解释分（见 12_PLACE_NAME_RESOLUTION.md 第 4.2 节）。

**验收**：`GROUND` 不再把"全村 466 地块"作为单一候选；方向/村名无数据时 `unresolved_reason` 稳定输出。

**涉及文件**：`spatial/grounding/grounding.py`、`resolver.py`、`contracts/spatial/grounding_contracts.py`。

---

## P2 — 补齐 finding producer lineage

**目标**：让 `compile_repair_directives` 不再因缺 lineage 而整批 `blocked`。

- [ ] `domain/validation/validate_checks.py`：给 `area_conservation` / `topology` / `continuity` /
      `accessibility` / `classification_missing` 补 `target_ids`/`bsms`/`evidence_refs`（§18.5 已列清单）。

**验收**：上述 finding 出现时可编译为具体 `rebuild_geometry`/`reallocate` 指令，而非 `missing_*_lineage` blocked。

**涉及文件**：`domain/validation/validate_checks.py`、`repair_directives.py`。

---

## P3 — LLM access 工具绑定（闭集动作空间）

**目标**：让 6 个 access 工具从"死注册"变为可被 explore 场景 LLM 实际调用。

- [ ] `workflow/tools/execute_node.py`：修复读 `ToolRegistry.get_tool()` 而非遗留空 `TOOL_REGISTRY`（17 文档 3.4）。
- [ ] `workflow/conversation/node.py`：为 explore 场景 `llm.bind_tools(ToolRegistry.for_agent("explore"))`（17 文档 3.3）。

**验收**：access 工具经通用执行路径可执行并返回 `ToolMessage`，不再抛"工具未注册"。

**涉及文件**：`workflow/tools/execute_node.py`、`workflow/conversation/node.py`、
`infrastructure/llm/tools/access/*`。

---

## P4 — 渲染优化（最后做）

**目标**：权威几何稳定后补齐图面质量；视觉审查作为 QA，不作几何真值源。

- [ ] 道路分级线宽、比例尺、点位标签避让、规划/现状差异高亮、图例与图层一致。

**验收**：MiniMax 视觉审查确认道路可见、点位可辨、变更可辨、比例尺存在。

**涉及文件**：`infrastructure/rendering/*`、`workflow/stages/deliver.py`。

---

## 参考

- [18_EXA_ARCHITECTURE_ALIGNMENT.md](18_EXA_ARCHITECTURE_ALIGNMENT.md)：对齐结论
- [16_20260813_ITERATION_LOG.md](16_20260813_ITERATION_LOG.md)：本轮迭代细节（§13–§19 与 P0–P2 逐条对应）
- [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md)：状态台账
