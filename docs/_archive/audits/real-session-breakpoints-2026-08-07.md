# Real session breakpoint audit (2026-08-07)

## Native access violation

- Reproduction: the first live fixture run crashed with process exit `-1073741819` (`0xC0000005`) during concurrent L1 RAG/LLM work. There was no Python traceback and no pytest timeout marker at the crash point.
- First divergence: L1 dimension workers overlapped synchronous OpenAI-compatible embedding calls and the local Chroma/HNSW query path while `Send` fan-out was active; RSS was approximately 1.5 GB.
- Evidence: `backend/real-llm-final29.log` ends in L1 RAG/prompt setup; the next run with the repair crossed the same phase without a native crash.
- Resolution: serialize the complete `HierarchyVectorStore.retrieve` native query section and bound L1 streaming calls with `L1_LLM_MAX_CONCURRENT` (default `3`). Real RAG and the configured LLM remain enabled.
- Residual risk: this is a process-local guard. Multiple processes must not write the same embedded Chroma persistence path; production should use a service-mode vector database or a per-process path.

## L3 non-spatial programme rows blocking SELECT

- Reproduction: the live L3 compiler produced 40 project-program rows, but only 9 had spatial references. `traffic_planning-int-0` had no spatial instruction, so SELECT retried GROUND three times and correctly refused to fabricate a parcel.
- First divergence: `_to_project_target` treated every L3 programme row as a spatial target even when `map_intervention_to_spec` returned no spec.
- Resolution: `ProjectTarget.requires_spatial` is now explicit and compiler-derived. Non-spatial rows remain execution tasks; spatial rows still fail closed when GROUND has no candidates.
- Core proof: existing SELECT no-fallback tests continue to require `RETRY_GROUND` for manually constructed spatial targets; the live chain must prove that non-spatial rows no longer block selection.

## Invalid uploaded geometry at constraint checks

- Reproduction: direct validation of the repository fixture reports one invalid
  feature in `backend/tests/fixtures/mvp_village/gis/ecological_protection.geojson`
  (feature index 4) and five invalid features in
  `backend/tests/fixtures/mvp_village/gis/landuse.geojson` (indices 22, 104,
  258, 446, and 575). Shapely reports `Ring Self-intersection`; the land-use
  samples include BSM `441426211000049192`, `441426211000049300`, and
  `441426211000055592`.
- First divergence: the upload endpoint accepted valid JSON/FeatureCollection
  syntax but did not record topological validity. A later constraint predicate
  received an invalid land-use polygon and GEOS reported
  `TopologyException: side location conflict`.
- Official basis: Shapely documents `shapely.validation.make_valid` and `is_valid` for repairing/guarding invalid geometries.
- Resolution: the upload boundary now records a bounded geometry audit
  (feature count, invalid count, source feature index, reason, and BSM sample)
  without mutating the raw upload. Spatial index construction repairs invalid
  parcel and constraint geometries with `make_valid`; unrecoverable geometries
  are excluded and remain diagnosable rather than reaching GEOS predicates.
- Core evidence: `test_real_session_backend.py` logs the two source files and
  the six invalid source features before building the session bundle; the
  complete core gate passes after the boundary repair.
- Residual risk: a human review is still required when a required village has no real BSM-backed parcel geometry; validity repair cannot invent missing source data.
