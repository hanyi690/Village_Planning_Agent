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
                                                        └─> Task 4 evidence/gates
Task 4 ──> Task 4A L1-constrained Flash source semantics ──> Task 5 L3 goal boundary
Tasks 4A + 5 ──> Task 6 collection binding ──> Task 7 GROUND cardinality
                                         └──> Task 8 SELECT multi-member scenario
Task 8 ──> Task 9 operation-aware EXECUTE ──> Task 10 validation/delivery
Accepted T1-T10, including T4A ─────────────> Task 11 fresh replay and docs
```

Tasks are independently assignable at the indicated dependency boundary, but execution is **serial by default**. Each worker owns only the files listed in its task and must return test output plus a concise file-change ledger. If a worker encounters overlapping user changes, it stops editing the overlap and reports the exact hunk.

## Subagent Dispatch and Reclamation Protocol

- [ ] The root agent remains the reviewer/orchestrator. Run at most **one implementation subagent at a time**; do not let child agents spawn additional agents.
- [ ] Before dispatch, run `list_agents`. If a previous implementation agent is still `running` or `waiting`, resume/review/reclaim it before creating the next one.
- [ ] Give the worker exactly one Task ID and its `Owns` list. Files outside that list are read-only; expanding ownership requires root approval and a plan edit first.
- [ ] The worker must return: changed files, public interfaces produced, focused test command/result, known gaps, `git diff --check` result, and Python/uvicorn cleanup result.
- [ ] The root reviews the diff and reruns the task's focused tests. Task status changes to accepted only after this review.
- [ ] For task-local defects, use `followup_task` on the same agent. After acceptance or terminal rejection, interrupt/reclaim that agent and confirm `list_agents` shows only `/root` before dispatching the next task.
- [ ] Never leave a replay, pytest, FastAPI, uvicorn, KG rebuild, or model process running between tasks.

## Exclusive File Ownership Matrix

| Task | Exclusive write scope | Read-only upstream | Dispatch rule |
|---|---|---|---|
| T1 | KG ontology/layer semantic builders + its new test | registry, source bundle | fresh agent, then reclaim |
| T2 | KG business queries + `kg_fact_contracts.py` + its test | T1 outputs | after T1 accepted |
| T3 | L1 fact contracts/aggregation + its test | T2 contract | after T2 accepted |
| T4 | Evidence contracts, three retrievers, L1 evidence gate + tests | T2/T3 contracts | after T3 accepted |
| T4A | Flash source-semantic contracts/classifier/cache + ingestion hints + tests | T3/T4 verified facts | after T4 accepted |
| T5 | Planning claim/draft/adapter/assembler only + tests | T3/T4A facts | after T4A accepted |
| T6 | Identity/binding + target projection mapper/compiler/stage + tests | T4A/T5 outputs | after T5 accepted |
| T7 | Grounded problem/resolver/ground candidate builder + tests | T6 binding | after T6 accepted |
| T8 | Scenario contract/solver/builder/select stage/network context + tests | T7 domain | after T7 accepted |
| T9 | Road operation factors and execution contracts/materializers + tests | T8 scenario | after T8 accepted |
| T10 | Final validation/delivery/map-layer read side + tests | T9 results | after T9 accepted |
| T11 | Replay evidence and documentation only | accepted T1-T10 | single replay owner |

No two tasks share production-file write ownership. A later task may consume an earlier interface but must not reopen the earlier task's files. If integration proves an earlier interface insufficient, return an interface-change request to the root; do not patch the upstream file opportunistically.

---

## Task 1: Enforce Existing KG Layer Semantics and Source Identity

**Depends on:** none

**Owns:**

- Modify: `backend/app/infrastructure/kg/ontology.py`
- Modify: `backend/app/infrastructure/kg/builder/layer1_extended.py`
- Verify: `backend/app/infrastructure/kg/builder/layer1_core.py`
- Create: `backend/tests/core/test_kg_source_fact_type_boundaries.py`

**Interfaces:**

- Consumes: `GIS_LAYER_REGISTRY` entries and existing source provenance predicates.
- Produces: a composite business-feature classification rule based on `gis_type_ref + semantic_group + geometry_kind + source provenance`; Task 2 must query through this rule.

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

**Interfaces:**

- Consumes: T1 composite business-feature classification.
- Produces: `KGFactRecord` and snapshot-scoped KG query results; T3 and T4 consume these without parsing display strings.

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

**Current implementation status (2026-08-19): PARTIAL.** `KGFactRecord`、完整 source identity
过滤、current road/facility selector 事实和 typed retrieval 已落地并有回归测试；source
collection 查询下沉到 `spatial_ref.py`、全量业务对象计数约束和所有拓扑查询仍待收敛。

**Suggested commit:** `fix(kg): emit snapshot-scoped typed evidence facts`

---

## Task 3: Introduce Typed, Traceable L1 Facts

**Depends on:** Task 2

**Owns:**

- Modify: `backend/app/contracts/domain/l1_contracts.py`
- Modify: `backend/app/domain/assessment/aggregate.py`
- Create: `backend/app/domain/assessment/l1_fact_projection.py`
- Create: `backend/tests/core/test_l1_typed_fact_contract.py`

**Interfaces:**

- Consumes: `KGFactRecord` from T2 plus existing report/GIS EvidenceFact inputs.
- Produces: authoritative `L1Fact` records and deterministic legacy string projections; T4 gates them and T5 cites `fact_id`.

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
    semantic_type: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    value: str | int | float | None = None
    unit: str = ""
    counting_basis: str = ""
    source_refs: list[str] = Field(min_length=1)
    source_span: str = ""
    source_snapshot_ref: str = ""
    source_feature_ids: list[str] = Field(default_factory=list)
    derivation: str = ""
```

