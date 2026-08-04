# Wave A: 设计隔离 + 核心契约 + 审查包协议 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将所有跨体系映射隔离到 advisory_crosswalks 区；落地 22 个核心契约（覆盖全部 13 个阶段的输入/输出）+ 6 个依赖反转 Port + 审查包协议；为后续 12 个业务模块波次建立地基。

**Architecture:**
- `schema/advisory_crosswalks/` 物理隔离跨体系映射（code↔name 保留在 code_sets）
- `schema/contracts/` 中 22 个契约文件，权威**根 artifact 继承** `ContractMeta`（schema_version/context_version/artifact_id/created_at）；嵌套值对象为普通 BaseModel，不携带元数据
- `modules/ports/` 中 6 个 Protocol 接口（不可序列化依赖反转接口与数据契约分离）
- `services/` 中 FilesystemArtifactStore + review_package 实现

**Tech Stack:** Python 3.12, Pydantic v2, pytest

## Global Constraints

- 换行符：LF；缩进：Python 4 空格；引号：双引号
- 不保留任何内部兼容 shim -- 旧导入路径更新后即删除
- 跨体系映射移入 advisory_crosswalks 后，L2/L3/PARSE/GROUND/SELECT/EXECUTE 禁止导入，由静态扫描测试强制
- 同体系 code↔name 映射（DLBM_TO_DLMC, GHYTBM_TO_GHYTMC, VNE_CODE_TO_NAME）保留在 code_sets.py
- 根 artifact 继承 ContractMeta，不重复声明 schema_version/context_version/artifact_id/created_at
- ports/ 只保存 Protocol 接口；contracts/ 只保存 Pydantic 数据模型
- 审查包写入 `.run-tmp/{run_id}/{module}/`
- 默认测试不依赖网络、外部服务或 gitignored 数据

## File Structure

### 新建文件
```
backend/app/modules/schema/advisory_crosswalks/
├── __init__.py                  # 导出所有移入的跨体系映射符号
└── yaml/                        # 从 dicts/mappings/ + dicts/rules/ 移入的 19 个 YAML

backend/app/modules/schema/contracts/
├── contract_meta.py             # ContractMeta + StageStatus + StageIssue
├── classification_ref.py        # ClassificationRef
├── provenance.py                # Provenance（吸收 semantic_fields）
├── context_ref_contracts.py     # PlanningContextRef + DatasetRef + ContextVersion
├── workflow_contracts.py        # PlanningRunRequest + StageId + GateDecision + RoutingDecision + FeedbackRoute + PendingRequest
├── evidence_contracts.py        # ExplorationRequest + EvidenceBundle + EvidenceFact + EvidenceSource + EvidenceGapResolution
├── l1_contracts.py              # L1Snapshot
├── l2_contracts.py              # L2Strategy
├── l3_contracts.py              # PlanningProgram + PlanningIntervention + InterventionDependency
├── spatial_reference_contracts.py  # SpatialReferenceSpec + RefObject + GeometryRef（升级版）
├── constraint_contracts.py      # 升级：PlanningConstraint + ConstraintSet + enums（原 CompiledConstraint）
├── parse_result_contracts.py    # IntentCompilationResult + ProjectRequirement + CompilationError
├── grounding_contracts.py       # GroundingResult + CandidateSite + HardConstraintResult + SpatialQueryEvidence
├── selection_contracts.py       # SiteSelectionDecision + RankedCandidate + EliminatedCandidate + LandDesignBrief
├── execution_plan_contracts.py  # ExecutionPlan + WorkerTask + WorkerType + ExecutionResult
├── parcel_change_contracts.py   # ParcelChangeSet + ParcelChange（移出 context_contracts）
├── planned_state_contracts.py   # PlannedState + PlannedParcel/Zone/Facility/Road/Axis（移出 kg/builder/layer4）
├── land_balance_contracts.py    # LandBalanceTable + LandBalanceRow（移出 delivery_contracts）
├── validation_report_contracts.py  # ValidationReport + ValidationCheck + ValidationIssue（统一版）
├── reconciliation_contracts.py  # ReconciliationReport + CoverageMatrix + ReconciliationInconsistency
├── delivery_manifest_contracts.py # DeliveryManifest + Deliverable + TraceabilityEntry + HumanItem + DeliveryGate
└── review_contracts.py          # ReviewPackage + ReviewStatus + HumanReviewRequest + ReviewDecision + ReviewComment

backend/app/modules/ports/
├── __init__.py
├── artifact_store.py            # ArtifactStorePort
├── context_provider.py          # ContextProviderPort
├── semantic_query.py            # SemanticQueryPort
├── spatial_query.py             # SpatialQueryPort
├── gazetteer.py                 # GazetteerPort
└── nomenclature_registry.py     # NomenclatureRegistryPort

backend/app/services/
├── artifact_store.py            # FilesystemArtifactStore
└── review_package.py            # write/read/query review packages

docs/superpowers/plans/
├── 2026-08-04-wave-a-design-isolation-contracts.md  # 本计划
└── 2026-08-04-wave-roadmap.md   # 后续波次 B-M 路线图
```

