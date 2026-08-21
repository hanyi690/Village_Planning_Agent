# 当前实现状态补充（2026-08-18）

本文承接已归档的 `../_archive/design/10_IMPLEMENTATION_STATUS.md` 历史台账。旧文档中的“当前活动 demo 规划图层为 0”
仍适用于 `fresh-ground-20260817-test3` 和默认旧入口，但不能覆盖最新的 source-aware clone-only
replay28。后续阅读实现状态时，以本文、
[`RELATION_AWARE_MODIFICATION_LEDGER.md`](RELATION_AWARE_MODIFICATION_LEDGER.md) 和
[`29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md`](modules/spatial-execution/29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md)
的时间顺序记录为准。

## 当前可证实状态

> **证据状态说明（2026-08-18）：** 下表的 `PARTIAL`/`CLONE_ONLY`/`GAP` 均以
> `.run-tmp/sdd/2026-08-17-relation-aware-spatial-planning-gap-closure-v2/replay-sourceaware-replay28-report.json`、
> `task-f5-source-line-audit-report.md`、`task-road-geometry-report.md` 和
> `task-wave3-geometry-persistence-report.md` 为准。replay28 是 source-aware clone/replay 证据，
> 不是默认 live `COMPLETE` 验收。

| 阶段 | 当前证据 | 状态 |
|---|---:|---|
| TARGET_PROJECTION | 170 typed specs；source-aware stage 已读取 L1 observation/binding | `PARTIAL` |
| GROUND | 42 exact Point、1802 parcel candidate、329 corridor candidate；旧 replay 的 exact Line=0，但 fresh-root 真实金田 bundle 已得到 targeted exact Line；16 worker tasks 的输入仍含 deferred ledger | `PARTIAL` |
| SELECT | 16 placed、154 deferred | `PARTIAL` |
| EXECUTE | 16 worker tasks；16 final features（4 Point + 12 Polygon） | `PARTIAL` |
| VALIDATE/RECONCILE | 0 relation findings；geometry quality invalid/empty/placeholder/duplicate=0 | `CLONE_ONLY` |
| DELIVER | 15 render layers；122 non-baseline planning overlays；orphan=0 | `CLONE_ONLY/PARTIAL` |
| `/map-layers` | 同 run-root CAS descriptor 可解引用并可审计 | `PARTIAL` |
| 默认 live demo | 尚未完成 fresh live graph | `GAP` |
| live second resume | 尚未完成真实 LLM/worker counter delta 证明 | `GAP` |
| road/axis exact Line | 真实金田 bundle 的 source-feature ID/Line 已通过 fresh-root 道路验收；单条真实道路的 MiniMax source-semantic binding 也已通过；全量 axis/默认 live graph 仍未验收 | `PARTIAL` |

补充：真实 `data/gis/jintian/current/road.geojson` 的 131 条 `MultiLineString` 已通过
`backend/tests/characterization/test_real_source_line_grounding.py` 贯通
`source bundle → KG → spatial adapter → SpatialResolver → GROUND`，可得到
`line/exact_feature/execution_geometry`。因此 exact Line 的剩余问题是规划目标缺少可审计的
source-feature binding，而不是 GROUND 或 KG 不支持线几何。

这里的 131 是当前道路源层的 GIS feature 数，不是规划文本中的人工数量 275。只有显式
`source_feature_ids`、源快照/feature digest 和同快照 lineage 同时成立时，source geometry
才可成为真实 line；缺少这些绑定时必须保持 `PARTIAL`/deferred，不能从数量或道路文本自动猜测。

## 2026-08-19 实际使用审计增量

本轮用本地真实 bundle/KG 与模拟 LLM 完成了主链验收，并用显式 opt-in 的真实 MiniMax
完成了单设施 source-semantic smoke；外部 Exa/RAG 保持关闭。

- L1 已移除未被主路径使用的 `L1DimensionFragment` 和 `merge_fragments` 兼容契约；每个维度
  compiler 直接生成 partial `L1Snapshot`，唯一的 L1 aggregate 合并为最终 snapshot。`L1Fact`、
  `L1LocationFact` 和报告 provenance 是 L1 的机器消费边界。
- L1 `L1Fact` 已成为快照内权威记录，含 `fact_id`、来源报告/快照、source feature IDs、source span、计数基准和语义类型；旧 `facts`/`facts_by_dimension` 仅为确定性展示投影。
- 统一 evidence projection 已按 L1Fact 的 typed semantic type/source feature identity 判断空间角色；`public_service`、`socio_economic` 等专业维度中的设施/道路/地块 fact 不再因维度名不是 `location` 而被降级为普通背景，仍不读取 report 关键词。
- KG cognition 的机器边界新增 `KGFactRecord`。它只对完整 source identity 且单一快照的集合输出权威事实；行政线、等高线等同为 RDF 类型但不满足当前道路 selector 的要素不会混入道路事实。
- GROUND/SELECT 对多个 `grounded_source_feature` 已支持 `all_members`，场景保留全部 `ScenarioFeature`；EXECUTE 计划按成员拆成稳定任务并携带完整 `candidate_ids`，因此不再默认只执行集合的第一个成员。
- 统一 Explore EvidenceBundle 已增加 provenance/口径闸门：typed 数值事实必须携带 value、unit、counting basis；`source_feature` 还必须有 collection、snapshot 和 feature IDs/digest。缺失 lineage 标为 `unverified` 并形成 evidence gap；同范围、同快照、同单位、同口径的不同值才标 `contradicts`，不同快照/集合/口径只标 `different_counting_basis`，不会把报告数量与 GIS feature 数量混算。
- 2026-08-20 报告检索边界已收敛：L1/L2/L3 `report_body` 只能作为 `planning_background/context` 进入规划 prompt，即使正文出现“位于”、数字、道路、地块或面积，也不会被标为 `spatial_fact`、`feature` 或 `grounding`；空间定位仍必须来自 typed L1 spatial fact 与 bundle/KG EvidenceGraph。空间事实进入 prompt 时只附带不透明 `bundle://feature/<BSM>` ref，不嵌入几何，规划 LLM 只能沿 bundle bridge 请求权威几何。
- 当前已用 legacy `275` 道路统计 vs 当前 `131` 条源线回归，证明 275 不会被判为与 131 的合法数量冲突；真实 `bundle/KG + simulated LLM` 的 GROUND→SELECT→EXECUTE→render 验收仍保持通过。
- T4A source-semantic 已落地：`SourceSemanticClassifier` 只从当前 L1 typed facts/KG 候选构造闭集，两次 Minimax 结构化提案必须一致且通过 source ID、层、几何类型和数量约束；`accepted` overlay 才能进入 EvidenceGraph、source binding 和 target projection。`ambiguous/unresolved`、provider 关闭/失败都写显式诊断，不能由旧一字符映射、substring 或正则文本协议补齐。
- 2026-08-19 真实 MiniMax source-semantic smoke 已通过：`祠` source feature + L1 `祠堂` fact
  经过真实两次 typed proposal，得到 `accepted → 祠堂`、稳定 fingerprint，并安装到 EvidenceGraph；
  验收位于 `tests/acceptance/test_real_source_semantic_binding.py`，默认 skip，只有
  `RUN_REAL_SOURCE_SEMANTIC=true` 才消耗 provider 额度。
- 2026-08-19 真实 source-semantic 验收进一步贯通到 EvidenceGraph 查询：设施点注册路径现在读取 accepted
  overlay，不再只给道路/水体注册路径使用；真实两次 MiniMax proposal 后，`社前村祠堂的BSM` 得到唯一
  `resolved` candidate，保留 canonical `祠堂`、bundle BSM、source feature ID 和 L1 fact ref。验收实测
  `1 passed in 19.64s`；fixture 同时补齐结构化 `location` 和合法 BSM，未放宽 report 正文解析。
- 2026-08-19 真实 source binding 已接入本地真实 bundle/KG 的
  `l3_aggregate → TARGET_PROJECTION node → GROUND node` acceptance：只对一个 target-bound
  `祠` feature 开启真实 Minimax，EvidenceGraph facility query resolved，projection gate 和
  ground gate 均通过；默认仍使用 simulated branch，real branch 由
  `RUN_REAL_L3_SOURCE_SEMANTIC=true` 显式开启。随后同一 fresh L3 产物已继续通过
  `SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER/render`；模拟分支耗时 24.84s，
  真实 MiniMax source-semantic 分支耗时 42.34s（pytest timeout 显式设为 120s）。这证明了
  source-semantic + fresh L3 + 真实 bundle/KG 的完整 stage chain，但还不等于默认 live root
  graph、道路 exact Line 或真实 resume 零增量已经完成。
- 2026-08-19 L3 双通道输出边界已收敛：初始 provider 调用同时要求 `report_body + claims`，移除
  `PlanningClaimSet only` 冲突指令；`report_body` 为空时以 `l3_report_body_empty` 显式失败，
  不再把 claims JSON 发布到前端。claims 仍写入 L3 report 的 `instruction` artifact，正文只写入
  `content`/SSE；旧的空正文 claim cache 由 `l3-dual-output-v2` contract key 自动失效。L3 prompt
  同时明确正文/机器 claims 的双通道职责：L1 report 作为现状分析背景，L1 spatial facts/location
  facts 作为独立的空间证据区块，供 `source_fact_refs` 原样引用，不能引用自由文本、BSM、坐标或几何。
