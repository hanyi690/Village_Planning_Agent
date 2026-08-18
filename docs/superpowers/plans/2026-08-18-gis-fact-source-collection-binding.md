# GIS Fact and Source Collection Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild KG/L1 as an accurate, typed evidence base; ensure L3 contains goals rather than invented facts; and carry audited GIS source-feature sets through GROUND, SELECT, EXECUTE, validation, and delivery so the default live workflow produces non-empty, meaningful planning layers.

**Architecture:** Original reports, versioned GIS snapshots, and the canonical KG form the L1 fact base. L3 goals cite typed L1 fact IDs. TARGET_PROJECTION compiles each single operation into either a source-collection binding, an explicit source-feature subset, or a generated-candidate demand. GROUND distinguishes required factual members from alternatives; SELECT retains all required members and optimizes only alternatives/subsets; EXECUTE materializes operation-aware features with complete source and scenario lineage.

**Tech Stack:** Python 3, Pydantic v2, RDFLib/GeoSPARQL, Shapely, GeoJSON, pytest, SQLite artifact/checkpoint stores, existing workflow graph and delivery APIs.

## Global Constraints

- [ ] Treat the canonical KG as an authoritative evidence system after it passes snapshot, semantic-type, source-identity, and geometry consistency checks. Do not bypass it with a one-off manual binding overlay.
- [ ] Keep three concepts separate: a report business count, a GIS source feature count, and a graph/topology edge count. Every numeric fact must carry a `counting_basis`.
- [ ] Never use quantity equality as proof that a target binds a source collection.
- [ ] Never synthesize exact points or lines from centroids, parcel unions, representative points, or arbitrary two-point connections.
- [ ] Keep hard constraints fail-closed. Change their semantics only when the operation differs, such as `preserve_existing` versus `new_corridor`.
- [ ] Preserve the dirty worktree. Do not reset, discard, stage, or commit unrelated changes.
- [ ] Use focused tests first. Do not launch the full FastAPI/demo stack during implementation.
- [ ] After every pytest, rebuild, or replay command, inspect `python`, `python3`, and `uvicorn`; terminate only confirmed processes started by that task.
- [ ] Do not copy the large business database. Use the existing controlled clone/checkpoint mechanism and bounded memory preflight.
- [ ] Use one status token in maintained documents: `CURRENT`, `PARTIAL`, `GAP`, `TARGET`, `HISTORICAL`, or `DEPRECATED`.

## Evidence Baseline and Non-Negotiable Semantics

- The source report says that Road 122 is the main external road and the only east-west road; internal village roads are comb-shaped and mostly north-south; some are gravel or farm roads; most are narrower than 8 m; the village has one parking lot and three bus stops, with one shelter.
- The statutory planning text sets operation goals: Road 122 controlled to 8 m, all internal roads hardened, main roads at least 6 m, branches at least 4 m, and lanes at least 2 m.
- `data/gis/jintian/current/road.geojson` contains 131 current-road `MultiLineString` source features. That is a source-record count, not a human road count and not a topology-edge count.
- The polluted value 275 is exactly 131 current-road features plus 144 administrative-boundary features. It must disappear from rebuilt L1 and cannot be retained as a competing road fact.
- L1 contains typed facts. L3 contains goals that cite those facts. A preserve target may bind a complete current-road collection; a harden/widen target needs a supported subset or explicit scope; a new connection needs endpoints and network analysis.

## Dependency Graph and Assignment Boundaries

```text
Task 1 KG types ──> Task 2 KG query/count semantics ──> Task 3 typed L1 contracts
                                                        ├─> Task 4 evidence/gates
                                                        └─> Task 5 L3 goal boundary
Tasks 4 + 5 ──> Task 6 collection binding ──> Task 7 GROUND cardinality
                                         └──> Task 8 SELECT multi-member scenario
Task 8 ──> Task 9 operation-aware EXECUTE ──> Task 10 validation/delivery
Tasks 1-10 ─────────────────────────────────> Task 11 fresh replay and docs
```

