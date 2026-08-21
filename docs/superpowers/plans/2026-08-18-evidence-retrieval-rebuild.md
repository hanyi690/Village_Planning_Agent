# Evidence Retrieval Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild spatial evidence retrieval so multi-source bundle features, L1 typed facts, KG entities/relations, deterministic topology, and bounded external evidence jointly produce auditable inputs consumable by GROUND, SELECT, EXECUTE, VALIDATE, and RENDER.

**Architecture:** L1 typed location/spatial facts are the semantic-to-place bridge: they carry the report's village context, aliases, relation mentions, spatial hints, and provenance that raw KG/bundle metadata often lacks. Bundle remains the authoritative source for feature geometry and canonical bundle feature BSMs. The existing KG is the single semantic and topology relation store: a deterministic bundle-backed KG builder materializes complete geometry relations into the KG with feature identity, CRS/tolerance, snapshot, and provenance metadata. A new evidence packet/query planner first resolves L1 semantics into village/entity scopes, then queries the enriched KG and bundle, artifacts, and optional external evidence. LLMs may parse intent and rank supplied candidates, but may not invent BSMs, source feature IDs, or execution geometry.

**Tech Stack:** Python 3, Pydantic v2, rdflib, Shapely/pyproj, pytest, existing PlanningContext/VillageBundle/KG/grounding contracts.

## L1 Terminology and Context Policy

- `AnalysisReport` is the human-readable L1 report artifact (`content` plus structured `instruction/observations` and provenance), normally produced per dimension/worker.
- `L1LocationFact` is the semantic fact exposed to retrieval: mention, role, aliases, village/spatial hint, related mentions, source span, and evidence refs.
- Target architecture removes `L1DimensionFragment` from the L1 production contract. Each dimension
  report is compiled into a partial `L1Snapshot` from report body + structured observations + provenance,
  and one deterministic reducer normalizes those partial snapshots into `L1Snapshot` fact records. There
  is no fragment compatibility adapter; callers consume the typed snapshot contract.
- `L1Snapshot` remains the single stage-level aggregate/artifact for facts, gaps, and provenance consumed by later stages and resume. It is not a second report and is not sent wholesale to an LLM.
- Normal retrieval sends structured L1 facts plus only the relevant source spans/chunks. A full report is retained for audit and explicit report retrieval, not injected as default LLM background.
- LLM candidate disambiguation receives a bounded packet: the query, L1 semantic scope, top-K KG/bundle candidates, topology paths, and selected source spans. It never receives the whole session report by default.

## Global Constraints

- Preserve unrelated user worktree changes; edit only files required by this plan.
- Use `apply_patch` for source edits and small unambiguous anchors.
- Preserve source BSMs; generated bundle feature BSMs must be explicitly marked synthetic.
- A bundle feature BSM is `12-digit admin code + 8-digit persisted sequence`; allocation must be deterministic for initial build and append-only for resume/incremental builds.
- Geometry is authoritative only in the bundle; KG/evidence records may carry references or snapshots but not competing execution geometry.
- L1 facts are semantic observations and never become geometry without bundle/KG/topology validation.
- L1 facts are not merely a scoring dimension: they are the primary semantic scope input for report-derived village/facility/road mentions.
- There is no second topology database/layer in the target architecture. `TopologyMaterializer` is only an internal KG-building operation; the canonical relation store and query surface are the enriched KG.
- A facility fact such as `祠堂 @ xx村` must preserve both the facility mention and its village/related-mention context; dropping that context before retrieval is a correctness bug.
- Village localization proceeds as `L1 semantic scope -> village entity/cluster -> bundle feature candidates -> topology verification`, never as global name matching first.
- External retrieval is supplemental, provenance-bearing, and low priority when session evidence exists.
- Every new process/test command must be bounded; inspect the process table after long-running tests and terminate only processes created by this task.

## Storage and performance policy

- RDFLib remains the local/test implementation of the KG contract, not an
  excuse to run unbounded global scans. It must expose indexed lookup paths for
  BSM, source feature ID, canonical/alias name, entity type, and relation.