- 2026-08-19 fresh simulated L3 道路目标已完整通过
  `source_fact_refs → accepted source-semantic snapshot → source feature binding →
  TARGET_PROJECTION → GROUND exact Line`：候选保留唯一 source feature ID、`current_road` collection、
  source snapshot/digest、`l1_fact_refs` 和 bundle-authoritative WKT；同时补齐
  `source_semantic_classification` CAS artifact key，以及 `GeometryRef`/`SpatialReferenceSpec` 的
  source identity/fact lineage 字段。该验收尚未等同于默认 live root graph 或真实 MiniMax 道路调用。
- 道路语义断点已补齐：即使 source road 没有原始名称，只要 L1 fact 经模拟/生产 Minimax 以 `accepted` 绑定到 `source_feature_id`，KG 也会保留该道路实体和拓扑关系，bundle feature BSM/geometry 再按同一 identity 合并为 EvidenceGraph 候选；`parcel → road` 的反向 `sfIntersects` 也会进入 EvidencePacket。`axis/轴线` 使用同一 `current_road + LineString/MultiLineString` 闭集兼容，但保留自身 `asset_kind=axis` 和轴线参数，不通过名称别名映射成道路 claim。无 accepted 绑定时仍只保留弱 role 候选或 unresolved，不会猜道路名称。覆盖：`test_road_evidence_semantic_binding.py`、`test_flash_source_semantic_classifier.py`、真实 131 条道路 source-line 测试。
- 生产 Minimax 入口由 `SOURCE_SEMANTIC_LLM_ENABLED=true` 显式开启，分类快照按 source/L1/vocabulary fingerprint 持久化；默认测试关闭，resume 优先加载快照，不重复请求。模型构造失败不会换 provider，仍保留 unresolved 结果。
- 公共 `/sessions/{session_id}/evidence/query` 与 TARGET_PROJECTION 共用
  `source_semantic_runtime.py`：有匹配快照时只回放；没有快照且开关显式打开时才调用 Minimax，进程内只保留 16 个快照的有界 LRU。关闭、输入为空、provider 不可用、快照不匹配和模型未接受都会写入
  `source_semantic_diagnostics` 与 EvidenceGraph `query_trace`，不会静默变成精确 BSM。