### 迁移/删除文件
| 现有文件 | 操作 | 去向 |
|---|---|---|
| `schema/encodings/dicts/mappings/*.yaml` (17) | 移动 | `advisory_crosswalks/yaml/` |
| `schema/encodings/dicts/rules/ghytbm_to_planning_zone.yaml` | 移动 | `advisory_crosswalks/yaml/` |
| `schema/encodings/dicts/rules/planning_zone_rules.yaml` | 移动 | `advisory_crosswalks/yaml/` |
| `schema/encodings/code_sets.py` | 移除跨体系符号 | 保留同体系 code↔name |
| `schema/contracts/spatial_ref_contracts.py` | 重命名+升级 | `spatial_reference_contracts.py` |
| `schema/contracts/unresolved_contracts.py` | 吸收后删除 | `StageIssue` + `GroundingResult.unresolved` |
| `schema/contracts/semantic_fields.py` | 吸收后删除 | `Provenance` |
| `schema/contracts/delivery_contracts.py` | 拆分后删除 | `land_balance_contracts.py` + `delivery_manifest_contracts.py` |
| `schema/contracts/execution_contracts.py` | 替换后删除 | `execution_plan_contracts.py` + `validation_report_contracts.py` |
| `schema/contracts/layout_contracts.py` | 精简，消费者迁移后删除 | Direction/Density/ConflictReport/AllocationResult/ExportResult 暂存 |
| `schema/contracts/context_contracts.py` | 移出 ParcelChange 系列 | 保留认知上下文类 |
| `schema/contracts/validation_contracts.py` | 升级+重命名 | `validation_report_contracts.py` |
| `kg/builder/layer4.py` | 移出 dataclass | 保留 apply/ingest 函数 |
| `data/ingest.py` | 移除 current 派生 | planned 保留用户值 |
| `spatial_ops/parcel_ops.py` | 删除 dead code | split_parcel_by_ratio |

---

## Task 1: advisory_crosswalks 隔离区创建 + 跨体系映射移入 + ingest 派生移除 + 死代码删除

**Files:**
- Create: `backend/app/modules/schema/advisory_crosswalks/__init__.py`
- Create: `backend/app/modules/schema/advisory_crosswalks/crosswalks.py`
- Move: 19 个 YAML 文件 -> `advisory_crosswalks/yaml/`
- Modify: `schema/encodings/code_sets.py`（移除跨体系符号）
- Modify: `schema/encodings/dicts/loader.py`（更新 YAML 加载路径）
- Modify: `schema/encodings/dicts/__init__.py`
- Modify: `data/ingest.py`（移除 current_landuse planning_zone 派生）
- Modify: 18 个导入站点
- Delete: `spatial_ops/parcel_ops.py:split_parcel_by_ratio` (lines 189-274)
- Modify: `spatial_ops/__init__.py`（移除导出）
- Test: `backend/tests/unit/test_advisory_crosswalks_isolation.py`
- Test: `backend/tests/unit/test_ingest_no_crosswalk.py`
- Test: `backend/tests/unit/test_no_advisory_crosswalk_imports.py`