- [x] Add `fact_records` to `L1Snapshot`. Keep `facts` and `facts_by_dimension` as deterministic display projections generated from records.
- [ ] Validate that document observations carry a report ref plus a non-empty locator/span; GIS and KG facts carry a snapshot ref; derived metrics carry their input fact IDs and derivation.
- [ ] Deduplicate by stable fact fingerprint, not by statement text alone.
- [ ] Aggregate typed records without stripping source spans, source IDs, units, or counting basis.
- [ ] Serialize records into planning context so L2/L3 can cite fact IDs.
- [ ] Store facility observations structurally: use `semantic_type="facility"`, preserve the exact L1 entity phrase in `attributes["entity_phrase"]` (for example `停车场` or `公交站点`), and add `attributes["entity_concept_ref"]` only when the current KG snapshot already resolves one. Do not require a global `parking_lot/bus_stop` business enum and do not recover authoritative facility types later by regex-parsing `statement`.
- [ ] Preserve nested qualifiers from the report instead of flattening them into extra facility entities: `3 bus stops` and `1 parking lot` are four facility members; `only one bus stop has a shelter` is an attribute/subfact of the bus-stop set, not a fifth facility. Preserve the parking lot's village-committee location and underuse observation as separate linked attributes/facts.
- [ ] Add migration tests that load legacy artifacts but label legacy strings `unverified_legacy` rather than silently treating them as authoritative facts.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_l1_typed_fact_contract.py tests/core/test_l1_source_fact_contract.py tests/core/test_l1_identity_binding_contracts.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** Every authoritative L1 fact is traceable to a report span, GIS snapshot, or canonical KG record; the 275 legacy string cannot pass as an authoritative fact.

**Current implementation status (2026-08-19): PARTIAL.** `L1Snapshot.fact_records`、稳定 ID、
来源投影、聚合去重、PlanningContext/L2/retriever 消费已落地；旧
`L1DimensionFragment` 输入契约和兼容 adapter 已移除。旧 artifact 迁移标记和全部 nested
qualifier 结构化校验仍不属于当前生产路径，历史 artifact 必须显式标记为
`unverified_legacy`，不能静默升级为权威 fact。

**Suggested commit:** `feat(l1): add typed provenance-rich fact records`

---

## Task 4: Make EXPLORE and the L1 Evidence Gate Enforce Fact Quality

**Depends on:** Task 3

**Owns:**

- Modify: `backend/app/evidence/retrieval/retrievers/kg_retriever.py`
- Modify: `backend/app/evidence/retrieval/retrievers/report_retriever.py`
- Modify: `backend/app/evidence/retrieval/retrievers/bundle_retriever.py`
- Modify: `backend/app/domain/assessment/gate.py`
- Modify: `backend/app/contracts/evidence/evidence_contracts.py`
- Create: `backend/tests/core/test_l1_fact_conflict_gate.py`
- Create: `backend/tests/core/test_explore_typed_fact_evidence.py`

