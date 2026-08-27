# Relation-Aware TARGET_PROJECTION / EXECUTE Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: 将 06 TARGET_PROJECTION / GROUND / SELECT / EXECUTE 设计落地为一条可恢复、可验证、以真实 GIS 几何和规划关系为核心的执行链，并使用真实金田村数据产生可渲染规划结果。

Architecture: 保留当前会话级 Layer-1 KG、GroundedAnchor、PlaceEvidenceIndex、现有分配器和 delivery 管线，新增 evidence/identity overlay、PlanningIntentGraph、ConstraintFactorGraph、PlanningScenario 四个明确边界。LLM 只从闭集候选中编译目标和关系；确定性 GIS/网络模块生成并验证几何；ExecutionDAG 只负责可恢复执行和 capability deferred。

Tech Stack: Python、Pydantic、rdflib、Shapely、现有 app.spatial、LangGraph checkpointer、artifact CAS、pytest、真实 MiniMax provider、现有渲染脚本。

## Global Constraints

- 真实验收只使用项目已经配置的真实 MiniMax 数据，不输出或记录任何 API key。
- 不使用正则、线宽或 geometry_kind 作为道路、管线等资产类型的主分类器。
- LLM 不得生成 BSM、坐标、WKT、面积、距离、拓扑真值、网络路径或 GIS 分数。
- L1 village anchor 的 BSM 集只能表示 village_scope，不能被当作精确设施点。
- 已完成 artifact 必须在 resume 时复用；失败节点不得重跑无关 L1/L2/L3 或 LLM batch。
- 所有关系、候选几何、约束和验证结果必须带 source、evidence 和 artifact lineage。
- 核心路径不得用 TODO、pass、mock 或空实现代替；不支持能力必须进入 durable deferred。
- 每个改变行为的任务先写回归测试，再实现，再运行 focused pytest。
- 保留当前工作树中的无关用户改动，不执行破坏性清理。

---

### Task 1: 建立实现基线和运行证据边界

Files:
- Create: docs/superpowers/sdd/2026-08-17-relation-aware-target-projection-execute/progress.md
- Create: docs/superpowers/sdd/2026-08-17-relation-aware-target-projection-execute/module-evidence.md
- Modify: docs/design/27_IMPLEMENTATION_VS_DESIGN.md
- Test: backend/tests/core/test_relation_aware_pipeline_contracts.py

Interfaces:
- 输入：06 和 28 设计文档、artifact registry、当前测试配置。
- 输出：module_id 到 implementation_path、artifact_key、verification_command 的映射，以及统一日志字段。

- [ ] Step 1: 把 06 文档的阶段、契约和验收条目登记为模块证据清单。
- [ ] Step 2: 核对 artifact key，确保新增产物不覆盖 grounded_anchors、target_projection、global_site_allocation 和 render_artifacts。
- [ ] Step 3: 测试 artifact descriptor 必须包含 schema_id、schema_version、producer_stage、run_id 和 digest。
- [ ] Step 4: 统一记录 session_id、run_id、stage、dimension、artifact_key、attempt、resume_source、llm_call_id、candidate_count、relation_count、elapsed_ms 和 status。
- [ ] Step 5: 运行 pytest backend/tests/core/test_relation_aware_pipeline_contracts.py -q，先确认缺口，再实现最小日志登记并重跑。

### Task 2: 增加 L1 observation、空间粒度和 entity binding 契约

Files:
- Create: backend/app/contracts/evidence/identity_contracts.py
- Create: backend/app/evidence/identity/observation_store.py
- Modify: backend/app/contracts/spatial/grounding_contracts.py
- Modify: backend/app/contracts/ports/place_resolution_contracts.py
- Modify: backend/app/domain/ground/anchors.py
- Test: backend/tests/core/test_l1_identity_binding_contracts.py

