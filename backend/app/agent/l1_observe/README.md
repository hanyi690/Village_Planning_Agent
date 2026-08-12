# L1 / ASSESS adapter

L1 workers may produce reports and evidence claims. `l1_aggregate` persists the typed snapshot through
`app/infrastructure/artifacts/runtime.py` and returns an immutable CAS descriptor. It does not create
spatial decisions or load raw GIS into workflow state.

The target architecture maps this adapter to `ASSESS`; the authoritative future output is an
`AssessmentSnapshot`, not report text.