**Interfaces:**

- Consumes: T2 `KGFactRecord` and T3 `L1Fact` identity/provenance rules.
- Produces: source-span/source-feature-aware `EvidenceFact` records and support relations; T5/T6 consume only verified refs.

**Purpose:** Prevent Explore from promoting KG diagnostics, free-form summaries, or incomparable counts into facts.

- [x] Change `kg_retriever.py` to emit the typed records from Task 2 rather than constructing `EvidenceFact` from `entity_counts` strings.
- [x] Make report evidence include exact document refs and source spans for the traffic statements supplied in the baseline.
- [x] Make GIS evidence include source collection key, snapshot digest, geometry kind, feature IDs, and source-feature count.
- [ ] Reuse the actual `annotations_current` source for facility retrieval. A `facilities` scope must include the 30 current facility annotations and expose the three station features and one parking feature as typed source evidence, not merely a group-count string.
- [ ] Return original report document refs and exact spans for the traffic-facility observations instead of using generated `L1:traffic` as the terminal source.
- [x] Add support relations: `supports`, `contradicts`, `different_counting_basis`, and `unverified` (the existing primary relation is preserved; quality relations are additive).
- [x] Compare numbers only when subject scope, time/snapshot, unit, and counting basis are compatible.
- [x] Gate any quantitative fact without valid lineage; emit an evidence gap rather than guessing.
- [x] Add a regression test with the legacy 275 statement and the 131-feature collection. Expected result: 275 is `unverified`; 131 remains a valid source-feature fact; the system does not call them a legitimate count mismatch.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_l1_fact_conflict_gate.py tests/core/test_explore_typed_fact_evidence.py tests/acceptance/test_real_l1_resolution_coverage.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** Explore may enrich missing evidence, but cannot transform an internal KG count or model summary into an authoritative L1 fact.

**Suggested commit:** `fix(evidence): gate facts by provenance scope and counting basis`

---

## Task 4A: Classify Ambiguous Source Vocabulary with L1-Constrained Flash Batches

**Depends on:** Tasks 3 and 4

**Owns:**

- Create: `backend/app/contracts/evidence/source_semantic_contracts.py`
- Create: `backend/app/evidence/identity/flash_source_semantic_classifier.py`
- Create: `backend/app/evidence/identity/source_semantic_store.py`
- Modify: `backend/app/data/ingestion/source_identity.py`
- Modify: `backend/app/data/model/spatial_types.py`
- Modify: `backend/app/infrastructure/llm/factory.py`
- Create: `backend/tests/core/test_flash_source_semantic_classifier.py`
- Create: `backend/tests/core/test_source_semantic_classification_replay.py`

**Interfaces:**

- Consumes: T3 structured `L1Fact` records, T4 verified evidence relations, and immutable GIS source descriptors (`source_feature_id`, snapshot digest, raw label, layer identity, geometry kind, and minimal source properties).
- Produces: a persisted `SourceSemanticClassificationSnapshot`. T5 may cite its supporting L1 facts; T6 may consume only decisions whose status is `accepted`. Neither task may read raw model text as a binding input.

**Purpose:** Replace brittle abbreviation tables and free-text regex guesses such as `停 -> 停车场` with a bounded semantic proposal step. The GIS feature ID, geometry, raw label, layer, and snapshot remain authoritative source facts. The expanded meaning of an abbreviated raw label is a snapshot-scoped inference constrained by L1, never a mutation of the source feature or an unqualified canonical KG fact.