- Production persistence is PostgreSQL + PostGIS when the system serves more
  than one village/session concurrently, needs cross-session spatial queries,
  or a bundle exceeds the in-memory latency/memory budget. PostGIS is the
  physical implementation of the same KG entity/relation model; it is not a
  second topology database.
- The PostGIS schema stores KG entities, bundle feature identity, geometry,
  and KG relation records together. Geometry remains bundle-authoritative for
  execution; the spatial database provides indexed filtering and relation
  persistence, while the KG API remains the only consumer-facing relation
  surface.
- Runtime selection is explicit through `DATABASE_URL` plus
  `KG_STORAGE_BACKEND`; SQLite/RDFLib remains the default local mode and a
  PostGIS deployment must opt in with a PostgreSQL async driver and run the KG
  schema migration.
- Migration is capability-based: local tests use SQLite/RDFLib; production
  selects PostGIS through a storage adapter and keeps the same EvidencePacket
  contract. No request path may silently fall back to an O(n²) geometry scan.
- Cache keys use one bundle spatial snapshot digest per immutable bundle. Any
  in-place geometry edit must invalidate that digest. Session KG and query
  caches must be bounded and released on close/resume completion.

---

### Task 1: Freeze the current retrieval boundary and L1 semantic-scope failures

**Files:**
- Inspect: `backend/app/evidence/index/place_evidence_index.py`
- Inspect: `backend/app/contracts/ports/place_resolution_contracts.py`
- Inspect: `backend/app/contracts/domain/l1_contracts.py`
- Inspect: `backend/app/evidence/retrieval/*`
- Inspect: `backend/app/infrastructure/kg/*`
- Test: `backend/tests/characterization/test_evidence_retrieval_rebuild.py`

**Interfaces:**
- Consumes: current `PlanningContext`, `VillageBundle`, `PlanningKG`, `L1Snapshot`.
- Produces: failing characterization tests that state the required feature-BSM, L1, KG, and topology behavior before refactoring.

- [ ] Write tests proving a facility L1 fact with `spatial_hint`, `source_span`, `related_mentions`, and village fact resolves within the referenced village scope rather than globally.
- [ ] Write tests for a multi-source bundle where annotation and facility points both retain their own BSM, while nearby parcel BSMs are separate.
- [ ] Write a test for `xx村 + 祠堂` that returns explicit `resolved`, `resolved_multiple`, or `ambiguous` status instead of silently selecting the first match.
- [ ] Write a test proving an L1 facility fact can bind to a bundle point through KG alias plus topology, with all provenance refs present.
- [ ] Write a test proving a generated coordinate or BSM returned by a simulated LLM is rejected unless it resolves to an existing bundle feature.
- [ ] Run only the new characterization file and record the expected failures.

### Task 2: Introduce the L1 semantic scope contract

**Files:**
- Create: `backend/app/contracts/evidence/l1_scope_contracts.py`
- Modify: `backend/app/contracts/domain/l1_contracts.py`
- Modify: `backend/app/evidence/identity/observation_store.py`
- Modify: `backend/app/evidence/identity/binding_store.py`
- Test: `backend/tests/core/test_l1_semantic_scope_contract.py`

**Interfaces:**
- Consumes: `L1LocationFact`, `L1Snapshot`, report provenance, village facts, and relation mentions.
- Produces: `L1SemanticScope`, `L1MentionContext`, and durable scope references used by evidence graph retrieval.

- [ ] Define `L1MentionContext` with mention, normalized name, role, aliases, `spatial_hint`, `related_mentions`, report/source span, dimension, confidence, and evidence refs.
- [ ] Define `L1SemanticScope` with scope ID, village mentions, facility/road mentions, relation hints, source observation refs, confidence, and unresolved semantic gaps.
- [ ] Build scopes by linking facility/road facts to explicit village facts and longest-match village names in `spatial_hint`/`source_span`; do not infer geometry at this stage.
- [ ] Preserve independent observation IDs so multiple reports can support one scope without overwriting each other.
- [ ] Persist scope and binding refs across resume; a resumed run must not call the LLM again merely to reconstruct the same L1 semantic scope.
- [ ] Test facility-at-village, multiple villages in one report, alias-only village hints, missing village context, conflicting L1 facts, and provenance retention.