Tasks are independently assignable at the indicated dependency boundary. Each worker owns only the files listed in its task and must return test output plus a concise file-change ledger. If a worker encounters overlapping user changes, it stops editing the overlap and reports the exact hunk.

---

## Task 1: Enforce Existing KG Layer Semantics and Source Identity

**Depends on:** none

**Owns:**

- Modify: `backend/app/infrastructure/kg/ontology.py`
- Modify: `backend/app/infrastructure/kg/builder/layer1_extended.py`
- Verify: `backend/app/infrastructure/kg/builder/layer1_core.py`
- Create: `backend/tests/core/test_kg_source_fact_type_boundaries.py`

**Purpose:** Make the existing three-dimensional KG semantics authoritative for every business query. The repository already distinguishes `gis_type_ref`, `semantic_group`, `geometry_kind`, and `GisLayerSet`; P0 must stop consumers from discarding those dimensions. More specific RDF subclasses are an optional compatible refinement, not a prerequisite for correct counts or retrieval.

- [ ] Write failing tests that build a minimal KG with one current road, one administrative boundary, one contour, and one elevation point.
- [ ] Assert that the current-road resource has the composite identity `current_road + transport + line`.
- [ ] Assert that administrative boundary, contour, and elevation resources have `admin_boundary_line + admin + line`, `contour_line + terrain + line`, and `elevation_point + terrain + point` respectively.
- [ ] Assert that all four preserve `source_feature_id`, `source_dataset`, `source_snapshot_ref` or digest, and GeoSPARQL WKT.
- [ ] Introduce a shared business-feature selector that requires `gis_type_ref`, `semantic_group`, geometry kind, and snapshot/source provenance rather than relying on `rdf:type` alone.
- [ ] If compatibility analysis permits, add `AdministrativeBoundary`, `ContourLine`, and `ElevationPoint` subclasses and dual-type old resources during migration. Do not make this optional ontology cleanup the P0 acceptance gate.
- [ ] Confirm `layer1_core.py` still emits current roads as `Road` with the transport semantic group.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_kg_source_fact_type_boundaries.py tests/core/test_place_evidence_kg_types.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** A transport-road query cannot include admin or terrain features even before optional subclass migration, and no source identity or geometry is lost.

**Suggested commit:** `fix(kg): separate transport admin and terrain entity types`

---

## Task 2: Replace Raw RDF Counts with Typed KG Fact Queries

**Depends on:** Task 1

**Owns:**

- Modify: `backend/app/infrastructure/kg/queries/cognition.py`
- Modify: `backend/app/infrastructure/kg/queries/semantic.py`
- Modify: `backend/app/infrastructure/kg/queries/spatial_ref.py`
- Create: `backend/app/contracts/evidence/kg_fact_contracts.py`
- Create: `backend/tests/core/test_kg_typed_fact_queries.py`

**Purpose:** Make KG results accurate evidence instead of presentation strings assembled from unqualified node counts.

- [ ] Add a typed KG fact record similar to:

```python
class KGFactRecord(BaseModel):
    fact_id: str
    subject_scope: str
    predicate: str
    value: str | int | float
    unit: str = ""
    counting_basis: Literal[
        "source_feature", "business_object", "topology_edge", "derived_metric"
    ]
    semantic_group: str
    source_snapshot_ref: str
    source_feature_ids: list[str] = Field(default_factory=list)
    derivation: str = ""
```