Interfaces:
- EvidenceObservation 保存 observation_id、mention、normalized_name、role、observed_type、source_document_ref、source_span、spatial_hint、relation_mentions、temporal_status、confidence。
- GeometryGranularity 枚举 exact_feature、parcel_set、settlement、village_scope、none。
- GroundedEntityBinding 保存 mention_ref、canonical_entity_ref、status、geometry_granularity、geometry_ref、source_bsms、candidate_refs、evidence_refs、relation_evidence_refs、confidence 和 uncertainty_reason。
- ObservationStore.put_snapshot(session_id, observations, parent_digest) 返回 ArtifactDescriptor。
- ObservationStore.load_snapshot(state) 返回 EvidenceObservation 列表。

- [ ] Step 1: 测试相同名称的 observation 拥有不同 observation_id，同一 canonical entity 可以引用多个 observation。
- [ ] Step 2: 测试 village fallback 只能得到 village_scope，不能填充 exact_feature 或具体 POINT。
- [ ] Step 3: 测试 query_error、ambiguous、unresolved、insufficient_geometry 是不同状态。
- [ ] Step 4: 实现严格 Pydantic 契约和 JSON round-trip。
- [ ] Step 5: 将 GroundedAnchor 映射为 observation/binding 输入，保留旧 grounded_anchors artifact 兼容。
- [ ] Step 6: 将 anchor 增强写入 l1 observation/entity binding overlay，禁止写入 base Layer-1 图。
- [ ] Step 7: 运行 focused pytest 并保存输出。

### Task 3: 将 PlaceEvidenceIndex 改为完整 fingerprint 的可恢复快照

Files:
- Modify: backend/app/evidence/index/place_evidence_index.py
- Modify: backend/app/evidence/index/evidence_scorer.py
- Modify: backend/app/evidence/retrieval/place_evidence_index.py
- Modify: backend/app/workflow/layers/context_bootstrap.py
- Modify: backend/app/infrastructure/artifacts/runtime.py
- Test: backend/tests/core/test_place_evidence_snapshot_resume.py

Interfaces:
- PlaceEvidenceFingerprint.compute(context, l1_digest, resolver_config_digest) 返回 fingerprint。
- PlaceEvidenceIndex.build(context, fingerprint=None) 返回 index。
- PlaceEvidenceIndex.to_snapshot() 返回可序列化 dict。
- PlaceEvidenceIndex.from_snapshot(payload, context) 恢复 index。
- PlaceEvidenceIndex.resolve(mention, allow_llm=False) 返回 PlaceResolutionResult。

- [ ] Step 1: 不同 L1 snapshot digest 产生不同 index fingerprint。
- [ ] Step 2: 进程缓存清空后，bootstrap 恢复 entries、candidates、relation_refs 和 query_trace。
- [ ] Step 3: fuzzy_short_name 不能单独返回 resolved。
- [ ] Step 4: fingerprint 纳入 bundle、Layer-1、derived topology、L1 snapshot、grounded anchors、gazetteer、配置和 resolver 版本。
- [ ] Step 5: 保留 KG 名称、L1 fact、facilities_current、annotations_current 和 parcel centroid cache 作为候选源。
- [ ] Step 6: 将 geometry_near_anchor、geometry_granularity 和 source conflict 加入确定性 evidence。
- [ ] Step 7: resume 时优先加载 index snapshot，digest 不变时跳过重建。
- [ ] Step 8: 运行 focused pytest，确认缓存命中时 LLM call count 为零。

### Task 4: 实现相关 mention 联合消歧

Files:
- Create: backend/app/evidence/identity/mention_graph.py
- Create: backend/app/evidence/identity/joint_resolver.py
- Modify: backend/app/spatial/grounding/resolver.py
- Modify: backend/app/spatial/grounding/report_grounder.py
- Modify: backend/app/infrastructure/llm/instructor_client.py
- Test: backend/tests/core/test_joint_place_resolution.py