### Task 3: Introduce canonical multi-source feature identity and evidence packet contracts

**Files:**
- Create: `backend/app/contracts/evidence/feature_identity_contracts.py`
- Create: `backend/app/contracts/evidence/evidence_packet_contracts.py`
- Modify: `backend/app/contracts/ports/place_resolution_contracts.py`
- Modify: `backend/app/data/model/canonical.py`
- Test: `backend/tests/core/test_bundle_feature_identity_contract.py`

**Interfaces:**
- Consumes: current bundle BSM assignment and source feature metadata.
- Produces: `BundleFeatureIdentity`, `FeatureEvidenceRef`, `SpatialRelationEvidence`, and `EvidencePacket` contracts used by all later tasks.

- [ ] Define `BundleFeatureIdentity` with `bundle_feature_bsm`, `admin_code_12`, `sequence_code_8`, `source_feature_id`, `source_layer`, optional `source_bsm`, `bsm_kind`, `geometry_digest`, and `bundle_snapshot_digest`.
- [ ] Define `FeatureEvidenceRef` with feature identity, geometry reference, entity refs, relation refs, and provenance refs.
- [ ] Define `SpatialRelationEvidence` with subject/object feature refs, predicate, metric/tolerance/CRS metadata, computation method, and provenance.
- [ ] Define `EvidencePacket` with request, snapshot versions, candidate evidence refs, L1 refs, relation paths, external refs, ambiguity status, and query trace.
- [x] Extend place candidates/entries with `feature_bsm`, `source_feature_id`, `source_layer`, `source_bsm`, and `related_parcel_bsms`; typed feature identity is authoritative.
- [ ] Add collision-safe, persisted bundle BSM allocation that uses explicit feature administrative codes when available and never falls back to the first counter key for a multi-administration bundle.
- [ ] Add tests for source BSM preservation, synthetic BSM generation, collision avoidance, round-trip counter/mapping restoration, and append-only assignment.
- [ ] Run the identity contract tests and the existing bundle BSM tests.

### Task 4: Materialize complete bundle-backed topology into the existing KG

**Files:**
- Modify: `backend/app/spatial/query/bridge.py`
- Modify: `backend/app/infrastructure/kg/builder/builder.py`
- Modify: `backend/app/evidence/model/relation_evidence.py`
- Test: `backend/tests/core/test_evidence_topology_materializer.py`

**Interfaces:**
- Consumes: `VillageBundle` and `BundleFeatureIdentity`.
- Produces: deterministic KG relation triples/attributes for `same_coordinate`, `co_located`, `located_in`, `contains`, `near`, `touches`, `intersects`, and `overlaps` where geometry types support them.

- [ ] Build a stable feature iterator over points, lines, and polygons that exposes feature BSM, source feature ID, layer, geometry digest, and CRS.
- [ ] Normalize geometry and use a metric CRS or geodesic distance for `near`; store the chosen CRS and tolerance in each relation record.
- [ ] Emit `co_located` separately from `same_as`; never merge two source features solely because coordinates match.
- [ ] Emit KG relation IDs and provenance refs that can be consumed by the evidence index, GROUND, SELECT, and VALIDATE.
- [x] Replace ad hoc cross-layer relation payloads with a single bundle-backed KG relation builder and expose it through EvidenceGraph.
- [ ] Test deterministic ordering, invalid geometry handling, CRS/tolerance recording, same-coordinate non-destructive behavior, and point-in-village/parcel relations.
- [ ] Run topology tests and existing cross-layer topology validation tests.
- [ ] Add a storage adapter contract and PostGIS schema/index plan; keep the
  RDFLib implementation as the deterministic local adapter until the spatial
  backend acceptance benchmark passes.