- 2026-08-20 source-semantic runtime 已真正接入 KG vocabulary：按当前 L1 fact 的 phrase/type 定向查询同一 KG snapshot 的 canonical entity，作为 `kg_snapshot` candidate 提供概念 provenance；与唯一匹配的 L1 candidate 合并而不是制造第二个选择，无法唯一合并时保持 ambiguity。查询有界于每个 L1 fact 最多 8 个 KG entity、全局最多 128 个候选，不扫描全图、不复制几何，KG vocabulary 也进入 source-semantic fingerprint。覆盖 `test_flash_source_semantic_classifier.py`、道路/真实 source-line 组合测试共 20 passed，随后 URI 类型键回归 7 passed；真实金田村 13 个同名“祠”实体验证为 type-level KG candidate，不会任选一个空间点。
- 2026-08-20 source-semantic classifier 又增加了兼容性预筛：没有任何闭集 candidate 与 source layer/geometry kind 兼容的要素直接生成显式 `unresolved`，不进入 MiniMax batch；只有存在可选 candidate 的设施点/道路才消耗两次 typed proposal。这样设施事实不会把全部无名道路送进模型，道路事实也不会把点状注记送进模型；该优化不改变 fail-closed 语义，覆盖回归 9 passed。
- 2026-08-20 fresh-root 道路入口已通过真实金田 bundle 验收：`L1 fact_id/semantic_type/value → L3 source_fact_refs` 不携带任何 source feature ID，模拟 typed classifier 只返回闭集 `candidate_ref` 或 abstain；生产 `target_projection_node` 经过 source-semantic snapshot 和 source binding 后生成唯一 `current_road` binding，生产 `ground_node` 最终得到 bundle/KG 提供的 `exact_feature + execution_geometry + LineString/MultiLineString WKT`。131 条道路按 32 条分批、两次 proposal 校验共 10 次模拟结构化调用，验收 `1 passed`；这证明 stage 入口不是手工 `map_intervention_to_spec()` 替代，但尚不等同于真实 MiniMax provider 调用。
- 2026-08-20 又完成一次显式 opt-in 的真实 MiniMax 道路语义 smoke：在真实金田 bundle 的 131 条 `current_road` 中只送入 1 条，L1 闭集候选为“村道”，两次 typed proposal 均接受同一 candidate；验收 `1 passed`（约 26 秒）。模型只负责语义绑定，source feature ID 仍来自 bundle，未向模型索取或接受 BSM/坐标/几何；全量 graph/resume 仍未因额度限制启动。
- 2026-08-20 再完成显式 opt-in 的真实 MiniMax 轴线语义 smoke：同一真实金田 bundle 只送入 1 条 `current_road`，L1 闭集候选为“发展轴线”，两次 typed proposal 均接受 `axis` candidate；验收 `1 passed`（约 30 秒）。source feature ID 仍来自 bundle，`asset_kind=axis`/轴线参数不被改写成 road；全量 graph/resume 仍未启动。
- 2026-08-20 外部锚点与 KG spatial-type boundary 也已收敛：外部道路名称点进入 `PlaceRef`，不再伪装为 `Road`；外部道路线与水系线分别进入 `external_roads`、`water_lines`，不再共用 `roads_current`；`current_road` builder 对非 LineString/MultiLineString 显式跳过并返回计数诊断。bundle retriever 对这些 layer 使用 `external_spatial_context + context_only + confidence=0.65`，不能冒充本地约束或 exact execution。真实 bundle/类型边界回归联合 `42 passed`。
- 2026-08-20 本地真实金田 benchmark 复核空间类型分区：KG `Road=131`、`AdministrativeBoundary=144`、交集 `0`；KG 冷启动约 `11.4s`，EvidenceGraph 1000 次查询约 `40.6s`，混合 KG 查询 10000 次约 `1.0s`。benchmark finally 后 `session_count=0`、`layer1_cache_size=0`、`query_cache_size=0`，RSS 从约 `475.8MB` 降至约 `276.0MB`；该 benchmark 不调用 MiniMax/RAG/Exa。
- 2026-08-20 真实金田 bundle 的 `EXECUTE → VALIDATE → RECONCILE → DELIVER/render` 验收重新通过 `3 passed`；结果继续沿 bundle-authoritative geometry、局部子几何和 candidate lineage 生成，未因外部锚点分层而把 advisory 线层写入执行成果。该结果仍是显式验收输入，不等同于默认 live root graph。
- 2026-08-20 VALIDATE 失败信息已收敛为可迭代反馈：每个失败检查保留 `actual/expected`、责任 stage、target id、受影响地块 BSM、evidence refs 与修复建议；可编译的 repair impact 路由到对应 `RETRY_*`，可部分交付的目标进入 typed deferral，缺少目标血缘或无安全修复路径才进入 `HUMAN`。`validation_feedback` 同时进入工作流投影、HUMAN review 和 diagnostic terminal，不能只返回“失败”或静默丢弃定位依据。
- 2026-08-20 fresh-root 的第二次 TARGET_PROJECTION/GROUND replay 已验证零增量：source-semantic classifier 调用数保持 10，projection、semantic snapshot、grounding result 的 descriptor digest 均保持不变。为此 CAS parent 集合排除当前 stage 自己的 gate，并在同 schema/parent/semantic digest 时复用既有 descriptor；`ContractMeta.created_at` 和 provenance timestamp 不再制造伪新 artifact。空间、source-semantic、KG 类型和 artifact CAS 联合回归 `38 passed`。
- `retrieve_evidence()` 直连调用（包括 GROUND 的 packet prefetch 和 LLM evidence tool）也先走同一语义 runtime，不再只有 HTTP route 才能获得 source-semantic overlay。GROUND 的候选判别必须使用 typed `with_structured_output`；缺少 typed adapter 或结构化结果无效时保持 unresolved，不再用 `invoke()` 文本/正则抠编号。source-semantic contracts 同时关闭 JSON/text fallback。
- Evidence retrieval 与 GROUND 的文本边界已进一步收敛：`evidence/retrieval`、`spatial/grounding` 不再使用正则解析空间身份；L1 检索只接受 `l1_fact_records`，RAG 没有向量 chunk 时不生成 opaque 兼容 fact；村落/水体 mapping 只接受 typed mapping。EvidenceGraph 未解析出空间范围时只返回 `unresolved + HumanReviewQueue`，不会把最近聚落或整块 BSM 静默提升为候选。
- `domain/ground/anchors.py` 的候选消歧也只接受 Minimax/LLM 的 typed `candidate_index`；provider 缺失、额度耗尽、结构化结果无效时写入 `context.grounding_unresolved`，不再解析自由文本编号或选择第一个候选。L3 功能区词汇提取同样只接受 typed output；LLM 开关关闭才使用显式的表格编译，LLM 失败不会静默降级。
- 大地块规划链路由 `SELECT` 的 `derive_planning_subgeometry` 产生局部 WKT，`CandidateGeometry` 的 bbox 取 refined WKT 而非源 BSM bbox；非 `execution_geometry` 候选在 EXECUTE 显式 deferred，禁止回退到 land-design 全地块铺回。`source_area_ha`、`planning_area_ha`、`coverage_ratio`、操作和诊断随 scenario/render lineage 保留。
- 设施点执行不再根据点所在位置回读并整块重分类 BSM，而是生成以 authoritative point 为中心的局部 footprint；分区 scope/corridor/parcel candidate 直接 deferred，不进入整块 parcel allocation。新增真实大地块/局部设施与 scope candidate 边界验收覆盖该约束。
- `PlanningScenario` 已移除单值 `selected_candidate_ids` 视图；选择唯一来源是 typed `ScenarioTargetSelection.candidate_ids`。SELECT/EXECUTE 不再把多成员集合压成第一个候选，计划构建按成员展开 worker task，单候选之外不写单 geometry 元数据。
- EvidenceFact 已显式携带 `evidence_role`、`source_kind`、`spatial_granularity`、`planning_use`。规划 LLM 背景分别呈现 L1/KG/Bundle/报告/RAG/外源文本和 EvidenceGraph 候选/拓扑；文本只能作为 planning context，空间执行仍只接受 bundle-authoritative geometry ref。
- 2026-08-19 RAG 额度保护已收敛：`_legacy_run_rag()` 在 state 缺少 `rag_enabled` 时使用全局 `RAG_ENABLED`（默认 false），显式 `source:rag` 在关闭或向量服务不可用时写入区分的 typed trace，不再静默返回空背景。prompt 回归同时确认报告分析进入“规划语义背景”，L1 fact 进入“空间事实与定位依据”，且不向 LLM prompt 注入执行几何。
- 2026-08-19 Exa 显式 opt-in 真实 smoke 仅执行 1 次、`result_limit=1`、summary 模式并在 finally 关闭 HTTP adapter；provider 返回 typed `provider_unauthorized`（HTTP 401），没有产生外源 fact，也没有静默回退。默认进程仍解析为 `UnavailableExternalSearchAdapter`；成功生产检索仍待部署侧修复 Exa 授权后再验收，不能把本次失败当作外源能力已完成。
- GROUND packet prefetch 的空结果和异常会进入 `spatial_query_evidence`，不再以“direct resolver fallback”语义吞掉检索故障；EvidenceGraph/SpatialResolver 是唯一定位 authority，无法绑定时保持 unresolved。
- `retrieve_evidence()` 的 EvidenceGraph 预取/最终拼接异常现在会进入 `EvidencePacket.query_trace`，并写入 `missing_evidence=evidence_graph_unavailable`；图检索故障不会再只留在 debug 日志后伪装成普通空候选。
- EvidenceGraph 的空间身份仍由 bundle feature ref 提供；KG/L1 只负责语义、实体与拓扑证据。查询中的可解释 substring 候选召回不等于语义兼容映射，最终 exact binding 只能来自原始文本完全一致或已验证的 accepted Minimax overlay。
- `build_scenario_features()` 只接受 `target_id → candidate_ids[]`，不再隐式包装单值选择；场景/执行模块的多候选语义只有一个 typed 入口。
- 真实 Ground Minimax 调用由 `GROUND_LLM_ENABLED=true` 显式开启，默认测试关闭；注入的 simulated typed LLM 不受该生产开关影响，便于离线验收结构化协议与 unresolved 行为。
- 空间 LLM 预算已调整为生产默认每轮最多 16 次、单次 60 秒、并发 4；预算只在确定性候选图完成后为分组的歧义消歧、查询语义解析和名称回填预留，缓存/resume 命中不重新调用，额度/限流会停止当前预算波次。实体提取、查询语义和聚落映射的真实 flash provider 同样受 `GROUND_LLM_ENABLED` 与显式禁用开关约束，测试默认不会创建 provider。
- workflow 内的 L1 hydration、report grounding、SpatialResolver、cluster mapping、mention enhancement 和 `ground_aggregate` 现在共享同一 transient `workflow:<session>` budget；evidence API/tool 的查询语义解析按 query scope 单独限额。预算含 `reserved/completed/failed/remaining` 运行时计数，不进入 artifact，也不跨 resume 复用；空间四类 structured output 已显式关闭 content-JSON fallback，结构化失败只能 unresolved。
- 2026-08-19 真实 bundle acceptance 已验证 `EvidencePacket → ground_aggregate → GroundingResult → SELECT → subgeometry → EXECUTE → VALIDATE → RECONCILE → DELIVER/render` 主链：GROUND 不再由测试复制 `CandidateGeometry`，设施点的 `feature_bsms` 与其关联地块的 `source_parcels` 分离保留，SELECT/执行沿同一 candidate lineage 运行。子几何面积比例超过 1 的投影误差现在被显式记录为 `coverage_ratio_clamped_to_source_extent`，不会让 SELECT 因契约校验直接中断。
- 2026-08-19 同名/多村 L1 文段若同时包含多个村，PlaceEvidenceIndex 写入 `village_anchor_ambiguous` 并保持未绑定，不再按最长名称或首个 gazetteer entry 静默选择；有明确 `spatial_hint` 时只使用该显式村名的 source-backed entry。KG retriever 对 `GROUND/SELECT/EXECUTE/...` 使用显式 stage map，禁止把业务阶段名当整数解析。
- 2026-08-19 GROUND 新增 packet relation bridge：`SpatialRelationEvidence` 会以 `evidence_packet_relation` 进入 `SpatialQueryEvidence`，并在目标的 intent graph 已声明关系 factor 时补充 relation id、predicate、KG provenance、bundle geometry ref 和 L1 refs。该 bridge 不创建隐式 factor、不修改 hard/soft/status，避免把现状拓扑误当成规划意图；真正的 relation evaluator 仍只执行 typed `ConstraintFactor`。
- 2026-08-19 PlaceEvidenceIndex 的 substring 召回增加内部二元字符倒排索引；exact/alias/ambiguous 语义和 EvidenceGraph 公共边界不变，短名称仍走完整 key 集合，避免因优化漏掉单字或跨词边界候选。KG relation 的批量查询仍待大规模 bundle benchmark 后决定。
- 2026-08-19 TARGET_PROJECTION 在写入 source-semantic/authoritative-source 诊断后重新计算 gate；缺少 `planning_program` 显式失败，命名村庄无权威 BSM 会进入 `NEEDS_REVIEW`，不能以编译前的 `passed=True` 继续进入 GROUND。typed facility 的 location hint 若同时包含地点和 facility type（如“社前村+祠堂”），mapper 编成地点域与设施类型的 `AND`，保留多村候选未分类时的原有 `OR`。
- 2026-08-19 离线模拟 L3 claim 已经通过真实 `l3_aggregate → TARGET_PROJECTION node → GROUND node`；测试不再手工构造 `IntentCompilationResult`/`SpatialReferenceSpec`，而是从 CAS `PlanningProgram` 恢复，最终 candidate 保留 bundle feature/source refs。复合 spec 的 resolver 现在合并子查询的 feature BSM、source feature ID、entity/relation/L1 refs 与 authoritative geometry，不再只留下 parcel BSM 交集。设施 typed 子引用使用 EvidenceGraph 已验证的 `attributive(entity_type)` 路径。
- 2026-08-19 GROUND 的 EvidencePacket 预取递归遍历 composed children；“地点 AND 设施类型”不再因顶层没有 reference 而跳过统一检索。L3 semantic repair 新增 `L3_SEMANTIC_REPAIR_LLM_ENABLED`，默认关闭且写入 `llm_semantic_repair_disabled` typed warning，只有生产显式开启或注入模拟 typed LLM 时才调用 provider。
- KG 无名道路/水体的 L1 名称回填已改为 `CandidateChoice` typed closed-set output；不再从自由文本正则提取编号，也不接受无 typed adapter、越界编号或无匹配结果。模拟 Minimax 已覆盖多候选道路的第 2 候选选择；失败保持 `unresolved` 并留下日志/诊断。
- 真实 provider acceptance 的生命周期边界已补齐：应用 shutdown 和 acceptance fixture teardown
  会关闭 Instructor async/sync client、HTTP connection pool，并回收 session KG process pool；
  provider smoke 不应依赖宽范围进程清理。
- 2026-08-19 L3 prompt 已进一步收敛：L1 report 继续作为有界的现状分析背景；L1 spatial
  facts/location facts 单独注入空间位置证据，用于可审计的 `source_fact_refs` 和后续 GROUND，
  不再从 report 正文按“位于/分布/布局”等词挑选位置证据，也不把 fact 误当作分析正文。L2/同层
  背景有字符上限并显式标识截断，不把截断文本当作空间证据；模板中的“至少若干项目”和示例数值
  也被明确降级为排版示例，N/A 不再允许用经验值补造。
- 2026-08-19 live root/resume 验收改为双重显式开关：没有
  `RUN_REAL_GRAPH_RESUME=true` 时即使配置了 provider key 也不会执行 preflight 或真实调用；真实验收
  的内存采样线程在 teardown 中显式 `join`。默认关闭路径已通过 1 passed、1 skipped 验证；这不是
  live root 完成证明，真实主图和第二次 resume 的 provider/worker 零增量仍保持 GAP。