- [ ] Remove one-character abbreviation expansion from the authoritative identity path. Existing maps such as `站 -> 公交站`, `祠 -> 祠堂`, and `停 -> 停车场/停车` may remain only as explicitly named `legacy_semantic_hint` or UI-display compatibility data; binding code must not treat them as verified semantics.
- [ ] Allow a deterministic fast path only for normalized exact equality with a canonical label that is present in the current KG/source snapshot or in the current L1 entity phrase, such as a source label already equal to `停车场`. Unicode/whitespace normalization is allowed; abbreviation expansion, substring rules, fuzzy matching, and regex-derived acceptance are not. No global string-to-type table is authoritative.
- [ ] Materialize the candidate vocabulary per `(source_snapshot, L1 fingerprint, layer scope)` instead of loading a fixed business vocabulary. Each candidate must originate from an entity-denoting L1 fact or an already-resolved KG semantic reference in this snapshot, carry its exact display phrase, source fact refs, optional KG concept ref, geometry/layer compatibility, and counting basis. If no fact or KG concept supplies a candidate, Flash must abstain; it may not invent one.
- [ ] Derive candidate refs deterministically: use `kg:<semantic-concept-uri>` when the current KG resolves the phrase, otherwise use `l1:<fact_id>:entity` (or another stable fact-derived ref). The model may select these refs but may never create a new ref. Thus the batch is operationally closed for safety while its business vocabulary remains data-driven and can change with each L1/KG snapshot.
- [ ] Admit only entity-denoting facts into the candidate-type list. Qualifiers such as `has_shelter`, `underused`, `located_at_village_committee`, surface condition, or adequacy may constrain or annotate a matched feature but may not become extra source-feature classes.
- [ ] Give Flash a small, canonical JSON context rather than the whole report:

```text
source items:  [{source_feature_id, raw_label, layer_key, geometry_kind, minimal_properties}]
L1 context:    [{fact_id, statement, semantic_type, attributes, value, unit, counting_basis}]
candidates:    [{candidate_ref, display_phrase, origin, supporting_fact_refs,
                 optional_kg_concept_ref, compatible_layers, compatible_geometry_kinds}]
instruction:  choose one candidate_ref or abstain for every source item; never invent a
              candidate, label, feature ID, fact ref, coordinate, BSM, geometry, count,
              or source property
```

- [ ] Sort source items, facts, candidates, and output fields before prompt hashing. Batch at most 32 ambiguous source features or vocabulary items per call; do not issue one model request per feature. The 30 current facility annotations must fit in one bounded batch.
- [ ] Add strict typed contracts similar to:

```python
class SourceSemanticCandidate(BaseModel):
    candidate_ref: str
    display_phrase: str
    origin: Literal["l1_fact", "kg_snapshot", "canonical_exact"]
    supporting_fact_refs: list[str] = Field(min_length=1)
    optional_kg_concept_ref: str = ""
    compatible_layers: list[str] = Field(default_factory=list)
    compatible_geometry_kinds: list[str] = Field(default_factory=list)

class SourceFeatureSemanticProposal(BaseModel):
    source_feature_id: str
    candidate_ref: str | None = None  # None means abstain
    supporting_fact_refs: list[str] = Field(default_factory=list)

class SourceFeatureSemanticDecision(BaseModel):
    source_feature_id: str
    raw_label: str
    semantic_type: str = ""  # copied from the accepted candidate, never model-authored
    status: Literal["accepted", "ambiguous", "unresolved"]
    authority: Literal["canonical_exact", "inferred_current"]
    supporting_fact_refs: list[str] = Field(default_factory=list)
    proposal_digests: list[str] = Field(default_factory=list)

class SourceSemanticClassificationSnapshot(ContractMeta):
    source_snapshot_ref: str
    source_snapshot_digest: str
    l1_fact_fingerprint: str
    vocabulary_fingerprint: str
    prompt_version: str
    model_id: str
    decisions: list[SourceFeatureSemanticDecision]
    fingerprint: str
```