### Task 5: Replace the flat place index with an L1-first joined evidence graph view

**Files:**
- Create: `backend/app/evidence/retrieval/evidence_graph.py`
- Modify: `backend/app/evidence/index/place_evidence_index.py`
- Modify: `backend/app/evidence/index/evidence_scorer.py`
- Modify: `backend/app/evidence/index/resolution_coverage.py`
- Test: `backend/tests/core/test_evidence_graph_join.py`

**Interfaces:**
- Consumes: `L1SemanticScope`, bundle feature identity registry, KG entities/aliases/relations, L1 location facts, topology relations, and version metadata.
- Produces: a deterministic candidate graph and `EvidencePacket` fragments; no direct KG object access from downstream resolvers.

- [ ] Build indexes by canonical name, alias, role, source feature ID, feature BSM, entity ID, L1 fact ref, relation ref, and village/admin scope.
- [ ] Make L1 semantic scope the first candidate-generation phase for report-derived queries: resolve village scope and relation mentions before global facility/road name lookup.
- [ ] Use the village scope's KG entity/cluster and bundle polygon relations to produce a bounded candidate set; retain the scope path in the query trace.
- [ ] Only fall back to global KG/bundle name search when the L1 scope is missing or explicitly broad, and mark the weaker evidence in the packet.
- [ ] Register both `annotations_current` and `facilities_current` as typed point features, preserving each point’s own BSM.
- [ ] Join L1 facts to KG candidates by exact alias/entity type before geometric fallback; retain conflicts rather than overwriting them.
- [ ] Join candidate points to village and parcel features using materialized topology relation IDs.
- [ ] Replace `source_bsms`-only scoring with explicit evidence dimensions for L1 exactness, KG identity, bundle feature identity, topology path, source provenance, and external support.
- [ ] Make generic short-name matches remain ambiguous when multiple geometries or source features survive.
- [ ] Add an explicit `query_facility_bsms(village_name, label, role='facility')` API returning structured multiple/ambiguous results.
- [ ] Run the new graph join tests and existing place resolution characterization tests.

### Task 6: Build the retrieval planner across L1, KG, bundle, topology, artifacts, and external evidence

**Files:**
- Modify: `backend/app/evidence/retrieval/query_planner.py`
- Modify: `backend/app/evidence/retrieval/router.py`
- Modify: `backend/app/agent/explore/service.py`
- Modify: `backend/app/evidence/retrieval/retrievers/bundle_retriever.py`
- Modify: `backend/app/evidence/retrieval/retrievers/kg_retriever.py`
- Modify: `backend/app/evidence/retrieval/retrievers/report_retriever.py`
- Create: `backend/app/evidence/retrieval/retrievers/external_retriever.py`
- Test: `backend/tests/core/test_unified_evidence_query_planner.py`

**Interfaces:**
- Consumes: structured `ExplorationRequest`, L1 facts, evidence graph, KG, bundle, artifact/history stores, and an injectable external provider.
- Produces: bounded, versioned `EvidencePacket` results with source-specific trace and sufficiency status.

- [ ] Extend query planning from retriever selection to a deterministic join plan: L1 semantic scope → KG village/entity candidates → bundle features → topology paths → artifact/external enrichment.
- [ ] Route village/facility/road questions to L1 scope construction and the evidence graph before generic report/RAG retrieval.
- [ ] Keep external retrieval disabled when session evidence is sufficient; when enabled, tag every result as external and never promote it directly to an executable feature.
- [ ] Add cache keys containing bundle snapshot, KG version, L1 snapshot, topology version, external provider version, and query fingerprint.
- [ ] Make evidence sufficiency explain missing feature identity, missing geometry binding, missing topology, conflict, or external-only support separately.
- [x] Test bounded rounds, cache invalidation, source priority, explicit external opt-in, and no-geometry-invention behavior.

### Task 7: Expose safe bundle/KG/topology tools to the LLM and enforce candidate-only output

