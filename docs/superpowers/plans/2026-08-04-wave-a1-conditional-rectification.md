# Wave A.1: 条件整改（进入 Wave B 前）

> 对应审查结论：基础骨架通过，但"运行时隔离、契约冻结、可审查基础设施"需条件整改。
> 执行方式：子代理驱动，每任务独立可验收，串行提交。

## 验收口径（全部满足才标记 Wave A 最终通过）
1. 默认活动链无法访问 advisory crosswalk（传递依赖扫描归零）
2. 旧映射式 EXECUTE 默认不可产生正式规划成果（fail-closed + legacy 开关 + 输出标记"非规划成果"）
3. PARSE 独立顶层且 hybrid repair 设计进入权威文档与契约
4. Artifact 和 Review revision 可持久化、可重放、可批准
5. 跨阶段契约不再依赖关键 Any/dict 占位（根 artifact 级）
6. 违规预算只减不增、最终归零；架构预算测试满足修订后基线

## Task A1-1: 传递依赖扫描 + 违规预算测试（测试基础设施）
- 重写 `tests/unit/test_no_advisory_crosswalk_imports.py`：
  - 删除 `test_known_violations_still_exist`（不再要求违规文件存在）
  - 改为：活动链可达模块（agent 全部阶段 + tools/gis + kg + spatial_ops + data + parsing + utils）对 advisory_crosswalks 的传递依赖扫描
  - 建立 VIOLATION_BUDGET 注册表（文件 → 引用数，只减不增），逐任务消除
- 新增 LLM tool registry 不包含 map_code 的测试

## Task A1-2: PARSE 顶层阶段契约 + 权威文档（P0-4）
- `schema/contracts/parse_contracts.py`（或新文件）新增：
  - `ParseMode` (COMPILE/REPAIR/REVISE)
  - `ParseRevisionRequest`
  - `ParseDiagnostic`
  - `CompilationPatch`（field_path, operation, source_text_loc, actor, confidence, base_revision）
  - `ParseTrace`
  - `CompilationStatus`
- 升级 `IntentCompilationResult`：program_ref, base_revision_ref, typed_intent, spatial_reference_specs, constraint_set, diagnostics, patches, compilation_status, confidence, provenance
- 更新 `docs/architecture/agent-graph.md` + `docs/superpowers/plans/2026-08-04-wave-roadmap.md`：PARSE 独立顶层 + hybrid repair 设计

## Task A1-3: ArtifactStore / ReviewPackage 重构 + 类型化 Ports（P0-3）
- 目录：`.run-tmp/{run_id}/artifacts/{module}/{artifact_id}/manifest.json + payload`；`.run-tmp/{run_id}/reviews/{module}/{review_id}/manifest.json + review files`
- ArtifactStore：完整 envelope、校验摘要、revision、metadata 保真（context_version/artifact_type）、原子写入、路径边界约束
- ReviewPackage：review_id、revision、状态持久化、ReviewDecision 持久化 + Gate 联动、只存 ArtifactRef 不嵌大对象
- 类型化 PlanningPorts 替换 PlanningContext 的 dict[str, Any]

## Task A1-4: 契约冻结修正（P0-2）
- 文档措辞："根 artifact 继承 ContractMeta"，非"全部继承"
- 修复 ContractMeta 在 PlannedState 等根模型重复声明
- Provenance 进入所有权威根 artifact
- DeliveryGate 移除固定 15% 阈值（改为可配置/字段）；LandBalance 移除硬编码农业/建设/生态汇总（改为输入参数）

## Task A1-5: map_code 移除 + lookup_land_use_code 同体系化（P0-1 工具部分）
- 从生产代码移除/停用 `map_code`（不注册、不暴露）；保留为离线研究脚本
- `lookup_land_use_code` 只返回同体系 code→name；移除 zone_type/vne_code 跨体系字段
- `decode_code` 保持同体系 name 查询（不依赖 crosswalk）

## Task A1-6: KG BaseFacts 跨体系派生移除（P0-1 KG 部分）
- layer1.py / layer1_core.py / enrichment.py：
  - `resolve_zone_type_for_dlbm`（taxonomic_parent 派生）→ 移除，BaseFacts 不再从现状 DLBM 派生 zone_type
  - `PLANNING_ZONE_TO_CONTROL_CODE`（legal_constraint 派生）→ 移除/fail-closed
  - `get_ghytbm_for_dlbm`（allowed_operations 派生）→ 移除/fail-closed
  - semantic.py encoding_bridges 跨体系字段 → 仅保留同体系 dlmc
- BaseFacts 只保留同体系事实分类与名称（semantic_label = DLBM_TO_DLMC）

## Task A1-7: 旧 MIP/ZoneGenerator 链 fail-closed + legacy 开关（P0-1 EXECUTE 部分）
- generate.py / zone_generator / land_use_zone_generator / space_control_generator / mip_allocator / mip_solver / planning_zone_mapper / zone_type_deriver：
  - 默认 fail-closed（无 legacy 开关时抛错或返回"非规划成果"）
  - 显式 legacy 开关（环境变量 GIS_LEGACY_MAPPING=1）仅供对照测试
  - 输出标记"非规划成果"

## Task A1-8: 其余生产引用清理 + 归零验证（P0-1 剩余）
- utils/code_lookup.py：`DLBM_TO_ZONE_TYPE` 改同体系（zone_types_appendix5 encoding 直接构建）
- data/base_conversion.py、encoding_detector.py：DLBM→GHYTBM 基数转换移出活动链（fail-closed 或离线）
- spatial_ops/context.py、relations.py、export_package.py：get_zone_type_for_dlbm / dlbm_to_planning_zone 移除/fail-closed
- parsing/table_schema_inference.py：GHYTBM_TO_VNE 移除/fail-closed
- gis_test_routes.py / compare_layouts.py / dynamic_zoning.py / layout_validator.py / metrics_calculator.py：按隔离语义处理（测试/离线可保留但标记，或 fail-closed）
- 最终：传递依赖扫描 + 违规预算归零验证

## 测试补充（贯穿各任务）
- advisory crosswalk 传递可达性测试
- LLM tool registry 不包含 map_code
- Contract JSON round-trip、无效枚举、缺失 ID、跨 artifact 关联测试
- PARSE patch 不得覆盖未声明字段
- ArtifactStore revision、metadata 保真、原子写入、路径边界测试
- ReviewDecision 持久化及 Gate 联动测试
- review/artifact 目录互不污染测试