Interfaces:
- build_mention_graph(observations, candidate_index) 返回 MentionGraph。
- resolve_joint(graph, evidence_index, llm, budget) 返回 GroundedEntityBinding 列表。
- JointResolutionBatch 保存 mention_refs、candidate_ids、relation_refs 和 evidence_refs。

- [ ] Step 1: 测试同一段落中卫生室、社前村、入口道路共享 scope 和 topology 因子。
- [ ] Step 2: 测试同名设施在不同村域、不同类型下不会因文本相同而合并。
- [ ] Step 3: 测试 LLM 返回候选目录之外的值时被拒绝并降级为 ambiguous。
- [ ] Step 4: 实现名称、角色、类型、village hint、KG serves/nearby 和真实 geometry 候选因子。
- [ ] Step 5: 按相关 mention 组批量调用 LLM，每组独立次数、单次超时和总预算。
- [ ] Step 6: 预算耗尽后保留确定性候选或 ambiguous，不进行串行长尾重试。
- [ ] Step 7: 保存 binding batch artifact 和 query_trace。
- [ ] Step 8: 运行 focused pytest，缓存命中时 LLM call count 必须为零。

### Task 5: 建立 PlanningIntentGraph 和 target projection 编译器

Files:
- Create: backend/app/contracts/planning/intent_graph.py
- Create: backend/app/domain/program/target_projection/intent_graph_compiler.py
- Modify: backend/app/domain/program/assembler.py
- Modify: backend/app/domain/program/target_projection/compile.py
- Modify: backend/app/domain/program/target_projection/gate.py
- Modify: backend/app/contracts/program.py
- Test: backend/tests/core/test_planning_intent_graph_compiler.py
- Test: backend/tests/core/test_target_projection_relation_preservation.py

Interfaces:
- PlanTargetNode 保存 target_id、target_kind、asset_kind、operation、existing_entity_ref、evidence_refs、required_capabilities。
- PlanRelationIntent 保存 relation_id、relation_template、subject_ref、object_ref、criticality、evidence_refs、source_claim_refs。
- PlanningIntentGraph 保存 nodes、relations、source_claim_refs 和 fingerprint。
- compile_planning_intent(program, bindings, rule_catalog) 返回 PlanningIntentGraph。

- [ ] Step 1: 测试设施、聚落、道路和项目的 serve/connect/within 关系在 projection 后仍存在。
- [ ] Step 2: 测试多个硬空间条件默认编译为 AND，显式 alternative_group 才编译为 OR。
- [ ] Step 3: 测试 water_supply、sewer、utility_line 不会映射为 road。
- [ ] Step 4: 实现闭集 target、asset、operation 和 relation template catalog。
- [ ] Step 5: 将 PlanningProgram.dependencies 转成 typed relation edges，旧字符串只作兼容输入。
- [ ] Step 6: 将 LLM draft 解析到真实 binding，禁止自由实体。
- [ ] Step 7: 保存独立 intent graph artifact，GROUND 不原位修改 target projection。
- [ ] Step 8: 运行 focused pytest 并核对 fingerprint 稳定。

### Task 6: 增加点、线、面 CandidateGeometry 和 ConstraintFactorGraph

Files:
- Create: backend/app/contracts/spatial/candidate_geometry.py
- Create: backend/app/contracts/spatial/constraint_factor.py
- Create: backend/app/domain/ground/candidate_geometry.py
- Create: backend/app/domain/ground/constraint_compiler.py
- Modify: backend/app/domain/ground/aggregate.py
- Modify: backend/app/spatial/grounding/grounding.py
- Modify: backend/app/spatial/allocation/global_site_allocator.py
- Test: backend/tests/core/test_typed_candidate_geometry.py
- Test: backend/tests/core/test_constraint_factor_compiler.py

