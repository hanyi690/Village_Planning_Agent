# Round-1 Audit: D — Evidence Module (M3)

Scope: `backend/app/evidence/` only (additive). No files outside this directory were modified.

## Files created

```
app/evidence/model/l1_location_fact.py        app/evidence/model/place_resolution.py
app/evidence/model/relation_evidence.py       app/evidence/model/external_search.py
app/evidence/retrieval/__init__.py            app/evidence/retrieval/place_evidence_index.py
app/evidence/retrieval/external_search_policy.py
app/evidence/retrieval/explore_service.py
app/evidence/kg/__init__.py                   app/evidence/kg/base_facts.py
app/evidence/kg/derived_relations.py          app/evidence/kg/reverse_relation_index.py
```

## Re-exported vs newly defined

- **Re-exported (single owner):**
  - `RelationEvidence` ← `app.contracts.workflow.repair`
  - `PlaceResolutionResult` / `PlaceResolutionCandidate` ← `app.modules.schema.contracts.place_resolution_contracts`
  - `EvidenceBundle` (runtime) ← `app.modules.schema.contracts.evidence_contracts`
- **Newly defined:**
  - `L1LocationFact` (strict, `extra="forbid"` via `StrictContractModel`; geometry_ref optional)
  - `DirectionalRelation` StrEnum {direct, inverse}
  - `PlaceResolutionStatus` StrEnum — values: `exact`, `ambiguous`, `unresolved`, `conflict`, `insufficient_geometry`
  - `ExternalClaimDraft` {claim_text, source, url, published_at, confidence} — no geometry/BSM/classification/planning fields
  - `ExternalSearchEvidence` (read-only evidence container; cannot create planning objects)
  - `PlaceEvidenceIndexService` (implements `app.contracts.ports.place_evidence.PlaceEvidenceIndex`; lazy-imports `SpatialResolver`; fuzzy short-name can only yield `ambiguous`; never auto-picks first)
  - `ExternalSearchPolicy` + `ExternalSearchDecision(Code)` — gates on dimension/freshness/max_cost/allowlist before any provider call
  - `ExploreService` + `ExploreOutcome` enum {success, not_found, stale, query_error, ambiguous, insufficient_geometry, external_denied, external_failed}; local-first then policy+port
  - `BaseFacts` — NOT found in `app/modules/kg/` (only builder comments); minimal strict container {facts, provenance} marked as semantic index, not spatial truth
  - `DerivedRelations` {relations: list[RelationEvidence], query_trace}
  - `ReverseRelationIndex.lookup(subject, predicate) -> list[object_ref]` — returns full list, never first candidate

## Notes

- `PlaceResolutionResult.status` (reused) carries only `resolved|ambiguous|unresolved`; `PlaceResolutionStatus` keeps the finer distinctions in the same module and is recorded via `unresolved_reason`/trace.
- `ExploreService.resolve` returns the reused `EvidenceBundle`; the typed outcome is read via `outcome_of(bundle)` (provenance trace tag).
- `app/evidence/model/__init__.py` updated additively only.

## Import verification

```
python -c "import app.evidence.model.l1_location_fact; ... ; print('OK')"  # from backend/
Result: OK (Python 3.12.10)
```