- 2026-08-19 证据垂直切片回归通过 18 项：真实 bundle/KG/L1 typed facts 可回答“金田村祠堂的 BSM”，
  返回 `bundle://feature/<BSM>` 与 bundle-authoritative identity；raw GIS 标签“祠”只在显式模拟
  MiniMax 的两次 typed proposal 一致并 accepted 后绑定到“祠堂”，多源 EvidenceGraph/拓扑/执行 lineage
  测试均通过。`EVIDENCE_EXTERNAL_PROVIDER=disabled` 与 `RAG_ENABLED=false` 的额度保护保持有效。
- 2026-08-19 本地 RDF spatial index 小基准（5000 entities + 5000 relations，单进程、非生产压测）：
  rebuild 约 829ms，名称查询 10000 次约 186ms，拓扑查询 10000 次约 118ms，Python traced peak
  约 6.3MB。当前结论是继续使用 KG 内部的有界索引，不提前维护第二套 topology DB；是否切 PostGIS
  仍需用真实大 bundle、空间谓词和 RSS 采样补测，不能把该微基准当生产容量结论。
- 2026-08-19 真实金田村全量本地 benchmark（660 地块、561 行政边界线、131 道路、34 注记点、29,009
  triples、1,129 entities、3,197 relations）已补测：bundle ingestion 约 2.17s，KG 冷构建约 12.84s，
  Layer-1 cache clone 约 2.19s，EvidenceIndex 构建约 2.27s，EvidenceGraph 1,000 次设施语义查询约
  44.23s（约 44ms/次），KG 10,000 次混合名称/关系查询约 0.97s。冷构建峰值 RSS 约 480MB，tracemalloc
  peak 约 152.6MB；可重复脚本在最后一个 session 释放后报告 `layer1_cache_size=0`、`session_count=0`，
  RSS 从约 480MB 降至约 268MB，剩余主要是解释器 allocator/模块常驻，脚本进程退出后由操作系统回收。
  `KGManager.remove_session()` 现在只在最后一个 session 引用消失时释放 Layer-1 clone；
  可重复脚本为 `backend/scripts/benchmark_real_evidence.py`。当前规模仍可使用有界 RDF/index，不足以
  证明生产无限扩展；后续需在更大 bundle 上继续 RSS/并发 benchmark 后再决定 PostGIS。
- 2026-08-19 Evidence 查询演示暴露并已修正两个状态错误：最终 EvidenceGraph 候选数现在会重新决定
  `ambiguity_status`，多候选不再显示“已定位”；`PlaceResolutionCandidate` 的加权总分会归一化后再进入
  `FeatureEvidenceRef.confidence`，不再因超过 1 后统一截断而把所有候选显示为 100%。语义开关关闭时，
  原始 GIS 标签仍保持未完成/多候选，不会冒充 L1 fact 或唯一空间定位。
- 2026-08-19 真实金田村 Evidence 查询黑盒验收进一步发现：同一请求先在语义关闭状态缓存为多候选、再安装
  accepted source-semantic 后，若只依赖 bundle/artifact 版本会复用旧 packet。检索缓存键现加入当前 typed
  L1/source-semantic context digest；同一生产 `retrieve_evidence()` 入口已验证能够从 `multiple` 重新计算为
  `resolved`，不再让前端与 GROUND 看到过期空间状态。
- 2026-08-19 新增真实 bundle 空间查询特征验收 `test_real_spatial_evidence_queries.py`：金田村 131 条现状道路
  和从 31xx `landuse_current` 派生的水体均由同一个 EvidenceGraph 返回有限候选；地块 bbox 命中真实 BSM，
  返回对象只含 `bundle://feature/<BSM>`、source feature ID 和关系，geometry 仍只从 bundle 读取。该验收与
  现状道路直接 GROUND 接地测试合计 `3 passed`，证明道路/水体/地块查询没有另建几何副本，也没有把 parcel
  集合误当作 exact Line/Point。
- 2026-08-19 修正 KG 类型污染：`add_boundaries()` 不再把 `admin_boundary_line` 写成 RDF `Road`，
  `add_terrain_entities()` 也不再把 `contour_line` 写成 RDF `Road`；新增有真实空间几何的
  `AdministrativeBoundary`、`ContourLine` 类型，二者仍进入空间实体静态层并保留 BSM/source geometry，
  但不会进入道路 EvidenceGraph、道路拓扑统计或道路 GROUND 候选。行政线/等高线只在其自身空间语义下参与查询。
- 2026-08-20 EXECUTE 优先级已收敛为两个独立但可合并的规划 worker：项目地块 worker 负责
  `项目语义定位 → 选定地块/子几何 → 建设用地性质变更`；道路 worker 负责
  `道路语义 → target-bound 线性成果 → 米制宽度缓冲 → 与真实地块求交 → 交通运输用地变更`。
  道路不再只写 `PlannedRoad` 线层；新建道路和明确 `widen` 的现状道路同时写交通用地
  `ParcelChange` 和剩余地块的 preserve 分区，`upgrade/repair/harden` 仍只表达现状道路干预，
  不虚构新增用地。缺少目标线、道路等级、宽度、当前 DLBM 或地块相交时显式失败，不把整块
  BSM 静默改为道路。
  合并层进一步按 `derived_from_bsms + after_geometry` 检测项目/道路重叠：同一源地块的非重叠子几何可以
  共存，真实重叠进入 blocking conflict。覆盖 `test_road_parcel_materializer.py`、
  `test_materialization_source_overlap.py` 与道路准备回归共 `17 passed`，完整执行渲染回归 `2 passed`。
- 2026-08-20 真实金田道路执行 acceptance 已补齐：从真实 `current_road` 取一条 source-bound
  `MultiLineString`，与真实 660 个 current landuse 地块进入独立 road worker，成功生成
  `planned_road`、`1006 农村道路`交通运输用地变更、剩余地块 preserve、`PlannedState.roads/parcels`
  以及 `function_zone/planned_road` 渲染图层；同一 acceptance 还覆盖现状道路 `widen`。
  测试默认不启用任何 provider。该验收证明的是 source-bound 线物化和真实地块分割，不等同于
  真实 MiniMax 全图或 Stage-4 全量新路线调用。
- 2026-08-20 模拟 LLM 已跑通真实 `create_unified_planning_graph` 根图：`L1 → L2 → L3 →
  TARGET_PROJECTION → GROUND → SELECT → EXECUTE worker registry（本场景为 road worker）→ VALIDATE → RECONCILE →
  DELIVER/render`，RAG、Exa 和真实 MiniMax 均关闭。验收 `test_simulated_root_graph_road_delivery.py`
  通过；根图最终同时落出 `PlannedState.roads` 线几何、`ParcelChangeSet` 的 `1006` 道路子面和
  preserve remainder，并证明终态二次 resume 不增加模拟模型调用。该结果是 quota-free 的真实编排验收，
  不是把模拟响应当作生产语义质量证明；根图中的 L1 gate 仍会显式保留一次 HUMAN/retry 诊断，
  后续应单独收敛为可复用证据快照，避免同一 L1 结果重复调用。
- 2026-08-20 EvidenceSource 已在统一 merge boundary 补齐 `evidence_role`、`authority`、`supports`、
  `availability` 和 `snapshot_ref`：bundle/GIS 只能作为 geometry-authoritative，KG 作为 topology-authoritative，
  L1 作为 typed semantic fact，L1/L2/L3 report 与 RAG/外源文本只能作为 planning context/advisory；这些边界
  同时进入规划 LLM prompt 与前端 Evidence 查询演示。来源合并按 source type/reference/role/authority 去重，
  不再因相同引用丢失多源作用差异。
- 2026-08-20 公共 Evidence 查询对 GROUND LLM 查询解析增加显式 `spatial_query_parser` trace：关闭、无结构化引用、
  provider 失败分别可观察；provider 失败仍允许本地 EvidenceGraph 查询，但不会伪装成解析成功或静默兼容映射。
  前端显示该状态。真实金田道路/水体/地块空间查询与真实空间 stage-chain 回归分别通过 `1 passed`，候选置信度
  仍保持概率归一化且多候选不会显示为唯一定位；测试输出完成后遗留 pytest 进程按精确 PID 回收。
- 2026-08-20 LLM 的 `query_evidence_graph`/`query_facility_bsms` tool 已不再绕过统一 Explore 服务直接读取
  EvidenceGraph；现在与 HTTP evidence/query、GROUND 共享 `retrieve_evidence()`，tool 返回
  `EvidencePacket + EvidenceBundle + SpatialCognitionEvidence`，因此 L1 typed fact、KG/bundle identity、报告背景、
  RAG/外源状态和来源作用可以被同一规划 LLM 观察。tool 仍只返回 `bundle://feature/<BSM>`，权威几何必须通过单独
  的 bundle geometry tool 按验证过的 feature ref 获取。
- 2026-08-20 GROUND 锚点边界进一步收紧：设施、道路、水体和地标只有 bundle/source-feature geometry 才能成为
  resolved anchor；删除按 KG nearby/村簇重叠选取线/水体实体的 linear fallback，`bundled:coarse` 不再算空间证据。
  村域仍可保留为显式 `scope_candidate`，但没有实体几何时只能作为范围证据，不能进入 exact feature 或 EXECUTE。
  缺失身份时写入 `identity_candidate_missing`/`grounding_spatial_evidence_missing`，不再静默提升相邻地块 BSM。
