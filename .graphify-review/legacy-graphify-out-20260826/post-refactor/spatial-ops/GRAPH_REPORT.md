# Graph Report - C:\Users\24957\AppData\Local\Temp\opencode\gfx-spatial  (2026-08-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 990 nodes · 2490 edges · 38 communities (36 shown, 2 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 117 edges (avg confidence: 0.67)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ecc7e2d0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37

## God Nodes (most connected - your core abstractions)
1. `build_planning_nodes()` - 41 edges
2. `score_road_candidates()` - 24 edges
3. `compare_road_plans()` - 23 edges
4. `structure_road_requirements()` - 23 edges
5. `_planning_nodes()` - 20 edges
6. `run_stage4_road_planning()` - 19 edges
7. `_manual_confirmation_indexes()` - 18 edges
8. `PlanningNodeBuildConfig` - 18 edges
9. `RoadPlanningConfig` - 18 edges
10. `_clean()` - 18 edges

## Surprising Connections (you probably didn't know these)
- `_build_residential_clusters()` --calls--> `_find_parcels_near_point()`  [INFERRED]
  context/context.py → geometry/geometry.py
- `_build_spatial_relations_block()` --calls--> `_compute_spatial_relations()`  [INFERRED]
  context/context.py → geometry/relations.py
- `_build_zone_adjacency_block()` --calls--> `_compute_zone_adjacency()`  [INFERRED]
  context/context.py → geometry/relations.py
- `_parcel_centroid()` --calls--> `_compute_centroid()`  [INFERRED]
  grounding/grounding.py → geometry/geometry.py
- `_resolve_constraint()` --calls--> `build_constraint_index()`  [INFERRED]
  grounding/grounding.py → index/bridge.py

## Import Cycles
- None detected.

## Communities (38 total, 2 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (101): _action_from_text(), _add_candidate(), _as_list(), _bbox_list(), _bsm_bundle_summary(), build_planning_nodes(), _bundle_context_for_bsms(), _bundle_spatial_context() (+93 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (61): ndarray, _access_cluster_requests(), _candidate_requests(), _component_records(), _constraint_context(), _demand_accessibility(), _environment_score(), _feature_collection() (+53 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (46): GridKey, Road-network construction and future road-planning services., _apply_endpoint_snap(), build_road_network(), _canonical_geometry_key(), _cluster_endpoints(), _feature_collection(), _grid_coordinate() (+38 more)