**Files:**
- Modify: `backend/app/infrastructure/llm/tools/access/bundle.py`
- Modify: `backend/app/infrastructure/llm/tools/access/knowledge.py`
- Create: `backend/app/infrastructure/llm/tools/access/evidence.py`
- Modify: `backend/app/infrastructure/llm/tools/registry.py`
- Test: `backend/tests/core/test_llm_evidence_tools.py`

**Interfaces:**
- Consumes: `EvidencePacket` and read-only bundle/KG/topology accessors.
- Produces: structured LLM tool responses containing candidate IDs, evidence paths, and optional bundle geometry fetches by verified feature reference.

- [ ] Add a tool for `query_facility_bsms` and generic `query_evidence_graph` that returns feature BSMs, source refs, related parcel BSMs, and topology paths.
- [ ] Add a KG neighborhood tool that returns typed entities, aliases, relations, and provenance without dumping the full graph.
- [ ] Require explicit `feature_ref` before returning geometry; geometry is fetched from bundle and is never accepted from the LLM.
- [ ] Add a simulated LLM adapter that can select only from supplied candidate IDs and rejects unknown IDs, fabricated BSMs, and fabricated coordinates.
- [ ] Test tool registration, bounded result size, source snapshot propagation, and invalid LLM selections.

### Task 8: Connect Evidence Packet to GROUND, SELECT, EXECUTE, and RENDER

**Files:**
- Modify: `backend/app/domain/ground/anchors.py`
- Modify: `backend/app/domain/ground/aggregate.py`
- Modify: `backend/app/domain/allocation/select_service.py`
- Modify: `backend/app/evidence/identity/binding_store.py`
- Modify: `backend/app/workflow/stages/execute.py`
- Modify: `backend/app/domain/validation/relation_validation.py`
- Test: `backend/tests/core/test_evidence_to_execution_lineage.py`

**Interfaces:**
- Consumes: resolved `EvidencePacket` and canonical feature/relation refs.
- Produces: exact source-backed candidate geometry, selection bindings, worker tasks, final planned features, and render lineage.

- [ ] Ensure GROUND carries feature BSM, source feature ID, entity ref, relation refs, L1 refs, and snapshot digest into every exact point/line candidate.
- [ ] Ensure SELECT consumes verified candidates and never re-resolves names or creates geometry.
- [ ] Ensure EXECUTE workers use authoritative bundle geometry or explicit worker-generated geometry with operation lineage; no unresolved evidence may materialize or expand to a source BSM silently.
- [ ] Ensure final planned features and render manifests expose source feature BSMs and evidence refs.
- [ ] Validate final geometry and relation topology against the same bundle snapshot used for grounding.
- [ ] Run a simulated LLM full vertical slice for a village facility and planned road.

### Task 9: Remove legacy retrieval ambiguity and complete regression/low-memory audit

**Files:**
- Modify: `backend/app/evidence/index/place_evidence_index.py`
- Modify: `backend/app/contracts/ports/place_resolution_contracts.py`
- Modify: relevant docs under `docs/design/modules/explore` and `docs/design/modules/kg-place`
- Test: `backend/tests/acceptance/test_evidence_retrieval_execution_acceptance.py`

**Interfaces:**
- Consumes: all rebuilt retrieval contracts and downstream integration behavior.
- Produces: documented migration behavior, acceptance evidence, and no unresolved legacy path for facility BSM lookup.

- [ ] Migrate remaining consumers from ambiguous `source_bsms` semantics to explicit feature/related fields.
- [ ] Remove flat name-only paths that can select the first candidate; an unresolved or non-executable candidate must remain explicit.
- [ ] Add acceptance coverage for `xx村的祠堂的BSM`, multi-source same-coordinate facilities, L1/KG conflict, external-only fallback, planned road linkage, and render lineage.
- [ ] Run the focused suite, then the complete backend regression relevant to evidence/GROUND/SELECT/EXECUTE/DELIVER.
- [ ] Check Python/pytest/worker processes after each long run and reclaim only task-owned processes.
- [ ] Update implementation status with exact test commands and artifact paths; do not mark complete unless the requirement-by-requirement audit passes.