- 2026-08-20 L1 输出边界进一步收敛：`L1DimensionOutput.report_body` 与 typed observations 必须来自结构化
  provider 输出；空报告、结构化解析失败和 provider 错误均显式产出 `llm_typed_output_error`，不再把 Markdown
  表格/正文正则解析结果伪装成 L1 fact。L1 的 `fact_records` 现在只保留空间观察（KG/GIS/bundle 的
  source-backed identity/geometry 语义），报告正文、约束和分类分析仍保留在 report/display projection，供规划
  LLM 作为背景，不会越过空间 fact 边界进入 GROUND。
- 2026-08-20 道路执行成功条件进一步收紧：road worker 只有在交付图层中出现带 target binding 的线性成果时才算
  成功；删除“单目标但没有实际产出也算成功”的兜底。道路建设仍由独立 road worker 负责两类结果：先写
  target-bound `PlannedRoad` 线，再用声明的道路宽度与 bundle authoritative current landuse 求交，写入
  `ParcelChange` 的 `1006` 交通运输用地子面和 preserve remainder；没有 source geometry 时只能 deferred/fail-closed。
- 2026-08-20 修复 KG CAS/session 恢复边界：`PlanningKG.from_turtle()` 恢复 RDF snapshot 后立即重建
  `RdfSpatialKGIndex`，因此恢复的 session KG 与 fresh build 使用同一 `find_entities/find_relations` 查询面，
  EvidenceGraph 不会因索引为空而误报本地证据缺失。
- 2026-08-20 修复 L1 scope 输入优先级：PlaceEvidenceIndex 同时发现旧 `location_facts` 和 typed
  `l1_fact_records` 时优先使用 typed records；旧 projection 只作为没有 typed records 的迁移输入，避免
  丢掉 `fact_id`、source refs 和空间语义 provenance。该 scope 仍然不包含几何，几何绑定继续由 KG/bundle 完成。
- 2026-08-20 模拟根图又贯通了稳定 `/map-layers` 读侧：从 DELIVER 的
  `delivery_manifest`、`delivery_spatial_snapshot`、`render_layers` 重新读取并校验公开契约，前端同时得到
  `planned_road` 线层和 `complete_planned_landuse` 中 `planning_code=1006` 的交通运输用地。这里的
  `function_zone` 仍是 PlannedState 的分析叠加，不被冒充为权威地类修改；默认 live API、真实 provider 和
  全量 resume 仍保持未完成门槛。
- 这些是当前代码路径的增量闭环，不等同于 source collection binding、真实 fresh 主图、resume 零增量和全部道路/轴线 live 验收已完成；缺少绑定时仍必须 deferred。

另修复了一个接口丢失：`RoadTarget` 现在保留 `existing_road_feature_ids` 和 network
`existing_road_segment_ids`，mapper 和 compile 都接受显式的
`source_feature_ids`/`existing_road_feature_ids`/`road_feature_ids` 特征 ID 别名；这只修复审计
ID 的传递，不会从道路文本或数量不一致的源层自动猜测绑定。

## 不应混淆的两组结果

### 旧空图层证据

**HISTORICAL：** `fresh-ground-20260817-test3` 有 161 个 candidate，但全部是 `polygon/parcel_set`，exact Point、
exact Line、exact feature 均为 0；161 个 hard constraints 全部失败，SELECT=0，EXECUTE workers=0，
因此没有规划交付图层。

### 新 source-aware clone-only 证据

**PARTIAL / CLONE_ONLY：** replay28 从 clean main cursor 和 v3 source bundle 完成
`TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`。它证明
设施 Point 和 polygon overlay 已可以贯通主链，但不是默认 live 完成态：exact Line=0、154 个目标
仍 deferred、delivery status=partial，且 clone-only artifact 不能代替默认入口的 live acceptance。

`actual_change_count=0` 是相对 baseline 的变化字段，不代表规划 feature 为零；当前应使用
`planning_overlay_feature_count=122`、`selected_count=16` 和 `materialized_feature_count=1979`
区分规划结果、选中目标和所有物化 feature。

## 阶段边界

- GROUND 只召回 typed candidate；权威 Point/Line WKT 才能成为 `exact_feature`，BSM union 只能是
  parcel/corridor candidate。
- SELECT 负责 hard/soft relation、容量、保护约束和网络可行性；`violated` 终止组合，
  `pending/unknown/deferred` 进入 partial/deferred ledger。
- EXECUTE 只物化 SELECT 已选 candidate 的 source-backed geometry；缺 source ID/geometry 时
  deferred，不生成 centroid、representative point、入口点或两点连线。

## 下一验收门槛

1. 用默认 live root 的 source-aware bundle/KG 从 GROUND 之前 fresh replay，证明至少一个 road/axis
   exact Line；当前 simulated L3 道路链已通过，仍需 live root 入口验收。
2. 运行低内存 clone preflight，记录每阶段 yield、artifact digest 和 `/map-layers` 返回。
3. 用 fresh L3 道路/轴线目标实际验证刚补齐的 typed `source_fact_refs → accepted source-semantic
   decision → source feature binding → exact Line`，并检查 collection、snapshot、digest 和
   topology binding；不能用道路数量或文本名称猜测 Line。
4. 第二次 resume 证明 scenario/final-validation fingerprint 不变且 LLM/worker 增量为零；
   source-semantic snapshot 命中只能作为其中一部分，不能代替 worker counter。
5. 对大 bundle 做低内存空间查询基准，比较 RDFLib 本地索引和 PostGIS adapter 的候选召回、
   拓扑查询、内存峰值与 resume cache 释放，再决定生产切换，而不是预先维护第二套拓扑库。
6. 只有 fresh default-live replay、`/map-layers` 可读且上述 resume/idempotency gate 全部通过后，
   才能标记 `COMPLETE`；默认入口和旧 test3 的空结果仍必须 fail-closed。

## 当前回归与进程状态

2026-08-19 全量 `tests/core` 已通过：`758 passed, 56 warnings`（31.75s，关闭 pytest cache）。此前关于
`ScenarioFeature.relation_ids` 导致 final-validation/network fixture 失败的维护项已不再适用；本轮还同步
更新了 OpenAPI snapshot，并验证了多候选状态与 confidence 归一化。
不能继续作为当前状态描述。

Windows 下本轮 pytest 在输出完整通过结果后仍可能保持驻留进程；验收脚本必须等待命令结束，
若进程未退出，只能按本轮命令的精确 PID 回收，不能用宽范围进程名清理，以免误杀后端服务或
MCP/Node 进程。这是测试运行器的资源回收项，不代表规划工作流可以泄漏后台任务。

## 2026-08-20 复杂语义定位收敛

- EvidenceGraph 已支持同名/相似语义锚点的 Bundle 空间聚类：相关地块重叠或权威代表点在
  500m 内才连边，名称相同本身不连边；多簇必须走 typed closed-set GROUND LLM，失败保持
  `evidence_anchor_clusters_unresolved`。
- 真实金田 Bundle 的“炉池”特征测试不再显式传 hazards scope，仍从 4 个地址含炉池的地质
  灾害点定位为单一空间簇，并沿 Bundle/KG topology 得到 26 个相关地块；结果明确是推断范围，
  不是伪造的自然村边界。
- 查询 LLM 在现有 `SpatialReferenceSpec` 上增加 `semantic_terms` 与 `retrieval_scopes`，避免新建
  dimension fragment/compiler。两者都是闭集/原文约束，只控制 EvidenceGraph 候选召回；
  BSM、source feature identity 和 geometry 仍只能来自 Bundle/KG。
- API 默认 `entity_scope=[]`，表示不在 transport 层预先排除任何可定位类别。查询 LLM 可把
  hazards/facilities/parcels/roads/waters/zones 多类 scope 合并进统一 request；parser disabled、
  failed、rejected 与最终 effective scopes 都进入 `EvidencePacket.query_trace`。
- HTTP route 已删除第二次 EvidenceGraph enrichment；`retrieve_evidence()` 是唯一 enrichment
  边界，OpenAPI 生成类型是前端 Evidence DTO 的唯一来源。
- EvidenceGraph 通过私有索引的有界 n-gram 公开“部分语义探针”：当用户只说“炉池自然村”而
  源标签是“炉池赖木生”等更长名称时，仍会把已注册的灾害点/设施/道路候选交给统一候选链；
  探针不产生 BSM、坐标或几何，后续仍由 KG 关系、L1 事实和 Bundle 身份完成绑定。
- 真实 HTTP Bundle 验收已通过：`炉池自然村在哪里` 在未声明 hazards scope、未启用 RAG/外源
  检索时返回 4 个灾害点，并汇总 26 个关联地块；查询上下文使用缓存，不再为每个只读请求强制重建。
- 候选分数已拆成来源权威、语义匹配、空间支持、外源支持、检索排序和最终选择六个不同含义；
  前端不再把 Bundle 几何存在显示为 100% 定位置信度。