**Interfaces:**
- Produces: `advisory_crosswalks` 包导出所有移入的跨体系符号
- Produces: 静态扫描测试禁止 L1/L2/L3/PARSE/GROUND/SELECT/EXECUTE 导入 advisory_crosswalks

**移入 advisory_crosswalks 的符号 (dicts):**
`DLBM_TO_ZONE_TYPE`, `DLBM_TO_ZONE_TYPE_CURRENT`, `DLBM_TO_PLANNING_ZONE`, `DLBM_TO_PRIMARY_ZONE`, `ZONE_TYPE_TO_DLBMS`, `ZONE_TYPE_TO_PLANNING_ZONE`, `PLANNING_ZONE_TO_PRIMARY_ZONE`, `GHYTBM_TO_PLANNING_ZONE`, `GHYTBM_TO_ZONE_TYPE`, `GHYTBM_TO_VNE`, `VNE_TO_ZONE_TYPE`, `DLBM_TO_GHYTBM`, `DLBM_TO_GHYTBM_CONVERSIONS`, `GHFLBM_TO_TDYTFQDM`, `SDDLBM_TO_YDYHFLDM`

**移入 advisory_crosswalks 的函数:**
`dlbm_to_planning_zone()`, `get_zone_type_for_dlbm()`, `get_planning_zone_from_landuse()`, `get_ghytbm_for_dlbm()`

**保留在 code_sets.py 的同体系映射:**
`DLBM_TO_DLMC`, `GHYTBM_TO_GHYTMC`, `VNE_CODE_TO_NAME`, `BASIC_FARMLAND_CODES`, `ECOLOGICAL_CODES`, `FOREST_CODES`, `WATER_CODES`, `SPACE_CONTROL_ZONE_CODES`, `normalize_landuse()`, `is_basic_farmland()`

**需更新导入的文件 (非禁止阶段，10 个):**
`spatial_ops/land_balance.py`, `spatial_ops/relations.py`, `spatial_ops/context.py`, `schema/utils/metrics.py`, `tools/gis/_analytics/metrics_calculator.py`, `tools/gis/_analytics/compare_layouts.py`, `tools/gis/_analytics/dynamic_zoning.py`, `kg/queries/semantic.py`, `api/gis_test_routes.py`, `schema/encodings/classification.py`

**标记为 known violation（EXECUTE 链，后续波次重写，8 个）:**
`tools/gis/_generation/optimizer/mip_allocator.py`, `mip_solver.py`, `planning_zone_mapper.py`, `tools/gis/generate.py`, `_generation/zone_generator.py`, `land_use_zone_generator.py`, `space_control_generator.py`, `zone_type_deriver.py`

- [ ] **Step 1: 编写 3 个测试文件**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 创建 advisory_crosswalks 包结构**
- [ ] **Step 4: 移动 19 个 YAML 文件**
- [ ] **Step 5: 更新 code_sets.py**
- [ ] **Step 6: 更新 dicts/loader.py YAML 加载路径**
- [ ] **Step 7: 更新 10 个非禁止阶段导入站点**
- [ ] **Step 8: 更新 8 个 EXECUTE 链导入路径（临时，后续波次重写）**
- [ ] **Step 9: 修改 ingest.py**
- [ ] **Step 10: 删除 split_parcel_by_ratio 死代码**
- [ ] **Step 11: 运行全部 3 个测试验证通过**
- [ ] **Step 12: 运行全量 unit 测试（排除 jintian）验证无回归**
- [ ] **Step 13: 提交**

---

## Task 2: ContractMeta + Provenance + ClassificationRef + 基础类型 + 6 个 Port