- [ ] Replace `rdf:type`-only counts with queries constrained by canonical entity type, semantic group, source collection, and snapshot.
- [ ] Return `131 source features in current road collection` as a source-feature fact, never as `131 roads` or `131 road segments`.
- [ ] Require a documented aggregation key before returning a business-object count. If road names or canonical IDs are absent, do not invent a human road count.
- [ ] Keep topology edge counts under the network-analysis namespace and never merge them into L1 entity counts.
- [ ] Make `spatial_ref.py` resolve a source collection and explicit feature subset using snapshot-scoped IDs.
- [ ] Add a regression fixture where 131 transport lines and 144 admin lines coexist; the typed road query returns 131 and the admin query returns 144.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_kg_typed_fact_queries.py tests/contracts/test_kg_parsing_folded.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** KG facts state both meaning and counting basis; no consumer can interpret a raw node count as a real-world road count.

**Suggested commit:** `fix(kg): emit snapshot-scoped typed evidence facts`

---

## Task 3: Introduce Typed, Traceable L1 Facts

**Depends on:** Task 2

**Owns:**

- Modify: `backend/app/contracts/domain/l1_contracts.py`
- Modify: `backend/app/domain/assessment/aggregate.py`
- Modify: `backend/app/infrastructure/context/planning_context.py`
- Modify: `backend/app/ports/observation_store.py` if persistence adapters require the new field
- Create: `backend/tests/core/test_l1_typed_fact_contract.py`

**Purpose:** Ensure L1 facts can prove their origin and semantics. Plain strings remain a compatibility projection, not the authoritative representation.

- [ ] Add an `L1Fact` contract with at least:

```python
class L1Fact(BaseModel):
    fact_id: str
    statement: str
    fact_kind: Literal[
        "document_observation", "gis_observation", "kg_canonical_fact", "derived_metric"
    ]
    dimension_key: str
    subject_scope: str
    value: str | int | float | None = None
    unit: str = ""
    counting_basis: str = ""
    source_refs: list[str] = Field(min_length=1)
    source_span: str = ""
    source_snapshot_ref: str = ""
    source_feature_ids: list[str] = Field(default_factory=list)
    derivation: str = ""
```

- [ ] Add `fact_records` to `L1DimensionFragment` and `L1Snapshot`. Keep `facts` and `facts_by_dimension` as deterministic legacy views generated from records.
- [ ] Validate that document observations carry a report ref plus a non-empty locator/span; GIS and KG facts carry a snapshot ref; derived metrics carry their input fact IDs and derivation.
- [ ] Deduplicate by stable fact fingerprint, not by statement text alone.
- [ ] Aggregate typed records without stripping source spans, source IDs, units, or counting basis.
- [ ] Serialize records into planning context so L2/L3 can cite fact IDs.
- [ ] Add migration tests that load legacy artifacts but label legacy strings `unverified_legacy` rather than silently treating them as authoritative facts.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_l1_typed_fact_contract.py tests/core/test_l1_source_fact_contract.py tests/core/test_l1_identity_binding_contracts.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** Every authoritative L1 fact is traceable to a report span, GIS snapshot, or canonical KG record; the 275 legacy string cannot pass as an authoritative fact.

**Suggested commit:** `feat(l1): add typed provenance-rich fact records`

---

## Task 4: Make EXPLORE and the L1 Evidence Gate Enforce Fact Quality

**Depends on:** Task 3

**Owns:**

- Modify: `backend/app/evidence/retrieval/retrievers/kg_retriever.py`
- Modify: relevant report/GIS retrievers under `backend/app/evidence/retrieval/retrievers/`
- Modify: `backend/app/domain/assessment/gate.py`
- Modify: `backend/app/contracts/evidence/evidence_contracts.py` only if typed support relations are absent
- Create: `backend/tests/core/test_l1_fact_conflict_gate.py`
- Create: `backend/tests/core/test_explore_typed_fact_evidence.py`

**Purpose:** Prevent Explore from promoting KG diagnostics, free-form summaries, or incomparable counts into facts.