- 真实 MiniMax source-semantic smoke 已通过（1 case，两个一致性调用）：原始点标签“祠”在
  L1“祠堂/社前村”与 KG 闭集约束下被 accepted 并写入 EvidenceGraph。复杂查询 parser 的首次
  真实调用暴露了 260 completion-token 截断；预算已独立提升为 `GROUND_QUERY_SPEC_MAX_TOKENS=1200`，
  prompt 进一步约束根级多源召回和 `children=[]`。提升后的真实复验已通过：MiniMax 返回的原文
  semantic terms、hazards/parcels/facilities scopes 均通过闭集校验，未携带 BSM/坐标/执行 ID；
  真实调用结束后默认仍保持关闭。
- 2026-08-21 复杂语义查询又收敛了显式 role 边界：调用方明确要求 village/facility/road/water/hazard
  时只在兼容实体类型内消歧；未声明 role 的查询仍返回跨层候选集交给 LLM/后续 GROUND 选择，避免
  “园寨村”被同名灾害点的多源几何错误升级为歧义。检索器异常现在逐源进入 `EvidencePacket.query_trace`
  并显示错误原因；外源成功不会被本地失败列表覆盖。report-grounder 的分区 prompt 也改为只渲染一次，
  避免 JSON 模板花括号触发二次 format 失败。真实/模拟复杂定位回归 14 passed、跨层证据契约 69 passed，
  SELECT/地块修改/道路成果/VALIDATE/渲染血缘回归 27 passed；RAG、Exa、空间语义真实调用仍按额度保护默认关闭。
- 2026-08-21 `run_rag()` 已补齐 L1/L2/L3 规划上下文的外源证据入口，但由
  `EVIDENCE_EXTERNAL_FOR_LLM=false` 默认关闭；显式开启时复用生命周期 provider 和统一
  `retrieve_evidence()`，本地证据足够会短路，不足时才把 Exa/其他 provider 的文本 evidence
  放入规划 prompt。外源不可用、超时或检索器失败保留 typed availability/trace，不产生 BSM、几何或
  source identity，也不把“没有外源结果”伪装成有效背景。
- 2026-08-21 JinTian 本地 benchmark 显示 29,009 triples、1,129 entities、3,197 relations：
  Bundle ingest 约 2.0s、KG 冷构建约 9.5s、KG 缓存构建约 1.3s；KG 10,000 次混合查询约 0.8s。
  EvidenceGraph 重复解析同一 mention 的 1,000 次查询从 30.9s 降至 1.8s，新增的是每个 graph
  实例内有界 128 项 resolution LRU，key 纳入 Bundle digest、KG/L1/source-semantic 版本，缓存只存
  typed resolution/opaque identity，不复制 geometry/report。session release 后 layer1/session/query
  cache 均为 0，RSS 从约 488MB 回落到约 288MB；当前规模尚无切换 PostGIS 的性能证据，继续保留
  spatial storage adapter 作为后续大 bundle 基准入口。
- 2026-08-21 统一 `retrieve_evidence()` 的结果缓存进一步纳入 `village_name`、外源 policy、
  `data_snapshot.digest`、KG version，以及 RAG/外源运行开关；相同文本但不同空间作用域、provider
  策略或 typed context 版本不会复用旧的候选/外源背景。缓存版本回归与真实 HTTP evidence 回归
  `7 passed`，完整 core 回归保持 `800 passed, 1 deselected`。
- 2026-08-21 证据候选不再把 12 项上限伪装成完整召回：`EvidencePacket` 增加
  `candidate_total/candidate_offset/candidate_limit/candidates_truncated/next_candidate_offset`，
  HTTP `EvidenceQueryRequest` 与 LLM evidence tools 可以按页继续读取。候选生成先保留有界全量
  source-backed identity，再只把当前页投影给 LLM；Bundle 几何仍不进入 packet。前端 Evidence demo
  显示“当前页/总数”和下一页操作；超过页大小时明确提示还有候选，不将未返回项当作不存在。默认页
  行为不变，真实 HTTP、OpenAPI、完整 core 与模拟 root 回归分别保持 `1/16/801/2 passed`。
- 2026-08-21 文件型真实 HTTP 分页验收补齐：JinTian `祠堂`查询在 `candidate_limit=2` 时返回大于
  2 的 `candidate_total`，第 0 页和第 1 页的 2 个 Bundle identity 不重复，total/next offset
  一致。未启用源语义 LLM 的“设施点”宽泛查询仍明确返回 0 候选并保留
  `SOURCE_SEMANTIC_LLM_DISABLED`，没有把原始短标签静默提升为设施语义。
- 2026-08-21 Windows KG worker 增加 spawn 可用性门控：`python -`/无文件 launcher 不创建必然
  失败的 spawn pool，而进入显式日志标记的当前进程构建；正常文件型服务和 pytest 仍使用隔离进程。
  新增 guard 回归 `6 passed`；本轮孤儿 spawn 子进程已按精确 PID 回收，既有 MCP fetch 进程未触碰。
- 2026-08-21 空间查询结果状态再收紧：报告/文本事实存在但没有 Bundle-backed candidate 或关系时，
  packet 不再标记 `sufficient`，而返回 `partial/insufficient`、`spatial_candidates_unresolved`，并在
  `spatial_result_status` 中给出原因；分页 offset 超出 total 时返回 `candidate_offset_out_of_range`。
  真实“设施点”宽泛查询已验证这条失败返回仍包含源语义 LLM disabled 诊断，避免把无定位结果误报为有效空间答案。

- 2026-08-21 L1 typed `source_feature_ids` 已进入 PlaceEvidenceIndex 的精确绑定路径：先按 source ID
  扫描 Bundle 的 points/lines/polygons，再用 KG 作为索引线索；KG 返回的 BSM 必须通过
  `workspace.find_feature_by_bsm()` 回到 Bundle，并再次校验 feature 的 source ID，才可形成
  `bundle://feature/<BSM>` 和关联地块集合。显式 source ID 找不到 Bundle 实体时保留
  `l1_source_feature_unresolved:<id>`，不再按同名或坐标误绑其他实体，也不产生可执行几何。
- 2026-08-21 完整空间交付验收通过：真实 JinTian fixture 的
  `GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER` 生成地块规划图层，
  `/map-layers` 读取 `complete_planned_landuse` 的非空 FeatureCollection，并保持 source/subgeometry
  血缘；独立 road worker 生成 `planned_road` 线层并将道路与现状地块求交后写入 `1006` 交通运输用地，
  独立 facility worker 生成 `facility_point` 点层。模拟根图道路/设施交付和真实道路 land-use worker
  回归均通过。这个结论限定在本地 Bundle + 关闭外源 provider 的确定性演示路径，不等同于 Exa/RAG
  生产额度开启或任意未绑定数据都能执行。
- 2026-08-21 本轮回归：`tests/core` 为 `801 passed, 56 warnings`；真实 evidence HTTP 为 `2 passed`；
  完整 spatial stage-chain 为 `1 passed`；道路/设施根图与真实道路执行组合为 `4 passed`。pytest 结束后
  未发现测试进程残留；仅保留已有 fetch MCP 进程，未按进程名误杀。
- 2026-08-21 外源失败边界进一步收敛：当显式开启 external evidence 但 provider 返回
  `provider_timeout/provider_rate_limited/provider_unavailable/budget_exceeded/no_results` 等状态时，
  `EvidenceBundle.unresolved` 会保留 `external:<failure_code>`，统一规划 prompt 会显示
  `external_policy` 的 provider/status/failure code/message；成功结果仍标记为
  `external_context + planning_use=context + spatial_granularity=none`，不产生 BSM、source identity
  或几何。gate 的 EXPLORE gap resolution 也复用同一开关和 provider 生命周期，默认关闭时不会联网。
- 2026-08-21 非生命周期调用创建的 Exa client 已在 evidence HTTP route、L1/L2/L3 `run_rag()` 和 gate
  gap resolution 完成后显式 close；应用生命周期持有的 provider 不由请求提前关闭，避免 socket/进程泄漏。
  外源 prompt failure smoke、外源 fallback/API/gate 回归 `35 passed`，fresh root 的
  `source_fact_refs → typed source classifier → source feature binding → exact road line` 回归 `1 passed`。
- 2026-08-21 RAG unavailable 也进入统一规划背景诊断：`rag_source` 的 disabled/unavailable/failed 状态会
  在 prompt 中显示，专业向量文本仍不产生空间位置；session 删除或 evidence cache 清理时同步释放该
  session 的 `_RAG_LOGS`，避免只读检索和恢复迭代长期保留 RAG availability 对象。低内存/resume
  characterization `7 passed`，针对 RAG/cache/gate 的回归和全量 core 保持 `801 passed`。
- 2026-08-21 默认入口的额度安全 source-aware 验收补齐：模拟 L3 结构化输出从
  `TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER` 通过，
  其中道路目标只携带 `source_fact_refs`，source ID/Line geometry 仍由当前 Bundle/KG 绑定；模拟根图
  道路交付 `planned_road + 1006 transport landuse` 和设施交付 `facility_point` 各自通过，二次
  HUMAN/resume 不重复 LLM/worker 调用。三项验收分别为 `1 passed/33.10s`、`1 passed/57.66s`、
  `1 passed/57.33s`；真实远程 LLM 全图仍保持显式 opt-in，不因验收自动消耗额度。