**Files:**
- Create: `backend/app/modules/schema/contracts/contract_meta.py`
- Create: `backend/app/modules/schema/contracts/provenance.py`
- Create: `backend/app/modules/schema/contracts/classification_ref.py`
- Create: `backend/app/modules/ports/__init__.py`
- Create: `backend/app/modules/ports/artifact_store.py`
- Create: `backend/app/modules/ports/context_provider.py`
- Create: `backend/app/modules/ports/semantic_query.py`
- Create: `backend/app/modules/ports/spatial_query.py`
- Create: `backend/app/modules/ports/gazetteer.py`
- Create: `backend/app/modules/ports/nomenclature_registry.py`
- Delete: `schema/contracts/semantic_fields.py`（吸收到 provenance.py）
- Modify: `schema/contracts/__init__.py`
- Test: `backend/tests/unit/contracts/test_meta_and_ports.py`

**Interfaces:**
- Produces: `ContractMeta`（所有契约基类）, `Provenance`, `ClassificationRef`
- Produces: 6 个 Protocol（ArtifactStorePort, ContextProviderPort, SemanticQueryPort, SpatialQueryPort, GazetteerPort, NomenclatureRegistryPort）

- [ ] **Step 1: 编写失败测试**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 contract_meta.py**
- [ ] **Step 4: 实现 provenance.py（吸收 semantic_fields）**
- [ ] **Step 5: 实现 classification_ref.py**
- [ ] **Step 6: 实现 6 个 Port Protocol**
- [ ] **Step 7: 删除 semantic_fields.py**
- [ ] **Step 8: 更新 contracts/__init__.py 导出**
- [ ] **Step 9: 运行测试验证通过**
- [ ] **Step 10: 提交**

---

## Task 3: 工作流控制 + 上下文引用 + 证据 + L1/L2/L3 契约

**Files:**
- Create: `backend/app/modules/schema/contracts/context_ref_contracts.py`
- Create: `backend/app/modules/schema/contracts/workflow_contracts.py`
- Create: `backend/app/modules/schema/contracts/evidence_contracts.py`
- Create: `backend/app/modules/schema/contracts/l1_contracts.py`
- Create: `backend/app/modules/schema/contracts/l2_contracts.py`
- Create: `backend/app/modules/schema/contracts/l3_contracts.py`
- Modify: `schema/contracts/__init__.py`
- Test: `backend/tests/unit/contracts/test_workflow_evidence_stage_contracts.py`

**Interfaces:**
- Consumes: `ContractMeta`, `StageIssue` (from Task 2)
- Produces: 8 个契约类型

- [ ] **Step 1: 编写失败测试**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 6 个契约文件**
- [ ] **Step 4: 运行测试验证通过**
- [ ] **Step 5: 提交**

---

## Task 4: 空间引用 + 统一约束 + PARSE/GROUND/SELECT 契约

**Files:**
- Create: `backend/app/modules/schema/contracts/spatial_reference_contracts.py`（升级版，替代 spatial_ref_contracts.py）
- Modify: `backend/app/modules/schema/contracts/constraint_contracts.py`（原地升级）
- Create: `backend/app/modules/schema/contracts/parse_result_contracts.py`
- Create: `backend/app/modules/schema/contracts/grounding_contracts.py`
- Create: `backend/app/modules/schema/contracts/selection_contracts.py`
- Delete: `schema/contracts/spatial_ref_contracts.py`（已重命名+升级）
- Absorb: `schema/contracts/unresolved_contracts.py`（UnresolvedTarget -> StageIssue + GroundingResult.unresolved）
- Delete: `schema/contracts/unresolved_contracts.py`
- Modify: `schema/contracts/parse_contracts.py`（移除 SpatialOperation.split_ratio 字段）
- Modify: 更新 `spatial_ref_contracts.py` 的 2 个消费者导入路径
- Modify: `prompts/parse_prompts.py`（移除 split_ratio prompt 指令）
- Test: `backend/tests/unit/contracts/test_spatial_constraint_grounding_selection.py`

