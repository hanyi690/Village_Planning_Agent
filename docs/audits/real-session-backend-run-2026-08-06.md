# Real Session backend run (2026-08-06)

## Result

The core gate is green: `12 passed` under `backend/tests/core`, including the real-session test. The real-session test creates a multipart session in isolated SQLite, loads the repository's report and ten GIS GeoJSON files, executes PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER, and verifies the final DELIVER gate is `PASS`.

The test uses deterministic local adapters only for model/GIS network boundaries. It does not replace the supplied report or GIS inputs.

## Inputs

- Report: `backend/tests/fixtures/mvp_village/current_report.md`
  - SHA-256: `92DC1119E8104874976B224447DA651A6382CA3CCE2F05A30D310E58FBDE4480`
- GIS directory: `backend/tests/fixtures/mvp_village/gis/`
  - `admin_boundary_line.geojson`
  - `annotation.geojson`
  - `boundary.geojson`
  - `construction_zone.geojson`
  - `ecological_protection.geojson`
  - `farmland_protection.geojson`
  - `geological_hazard_points.geojson`
  - `historical_protection.geojson`
  - `landuse.geojson`
  - `road.geojson`

The upload endpoint records each source filename and checksum in the session input snapshot. Stage records then carry the source refs, `context_ref`, input checksum, parent artifact refs, output checksum, gate route, attempt and duration.

## Stage evidence

Every stage writes a `stage_started` record and a `stage_completed` or `stage_failed` record through the existing `StepReportModel` path. Large typed values do not cross the checkpoint boundary:

- PARSE writes `intent_compilation`.
- GROUND writes `grounding_result`.
- SELECT writes `site_selection` and `execution_plan`.
- EXECUTE writes `parcel_changeset`, `planned_state`, and `allocated_geojson`.
- VALIDATE writes `validation_report`.
- RECONCILE writes `reconciliation_report`.
- DELIVER writes `delivery_manifest`.

The operator-readable projection is available at:

- HTTP: `GET /api/sessions/{session_id}/stage-report.md`
- File: `.run-tmp/{session_id}/reports/stage-report.md`

Both are rendered from the same persisted StepReport rows. The same session also exposes `GET /api/sessions/{session_id}/positioning-trace`.

## Latest sample

One generated sample is retained during the test run at:

`.run-tmp/d7a0d871-a865-4d64-80cc-b28b2cac4a25/reports/stage-report.md`

Session IDs are intentionally random per run, so operators should use the ID returned by `POST /api/sessions` for the current report.

`Feasible` in the Markdown projection is now true when the persisted DELIVER stage has `gate_route: PASS`; the broader backend-run summary may still report missing optional export/render layers separately.

## Reproduction

```powershell
cd backend
D:\python\python.exe -B -m pytest tests/core/test_real_session_backend.py -q
D:\python\python.exe -B -m pytest tests/core -q
```

The repository pytest configuration applies a 30-second test timeout, 90-second session timeout, `thread` timeout diagnostics, and a workspace-local basetemp to avoid Windows TEMP permission stalls.