- [ ] Change `kg_retriever.py` to emit the typed records from Task 2 rather than constructing `EvidenceFact` from `entity_counts` strings.
- [ ] Make report evidence include exact document refs and source spans for the traffic statements supplied in the baseline.
- [ ] Make GIS evidence include source collection key, snapshot digest, geometry kind, feature IDs, and source-feature count.
- [ ] Reuse the actual `annotations_current` source for facility retrieval. A `facilities` scope must include the 30 current facility annotations and expose the three station features and one parking feature as typed source evidence, not merely a group-count string.
- [ ] Return original report document refs and exact spans for the traffic-facility observations instead of using generated `L1:traffic` as the terminal source.
- [ ] Add support relations: `supports`, `contradicts`, `refines`, `different_counting_basis`, and `unverified`.
- [ ] Compare numbers only when subject scope, time/snapshot, unit, and counting basis are compatible.
- [ ] Gate any quantitative fact without valid lineage; emit an evidence gap rather than guessing.
- [ ] Add a regression test with the legacy 275 statement and the 131-feature collection. Expected result: 275 is `unsupported/type_pollution`; 131 remains a valid source-feature fact; the system does not call them a legitimate count mismatch.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_l1_fact_conflict_gate.py tests/core/test_explore_typed_fact_evidence.py tests/acceptance/test_real_l1_resolution_coverage.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** Explore may enrich missing evidence, but cannot transform an internal KG count or model summary into an authoritative L1 fact.

**Suggested commit:** `fix(evidence): gate facts by provenance scope and counting basis`

---

## Task 5: Keep L3 as Goals and Split Mixed Road Claims

**Depends on:** Tasks 3 and 4

**Owns:**

- Modify: the planning-claim contract under `backend/app/contracts/`
- Modify: L3 claim assembly/compiler under `backend/app/domain/` and its prompt/adapter boundary
- Modify: `backend/app/data/ingestion/compiler/spec_mapper.py`
- Create: `backend/tests/core/test_l3_goal_fact_boundary.py`
- Create: `backend/tests/core/test_road_goal_operation_split.py`

**Purpose:** L3 expresses desired change. It cites L1 but cannot copy an unsupported quantity into a goal or combine preservation, upgrading, and new construction into one target.

- [ ] Add `source_fact_refs: list[str]` to planning claims and require each ref to resolve to an authoritative L1 fact.
- [ ] Keep narrative `evidence_refs` only for explanation; do not accept them as proof of a numeric or spatial premise.
- [ ] Reject or defer quantitative claims whose value/unit/counting basis do not match the cited facts.
- [ ] Split the current traffic intent into single-operation goals:

```text
preserve_current_network
harden_or_repair_bound_segments
widen_bound_segments_to_standard
create_east_west_connection
improve_transport_facilities
```

- [ ] Do not automatically apply “all roads hardened” or width standards to all 131 features unless the target scope and source attributes support that interpretation. Produce an evidence gap for unknown surface/width attributes.
- [ ] Do not retain JTC-014 as one `new + preserve + 275` claim. Regenerated artifacts must cite real traffic fact IDs and legal goal refs.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_l3_goal_fact_boundary.py tests/core/test_road_goal_operation_split.py tests/test_source_binding_target_projection.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** L3 cannot create facts; each target has one operation and an auditable relationship to L1 facts and planning-policy sources.

**Suggested commit:** `fix(l3): separate goals from facts and split road operations`

---

## Task 6: Replace Count-Equality Binding with Source-Collection Binding

**Depends on:** Tasks 4 and 5

**Owns:**

- Modify: `backend/app/contracts/evidence/identity_contracts.py`
- Modify: `backend/app/evidence/identity/source_feature_binding.py`
- Modify: `backend/app/evidence/identity/binding_store.py`
- Modify: `backend/app/data/ingestion/compiler/spec_mapper.py`
- Modify: `backend/app/domain/program/target_projection/compile.py`
- Create: `backend/tests/core/test_source_collection_binding.py`
- Modify: `backend/tests/characterization/test_road_source_geometry_binding.py`