Interfaces:
- GeometryRepresentation 保存 geometry_ref、geometry_kind、representation_role、source_ref、crs、accuracy_m、valid_time。
- CandidateGeometry 保存 candidate_id、target_id、geometry_kind、geometry_ref、source_feature_refs、source_bsms、generation_operation、hard_constraint_status、suitability_components 和 granularity。
- ConstraintFactor 保存 factor_id、template、scope_refs、operator、threshold、unit、hardness、evidence_refs 和 evaluator。
- compile_constraint_factors(intent_graph, evidence_index, bundle, kg) 返回 ConstraintFactor 列表。
- generate_candidates(target, context, factors) 返回 CandidateGeometry 列表。

- [ ] Step 1: facility 生成 point，road/utility 生成 line，zone/project 生成 polygon。
- [ ] Step 2: 缺少真实来源时状态为 insufficient_geometry，不生成默认 WKT。
- [ ] Step 3: 硬约束不满足时排除候选，软约束只产生评分因子。
- [ ] Step 4: 接入真实 bundle 几何、投影 CRS 距离、精确 overlay 和 ConstraintIndex。
- [ ] Step 5: 将旧 CandidateSite 映射到 CandidateGeometry，禁止未标注 geometry 自动归属目标。
- [ ] Step 6: 保存 factor evaluator 的输入 geometry、source BSM、规则版本和测量值。
- [ ] Step 7: 运行 focused pytest，核对点线面类型。

### Task 7: 用真实道路网络完成设施服务和线性目标连接

Files:
- Create: backend/app/domain/scenario/relation_evaluator.py
- Create: backend/app/spatial/network/service_allocation.py
- Modify: backend/app/spatial/network/network_index.py
- Modify: backend/app/domain/allocation/select_service.py
- Modify: backend/app/infrastructure/kg/builder/materialize_topology.py
- Test: backend/tests/core/test_facility_network_service.py
- Test: backend/tests/core/test_linear_target_connectivity.py

Interfaces:
- evaluate_service_relation(scenario, facility, demand_points, network_index) 返回 RelationSatisfaction。
- evaluate_connect_relation(line_candidate, endpoint_refs, network_index) 返回 RelationSatisfaction。
- solve_service_allocation(facility_candidates, demand_points, network_index, capacity, cutoff) 返回 AllocationResult。

- [ ] Step 1: 粗 KG serves/nearby 只能影响 candidate recall，不能直接产生 satisfied。
- [ ] Step 2: 网络不可达、超 cutoff、容量不足分别生成不同 finding。
- [ ] Step 3: 给当前粗关系写入 derivation metadata，继续供 PlaceEvidenceIndex 候选评分。
- [ ] Step 4: 实现 network locating、阻抗矩阵、容量约束和未覆盖需求。
- [ ] Step 5: 实现 road/utility endpoint、junction、corridor 和连通分量检查。
- [ ] Step 6: 保存 demand-to-facility allocation lines、route evidence 和 measured values。
- [ ] Step 7: 运行 focused pytest，纯几何 nearest 不能冒充网络服务。

### Task 8: 生成 PlanningScenario、RelationSatisfaction 和局部重算

Files:
- Create: backend/app/contracts/scenario/planning_scenario.py
- Create: backend/app/domain/scenario/scenario_solver.py
- Create: backend/app/domain/scenario/scenario_artifacts.py
- Modify: backend/app/domain/allocation/select_service.py
- Modify: backend/app/domain/materialization/plan_builder.py
- Modify: backend/app/domain/validation/validate_checks.py
- Test: backend/tests/core/test_scenario_relation_satisfaction.py
- Test: backend/tests/core/test_scenario_incremental_recompute.py

Interfaces:
- PlanningScenario 保存 scenario_id、baseline_ref、selected_candidates、scenario_features、relation_satisfactions、findings、metrics 和 fingerprint。
- solve_scenarios(problem, max_scenarios=3) 返回 PlanningScenario 列表。
- evaluate_scenario(scenario, problem, context) 返回更新后的 PlanningScenario。
- affected_subgraph(change, problem) 返回受影响 target/relation id 集合。