### Community 3 - "Community 3"
Cohesion: 0.12
Nodes (50): HTMLParser, Inputs and safety settings for evidence-backed demand extraction., Stage2StructureConfig, _action(), _assign_ids(), _classify_demand(), _clean(), _constraint_record() (+42 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (34): ConflictDetector, ConflictReport, ConstraintViolation, MetricConflict, Any, Cross-dimension conflict detector based on semantic qualifiers.  Detects three t, Complete conflict detection results., Detect cross-dimension conflicts from dimension report data.      Uses CROSS_DIM (+26 more)

### Community 5 - "Community 5"
Cohesion: 0.14
Nodes (43): _augment_graph(), _average_access_time(), _base_graph(), compare_road_plans(), _deadends(), _direction_similarity(), _endpoint_rate(), _endpoints() (+35 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (25): _normalize(), Any, PlaceEvidenceEntry, Evidence scorer - 8 deterministic dimensions from design §4.2.  Scores are confi, Score an index entry across the eight evidence dimensions.      Args:         me, Weighted sum of an evidence dict; prohibited dims contribute nothing., Normalize a place name: strip whitespace and village suffixes., score_candidate() (+17 more)

### Community 7 - "Community 7"
Cohesion: 0.15
Nodes (35): _accessibility_context(), _candidate_accessibility_benefit(), _constraint_unions(), _feature_collection(), _hard_and_soft_constraints(), _intersection_length(), _landuse_context(), _load_graph() (+27 more)

### Community 8 - "Community 8"
Cohesion: 0.17
Nodes (33): Inputs and thresholds for Stage-3 demand/network spatial binding., SpatialBindingConfig, _as_list(), _bind_demands(), _bind_projects(), bind_road_spatial_requirements(), _collection_crs(), _constraint_features() (+25 more)

### Community 9 - "Community 9"
Cohesion: 0.13
Nodes (30): Ranker, compute_coverage_matrix(), DemandPoint, FacilityCandidate, greedy_maximal_covering(), haversine_m(), Maximal covering location problem (MCLP) solver.  Pure module (``math`` / ``data, Solve MCLP exactly with pulp; fall back to greedy if pulp is missing. (+22 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (21): BaseGeometry, Condition, MappingContext, ProvenanceAudit, TypingRule, VocabularyCategory, CustomZoningGenerator, Select parcels until cumulative area reaches the target (hectares).      Parcels (+13 more)

### Community 11 - "Community 11"
Cohesion: 0.14
Nodes (27): classify_spatial_description(), _default_gazetteer(), _extract_linear_mention(), _extract_toponym(), Any, query_excluded_parcels(), 空间接地模块 — PARSE Agent spatial grounding.  职责 B: 将自然语言空间描述 (如"村北""靠近刘村") 接地为具体的空间锚, 从 ConstraintIndex 提取约束区内重叠地块 BSM（排除集）.      对每个地块检查是否与指定类型的约束多边形重叠.     当 zone_t (+19 more)

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (19): compute_target_area(), area_ratio * total_area_ha -> target_area_ha., build_constraint_index(), _build_rtree(), build_spatial_index(), ConstraintIndex, ConstraintOverlap, OverlapResult (+11 more)

### Community 13 - "Community 13"
Cohesion: 0.20
Nodes (22): apply_location_confirmations(), _constraint_tasks(), _copy_maplibre_assets(), _fingerprint(), generate_location_confirmation_workflow(), _is_generalized_or_route(), _map_html(), _norm() (+14 more)

### Community 14 - "Community 14"
Cohesion: 0.18
Nodes (22): apply_setback(), _as_polygon(), _cut_front(), _cut_strip_from_edge(), _edge_length(), _merge_slivers(), _obb_params(), obb_subdivide() (+14 more)

### Community 15 - "Community 15"
Cohesion: 0.23
Nodes (22): __getattr__(), Any, Load the CLI-capable builder lazily to keep ``python -m`` warning-free., _adapter_response_to_file(), _as_list(), _bbox_list(), build_planning_nodes_with_kg_retry_adapter(), build_planning_nodes_with_kg_retry_response() (+14 more)

### Community 16 - "Community 16"
Cohesion: 0.13
Nodes (18): _compute_land_balance(), export_gdb_package(), _find_layer_in_configs(), _normalize_fields(), Any, Export the standard GeoJSON planning package and land-balance table.  The output, Extract a generated layer's GeoJSON from layout_configs., Compute land use balance table from allocated GeoJSON.      Returns structured d (+10 more)

### Community 17 - "Community 17"
Cohesion: 0.16
Nodes (19): _build_constraints(), _build_facilities(), _build_landuse_dist(), _build_terrain(), _build_zone_adjacency_block(), compute_context_blocks(), _load_place_aliases(), Spatial context computation — ContextBlock-based spatial cognition cards.  [v4.3 (+11 more)

### Community 18 - "Community 18"
Cohesion: 0.13
Nodes (19): compute_proximity_weights(), ground_facility_spatial_preference(), ground_linear_spatial_preference(), ground_zone_spatial_preference(), _parcel_centroid(), query_parcels_in_bbox(), query_parcels_near_entity(), Extract centroid from parcel geometry (GeoJSON geometry dict). (+11 more)

### Community 19 - "Community 19"
Cohesion: 0.15
Nodes (18): compute_parcel_relations(), ConnectedRelation, _find_parcels_near_point(), NearbyRelation, ParcelRelations, point_in_polygon(), Any, Geometry computation helpers for spatial context.  Pure geometric operations: ce (+10 more)

### Community 20 - "Community 20"
Cohesion: 0.17
Nodes (13): Spatial grounding subpackage — resolve spatial descriptions, bind to bundle.  Co, _extract_location_tokens(), Any, SpatialResolver - single entry point for spatial reference resolution.  Consolid, Resolve a closed-set SpatialReferenceSpec to candidate BSMs.          Runs KG-si, Fill intent target candidate_bsms / anchors from gazetteer + KG anchors., Resolve intent location hints into candidate BSMs / coordinate anchors.      Mir, 位置文本 → 候选 token：'肩丰、田坑' / '肩丰至炉池段' / '园寨自然村'。 (+5 more)

### Community 21 - "Community 21"
Cohesion: 0.19
Nodes (16): Parcel geometry operations — split, merge, modify, reclassify, create., apply_operations(), create_parcel(), _get_attr(), merge_parcels(), modify_parcel(), Any, Parcel geometry operations — split, merge, modify, reclassify, create.  All geom (+8 more)

### Community 22 - "Community 22"
Cohesion: 0.29
Nodes (7): _local_name(), _normalise(), Any, RDFLib/PlanningKG adapter for Stage-2.6 spatial retry requests.  The road workfl, Resolve Stage-2.6 retry targets against an in-memory RDFLib KG.      ``kg`` can, RDFLibKGSpatialRetryAdapter, _strings()

### Community 23 - "Community 23"
Cohesion: 0.26
Nodes (12): Zone allocation — PuLP MIP global zone allocator adapter., allocate_zones(), _as_bsm(), _blacklisted_bsms(), _entry_area_ha(), _parcel_area_ha(), PuLPZoneAllocator, Any (+4 more)

### Community 24 - "Community 24"
Cohesion: 0.21
Nodes (10): AxisBuilder, Any, Development axis builder — spatial structure generation.  Extracted from engine., Auto-generate 一核一带三区 spatial structure., Return True if both coordinates are finite numbers., Build a corridor LineString along water parcels., Build development axis / spatial structure GeoJSON layers., Build spatial structure GeoJSON from intent and parcel data.          If intent (+2 more)

### Community 25 - "Community 25"
Cohesion: 0.32
Nodes (14): _as_list(), _features(), _ids(), _missing_fields(), _pn_ref(), _props(), Any, Path (+6 more)

### Community 26 - "Community 26"
Cohesion: 0.20
Nodes (12): DeliveryGate, Land balance calculation — L1 vs L4 parcel-level comparison and delivery gate., check_delivery_gate(), _code_to_name(), compute_land_balance(), _get_attr(), Any, Land balance calculator — L1 vs L4 parcel-level comparison.  Produces LandBalanc (+4 more)

### Community 27 - "Community 27"
Cohesion: 0.14
Nodes (5): Keep only BSM values that correspond to real bundle parcels., Bind instruction candidates to immutable bundle geometry.          Delegates to, One resolver bound to one ``PlanningContext``., Resolve a natural-language spatial description to candidate BSMs.          Deleg, SpatialResolver

### Community 28 - "Community 28"
Cohesion: 0.26
Nodes (12): compute_water_overlap(), For each water polygon, find completely covered DLBM=3100 parcels.      Uses sha, build_parcel_contexts(), _load_dem_slope(), _poi_hits(), Any, 地块多因子上下文构造（B3）— 供自定义功能区规则求值。  Migrated from agent/gis/vocab/context.py per docs/, 每地块邻近 POI（历史保护面质心名称）。 (+4 more)

### Community 29 - "Community 29"
Cohesion: 0.26
Nodes (11): _area_ha(), _bsm(), build_custom_planning_zone_layer(), build_custom_zone_allocation_inputs(), Any, Build the canonical village-scale custom planning-zone layer.  The existing voca, Merge globally allocated parcels into canonical planning-zone features., Check overlap and continuity of the canonical custom-zone result. (+3 more)

### Community 30 - "Community 30"
Cohesion: 0.32
Nodes (9): bind_exploration_to_bundle(), _bsm(), _context(), DeterministicBundleBinder, _features(), Any, Path, Deterministic semantic binding to immutable bundle geometry.  This module is a s (+1 more)

### Community 31 - "Community 31"
Cohesion: 0.36
Nodes (11): build_qgis_demo_package(), _clean_layer(), _copy_raster(), _find_gdal_executable(), _geometry_family(), Any, Path, Create a small, strict, QGIS-facing map package from road-demo outputs. (+3 more)

### Community 32 - "Community 32"
Cohesion: 0.22
Nodes (9): Geometry computation subpackage — pure geometry, relations, subdivision, axes., _compute_spatial_relations(), _compute_zone_adjacency(), Any, ResidentialClusterAnchor, Spatial relation computation helpers.  Functions that compute topological and di, Compute zone adjacency matrix from typed land-use parcels.      Accepts List[Bas, Compute spatial relations between residential clusters and zones.      Uses cent (+1 more)

### Community 34 - "Community 34"
Cohesion: 0.31
Nodes (9): _build_residential_clusters(), _build_spatial_relations_block(), _extract_annotation_villages_from_typed(), Any, ResidentialClusterAnchor, Build residential cluster anchors by clustering residential parcels (居民点)., Build spatial relations block from residential cluster anchors (居民点).      Must, Extract village name anchors from typed CurrentAnnotation list.      Uses a.cate (+1 more)

### Community 35 - "Community 35"
Cohesion: 0.33
Nodes (6): _build_village_meta(), Build village metadata block from bundle metadata and polygon data., _compute_centroid(), _compute_total_area(), Compute centroid of boundary polygon from GeoJSON FeatureCollection., Compute total area in hectares from a GeoJSON FeatureCollection.

### Community 36 - "Community 36"
Cohesion: 0.50
Nodes (4): _collect_entities(), compute_cross_layer_relations(), Extract (prefix, uri, shapely_geom) tuples from bundle layers., Compute all cross-layer spatial relations from bundle geometry.      Uses shapel

## Knowledge Gaps
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `score_road_candidates()` connect `Community 7` to `Community 2`, `Community 28`, `Community 15`?**
  _High betweenness centrality (0.178) - this node is a cross-community bridge._
- **Why does `_village_center()` connect `Community 11` to `Community 18`, `Community 28`, `Community 20`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **Why does `SpatialResolver` connect `Community 27` to `Community 18`, `Community 11`, `Community 20`, `Community 30`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `score_road_candidates()` (e.g. with `.shape()` and `__getattr__()`) actually correct?**
  _`score_road_candidates()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.07424328954882924 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.09218612818261633 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.08032786885245902 - nodes in this community are weakly interconnected._