**Purpose:** Bind by verified meaning and scope. Broad preservation binds the audited current-road collection; a partial intervention binds an explicit/audited subset; new construction does not bind existing geometry as its output.

- [ ] Add a binding contract similar to:

```python
class SourceFeatureSetBinding(BaseModel):
    binding_id: str
    target_id: str
    source_collection_key: str
    source_snapshot_ref: str
    source_feature_digest: str
    source_feature_ids: list[str] = Field(min_length=1)
    binding_mode: Literal["all_in_scope", "explicit_subset", "query_subset"]
    membership: Literal["required", "alternative", "eligible_subset"]
    operation: Literal["preserve", "harden", "repair", "widen", "reference"]
    source_fact_refs: list[str] = Field(min_length=1)
```

- [ ] Remove `_declared_road_quantity` as a binding gate and delete the `quantity == len(valid)` fallback.
- [ ] Remove facility count equality as identity proof as well. Extend the existing source vocabulary with `停 -> 停车场`, keep `站 -> 公交站`, and bind supported facility subsets by semantic type plus snapshot-scoped feature IDs.
- [ ] Reuse `EvidenceObservationSnapshot`, `GroundedEntityBindingSnapshot`, `PlaceEvidenceIndex`, and the KG spatial query adapter as binding inputs; do not create a parallel facility lookup store.
- [ ] Bind `preserve_current_network` to all features in the verified `roads_current` snapshot using the collection digest and the cited collection fact.
- [ ] Bind named roads or partial upgrades by explicit IDs or a deterministic KG query over source attributes. Persist the resolved membership and query fingerprint.
- [ ] Reject stale/missing feature IDs, digest mismatch, non-line members, mixed snapshots, and empty subsets.
- [ ] Keep `new_corridor` unbound to existing output geometry; existing roads may enter only as network/reference evidence.
- [ ] Replace the old mismatch characterization: a numeric mismatch is irrelevant; missing scope or invalid lineage is the actual failure.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_source_collection_binding.py tests/characterization/test_road_source_geometry_binding.py tests/test_source_binding_target_projection.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** A supported current-road goal binds its complete verified source collection without count comparison, and every member is snapshot-scoped and auditable.

**Suggested commit:** `feat(binding): add audited source feature set bindings`

---

## Task 7: Add Required-Set and Alternative Cardinality to GROUND

**Depends on:** Task 6

**Owns:**

- Modify: `backend/app/contracts/spatial/grounded_problem.py`
- Modify: `backend/app/domain/ground/aggregate.py`
- Modify: `backend/app/spatial/grounding/resolver.py`
- Modify: relevant candidate-domain builder under `backend/app/domain/ground/`
- Create: `backend/tests/core/test_grounded_candidate_cardinality.py`
- Modify: `backend/tests/core/test_point_line_grounding_without_parcel_area.py`

**Purpose:** Represent a factual feature set as required members, while retaining choose-one alternatives for generated sites and routes.

- [ ] Extend `GroundedCandidateDomain` with:

```python
selection_mode: Literal["all_members", "choose_one", "choose_subset"]
min_selected: int = 0
max_selected: int | None = None
binding_ref: str = ""
```

- [ ] Validate `all_members` as `min=max=len(candidate_ids)` and `choose_one` as `min=max=1` when resolved.
- [ ] For a source feature set, create one exact `CandidateGeometry` per line feature with `granularity=exact_feature`, `generation_operation=grounded_source_feature`, source ID, snapshot, and binding ref. Do not union the lines.
- [ ] Mark preserved source members `all_members`; mark alternative new site/corridor candidates `choose_one`; use `choose_subset` only when a capacity/objective explicitly requests a subset.
- [ ] Keep parcel unions as candidate-only polygon domains for point/line targets.
- [ ] Ensure hard-constraint results are operation-aware inputs, not silently copied from new construction to preservation.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_grounded_candidate_cardinality.py tests/core/test_point_line_grounding_without_parcel_area.py tests/core/test_typed_candidate_geometry.py tests/core/test_typed_candidate_domains.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** GROUND can carry all 131 exact source lines as one required set without interpreting them as 131 mutually exclusive alternatives.