- 2026-08-21 LLM 候选分页协议补齐：统一 EvidenceGraph prompt 现在同时显示当前页范围、总候选数、
  page limit、`candidates_truncated` 与 `next_candidate_offset`；当前页未闭合时明确要求继续查询，
  不再把前 8 个候选误写成完整候选集。`query_evidence_graph` 与 `query_facility_bsms` 返回统一
  `pagination.next_request`，模型可直接复制工具名和参数取得下一页；越界且没有下一页时显示证据缺口，
  不伪造“已完整”。本轮核心证据/语义回归 `15 passed`，真实 HTTP 分页 `2 passed`，分页协议烟测通过。
- 2026-08-21 分页状态继续收紧：`query_facility_bsms` 只有在所有候选页取完且唯一候选确实闭合时才返回
  `status=resolved`；当前页仍有未取候选时返回 `ambiguous/candidate_page_incomplete`，空页仍为
  `unresolved`，避免分页中的单项被误当成最终定位。
- 2026-08-21 GROUND 不再只消费 EvidencePacket 第一页：预取使用 `candidate_limit=64` 按
  `next_candidate_offset` 继续读取，并合并候选、L1 范围、source spans、KG relations、外源 refs 和
  诊断；分页安全上限或中途失败时保留已有证据但标记未闭合，resolver 禁止执行选择。完整合并后才
  将所有 Bundle-backed 候选交给 GROUND 选择 LLM，移除了 resolver 内部的 `[:8]` 静默截断。
  本轮真实 fixture 空间链与模拟道路/设施交付 `4 passed`，GROUND packet bridge/retry `13 passed`。
- 2026-08-21 对话检索 prompt 明确列出 `query_evidence_graph`、`query_facility_bsms` 和
  `bundle_geometry_by_feature_ref`，要求模型分页取完后再判断唯一定位，并禁止从报告/RAG/名称生成
  BSM、坐标或几何；工具仍通过 `execute_tools → conversation` 闭环返回结果。
- 2026-08-21 修复语义-only GROUND 预取断点：当结构化空间查询使用
  `semantic_terms/retrieval_scopes` 而不填 `reference.label_contains` 时，GROUND 现在仍会把原文语义词
  和 `hazards/parcels/facilities/...` 范围传入统一 `EvidenceGraph + Bundle + L1` 检索；此前该合法的
  `attributive` 查询会被错误地跳过。缺省范围也包含 hazards/zones，避免“村名只出现在地质灾害点地址中”
  时漏掉可作为粗定位锚点的点及其关联地块。语义回归 `33 passed`、完整执行渲染 `2 passed`、真实
  evidence HTTP `2 passed`、全量 core `801 passed`。
- 2026-08-21 直接 GROUND 解析路径同步收紧：EvidenceGraph 的模糊候选页显式使用 64 条上限，
  空间证据链不再静默只采前 8 条；这只扩大有界召回和 lineage，不改变“几何必须回 Bundle、
  多候选必须交给 LLM、LLM 失败保持 unresolved”的选择边界。针对性 EvidenceGraph/GROUND 回归
  `37 passed`，本轮验收未留下 pytest 子进程。
- 2026-08-21 移除 GROUND packet 预取的目标数 `8` 截断：现在所有已编译的空间目标都会进入预取，
  由并发信号量 `4`、每目标候选页 `64` 和最多 `16` 页安全界限控制内存与单目标工作量；不再因
  目标排序靠后而静默漏检。移除后全量 core 回归仍为 `801 passed, 56 warnings`。
- 2026-08-21 根图性能验收定位并修复 Bundle 快照的重复几何序列化：`BundleStore.serialize()`
  现在复用同一次 canonical payload 生成 `SessionDataSnapshot`，并按要素增量计算 collection
  digest，不再在每个 L1/L2/L3 边界额外构建完整 GeoJSON 临时树。真实金田村模拟 root graph
  道路交付 `1 passed`（本轮约 2 分钟）、设施交付 `1 passed`（本轮约 2.5 分钟）；两次测试结束后
  均无 pytest 残留。快照/manifest 契约 `6 passed/5.31s`，真实空间 stage-chain 与道路成果回归
  `9 passed/39.30s`。这解决了明确的重复序列化路径，但大 Bundle 的单次 canonical JSON 编码
  仍是可观测成本，继续保留基准，不宣称已达到任意规模。
- 2026-08-21 规划 LLM 的统一证据查询补齐真实语义上下文：`run_rag()` 不再只发送维度名，
  现在带入项目/村名、任务描述、约束、L1 typed location facts 与空间事实，并声明
  `parcels/facilities/roads/annotations/hazards/waters/zones/settlements` 全部检索范围；
  查询只做有界召回，不解析或生成 BSM。L1 空间事实默认跨专业维度检索，因而交通规划可以使用
  自然环境报告中的炉池灾害点地址作为语义锚点；需要严格维度视图时必须显式传
  `strict_dimension=true`。
- 2026-08-21 EvidencePacket 的 `source_spans` 对 L1 空间事实带出事实正文，GROUND 候选选择
  提示扩大到 8 条来源文段；规划 prompt 对规划背景和空间事实的显示上限明确报告总数，不把截断
  静默当作不存在。针对性证据/语义回归 `27 passed`，真实金田村 evidence 查询 `1 passed`，
  真实空间 stage-chain `1 passed`，完整执行渲染 `2 passed`，真实道路/交通用地 `2 passed`，
  可视化执行 `1 passed`。测试结束后仅保留既有服务/MCP 进程，无 pytest 残留；当前确定性本地
  Bundle 路径已能实际生成地块规划图层、道路线层/交通用地 `1006` 和设施点层，远程 LLM/RAG/Exa
  仍按默认关闭、显式启用才消耗额度。
- 2026-08-21 演示 PNG 与交付渲染边界对齐：旧 acceptance 专用图只画地块，曾导致查看者一直看到
  “现状地块 + 变更地块”而误以为道路/设施没有变化；现在 `execution_result_v2.png` 和道路演示
  均调用生产 `render_comparison_preview`，从 typed planned overlays 绘制并在侧栏报告缺失成果。
  项目+设施演示明确显示 `planned_road` 未生成（因为输入无道路目标），真实金田村道路演示生成
  `planned_road` 1 个并显示 `1006` 交通用地。最终回归为完整执行渲染 `1 passed`、真实道路 `2 passed`、
  静态 renderer 质量 `8 passed`；未用示意线掩盖缺失道路。
- 2026-08-21 综合根图验收已闭合：同一次模拟 `L1/L2/L3 → TARGET_PROJECTION → GROUND →
  SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER` 同时产出地块变更、`planned_road` 线和
  `facility_point` 点，并从 `DeliverySpatialSnapshot` 的生产 `render_artifacts.static_preview`
  生成 `backend/output/execution_result_combined.png`；图侧栏显示规划道路 1 个、规划点 8 个，
  地块变更 17 个。此前只有地块的旧图不能再作为交付验收依据。
- 2026-08-21 真实 MiniMax root graph 受控试跑：L1 真实报告实际生成并完成 12 个维度，但该次
  子进程没有显式打开 `SOURCE_SEMANTIC_LLM_ENABLED`，所以日志明确记录
  `SOURCE_SEMANTIC_LLM_DISABLED`；GROUND 另暴露出候选选择未指定 MiniMax 的
  `function_calling` 且 300 token 上限会被思考内容耗尽。已将真实接地调用改为显式 function
  calling、上限 800 token；`test_grounding_llm_reason_alignment.py`、超时边界和统一接地回归
  `21 passed`。真实远程全图未继续重试，避免在开关错误时浪费额度；生产默认仍关闭，下一次真实
  验收必须在命令级显式打开 source semantic，并单独记录真实 L3 项目 claims 后再进入空间执行。
- 2026-08-21 受控真实 MiniMax L1→L3 交通验收已完成：真实 Bundle 加载 660 个地块、KG 和
  EvidenceGraph；交通 L1 生成 1108 字现状报告，但第一次返回 `observations=[]`，说明模型会
  写“131 条道路/道路网络/园寨村服务区”等正文空间事实，却可能漏掉 L1 spatial observation。
  系统没有把报告正文静默升级成 L1 fact；L1Snapshot 最终为 7 条 KG/GIS fact、0 条 location fact。
  继续使用真实生产 L3 prompt 后生成 2 个真实交通 claim：一级/二级村道分级（引用 2 条 L1 fact，
  location 为田园生活区/园寨村）和森林步道（位置提示为田坑村/营仔村但没有 source_fact_refs）。
  该结果证明真实模型已经能提出规划项目，同时暴露出 L3 位置提示需要继续由 EvidenceGraph/GROUND
  验证的边界；本次只验收 L1/L3，没有把未验证的森林步道送入 EXECUTE。已加强 L1 prompt 的聚合
  空间对象观察要求，以及 L3 prompt 对“L1 fact 已绑定/语义候选需 GROUND”两种状态的区分。真实
  调用结束后已回收当前运行进程，远程 source-semantic/RAG/Exa 仍默认关闭。L3 的 bounded repair
  现在同时带回当前合法 L1 fact 列表，允许模型删除无效 fact id 或逐字修复 fact 引用；没有
  source_fact_refs 的语义候选仍保留并交给 GROUND 检索。本轮针对性合同/失败迭代回归 `34 passed`，
  模拟根图道路交付仍为 `1 passed/119.83s`，测试进程已回收。
