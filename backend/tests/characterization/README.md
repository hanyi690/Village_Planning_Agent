# Characterization tests

These tests capture current behavior while a replacement pipeline or data contract is still settling. They are not permanent regression coverage.

Every file in this directory must have a removal condition recorded below. When the condition is satisfied, migrate any still-useful assertion to `unit`, `contracts`, `integration`, or `acceptance`, then delete the characterization file.

| File | Purpose | Removal condition |
| --- | --- | --- |
| `test_axis_source_geometry_binding.py` | Current axis-to-source geometry behavior | Canonical source-feature binding is stable in acceptance coverage |
| `test_context_and_kg_freshness.py` | Context/KG freshness baseline | Context snapshot contract is stable for one release |
| `test_evidence_vertical_slice.py` | Transitional evidence vertical slice | Replaced by the canonical evidence integration test |
| `test_low_memory_spatial_acceptance.py` | Low-memory runtime baseline | Runtime memory policy is covered by acceptance tests |
| `test_multi_source_geometry_contract.py` | Multi-source geometry baseline | Merged into spatial contract coverage |
| `test_place_evidence_source_identity.py` | Place/evidence identity baseline | Typed identity contract is stable |
| `test_planning_layer_quality_cas.py` | Planning-layer quality CAS baseline | Quality report schema is versioned and stable |
| `test_real_source_line_grounding.py` | Real source-line grounding baseline | Real-source acceptance suite covers line grounding |
| `test_real_spatial_evidence_queries.py` | Real spatial evidence query baseline | Canonical retrieval acceptance suite is stable |
| `test_relation_aware_current_baseline.py` | Relation-aware current behavior | Relation solver contract is stable |
| `test_replay_resume_zero_increment.py` | Replay/resume baseline | Replay manifest is promoted to a versioned acceptance fixture |
| `test_road_source_geometry_binding.py` | Road geometry binding baseline | Road binding is covered by canonical spatial integration tests |
| `test_source_feature_identity_binding.py` | Source feature identity baseline | Identity binding contract absorbs these assertions |
| `test_source_group_spec_mapper.py` | Source-group mapping baseline | Mapper contract is finalized |
| `test_wave3_validation_boundaries.py` | Wave 3 migration baseline | Wave 3 migration is closed and assertions are merged |
| `test_wave3e_bundle_snapshot.py` | Wave 3E bundle snapshot | Bundle snapshot is promoted to a versioned contract fixture |
| `test_wave3f_kg_rebuild.py` | Wave 3F KG rebuild baseline | KG rebuild acceptance is stable |

The `characterization` marker is applied automatically by `conftest.py`; these tests run only when explicitly selected with `-m characterization`.