- [ ] Use Instructor/Pydantic structured output only. A parse failure, truncated output, free-form answer, or schema retry exhaustion yields `unresolved`; there is **no free-text/regex fallback** for an accepted decision. The permissive fallback in `flash_mention_extractor.py` may be studied for call-budget and cache integration only and must not be reused as the semantic authority path.
- [ ] Fix `create_flash_llm()` so an explicit `temperature=0.0` is not replaced by `FLASH_MODEL_TEMPERATURE` through truthiness. Use the provider's lowest legal temperature where zero is unsupported, and record the effective value. Temperature and seed are reproducibility aids, not correctness guarantees.
- [ ] Run two bounded proposal passes for each uncached fingerprint. Normalize both typed outputs and accept a model-assisted edge only when `candidate_ref` and supporting fact refs are identical in both passes. A disagreement, abstention mismatch, or changed membership is `ambiguous`.
- [ ] Add a deterministic verifier after the model. Reject the whole affected batch, or mark affected members unresolved, for missing/duplicate/foreign feature IDs, omitted members, output-count mismatch, candidate refs outside the materialized per-batch set, foreign/missing fact refs, incompatible geometry/layer kind, or a candidate not backed by the current L1/KG snapshot.
- [ ] Treat quantities as consistency constraints, never identity proofs. Where L1 says `3个公交站点` and `1个停车场` and the GIS source batch contains three raw `站` points and one raw `停` point, require the accepted assignments to satisfy those business cardinalities and the source snapshot. If multiple assignments satisfy all constraints, no unique classification exists: mark the competing members `ambiguous` rather than selecting one by confidence or model order.
- [ ] Ignore model confidence for acceptance. Use a deterministic constraint/assignment check and accept only a unique evidence-compatible solution. An LLM answer that is fluent and repeated but violates source or L1 constraints is still rejected.
- [ ] Cache and persist by `source_snapshot_digest + l1_fact_fingerprint + vocabulary_fingerprint + prompt_version + schema_version + model_id + effective_temperature`. A resume with the same key makes zero model calls; any source or L1 change invalidates the key. Persist normalized input digest, both raw-output digests, verifier findings, and final decisions for audit.
- [ ] Store accepted inferred meanings as a semantic annotation overlay linked to source feature IDs and supporting L1 fact IDs. Do not change source IDs, WKT, raw labels, base KG layer/type assertions, or the original GIS snapshot. `inferred_current` must remain distinguishable from `canonical_exact` in KG/evidence queries.
- [ ] If Flash is disabled, unavailable, times out, exceeds budget, disagrees with itself, or cannot prove a unique closed-set assignment, emit an auditable unresolved/ambiguous artifact. Preserve the existing safe deferral/HUMAN path.
- [ ] Test all of the following with a fake model and no network: identical two-pass `3 x 站 + 1 x 停` proposals constrained by candidates dynamically materialized from the L1 phrases `公交站点` and `停车场` become three assignments to the former candidate and one to the latter; disagreement on `停` remains ambiguous; foreign candidate refs, duplicate features, missing fact refs, omitted output members, parse failure, and timeout never become accepted; cached replay makes zero additional calls; changed L1/source fingerprints force re-evaluation; and no regex fallback can accept `停`.
- [ ] Run:

```powershell
Set-Location backend
pytest -o addopts='' -p no:cacheprovider -q tests/core/test_flash_source_semantic_classifier.py tests/core/test_source_semantic_classification_replay.py tests/core/test_structured_output_runner.py tests/core/test_minimax_provider.py
Get-Process -Name python,python3,uvicorn -ErrorAction SilentlyContinue
```

**Acceptance:** Ambiguous source abbreviations can be resolved in a bounded batch only when two typed proposals agree and a deterministic L1/source constraint check has a unique valid solution. Random, malformed, unsupported, or merely high-confidence output cannot enter binding, KG canonical facts, or geometry production.

**Suggested commit:** `feat(evidence): add deterministic L1-constrained source semantic classification`

---

## Task 5: Keep L3 as Goals and Split Mixed Road Claims

**Depends on:** Tasks 3, 4, and 4A

**Owns:**

- Modify: `backend/app/contracts/program.py`
- Modify: `backend/app/domain/program/claim_draft.py`
- Modify: `backend/app/domain/program/claim_adapter.py`
- Modify: `backend/app/domain/program/assembler.py`
- Create: `backend/app/domain/program/road_goal_splitter.py`
- Create: `backend/tests/core/test_l3_goal_fact_boundary.py`
- Create: `backend/tests/core/test_road_goal_operation_split.py`

**Interfaces:**

- Consumes: T3 `L1Fact.fact_id`, T4 verified support relations, and accepted T4A semantic decisions when a goal cites an abbreviated GIS facility label.
- Produces: single-operation PlanningClaims/PlanningInterventions with `source_fact_refs`; T6 owns all spatial binding compilation.

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

**Depends on:** Tasks 4, 4A, and 5

**Owns:**

- Modify: `backend/app/contracts/evidence/identity_contracts.py`
- Modify: `backend/app/evidence/identity/source_feature_binding.py`
- Modify: `backend/app/evidence/identity/binding_store.py`
- Modify: `backend/app/data/ingestion/compiler/spec_mapper.py`
- Modify: `backend/app/domain/program/target_projection/compile.py`
- Modify: `backend/app/workflow/stages/target_projection.py`
- Create: `backend/tests/core/test_source_collection_binding.py`
- Modify: `backend/tests/characterization/test_road_source_geometry_binding.py`