- 2026-08-21 当前代码再次复跑本地真实数据基准：Bundle 载入 660 个地块、131 条道路、34 个
  标注点、40 个地质灾害点，耗时约 4.08 秒；KG 冷构建 20.18 秒、同 Bundle 缓存构建 2.77 秒，
  29,009 triples / 1,129 entities / 3,197 relations。空间类型分区为 `Road=131`、
  `AdministrativeBoundary=144`、交集 `0`。EvidenceGraph 建索引约 2.98 秒，1000 次“社前村祠堂”
  语义查询约 3.04 秒且每次返回 13 个候选；释放两个 session 后 `layer1_cache_size=0`、
  `session_count=0`、`query_cache_size=0`。这证明当前本地 evidence 路径有实际召回和可回收性，
  但 13 个祠堂候选仍必须交给 LLM/人工选择，不能由查询分数伪装成唯一定位。
- 2026-08-21 真实 MiniMax 交通输出形状的本地后半链路契约复跑通过：用同样的“已绑定道路”和
  “森林步道语义候选”两种输入状态验证 `l1_fact_bound` /
  `semantic_candidate_needs_grounding` 都能进入统一的
  `TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER` 回归；
  当前模拟根图 `1 passed/103.08s`，过程结束没有 pytest/python 子进程残留（仅保留启动前已有的
  两个服务进程）。这不是再次计费的远程调用，也不把模拟结果宣称为 MiniMax 已完成真实几何；
真实 MiniMax 的森林步道是否能闭合，仍需在明确打开 source-semantic/ground LLM 后单独验收。
- 2026-08-21 修复 EvidenceGraph 公开 scope 检索的语义前缀缺口：真实灾害点名称包含
  `炉池赖木生/炉池赖新珠/炉池赖新海/炉池林腾发`，但旧的 `query_scope_candidates("炉池", ["hazards"])`
  只做完整标签命中，可能返回空集；现在复用有界 `semantic_label_probes`，并在存在具体前缀时停用
  “按类别返回全部灾害点”的扩张。真实 Bundle 回归确认返回 4 个 hazard 候选，每个均保留真实 BSM、
  Bundle geometry ref 和关联地块；它们是自然村的空间锚点，不被提升为村界。EvidenceGraph/KG/多源
  回归 `41 passed`；不传 `entity_scope` 的跨类型查询也能从已登记名称自动发现 hazard 角色。直接
  `resolve_mention(role="village")` 仍会明确 unresolved，这是因为灾害点不是 village 实体；全面检索必须走
  统一 evidence query/scope 入口，再由 GROUND 结合证据选择或形成粗粒度村域。
- 2026-08-21 项目级 Evidence 查询不再要求调用方先猜图层：API 的 `entity_scope` 为空时，路由会覆盖
  `local_text → report → KG → Bundle → artifact → history` 六类项目内证据；其中 artifact 覆盖 L1/L2/L3
  及执行产物，history 保留恢复/修订线索。空间解析器即使从自然语言推导出 `facilities/hazards/parcels`
  等候选范围，也只把它作为候选召回提示，不会反过来缩窄项目级 source coverage。专业向量 RAG 与外源
  provider 仍必须显式启用，过期/不可用不会静默伪装成本地证据。
- 2026-08-21 真实 MiniMax GROUND 暴露并修复“报告村名清单误映射全部聚落”的风险：仅有“炉池、肩丰、营仔……”
  的报告枚举时，模型曾把 16 个宅基地聚落全部返回；该结果被判定为不合格，不能作为定位。现在
  `collect_spatial_anchor_evidence()` 通过统一 EvidenceGraph 无图层召回灾害点、KG/L1 lineage 和其关联
  Bundle 地块，再与确定性宅基地聚落做 BSM 交集，形成有界空间候选；LLM 只能在有真实空间证据支持的
  聚落中选择，越界 entry 整条拒绝而不是静默裁剪。真实金田村数据中“炉池”4 个灾害点给出
  `cluster 4=82、cluster 0=4、cluster 15=1` 的关联地块交集，单次 MiniMax 受控调用选择 `cluster 4`，
  最终聚合 24 个真实宅基地 BSM；调用预算 `reserved/completed=1`，client 关闭且没有新增残留进程。
- 2026-08-21 MiniMax 结构化输出通道补齐标准双包装：provider 可能返回
  `<think>...</think> + ```json ... ```，统一 decoder 现在只接受这两个完整、已知的外层包装并继续
  做严格 JSON/Pydantic 校验；正文夹杂、截断、非标准 JSON、内部 wrapper 或尾随文本仍拒绝。该通道
  只产生 typed cluster indexes/evidence，不解析名称为 BSM/坐标，geometry 仍由 Bundle 权威返回。相关
  结构化、mapper、路由和 EvidenceGraph 回归 `72 passed`，真实空间检索回归 `1 passed`，subgeometry
  stage-chain `1 passed/35.07s`，模拟 L3→GROUND→EXECUTE→DELIVER `1 passed/49.74s`。
- 2026-08-21 修复报告正文在 GROUND 链路中的边界：`PlanningContext.reports` 只保留 Bundle 的报告
  manifest/summary，不再把 summary 当正文；`load_report_corpus()` 按 Bundle 的 L1/L2/L3 `report_id`
  从 `ReportStore` 有界读取正文，映射器随后只截取涉及待定位名称的段落（最多约 3000 字符）。报告内容
  仍是 `planning_background`，不会被提升为空间身份；BSM/geometry 继续只来自 L1 typed spatial facts、
  KG 和 Bundle。完整 core 回归 `801 passed`，规划图层端到端回归 `2 passed/82.37s`。
- 2026-08-21 清除 `report_grounder` 的静默空间回退：删除原始报告的数字/方位字符串解析、设施标签
  substring 匹配，以及“空间就近覆盖/空间就近”聚落分配。现在自然村 grounding 只接受明确的 Bundle
  村名点锚，或带逐字报告证据并通过 EvidenceGraph 空间锚候选约束的 typed LLM 映射；没有跨源锚点的
  名称保留 `unresolved + HumanReviewQueue`。同时将旧 report grounding 入口接入统一跨源 anchor
  collector，并把无证据的 typed mapping 整条拒绝，避免真实模型或 provider 失败时静默制造村域几何。
- 2026-08-21 收紧“项目级 Evidence 查询”的实现边界：未指定 `entity_scope` 的 `fact_check` 与
  `evidence_gap` 现在也必经 Bundle retriever，不再因为调用方没有猜中图层而漏掉空间数据；无 scope
  的 Bundle 查询在 points/lines/polygons 三类实际集合上做有界标签命中，返回真实 BSM、source
  collection 和 opaque feature ref，EvidenceGraph 再补齐跨类型候选、关联地块与 KG 拓扑。检索仍是
  相关证据检索，不是向 LLM 倾倒全量要素；RAG/外源继续显式开启、默认不耗额度。
- 2026-08-21 修复真实根图并发写报告的持久化竞态：`ReportStore.save/bulk_save` 现在按事件循环使用
  弱引用异步写锁，串行完成“查重 + 写入 + commit”，避免并行 L1/L2/L3 worker 的 SQLite lock
  让同层依赖报告在下一节点启动前不可见。锁不跨 session 保留死 event loop，也没有新增常驻进程。
  真实金田村 Bundle + 模拟规划 LLM 根图验收重新通过：道路 worker 产出线性成果并将修改地块标为
  `1006` 交通用地，设施 worker 产出 `facility_point`；两条链路均通过 GROUND→SELECT→EXECUTE→
  VALIDATE→DELIVER，轻量多源回归 `21 passed`。
- 2026-08-21 前端 Evidence 演示和规划 LLM prompt 均改为项目级来源覆盖视图：调用方不发送
  `entity_scope` 时显示“项目全域（未指定图层）”，并展开结构化事实、文本背景、KG/拓扑关系、冲突
  和未解析项；prompt 的来源摘要按 `source_type/evidence_role/authority` 分组并保留每类数量，避免
  report、L1、KG 或 GIS 来源被前六条截断。Bundle 几何仍只通过 opaque `geometry_ref` 使用。
- 2026-08-21 真实 HTTP Evidence 验收进一步发现并修正来源误标：Bundle 内的 `local-text:*` 文本片段
  在合并边界统一为 `local_text / planning_background / document_context`，不会再继承 Bundle 的
  `geometry_authoritative`。真实上传夹具验证无图层 `炉池自然村在哪里` 返回 `local_text + KG +
  gis_layer`、`planning_text + bundle_feature_identity` 和 4 个灾害点候选；夹具本身没有持久化的
  L1 typed records 或 L1/L2/L3 ReportStore manifest，因此不虚构 `l1/report` 来源。
- 2026-08-21 修复公共 Evidence 查询的上下文重复构建：`prepare_evidence_context()` 不再把“报告清单
  已加载但为空”误判为“未加载报告”，`PlanningContext.reports_loaded` 区分两种状态。真实 HTTP
  Evidence 验收从约 `42.79s` 降至 `25.03s`，仍通过同样的真实候选、来源和分页断言；版本、快照和
  L1 hydration 失效条件未放宽。
