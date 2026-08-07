# Graph Report - graphify-tmp-staging\data-kg-merged  (2026-08-07)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 706 nodes · 1548 edges · 32 communities (29 shown, 3 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 54 edges (avg confidence: 0.73)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7863f666`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- __init__.py
- report_entity_enrichment.py
- cognition.py
- KGManager
- SemanticMemoryStore
- PlanningKG
- RelationAnnotation
- interface.py
- spatial_ref.py
- .uri
- EntityTypes
- layer1.py
- KGSpatialQueryAdapter
- layer1_core.py
- DlqReport
- ingest.py
- _LRUCache
- KGGazetteerAdapter
- layer3.py
- _add_cross_type_relations
- Any
- build_control_line_entities
- ingest_planned_state_from_geojson
- .geo_feature_types
- adapters/__init__.py
- control_line_mapping.py
- EntityIdPolicy
- .get
- build_knowledge_graph_data
- DataBundleAssemblyAdapter
- detect_encoding
- execute_queries.py

## God Nodes (most connected - your core abstractions)
1. `EntityTypes` - 23 edges
2. `PlanningKG` - 21 edges
3. `KGBuilder` - 20 edges
4. `add_geo_feature_type()` - 20 edges
5. `KGManager` - 19 edges
6. `SemanticMemoryStore` - 19 edges
7. `BuildContext` - 18 edges
8. `extract_bindings()` - 17 edges
9. `kg_builder()` - 15 edges
10. `GazetteerEntry` - 15 edges

## Surprising Connections (you probably didn't know these)
- `KGGazetteerAdapter` --calls--> `extract_bindings()`  [INFERRED]
  adapters/gazetteer_adapter.py → enrichment/report_entity_enrichment.py
- `KGGazetteerAdapter` --uses--> `LocationAnchor`  [INFERRED]
  adapters/gazetteer_adapter.py → enrichment/report_entity_enrichment.py
- `KGSpatialQueryAdapter` --uses--> `EntityTypes`  [INFERRED]
  adapters/spatial_query_adapter.py → ontology.py
- `KGSpatialQueryAdapter` --uses--> `GeoPredicates`  [INFERRED]
  adapters/spatial_query_adapter.py → ontology.py
- `_nearest_features()` --calls--> `parse_wkt_point()`  [INFERRED]
  adapters/spatial_query_adapter.py → builder/geo_helpers.py

## Import Cycles
- None detected.

## Communities (32 total, 3 thin omitted)

### Community 0 - "__init__.py"
Cohesion: 0.06
Nodes (86): PlanningKG module - Pre-computed Spatial Materialized Knowledge Graph., EntityAnnotation, KG query subpackage - four-namespace query API (v4.8).  [v4.8] Queries organized, # NOTE: These are registered for namespace completeness but NOT yet wired into, _dlbm_to_name(), _ensure_entity_annotation(), _ensure_relation_annotation(), _find_parcel_uri() (+78 more)

### Community 1 - "report_entity_enrichment.py"
Cohesion: 0.07
Nodes (55): _build_bsm_to_dlbm(), _centroid_within_200m(), _cluster_dlbms(), _commit_instruction_anchors(), _commit_village_binding(), confirm_batch_with_llm(), _deterministic_pick(), extract_bindings() (+47 more)

### Community 2 - "cognition.py"
Cohesion: 0.08
Nodes (34): _build_constraint_block(), _build_context_block(), _build_layer_cards(), _build_structured_payload(), _collect_parcel_entities(), _derive_spatial_pattern(), get_layer_group_semantics(), get_village_cognition() (+26 more)

### Community 3 - "KGManager"
Cohesion: 0.12
Nodes (10): KGManager, Process-level KG instance manager with three-layer caching.      Usage:, Whether Layer 1 caching is enabled (can disable for debugging)., Get the KG instance for a session., Return only ``session_id``'s KG or raise a clear isolation error.          Inter, Return the most recently registered session KG, or a cached Layer 1 KG., Remove a session and its associated data., Get current version (for testing). Returns max version across sessions. (+2 more)