**Suggested commit:** `feat(ground): model required and alternative candidate domains`

---

## Task 8: Make SELECT Produce Multi-Member Target Selections

**Depends on:** Task 7

**Owns:**

- Modify: `backend/app/contracts/planning/scenario.py`
- Modify: `backend/app/domain/allocation/scenario_solver.py`
- Modify: `backend/app/domain/allocation/scenario_builder.py`
- Modify: `backend/app/domain/allocation/network_subproblem.py`
- Modify: `backend/app/workflow/stages/select.py`
- Create: `backend/tests/core/test_multi_member_scenario_selection.py`
- Modify: `backend/tests/core/test_relation_aware_scenario_solver.py`
- Modify: `backend/tests/core/test_scenario_fingerprint_determinism.py`

**Purpose:** Stop forcing exactly one candidate per target. Required sets are fixed scenario facts; only alternatives/subsets enter combinatorial search.

- [ ] Add an authoritative scenario selection contract:

```python
class ScenarioTargetSelection(BaseModel):
    target_id: str
    selection_mode: Literal["all_members", "choose_one", "choose_subset"]
    candidate_ids: list[str] = Field(min_length=1)
    binding_ref: str = ""
```

- [ ] Add `target_selections` to `PlanningScenario` and include its sorted canonical representation in the fingerprint.
- [ ] Retain `selected_candidate_ids: dict[str, str]` only as a compatibility view for `choose_one`; no consumer may use it as the authoritative selection after migration.
- [ ] Refactor `_choices()` and the product search: inject `all_members` into every assignment, enumerate `choose_one`, and apply bounded subset optimization only for `choose_subset`.
- [ ] Evaluate relations across all selected features for a target. Do not collapse a feature set to a union solely to satisfy the existing evaluator.
- [ ] Build one `ScenarioFeature` for each selected member, each with its candidate/source lineage and common target/binding reference.
- [ ] Add tests for 3 required road lines plus 2 facility alternatives: all 3 roads survive; exactly 1 facility is chosen; replay fingerprint is deterministic.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_multi_member_scenario_selection.py tests/core/test_relation_aware_scenario_solver.py tests/core/test_scenario_fingerprint_determinism.py tests/core/test_scenario_feature_lineage.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** SELECT preserves every required member and still solves alternatives deterministically within the configured search bound.

**Suggested commit:** `feat(select): support multi-member target selections`

---

## Task 9: Make Constraints and EXECUTE Operation-Aware

**Depends on:** Task 8

**Owns:**

- Modify: `backend/app/contracts/domain/road_planning.py`
- Modify: constraint compilation/evaluation modules under `backend/app/domain/allocation/` and `backend/app/domain/validation/`
- Modify: `backend/app/contracts/workflow/execution_plan_contracts.py`
- Modify: `backend/app/domain/materialization/plan_builder.py`
- Modify: `backend/app/domain/materialization/existing_road_materializer.py`
- Modify: `backend/app/domain/materialization/nodes/road_worker.py`
- Create: `backend/tests/core/test_road_operation_constraint_semantics.py`
- Create: `backend/tests/core/test_multi_feature_road_execution.py`

**Purpose:** Apply the correct spatial algorithm and constraint footprint for each road operation, and carry feature sets into execution without losing members.