- [ ] Step 1: 测试两个方案共享 baseline 但拥有不同 geometry 和 satisfaction。
- [ ] Step 2: 测试修正一个地名 binding 只重算关联 target/relation。
- [ ] Step 3: 测试关键 relation 缺 satisfaction 时 scenario 不能标记 complete。
- [ ] Step 4: 实现候选选择、资源排他、容量和关系评分。
- [ ] Step 5: 接入 network subproblem，不可达只生成局部 replacement/cut。
- [ ] Step 6: 实现 satisfied、partially_satisfied、violated、not_evaluable、deferred。
- [ ] Step 7: 将 satisfaction 和 findings 接入 VALIDATE 与 delivery manifest。
- [ ] Step 8: 运行 focused pytest。

### Task 9: capability routing、deferred ledger 和 resume

Files:
- Create: backend/app/domain/materialization/capability_registry.py
- Create: backend/app/domain/materialization/deferred_ledger.py
- Modify: backend/app/domain/materialization/nodes/route_prepare.py
- Modify: backend/app/domain/materialization/plan_builder.py
- Modify: backend/app/domain/materialization/execute_agent.py
- Modify: backend/app/infrastructure/runtime/planning_runtime_service.py
- Modify: backend/app/application/commands/resume_checkpoint.py
- Test: backend/tests/core/test_capability_deferred_resume.py

Interfaces:
- CapabilityRegistry.resolve(asset_kind, operation) 返回 CapabilityMatch。
- DeferredSpatialTask 保存 task_id、target_ref、grounded_target_ref、asset_kind、required_capability、reason、retryable 和 artifact_refs。
- DeferredLedger.put(task) 返回 ArtifactDescriptor。
- DeferredLedger.resume_available(capabilities) 返回可执行 DeferredSpatialTask 列表。

- [ ] Step 1: unknown linear/utility target 不进入 road worker。
- [ ] Step 2: unsupported_capability 不重试 LLM、不重跑 grounding，新增 capability 后可以 resume。
- [ ] Step 3: 实现 road、water_supply、sewer、stormwater、power、communication、drainage_channel 的显式 registry。
- [ ] Step 4: 修改 route_prepare，防止静态默认边和动态路由重复执行。
- [ ] Step 5: 持久化 deferred task、grounded_target_ref、relation 和 candidate artifact。
- [ ] Step 6: resume 只派发新增 capability 可处理的 task，并验证 artifact digest 不变。
- [ ] Step 7: 运行 focused pytest。

### Task 10: 真实运行、交付和渲染

Files:
- Modify: backend/app/workflow/stages/ground.py
- Modify: backend/app/workflow/stages/select.py
- Modify: backend/app/workflow/stages/execute.py
- Modify: backend/app/workflow/stages/deliver.py
- Modify: scripts/run_pipeline_real_jintian.py
- Modify: scripts/render_integrated_map.py
- Create: scripts/audit_relation_aware_run.py
- Test: backend/tests/acceptance/test_real_relation_aware_run.py

Interfaces:
- run_relation_aware_real(session_id, resume=True) 返回 RunAuditReport。
- audit_relation_aware_run(run_dir) 返回 RunAuditReport。
- render_integrated_map 必须输出 target projection、planning route 和 integrated render 三类文件。

- [ ] Step 1: GROUND、SELECT、EXECUTE 只读取上游 artifact，写自己的产物，不修改 target projection。
- [ ] Step 2: 每个阶段记录 start、complete、fail、resume、artifact digest、LLM calls、candidate count、relation count 和 elapsed time。
- [ ] Step 3: 使用真实金田村 bundle，记录实际 parcel、road、constraint、KG triple、anchor、binding、candidate 和 scenario 数量。
- [ ] Step 4: 运行主流程并确认三类渲染/图层文件存在。
- [ ] Step 5: 第二次 resume 必须复用完成阶段且不重复 LLM call。
- [ ] Step 6: 运行真实 acceptance 测试，最终验收不以 fixture/mock 代替。

