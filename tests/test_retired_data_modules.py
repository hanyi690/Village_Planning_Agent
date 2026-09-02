from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_retired_data_modules_and_legacy_cache_are_physically_absent():
    retired = (
        "backend/app/application/sessions/session_bundle.py",
        "backend/app/infrastructure/storage/bundle_store.py",
        "backend/app/data/catalog/external_anchors.py",
        "backend/app/infrastructure/evidence_runtime/retrievers/bundle_retriever.py",
        "backend/app/infrastructure/llm/tools/access/bundle.py",
        "backend/app/infrastructure/llm/tools/access/rag.py",
        "backend/app/infrastructure/kg/session_kg.py",
        "scripts/migrate_amap_validation_cache.py",
        "scripts/run_pipeline_real_jintian.py",
        "output/map_validation",
        "output/amap_validation",
        "output/bundle_cache",
        "output/intent_cache",
        "backend/app/data/ingestion/ingest.py",
        "backend/app/data/ingestion/adapters",
        "backend/app/data/ingestion/providers/poi.py",
        "backend/app/data/ingestion/providers/amap/anchor_service.py",
        "backend/app/data/ingestion/providers/tencent/anchor_service.py",
        "backend/app/data/ingestion/providers/tianditu/anchor_service.py",
        "backend/app/data/ingestion/gazetteer.py",
        "backend/app/data/ingestion/encoding_detector.py",
        "backend/app/data/catalog/admin_code_loader.py",
        "backend/app/data/model/location_parser.py",
        "backend/app/data/ports/ingest.py",
        "backend/app/data/ports/__init__.py",
        "backend/app/data/ports",
    )
    assert all(not (ROOT / relative).exists() for relative in retired)


def test_active_data_import_boundary_has_no_typed_ingest_exports():
    import importlib

    ingestion = importlib.import_module("app.data.ingestion")
    importlib.import_module("app.data.ingestion.sources")
    importlib.import_module("app.modules.data.application")

    assert not hasattr(ingestion, "ingest_landuse")
    assert not hasattr(ingestion, "result_to_parcels")


def test_provider_collectors_have_no_fixed_boundary_or_legacy_cache_dependency():
    collector_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "scripts/collect_amap_jintian_validation.py",
            "scripts/collect_three_provider_validation.py",
            "scripts/collect_tianditu_full.py",
        )
    )
    assert "DATA_LEGACY_BOUNDARY_FILE_FALLBACK" not in collector_text
    assert "output/map_validation" not in collector_text
    assert "boundary.geojson" not in collector_text


def test_output_contains_no_cache_or_legacy_bundle_input_directory():
    output_root = ROOT / "output"
    if not output_root.exists():
        return
    forbidden = [
        path
        for path in output_root.rglob("*")
        if "cache" in path.name.casefold()
        or (path.is_dir() and path.name.casefold() == "bundle" and path.parent.name.casefold() == "inputs")
    ]
    assert forbidden == []