- [ ] Define canonical road operations: `reference`, `preserve`, `harden`, `repair`, `widen`, and `new_corridor`.
- [ ] For `reference` and `preserve`, retain source geometry and lineage. Existing legal geometry is not rejected as if it were a proposed new occupation merely because it intersects farmland or another current constraint.
- [ ] For `harden` and `repair`, require an audited existing subset and materialize an attribute/operation overlay on the same centerline.
- [ ] For `widen`, require current/target width, compute the proposed impact buffer in a metric CRS, and evaluate new impact area against protection/control constraints.
- [ ] For `new_corridor`, require resolved endpoints, a routable network/cost surface, and hard-constraint-safe generated geometry. Never copy an existing line and label it new.
- [ ] Add `candidate_ids: list[str]` and `binding_ref` to `WorkerTask` and `TaskExecutionResult`; keep singular `candidate_id` only for backward-compatible single-member tasks.
- [ ] Make plan builder schedule either one idempotent set task or deterministic member tasks. Whichever form is chosen, every selected scenario feature must yield exactly one traceable execution result.
- [ ] Make the road materializer emit `source_feature_id`, `source_snapshot_ref`, `binding_ref`, `operation`, `target_id`, `scenario_id`, and relation IDs on every feature.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_road_operation_constraint_semantics.py tests/core/test_multi_feature_road_execution.py tests/core/test_final_relation_validation.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** Preserve/harden/widen/new operations have distinct constraint and materialization behavior; no selected member is dropped or relabeled.

**Suggested commit:** `feat(execute): materialize operation-aware road feature sets`

---

## Task 10: Validate and Deliver Distinct, Auditable Planning Layers

**Depends on:** Task 9

**Owns:**

- Modify: `backend/app/domain/validation/scenario_reconciliation.py`
- Modify: `backend/app/domain/validation/relation_validation.py`
- Modify: `backend/app/domain/validation/validate_checks.py`
- Modify: `backend/app/infrastructure/export/delivery_snapshot.py`
- Modify: the backend map-layer adapter used by `/map-layers`
- Create: `backend/tests/acceptance/test_road_planning_layer_delivery.py`
- Create: `backend/tests/core/test_source_set_member_completeness.py`

**Purpose:** Prove that planning output is complete, geometrically valid, semantically distinct from the baseline, and traceable to facts and decisions.

- [ ] Add a member-completeness check: every required/selected source member must appear in the scenario and in the expected execution output, unless an explicit deferred/failed ledger entry explains it.
- [ ] Reject empty, invalid, placeholder, duplicate-with-conflicting-operation, orphan, stale-snapshot, and geometry/source-kind-mismatch features.
- [ ] Validate that preserve overlays may share geometry with the baseline but have planning-operation lineage; do not count them as generated geometry changes.
- [ ] Publish separate render groups:

```text
current_road_reference
planned_road_preserve
planned_road_harden_or_repair
planned_road_widen
planned_new_connection
planned_transport_facility
road_fact_conflicts
```

- [ ] Ensure `/map-layers` reports baseline/planning distinction, feature counts, scenario ID, snapshot/digest, operations, and quality findings.
- [ ] Add an acceptance fixture with source roads, one preserved set, one upgraded subset, and one new route; assert non-empty planning layers and zero orphans.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_source_set_member_completeness.py tests/acceptance/test_road_planning_layer_delivery.py tests/characterization/test_wave3_validation_boundaries.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** The delivered map distinguishes facts from planning operations and proves that selected members survived the entire pipeline.

**Suggested commit:** `feat(delivery): publish audited road operation layers`

---

## Task 11: Rebuild, Run a Low-Memory Fresh Replay, and Reconcile Documents

**Depends on:** Tasks 1-10

**Owns:**

- Modify: `docs/design/modules/spatial-execution/06_TARGET_PROJECTION_EXECUTE.md`
- Modify: `docs/design/modules/explore/23_EXPLORE_RETRIEVAL_REDESIGN.md`
- Modify: `docs/design/modules/spatial-execution/28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md`
- Modify: `docs/design/modules/spatial-execution/29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md`
- Modify: `docs/design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md`
- Modify: `docs/design/RELATION_AWARE_MODIFICATION_LEDGER.md`
- Modify: the prior v2 plan only to label contradicted conclusions `DEPRECATED` or `HISTORICAL`
- Create: one bounded replay report under the existing `.run-tmp/sdd/...` evidence directory