### Task 11: 连续三次运行、视觉检查和逻辑审查

Files:
- Create: docs/superpowers/sdd/2026-08-17-relation-aware-target-projection-execute/run-1.md
- Create: docs/superpowers/sdd/2026-08-17-relation-aware-target-projection-execute/run-2-resume.md
- Create: docs/superpowers/sdd/2026-08-17-relation-aware-target-projection-execute/run-3-replay.md
- Create: docs/superpowers/sdd/2026-08-17-relation-aware-target-projection-execute/visual-review.md
- Create: docs/superpowers/sdd/2026-08-17-relation-aware-target-projection-execute/logic-review.md

- [ ] Step 1: fresh、resume、artifact replay 各运行一次，保存命令、时间、日志摘要和 digest。
- [ ] Step 2: 比较 target projection、selected geometry、scenario metrics、satisfaction 和 render manifest。
- [ ] Step 3: 用当前可用视觉工具检查目标投影、路径可执行性、图层清晰度和空间偏差；如果 Minimax 视觉 MCP 未连接，明确记录工具缺失，不伪造 Minimax 结论，并完成本地图像审查。
- [ ] Step 4: 至少记录目标关系遗漏、粗粒度定位误读、网络服务或容量不足三类逻辑风险，并给出可执行建议。
- [ ] Step 5: 每个偏差记录模块、证据、原因、方案、影响范围和优先级。

### Task 12: 沉淀结构化规划优化 prompt 和最终审计

Files:
- Create: docs/prompts/RELATION_AWARE_SPATIAL_PLANNING_OPTIMIZER.md
- Create: docs/superpowers/sdd/2026-08-17-relation-aware-target-projection-execute/final-audit.md
- Modify: docs/design/modules/spatial-execution/28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md

- [ ] Step 1: 从真实日志提取输入契约、闭集枚举、证据格式、失败状态和 resume 规则。
- [ ] Step 2: 写出 prompt 的输入、禁止事项、输出 schema、关系模板、证据引用和 validator 反馈格式。
- [ ] Step 3: 明确只能选择证据目录中的实体和候选，无法确定时输出 ambiguous/unresolved。
- [ ] Step 4: 用真实 replay 验证 prompt 不生成 BSM、WKT、自由 asset_kind 或 road fallback。
- [ ] Step 5: final-audit 逐项映射实现、真实日志、渲染、视觉检查、三次一致性、逻辑不足和 P0 记录。

## Verification Matrix

| 要求 | 证据 |
|---|---|
| 设计条目实现 | module-evidence、代码路径、focused pytest |
| 无核心空实现 | 核心路径的静态扫描和人工异常分支审查 |
| 真实执行 | run-1、真实 bundle digest、provider 日志和 artifact manifest |
| 目标投影图 | render manifest 的 target projection layer |
| 规划路径图 | route/allocation layer 和 RelationSatisfaction |
| 综合渲染图 | render_integrated_map 输出和本地图像审查 |
| Minimax 视觉校验 | visual-review，工具不可用时明确记录 |
| resume 不重复调用 | run-2 的 LLM call diff 和 artifact digest |
| 连续三次一致 | 三次 run 的 canonical digest 和 metrics 对比 |
| 逻辑不足至少三条 | logic-review |
| P0 重构记录 | 27 差异台账和 final-audit |

## Self-Review Coverage

本计划覆盖 06 文档的四阶段边界、三张图、契约、真实数据验收和迁移顺序，也覆盖 28 文档的
L1 observation、设施 KG、evidence provenance、空间粒度、typed geometry、网络服务、
scenario satisfaction、deferred capability 和 resume。Minimax 视觉 MCP 是否在当前工具集可用
是开放事实，必须在真实渲染产物生成后记录工具结果，不能通过文字推断完成。