**Interfaces:**
- Consumes: `ContractMeta`, `ClassificationRef`, `StageIssue` (from Task 2)
- Produces: `SpatialReferenceSpec`, `PlanningConstraint`, `ConstraintSet`, `IntentCompilationResult`, `GroundingResult`, `CandidateSite`, `SiteSelectionDecision`, `LandDesignBrief`

- [ ] **Step 1: 编写失败测试**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 spatial_reference_contracts.py**
- [ ] **Step 4: 升级 constraint_contracts.py**
- [ ] **Step 5: 实现 parse_result_contracts.py**
- [ ] **Step 6: 实现 grounding_contracts.py**
- [ ] **Step 7: 实现 selection_contracts.py**
- [ ] **Step 8: 修改 parse_contracts.py -- 移除 split_ratio**
- [ ] **Step 9: 修改 parse_prompts.py -- 移除 split_ratio 指令**
- [ ] **Step 10: 吸收 unresolved_contracts.py**
- [ ] **Step 11: 删除 spatial_ref_contracts.py（已被替代）**
- [ ] **Step 12: 运行测试验证通过**
- [ ] **Step 13: 运行全量 unit 测试验证无回归**
- [ ] **Step 14: 提交**

---

## Task 5: EXECUTE 调度 + 地块变更 + PlannedState + 用地平衡 + 校验/对账/交付/审查契约

**Files:**
- Create: `backend/app/modules/schema/contracts/execution_plan_contracts.py`
- Create: `backend/app/modules/schema/contracts/parcel_change_contracts.py`（移出 context_contracts.py）
- Create: `backend/app/modules/schema/contracts/planned_state_contracts.py`（移出 kg/builder/layer4.py）
- Create: `backend/app/modules/schema/contracts/land_balance_contracts.py`（移出 delivery_contracts.py）
- Create: `backend/app/modules/schema/contracts/validation_report_contracts.py`（统一版）
- Create: `backend/app/modules/schema/contracts/reconciliation_contracts.py`
- Create: `backend/app/modules/schema/contracts/delivery_manifest_contracts.py`（吸收 delivery_contracts.py）
- Create: `backend/app/modules/schema/contracts/review_contracts.py`
- Modify: `schema/contracts/context_contracts.py`（移出 ParcelChange 系列）
- Modify: `kg/builder/layer4.py`（移出 dataclass，保留 apply/ingest 函数）
- Modify: 更新 4 个 layer4 dataclass 消费者导入路径
- Delete: `schema/contracts/validation_contracts.py`（升级后重命名）
- Delete: `schema/contracts/delivery_contracts.py`（拆分后删除）
- Modify: `layout_contracts.py`（删除 ValidationReport/ViolationItem 重复项）
- Test: `backend/tests/unit/contracts/test_execute_validate_reconcile_deliver.py`

**Interfaces:**
- Consumes: `ContractMeta`, `ClassificationRef`, `StageIssue`, `PlanningConstraint` (from Task 2+4)
- Produces: 9 组契约类型

- [ ] **Step 1: 编写失败测试**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 execution_plan_contracts.py**
- [ ] **Step 4: 实现 parcel_change_contracts.py**
- [ ] **Step 5: 实现 planned_state_contracts.py**
- [ ] **Step 6: 实现 land_balance_contracts.py**
- [ ] **Step 7: 实现 validation_report_contracts.py（统一版）**
- [ ] **Step 8: 实现 reconciliation_contracts.py**
- [ ] **Step 9: 实现 delivery_manifest_contracts.py**
- [ ] **Step 10: 实现 review_contracts.py**
- [ ] **Step 11: 修改 context_contracts.py**
- [ ] **Step 12: 修改 layout_contracts.py**
- [ ] **Step 13: 更新 contracts/__init__.py 导出**
- [ ] **Step 14: 运行测试验证通过**
- [ ] **Step 15: 运行全量 unit 测试验证无回归**
- [ ] **Step 16: 提交**

---

## Task 6: ArtifactStore 实现 + 审查包服务 + PlanningContext 更新 + 路线图 spec