**Purpose:** Demonstrate the corrected design in the default live path, not merely in unit tests or a clone-only branch.

- [ ] Run a preflight that records available memory, expected database size, checkpoint path, source snapshot digests, and process IDs. Abort safely if memory bounds fail.
- [ ] Rebuild the canonical KG from the versioned GIS bundle. Verify:

```text
transport Road source features = 131
administrative boundaries are not Road
contours are not Road
elevation points are not Facility
legacy road fact 275 is absent
all source IDs and geometries round-trip GIS -> KG -> spatial query
```

- [ ] Regenerate L1 and assert that its traffic facts match the original report spans and typed GIS/KG records. It must not claim a human road count unless a supported aggregation exists.
- [ ] Regenerate L3 and assert that road goals are single-operation targets citing valid L1 fact IDs.
- [ ] Run fresh TARGET_PROJECTION -> GROUND -> SELECT -> EXECUTE -> VALIDATE -> RECONCILE -> DELIVER through the default live graph using the controlled checkpoint/clone mechanism.
- [ ] At GROUND, record exact point/line/polygon counts, selection modes, required-set size, snapshot refs, and candidate-only/deferred reasons.
- [ ] At SELECT, prove that the expected source set is preserved and alternatives are selected according to cardinality. Record hard-relation status.
- [ ] At EXECUTE and DELIVER, prove non-empty road planning overlays, source lineage, operation types, geometry validity, member completeness, and `/map-layers` visibility.
- [ ] Resume the same checkpoint a second time. Require unchanged scenario/final-validation fingerprints and zero new LLM or worker executions.
- [ ] After every command, close only task-owned stale backend processes and record final process/memory state.
- [ ] Update all owned documents to use the same evidence. Specifically remove or deprecate “275 versus 131 prevents binding,” explain the KG construction defect, add cardinality semantics, and distinguish clone-only replay28 from the fresh default-live result.

**Final acceptance gate:** Do not label the implementation `COMPLETE` until all conditions below hold:

- [ ] rebuilt KG is semantically typed and snapshot-consistent;
- [ ] L1 contains the supplied traffic facts and no polluted 275 road fact;
- [ ] L3 road targets cite L1 and contain one operation each;
- [ ] GROUND has source-backed exact lines with required/alternative cardinality;
- [ ] SELECT retains all required members and satisfies or explicitly defers hard relations;
- [ ] EXECUTE produces non-baseline road planning features with complete lineage;
- [ ] VALIDATE/RECONCILE report no empty, invalid, placeholder, orphan, duplicate, stale, or kind-mismatch defects;
- [ ] `/map-layers` exposes non-empty audited planning layers;
- [ ] second resume is idempotent with zero incremental LLM/worker work;
- [ ] no task-owned Python/uvicorn process remains.

**Suggested commit:** `docs(replay): close GIS fact binding plan with live evidence`

---

## Recommended Delegation Waves

1. **Wave A — fact correctness:** Task 1, then Task 2. Keep one worker on ontology/builder and the next on query semantics to minimize merge overlap.
2. **Wave B — evidence contracts:** Task 3, then Tasks 4 and 5 may run in parallel after agreeing on the final `L1Fact` interface.
3. **Wave C — spatial set semantics:** Task 6, then Task 7, then Task 8. These must be reviewed sequentially because each changes the next stage's contract.
4. **Wave D — outputs:** Task 9, then Task 10.
5. **Wave E — proof and documentation:** Task 11 only after focused suites pass. Use one replay owner to avoid checkpoint-branch pollution.

At each handoff, the worker returns: changed files, contract/schema effects, focused test commands and results, known remaining gaps, process cleanup result, and whether any existing user hunk was left untouched.
