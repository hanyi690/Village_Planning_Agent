# DATA MVP 真实输入闭包与设计文档 Implementation Plan

**Goal:** 将金田村当前真实输入固定为 DATA MVP 的可复现输入闭包，令真实上传经过统一 admission facade，补齐 receipt/gap/lifecycle、CAS reload、catalog slimming、精确 invalidation，并明确旧 `VillageBundle`/规划输入/在线 provider 路径不再属于 MVP 兼容保证。

**Architecture:** 以 `DataResourceCatalog`、`SessionDataSnapshot`、source admission、CAS artifact 和外部地图 cache inventory 作为 DATA 的产品边界。上传先经过 bounded temporal-role classifier，再由 `DataAdmissionFacade` 写入 receipt/gap 和 immutable catalog artifacts；bootstrap 只 reload 持久化 artifact，不重新解释上传正文。文档同时维护“当前代码已实现”和“仍需接通/验证”的差距。

**Tech Stack:** Python DATA 实现（GeoJSON、GeoTIFF/rasterio、Markdown、Pydantic、Shapely/pyproj）；CAS/Pydantic contracts；pytest DATA 回归测试；Markdown 设计文本；PowerShell/`rg` 只读盘点命令。

## Global Constraints

- MVP 的真实输入只包括 10 个 `data/gis/jintian/current/*.geojson`、`data/gis/jintian/terrain/dem.tif`、指定现状报告 Markdown，以及 `data/cache/map_observations/{amap,tianditu,tencent}` 的本地缓存；旧 `output/map_validation` 只读迁移。
- 不把不存在或未被用户指定的 `data/gis/广东DEM30M.zip` 写成输入；不把 `data/cache/tiles` 写成三家地图 provider 观测缓存。
- `data/gis/jintian/planned/`、规划文本、规划成果和 planned output 不进入 current DATA catalog。
- 旧 `VillageBundle`、BSM/DLBM typed 组装、外部在线重抓和 legacy anchor 注入代码可以暂留，但不属于 MVP 接口、验收或兼容保证。
- DATA 不承担规划决策、实体身份确认或把外部地图观测变为可执行几何。
- 不删除仍被旧会话引用的 Python 模块；默认运行路径不再调用 Bundle fallback，迁移 fallback 必须显式设置 `DATA_LEGACY_BUNDLE_FALLBACK=1`。

## Implementation status

The implementation tasks below were extended during execution: upload ingress now
calls the async temporal-role gate and `DataAdmissionFacade`; uploaded rows persist
receipt/gap/lifecycle plus all DATA artifact refs; session bootstrap reloads the
immutable catalog payload; `data_catalog` is a lightweight index over
`data_catalog_payload`; legacy Bundle and permissive coordinate handling are no
longer default paths; and regression tests cover replay, stale parent and exact
invalidation. The remaining checklist is retained as an audit trail for the
original documentation work.

---

### Task 1: 建立真实输入和实现事实基线

**Files:**
- Read: `data/gis/jintian/current/*.geojson`
- Read: `data/gis/jintian/terrain/dem.tif`
- Read: `docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md`
- Read: `data/cache/map_observations/{amap,tianditu,tencent}/`（旧 `output/map_validation` 仅作为只读迁移源）
- Read: `backend/app/data/ingestion/upload.py`
- Read: `backend/app/data/catalog/session_resource_catalog.py`
- Read: `backend/app/data/resource_catalog.py`
- Read: `backend/app/data/admission.py`
- Read: `backend/app/modules/data/application.py`
- Read: `backend/app/data/catalog/catalog.py`

**Interfaces:**
- Consumes: 用户指定的真实文件路径、GeoJSON/GeoTIFF/Markdown 读取器、source admission 和 catalog contract。
- Produces: 可写入设计文档的输入清单、媒体类型/CRS/几何类型、代码入口、当前实现状态和风险清单。

- [ ] **Step 1: 核验文件存在性、digest 和基础元数据**

  使用只读脚本检查 10 个 GeoJSON 的 `FeatureCollection`、要素数、几何类型、top-level CRS，检查 DEM 的 driver/CRS/shape/dtype/nodata，并记录报告的 UTF-8、行数和标题结构。对 provider 缓存只统计 manifest、normalized、attempt、request、raw/cache 文件，不读取凭据。

- [ ] **Step 2: 对照代码确认输入实际经过的路径**

  记录上传解析、session catalog 重建、通用 `DataResourceCatalog.from_records`、规范化几何、admission readiness、CAS 以及 external observation cache loader 的实际函数名；明确 `DataAdmissionFacade.admit` 与 legacy `DataCatalog.load_village_bundle` 是否被生产上下文调用。

- [ ] **Step 3: 将观察结果作为文档事实与目标设计分离**

  对“代码已经做了”“代码存在但未接通”“本轮只作为设计约束”三类事实分别标注，不把一次临时 probe、未执行的 facade 路径或历史 ZIP 输入写成 runtime verified。

### Task 2: 更新 DATA canonical 设计文本