**Interfaces:**

- Consumes: T4 verified source evidence, T4A accepted `SourceSemanticClassificationSnapshot` decisions, and T5 single-operation goals.
- Produces: `SourceFeatureSetBinding` plus source-scoped `SpatialReferenceSpec`; T7 must not infer membership again.

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
    source_semantic_decision_refs: list[str] = Field(default_factory=list)
```

- [ ] Remove `_declared_road_quantity` as a binding gate and delete the `quantity == len(valid)` fallback.
- [ ] Remove facility count equality as identity proof as well. Delete authoritative dependence on static abbreviation vocabulary. Bind facility subsets only from canonical-exact semantics or T4A `accepted` decisions, together with snapshot-scoped feature IDs and supporting fact refs. `ambiguous`, `unresolved`, raw model output, and `legacy_semantic_hint` are never binding inputs.
- [ ] Invoke/load T4A classification through the target-projection stage using the current source snapshot and L1 fingerprints. Persist the classification artifact reference in the stage output so resume reuses it and downstream lineage can audit it.
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

**Current implementation status (2026-08-19): PARTIAL.** `SourceFeatureSetBinding`、显式
member subset/collection binding、单快照校验、digest 和 binding ref 到 GROUND/EXECUTE 的
lineage 已落地；T4 verified source fact 注入、source semantic decision artifact 和所有
road/axis operation 的统一入口仍待完成。

**Suggested commit:** `feat(binding): add audited source feature set bindings`

---

## Task 7: Add Required-Set and Alternative Cardinality to GROUND

**Depends on:** Task 6

**Owns:**

- Modify: `backend/app/contracts/spatial/grounded_problem.py`
- Modify: `backend/app/domain/ground/aggregate.py`
- Modify: `backend/app/spatial/grounding/resolver.py`
- Modify: `backend/app/domain/ground/candidate_domain_builder.py`
- Create: `backend/tests/core/test_grounded_candidate_cardinality.py`
- Modify: `backend/tests/core/test_point_line_grounding_without_parcel_area.py`

**Interfaces:**

- Consumes: T6 `SourceFeatureSetBinding` and source-scoped spatial references.
- Produces: `GroundedCandidateDomain(selection_mode, min_selected, max_selected, binding_ref)` and exact per-member CandidateGeometry records; T8 treats this as authoritative.

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

**Current implementation status (2026-08-19): PARTIAL.** `GroundedCandidateDomain`、
`all_members`/`choose_one`、场景多成员选择已经实现并通过 3-member road regression；
source binding 仍未统一注入 `binding_ref`，`choose_subset` 尚未由容量/目标显式驱动。

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
- Modify: `backend/app/infrastructure/context/planning_context.py`
- Modify: `backend/app/infrastructure/context/planning_context_factory.py`
- Create: `backend/app/domain/allocation/scenario_context_builder.py`
- Create: `backend/tests/core/test_multi_member_scenario_selection.py`
- Modify: `backend/tests/core/test_relation_aware_scenario_solver.py`
- Modify: `backend/tests/core/test_scenario_fingerprint_determinism.py`

**Interfaces:**

- Consumes: T7 cardinality-aware grounded domains plus existing source roads/settlements.
- Produces: `ScenarioTargetSelection[]`, populated network/demand evaluator context, and multi-member `PlanningScenario`; T9 consumes scenario selections only.

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
- [x] Remove `selected_candidate_ids: dict[str, str]`; `ScenarioTargetSelection.candidate_ids` is the only selection contract for both `choose_one` and multi-member modes.
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

**Current implementation status (2026-08-19): PARTIAL.** `ScenarioTargetSelection` 和全部
成员场景特征已落地；网络/关系评估仍需继续审计“同一 target 的多个 feature”在全部 evaluator
中的语义。旧单值 selection view 已从当前 SELECT/EXECUTE 主链移除，多成员计划按成员展开。

**Suggested commit:** `feat(select): support multi-member target selections`

---

## Task 9: Make Constraints and EXECUTE Operation-Aware

**Depends on:** Task 8

**Owns:**

- Modify: `backend/app/contracts/domain/road_planning.py`
- Modify: `backend/app/domain/ground/constraint_factors.py`
- Create: `backend/app/domain/relations/road_operation_evaluator.py`
- Modify: `backend/app/contracts/workflow/execution_plan_contracts.py`
- Modify: `backend/app/domain/materialization/plan_builder.py`
- Modify: `backend/app/domain/materialization/existing_road_materializer.py`
- Modify: `backend/app/domain/materialization/nodes/road_worker.py`
- Create: `backend/tests/core/test_road_operation_constraint_semantics.py`
- Create: `backend/tests/core/test_multi_feature_road_execution.py`

**Interfaces:**

- Consumes: T8 `PlanningScenario.target_selections`, network/demand context, and ScenarioFeatures.
- Produces: operation-aware WorkerTasks/TaskExecutionResults and traceable planning features; T10 validates and renders them without re-deriving assignments.

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

**Current implementation status (2026-08-19): PARTIAL.** `WorkerTask`/`TaskExecutionResult`
已携带 `candidate_ids`，`all_members` 会被拆为稳定 member tasks 并保留 lineage；道路
preserve/harden/widen/new 的完整 operation-aware evaluator 和 resume 后重建计划的多成员传递仍待完成。

**Suggested commit:** `feat(execute): materialize operation-aware road feature sets`

---

## Task 10: Validate and Deliver Distinct, Auditable Planning Layers

**Depends on:** Task 9

**Owns:**

- Modify: `backend/app/domain/validation/scenario_reconciliation.py`
- Modify: `backend/app/domain/validation/relation_validation.py`
- Modify: `backend/app/domain/validation/validate_checks.py`
- Modify: `backend/app/infrastructure/export/delivery_snapshot.py`
- Modify: `backend/app/domain/delivery/render_layers.py`
- Modify: `backend/app/infrastructure/rendering/map_layers.py`
- Modify: `backend/app/application/queries/map_layers.py`
- Modify: `backend/app/application/projections/delivery.py`
- Create: `backend/tests/acceptance/test_road_planning_layer_delivery.py`
- Create: `backend/tests/core/test_source_set_member_completeness.py`

**Interfaces:**

- Consumes: T9 execution results and feature lineage.
- Produces: final completeness/quality findings, separated planning render groups, and the `/map-layers` read model consumed by T11 acceptance.

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

**Depends on:** Accepted Tasks 1-10, including Task 4A

**Owns:**

- Modify: `docs/design/modules/spatial-execution/06_TARGET_PROJECTION_EXECUTE.md`
- Modify: `docs/design/modules/explore/23_EXPLORE_RETRIEVAL_REDESIGN.md`
- Modify: `docs/design/modules/spatial-execution/28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md`
- Modify: `docs/design/modules/spatial-execution/29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md`
- Modify: `docs/design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md`
- Modify: `docs/design/RELATION_AWARE_MODIFICATION_LEDGER.md`
- Modify: the prior v2 plan only to label contradicted conclusions `DEPRECATED` or `HISTORICAL`
- Create: one bounded replay report under the existing `.run-tmp/sdd/...` evidence directory

**Interfaces:**

- Consumes: accepted interfaces and focused-test evidence from T1-T10.
- Produces: one default-live replay evidence pack, idempotent-resume proof, final process/memory audit, and reconciled status documents. It changes no production Python files.

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

## Serial Delegation Queue

1. `T1 -> review -> reclaim`
2. `T2 -> review -> reclaim`
3. `T3 -> review -> reclaim`
4. `T4 -> review -> reclaim`
5. `T4A -> review -> reclaim`
6. `T5 -> review -> reclaim`
7. `T6 -> review -> reclaim`
8. `T7 -> review -> reclaim`
9. `T8 -> review -> reclaim`
10. `T9 -> review -> reclaim`
11. `T10 -> review -> reclaim`
12. `T11 -> review -> reclaim`

Do not dispatch a later task merely because its predecessor's agent says “done.” The root must first verify the interface, diff boundary, focused tests, and process cleanup. Use the same agent only for corrections inside its original ownership; use a fresh agent for the next Task ID.

Every handoff must use this exact result envelope:

```text
TASK_ID:
STATUS: passed | failed | blocked
CHANGED_FILES:
PRODUCED_INTERFACES:
TEST_COMMANDS_AND_RESULTS:
GIT_DIFF_CHECK:
PROCESS_CLEANUP:
KNOWN_GAPS:
USER_HUNKS_LEFT_UNTOUCHED:
```