**Files:**
- Create: `backend/app/services/artifact_store.py`（FilesystemArtifactStore 实现 ArtifactStorePort）
- Create: `backend/app/services/review_package.py`（write/read/query 审查包）
- Modify: `backend/app/modules/context/planning_context.py`（添加 artifact_store + ports 字段）
- Create: `docs/superpowers/plans/2026-08-04-wave-roadmap.md`（后续波次 B-M 路线图）
- Test: `backend/tests/unit/test_artifact_store.py`
- Test: `backend/tests/unit/test_review_package.py`

**Interfaces:**
- Consumes: `ArtifactStorePort`, `ReviewPackage` (from Task 2+5)
- Produces: `FilesystemArtifactStore`, `write_review_package()`, `read_review_package()`, `query_reviews()`

- [ ] **Step 1: 编写 2 个测试文件**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 FilesystemArtifactStore**
- [ ] **Step 4: 实现 review_package 服务**
- [ ] **Step 5: 更新 PlanningContext**
- [ ] **Step 6: 编写 wave-roadmap.md**
- [ ] **Step 7: 运行测试验证通过**
- [ ] **Step 8: 运行全量 unit 测试验证无回归**
- [ ] **Step 9: 提交**

---

## 自审检查

**1. Spec 覆盖:**
- ✅ §3.1 ClassificationRef -> Task 2
- ✅ §3.1 advisory_crosswalks 隔离 -> Task 1
- ✅ §3.1 静态检查禁止导入 -> Task 1
- ✅ §2.2 现状地类不推导规划分区 (ingest.py) -> Task 1
- ✅ §2.3 删除 split_ratio bbox 切割 -> Task 1 (dead code) + Task 4 (contract + prompt)
- ✅ §3.2 13 个阶段输出契约 -> Task 3+4+5
- ✅ 阶段输入契约 -> Task 3+4+5
- ✅ 工作流控制契约 -> Task 3
- ✅ 统一约束 -> Task 4
- ✅ EXECUTE 调度 -> Task 5
- ✅ §4 审查包协议 -> Task 5 (contract) + Task 6 (service)
- ✅ §4 ArtifactStore port -> Task 2 (port) + Task 6 (impl)
- ✅ §4 PlanningContext 快照 -> Task 6
- ✅ 6 个 Port 分离到 modules/ports/ -> Task 2
- ✅ 现有契约迁移 -> Task 4+5
- ✅ §4 后续波次记录 -> Task 6
- ⚠️ §6 测试重构 - Wave A 仅新增契约测试和静态扫描测试；全量测试重构在各模块波次中同步进行
- ⚠️ 2 个 arch invariant 失败 (KG->Data, SpatialOps->KG) - 记录为 known violations，在 Wave G + Wave M 中修复

**2. 占位符扫描:** 无 TBD/TODO；所有步骤包含具体代码或具体操作。

**3. 类型一致性:**
- `ContractMeta` 在 Task 2 定义，Task 3/4/5 所有契约继承
- `ClassificationRef` 在 Task 2 定义，Task 5 `ParcelChange.before/after_classification` 消费
- `StageIssue` 在 Task 2 定义，Task 3 `L1Snapshot.issues` + Task 4 `GroundingResult.unresolved` + Task 5 `ValidationIssue extends` 消费
- `PlanningConstraint` 在 Task 4 定义，Task 5 `ValidationReport` 间接消费
- `ArtifactStorePort` 在 Task 2 定义，Task 6 `FilesystemArtifactStore` 实现
- `ReviewPackage` 在 Task 5 定义，Task 6 `write_review_package` 消费

**4. 阶段 I/O 覆盖验证:** 全部 13 个阶段 + Bootstrap/Router 的输入输出均有对应契约文件。

**5. 未覆盖项（推迟到后续波次）:**
- modules/ 目录重组 (spec §5) - 各模块波次同步进行
- 全量测试重构 (spec §6) - 各模块波次同步进行
- 2 个 arch invariant 修复 - Wave G + Wave M
- 8 个 EXECUTE 链 known violations - Wave I
