"""End-to-end runtime data-pipeline test (real DataCatalog full chain).

Covers the complete runtime data pipeline against a real temp SQLite:

  1. Upload persistence          — UploadedFile / planning_sessions rows
  2. build_session_bundle        — real DataCatalog -> VillageBundle + session
                                   context (uploads merged, reports attached)
  3. ReportStore.bulk_save       — dimension_reports write + read-back
  4. snapshot_session_bundle     — planning_bundles versioned snapshot
  5. KGManager.get_or_build_kg   — session KG build + registration
  6. resolve_bundle snapshot-first — snapshot path, no live rebuild
  7. EXPLORE access tools        — real calls against the session data

The spatial load goes through the REAL ``DataCatalog`` (boundary-first, WMS
layers skipped / water derived from parcels — deterministic offline).

NOTE: requires ``fastapi``; run with the project environment that has it
(e.g. ``D:\\python\\python.exe -m pytest backend/tests/integration``).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.db import make_session_with_uploads  # noqa: E402


@pytest.mark.asyncio
async def test_runtime_pipeline_e2e(sqlite_db, pipeline_reset, monkeypatch):
    setup, teardown = sqlite_db
    await setup()
    try:
        # ── Stage 1: upload persistence ───────────────────────────────────
        from app.database.operations import get_uploaded_files_by_session_async

        sid = await make_session_with_uploads("sess-e2e", "金田村")
        uploads = await get_uploaded_files_by_session_async(sid)
        assert len(uploads) == 2
        assert {u["file_category"] for u in uploads} == {"village_data", "gis_data"}
        assert all(u["parse_status"] == "success" for u in uploads)

        # ── Stage 2: build_session_bundle (real DataCatalog) ──────────────
        from app.services.session_bundle import build_session_bundle

        bundle = await build_session_bundle(sid)
        assert bundle.metadata.session_id == sid
        assert bundle.village_name == "金田村"
        assert bundle.parcel_count > 0
        assert len(bundle.lines.get("roads_current") or []) > 0
        assert len(bundle.points.get("annotations_current") or []) > 0
        assert "dem" in bundle.rasters.all_rasters

        sources = [t["source"] for t in bundle.documents.planning_texts]
        assert "upload" in sources, f"uploads not merged into planning_texts: {sources}"

        upload_groups = [k for k in bundle.polygons._layers.keys() if k.startswith("upload_")]
        assert upload_groups, "uploaded GIS not merged into bundle polygons"

        # ── Stage 3: reports bulk_save + read-back ────────────────────────
        from app.database.operations import get_session_reports_async
        from app.services.report_store import ReportStore

        store = ReportStore()
        await store.bulk_save([
            {
                "session_id": sid, "dimension_key": "location", "layer": 1,
                "version": 1, "report_id": "r-e2e-location",
                "content": "## 区位\n金田村位于广宁县排沙镇。", "summary": "{}",
            },
            {
                "session_id": sid, "dimension_key": "land_use", "layer": 1,
                "version": 1, "report_id": "r-e2e-landuse",
                "content": "## 用地结构\n以耕地为主。", "summary": "{}",
            },
        ])
        by_layer = await get_session_reports_async(sid)
        assert set(by_layer[1].keys()) == {"location", "land_use"}

        # ── Stage 4: versioned snapshot → planning_bundles ───────────────
        from app.database.operations import get_planning_bundle_async
        from app.services.bundle_store import BundleStore
        from app.services.session_bundle import snapshot_session_bundle

        snap = await snapshot_session_bundle(sid, trigger_reason="final")
        assert snap is not None

        record = await get_planning_bundle_async(sid)
        assert record is not None
        assert record["version"] == 1
        assert record["trigger_reason"] == "final"
        assert record["sha256"]

        restored = await BundleStore().load_bundle(sid)
        assert restored is not None
        assert restored.parcel_count == bundle.parcel_count
        assert (restored.layer_reports or {}).get(1, {}).get("location", {}).get("content")
        assert any(
            k.startswith("upload_") for k in restored.polygons._layers.keys()
        ), "snapshot lost uploaded GIS merge"

        # ── Stage 5: KG build + session registration ─────────────────────
        from app.modules.kg.manager import KGManager

        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        assert kg is not None
        assert KGManager().get_session_kg(sid) is kg

        # ── Stage 6: resolve_bundle is snapshot-first (no live build) ────
        from app.services import session_bundle as sb
        from app.tools.access.shared import resolve_bundle

        sb._bundle_cache.clear()
        calls = {"n": 0}

        async def _boom_build(*a, **k):
            calls["n"] += 1
            raise AssertionError("live build must not run when a snapshot exists")

        monkeypatch.setattr(sb, "build_session_bundle", _boom_build)
        rb = await resolve_bundle(sid)
        assert rb is not None
        assert calls["n"] == 0
        assert (rb.layer_reports or {}).get(1, {}).get("location", {}).get("content")
        assert any(
            t.get("source") == "upload" for t in rb.documents.planning_texts
        ), "snapshot path lost uploaded text"

        # ── Stage 7: EXPLORE access tools (real calls) ───────────────────
        from app.tools.access.bundle import (
            bundle_overview_impl,
            spatial_context_impl,
            spatial_features_impl,
        )

        overview = await bundle_overview_impl(sid)
        assert overview["village_name"] == "金田村"
        assert overview["parcel_count"] > 0
        assert overview["spatial_groups"]["lines"]["roads_current"]["count"] > 0
        assert set(overview["layer_reports"]["1"]) == {"location", "land_use"}

        ctx = await spatial_context_impl(sid)
        assert ctx["parcel_count"] > 0
        assert ctx["kg_cognition"], "spatial_context missing KG cognition"

        feats = await spatial_features_impl(sid, group="lines", max_features=5)
        assert feats["lines"]["roads_current"]["count"] > 0
        assert feats["lines"]["roads_current"]["shown"] <= 5
    finally:
        await teardown()