**Files:**
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md`

**Interfaces:**
- Consumes: Task 1 的真实输入基线和当前代码事实。
- Produces: DATA 的职责、输入闭包、处理流水线、产品契约、准入状态、失败恢复、持久化、外部缓存边界、旧兼容退出范围和当前 gap 的 canonical 文档。

- [ ] **Step 1: 修正文档状态和输入闭包**

  将 `dem.tif` 作为唯一 DEM 文件，删除 `广东DEM30M.zip` 输入表述；列出用户给出的 10 个绝对路径对应的仓库相对路径；将三家 provider 缓存定义为独立的只读 cache inventory。

- [ ] **Step 2: 写清当前实现的分层数据流**

  按“文件/上传 → 解析诊断 → source admission → session catalog → generic resource catalog → normalized representation/capability → snapshot/CAS → 下游只读消费”的顺序说明每一层保存什么、依赖什么、拒绝什么，并给出实际代码文件和函数入口。

- [ ] **Step 3: 明确不变量与失败语义**

  固化 source digest、dataset-scoped feature ref、native/normalized geometry 双表示、CRS fail-closed、admission status、quarantine、DataGap、外部观测不可执行等规则；区分当前已经能观察到的错误分类和尚未实现的完整恢复状态机。

- [ ] **Step 4: 增加“非 MVP/无兼容保证”章节**

  明确 `VillageBundle`、BSM/DLBM 固定组装、planned 数据、远程 API 抓取、legacy external anchor 注入、任意 GIS/字段/CRS 兼容均不构成 MVP 保证。保留代码不等于继续支持这些路径。

- [ ] **Step 5: 增加当前实现矩阵和下一步接线项**

  对上传解析、session 重建、generic catalog、facade、CAS、provider cache inventory、legacy path 分别标记 `IMPLEMENTED`、`PARTIAL`、`NOT WIRED` 或 `OUT OF MVP`，并只列出可验证的后续工作。

### Task 3: 同步验收与运行时文档

**Files:**
- Modify: `docs/design/acceptance/01_data_acceptance.md`
- Modify: `docs/design/acceptance/00_common.md`
- Modify: `docs/design/DOCUMENTATION_AUTHORITY.md`
- Modify: `docs/architecture/CURRENT_RUNTIME.md`
- Modify: `backend/app/data/README.md`
- Modify: `backend/app/data/ingestion/README.md`
- Modify: `backend/app/data/catalog/README.md`

**Interfaces:**
- Consumes: `DATA_EXECUTABLE_DESIGN.md` 的 canonical 规则。
- Produces: 不再宣称旧兼容路径和未验证探针结果的 supporting/current 文档。

- [ ] **Step 1: 重写 P0 输入表和验收条件**

  只保留 10 个 current GeoJSON、DEM、现状报告和三家本地缓存；删除不存在的 ZIP 和“全部 ADMITTED/CAS 已完成”的虚假运行记录；把尚未实际接通的 facade/CAS e2e 写为 `PARTIAL` 或待验证。

- [ ] **Step 2: 修正权威关系和当前运行描述**

  让 design、acceptance、CURRENT_RUNTIME、data README 对 DATA 的 owner、legacy transition 和 current/planned 隔离使用一致术语。

- [ ] **Step 3: 明确 catalog README 的 legacy 地位**

  将 `DataCatalog.load_village_bundle*` 定义为过渡/兼容代码而非 `app.data` 的 MVP 唯一入口；把 generic catalog/session snapshot 作为当前 DATA 规范入口。

### Task 4: 文档自检与 DATA 回归验证

**Files:**
- Test: `tests/test_geometry_lineage.py`
- Test: `tests/test_external_observation_cache.py`
- Test: `tests/test_external_observation_adapter.py`
- Verify: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Verify: `docs/design/acceptance/01_data_acceptance.md`

**Interfaces:**
- Consumes: Tasks 2–3 的文档变更和现有代码。
- Produces: 文档内部一致性结果、测试结果和仍然存在的实现 gap。

- [ ] **Step 1: 重新读取所有变更文件**

  检查相对路径、状态标签、用户给出的文件名、`dem.tif` 元数据和 `data/cache/map_observations` 路径没有互相矛盾。

- [ ] **Step 2: 执行现有 DATA 定向测试**

  运行：

  ```powershell
  python -m pytest tests/test_geometry_lineage.py tests/test_external_observation_cache.py tests/test_external_observation_adapter.py -q
  ```

  预期：现有 DATA/外部观测回归测试通过；测试结果只证明已有测试覆盖的代码，不将其扩大为完整真实输入 e2e 证明。

- [ ] **Step 3: 做静态旧承诺扫描**

  运行 `rg -n "广东DEM30M.zip|全部.*ADMITTED|CAS.*重载成功|兼容.*保证|load_village_bundle.*MVP" docs/design docs/architecture backend/app/data`，逐项确认只剩历史说明或已明确标注为 legacy/非 MVP 的内容。

- [ ] **Step 4: 汇总交付边界**

  最终说明：本次交付完成的是 DATA 设计/验收范围收敛和文档纠偏；旧代码没有被删除，后续若要物理移除 legacy path，需要单独的代码迁移任务和回归范围。