### Community 4 - "SemanticMemoryStore"
Cohesion: 0.15
Nodes (13): diff_round(), get_memory_dir(), get_semantic_memory(), load_memory_state(), memory_state_path(), Any, Path, SemanticMemoryStore — 实体和关系的语义注解存储。  v4.6 新增：替代旧的 _semantic_store（Dict[str, Dict (+5 more)

### Community 5 - "PlanningKG"
Cohesion: 0.07
Nodes (17): KGInputParcels, PlanningKG, Any, Container for typed parcels consumed by KG builder., RDF knowledge graph data container. No build logic., KGBuilder, KG construction orchestrator. Composes PlanningKG via composition., add_semantic_enrichment() (+9 more)

### Community 6 - "RelationAnnotation"
Cohesion: 0.11
Nodes (30): extract_bindings(), __getattr__(), Compatibility import for report-to-KG entity enrichment.  Use ``report_entity_en, Run the canonical implementation with legacy dependency injection., Compatibility wrapper for the report-enrichment wave entry point., Forward legacy access, including private test and integration helpers., run_wave(), _attribute_text() (+22 more)

### Community 7 - "interface.py"
Cohesion: 0.20
Nodes (17): close_kg_session(), KGSessionSnapshot, open_kg_session(), Any, query_session_sparql(), query_session_template(), Stable integration boundary for the planning knowledge graph.  External callers, Return the isolated PlanningKG object for advanced in-process callers. (+9 more)

### Community 8 - "spatial_ref.py"
Cohesion: 0.12
Nodes (22): _aliases(), KGSemanticQueryAdapter, Any, URIRef, KGSemanticQueryAdapter - KG-side implementation of the SemanticQueryPort.  Wraps, _all_parcel_bsms(), _entity_ids_by_label(), _entity_ids_by_type() (+14 more)

### Community 9 - ".uri"
Cohesion: 0.17
Nodes (27): add_annotations(), _add_boundaries(), _add_buildings(), _add_control_lines_from_typed(), _add_dem_raster(), _add_facilities_from_typed(), _add_natural_resource_zones(), _add_planning_elements_from_typed() (+19 more)

### Community 10 - "EntityTypes"
Cohesion: 0.08
Nodes (29): PlanningKG - RDF knowledge graph data container + query methods.  Construction l, parse_wkt_point(), add_cross_type_relations(), add_parcel_relations(), compute_cross_type_heuristic(), _entity_uri_by_bsm(), _parcel_uri_by_bsm_dlbm(), Layer 2: spatial relation builders (computed by spatial_ops, injected via parcel (+21 more)

### Community 11 - "layer1.py"
Cohesion: 0.06
Nodes (37): add_gis_layer_groups(), derive_taxonomic_parent(), get_all_gis_layer_groups(), get_allowed_operations(), get_gis_layer_group_info(), _gis_type_matches_group(), Semantic enrichment derivation logic (moved from ontology.py and layer1.py).  Pu, Wave A.1: removed. Cross-system DLBM→zone_type derivation is no longer     perfo (+29 more)

### Community 12 - "KGSpatialQueryAdapter"
Cohesion: 0.19
Nodes (13): _entity_centroid(), _entity_geometry(), _geometry_area(), KGSpatialQueryAdapter, _layer_members(), _nearest_features(), Any, CandidateSet (+5 more)

### Community 13 - "layer1_core.py"
Cohesion: 0.14
Nodes (31): KGBuilder - composition orchestrator for PlanningKG construction.  Replaces the, derive_legal_constraint(), derive_semantic_label(), Derive a Chinese semantic label from DLBM (same-system code→name only).      Wav, Wave A.1: removed. Cross-system planning_zone→control_code derivation is     no, add_bbox(), add_centroid(), add_geo_feature_type() (+23 more)

### Community 14 - "DlqReport"
Cohesion: 0.15
Nodes (11): BaseModel, DlqCategory, DlqEntry, DlqReport, Any, Dead Letter Queue — structured DLQ with three categories.  Categories:     geome, DLQ entry category — determines the downstream disposition., A single DLQ entry — preserves the raw feature + reason for replay.      Attribu (+3 more)

### Community 15 - "ingest.py"
Cohesion: 0.05
Nodes (59): get_alternative_ghytbms(), is_ambiguous(), lookup_ghytbm(), lookup_ghytbm_with_info(), 基数转换 — 三调 DLBM → 规划用途 GHYTBM (附录5) 转换.  这是 HUMAN_PLANNING_WORKFLOW §8 要求的"现状→规划第, DLBM -> GHYTBM 基数转换.      对"一一对应"类型直接返回 GHYTBM 编码。     对"一对多"类型返回主映射（默认选项）。, DLBM -> GHYTBM 基数转换（含转换类型和条件信息）.      Returns:         (ghytbm, conversion_type,, 判断该 DLBM 是否存在一对多消歧需求. (+51 more)

### Community 16 - "_LRUCache"
Cohesion: 0.18
Nodes (5): CacheKey, _LRUCache, KGManager — process-level KG caching with three-layer separation.  Architecture:, Composite cache key for Layer 1 static subgraph., Simple LRU cache with maxsize eviction.

### Community 17 - "KGGazetteerAdapter"
Cohesion: 0.31
Nodes (4): KGGazetteerAdapter, Any, GazetteerEntryLike, GazetteerPort

### Community 18 - "layer3.py"
Cohesion: 0.24
Nodes (9): build_intent_layer(), clear_intent_layer(), Any, Layer 3: PARSE intent (SpatialPlanningIntent -> RDF subgraph + SemanticMemorySto, Remove all L3 intent virtual entities from the RDF graph.      Called at end of, Serialize bbox tuple to comma-separated string for RDF literal., Build L3 intent virtual entities from SpatialPlanningIntent.      ZoneTarget, Fa, _serialize_bbox() (+1 more)

### Community 19 - "_add_cross_type_relations"
Cohesion: 0.33
Nodes (6): _add_cross_type_relations(), _compute_cross_type_heuristic(), Add cross-type spatial relations (facility-in-parcel, road-intersects-parcel, pa, Heuristic cross-type relation computation using centroid proximity (no shapely)., Safely convert a string to URIRef, returning None if invalid., _to_uri_safe()

### Community 20 - "Any"
Cohesion: 0.29
Nodes (6): compute_layer1_cache_key(), Any, Get Layer 1 KG from cache or build fresh.          Builds from bundle morphology, Register a KG instance for a session., Build complete KG with Layer 1 caching., Compute cache key from typed parcel list.      Uses hash of BSM+DLBM+area_sqm fo

### Community 21 - "build_control_line_entities"
Cohesion: 0.50
Nodes (3): build_control_line_entities(), Build ControlLine entity dicts (handles all 6 subtypes: 三线 + 灾害 + 洪涝).      Args, ProvenanceAudit

### Community 22 - "ingest_planned_state_from_geojson"
Cohesion: 0.50
Nodes (4): ingest_planned_state_from_geojson(), Path, Read planned/ GeoJSON files (landuse, road, construction_zone) into PlannedState, PlannedState

### Community 26 - "EntityIdPolicy"
Cohesion: 0.29
Nodes (6): apply_planned_state(), Layer 4: PlannedState (规划成果, 版本化增量).  L4 entities mirror L3 intent virtual entit, Apply PlannedState to KG Layer 4.      Sparse write: only entities with non-defa, EntityIdPolicy, URI with sequence suffix for entities sharing the same BSM.          Used when m, 统一实体标识契约 - 所有 KG 实体的 URI 生成与 BSM 绑定.      Rules:       L1 entities: uri = PLN[f"

### Community 27 - ".get"
Cohesion: 0.29
Nodes (3): Query KG with session-scoped cache and version-based invalidation.          Args, Bump KG version for session — invalidates all cached queries.          Call this, Return the mutation version for one session.

### Community 28 - "build_knowledge_graph_data"
Cohesion: 0.38
Nodes (6): build_knowledge_graph_data(), _legacy_merge_geojson_into_bundle(), Any, Application service for constructing the session planning knowledge graph.  Uses, Schema-only fallback: merge raw GeoJSON features into a bundle.      Used only w, Build knowledge graph from planning intent + land use data. Call once.      Data

### Community 29 - "DataBundleAssemblyAdapter"
Cohesion: 0.33
Nodes (4): DataBundleAssemblyAdapter, Any, Data-layer implementation of BundleAssemblyPort.  Wraps ``app.modules.data.catal, BundleAssemblyPort implementation backed by the DataCatalog merger.

### Community 30 - "detect_encoding"
Cohesion: 0.40
Nodes (3): detect_encoding(), Detect which encoding system a DLBM-shaped value belongs to.      Priority order, ProvenanceSource

### Community 31 - "execute_queries.py"
Cohesion: 0.40
Nodes (4): get_parcel_context(), Any, execute_queries — EXECUTE 阶段 KG 查询（激活提案 execute-kg-utilization §2）。  首个激活：get_pa, Parcel context: attributes + adjacency + constraints + settlement cluster.

## Knowledge Gaps
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EntityTypes` connect `EntityTypes` to `__init__.py`, `report_entity_enrichment.py`, `cognition.py`, `PlanningKG`, `spatial_ref.py`, `layer1.py`, `KGSpatialQueryAdapter`, `layer1_core.py`, `layer3.py`, `.geo_feature_types`, `EntityIdPolicy`?**
  _High betweenness centrality (0.155) - this node is a cross-community bridge._
- **Why does `GazetteerEntry` connect `report_entity_enrichment.py` to `EntityTypes`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Why does `KGManager` connect `KGManager` to `__init__.py`, `PlanningKG`, `interface.py`, `_LRUCache`, `Any`, `.get`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `EntityTypes` (e.g. with `KGSpatialQueryAdapter` and `Gazetteer`) actually correct?**
  _`EntityTypes` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `PlanningKG` (e.g. with `KGBuilder` and `.get_or_build_layer1()`) actually correct?**
  _`PlanningKG` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `KGBuilder` (e.g. with `PlanningKG` and `BuildContext`) actually correct?**
  _`KGBuilder` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `__init__.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06416978776529339 - nodes in this community are weakly interconnected._