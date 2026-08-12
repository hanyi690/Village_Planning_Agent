# Round-2 Audit: I — EXPLORE Evidence Retrieval Wiring (M3)

Scope: `backend/app/evidence/` (extend), `backend/app/infrastructure/search/` (new adapter), contracts reused untouched.

## Files

- **Created** `backend/app/infrastructure/search/__init__.py`, `backend/app/infrastructure/search/exa_adapter.py`
- **Extended** `backend/app/evidence/retrieval/explore_service.py` (rewired local-first chain)
- **Extended** `backend/app/evidence/retrieval/place_evidence_index.py` (`_mention_of` now also reads `canonical_name`/`entity_ref` so an `L1LocationFact` local request resolves)

## FakeExternalSearchAdapter

- Implements `ExternalSearchPort.search` (async), no Exa SDK, no network.
- Typed success: `result_records` limited by `result_limit`, `retrieval_status="success"`, cost/latency/request_id deterministic from request.
- Typed failures (never a bare exception), from constructor config + request:
  - `empty` (allowlist empty, requested domain/category not allowed, or no corpus match)
  - `provider_unavailable` (`retrieval_status="unavailable"`)
  - `timeout` (`retrieval_status="timeout"`, `SearchFailure.code="provider_timeout"`)
  - `budget_exceeded` (`retrieval_status="budget_exceeded"`, gated by `max_cost` vs request budget)
- Drop-in shape: same `search` signature as the future real Exa adapter; replace via DI.

## ExploreService wiring

- `__init__` gains `place_evidence_index` (defaults None); local pass runs first via `PlaceEvidenceIndexService.resolve(L1LocationFact)`.
- Local outcome mapping: `resolved → success`, `ambiguous → ambiguous`, reason `insufficient_geometry → insufficient_geometry`, `stale → stale_snapshot`, `empty mention → query_error`, else `not_found`.
- Only on a non-success local outcome does EXPLORE fall through to `ExternalSearchPolicy.evaluate` + `external_port` (the adapter).
- External claims are mapped only to `EvidenceSource`/`EvidenceFact` (`fact_type="external_claim"`, `status="needs_review"`); `ExternalClaimDraft` has no geometry/BSM/classification fields, so external claims can never create entities or planning objects.
- Returns the reused `EvidenceBundle`; typed outcome readable via `outcome_of(bundle)` (provenance trace tag). `STALE_SNAPSHOT` added to `ExploreOutcome`.

## Outcome taxonomy

`success`, `not_found`, `stale_snapshot` (+ legacy `stale`), `query_error`, `ambiguous`, `insufficient_geometry`, plus `external_denied` / `external_failed` for the gated/failed external path.

## Verification

```
python -c "import app.infrastructure.search.exa_adapter; import app.evidence.retrieval.explore_service; import app.evidence.retrieval.place_evidence_index; import app.evidence.retrieval.external_search_policy; print('OK')"
Result: OK (Python 3.12.10, pydantic 2.13.4)
```

Functional smoke: `FakeExternalSearchAdapter()` (empty allowlist) → typed `empty` failure with `SearchFailure`, no exception. Also verified success, `budget_exceeded`, `provider_unavailable`, `timeout`, and a full `ExploreService` chain (`not_found → policy allowed → external success`) producing only `external_claim` facts.
