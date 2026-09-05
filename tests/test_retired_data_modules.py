from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _retired_path_is_absent(relative: str) -> bool:
    path = ROOT / relative
    if not path.exists():
        return True
    if not path.is_dir():
        return False
    # Python may recreate ignored __pycache__ directories after the source
    # package is removed. They contain no executable source and are not part
    # of the retired implementation boundary.
    return not any(
        child.is_file()
        and child.suffix != ".pyc"
        and "__pycache__" not in child.parts
        for child in path.rglob("*")
    )


def test_retired_data_modules_and_legacy_cache_are_physically_absent():
    retired = (
        "backend/app/application/sessions/session_bundle.py",
        "backend/app/infrastructure/storage/bundle_store.py",
        "backend/app/data/catalog/external_anchors.py",
        "backend/app/infrastructure/evidence_runtime/retrievers/bundle_retriever.py",
        "backend/app/infrastructure/llm/tools/access/bundle.py",
        "backend/app/infrastructure/llm/tools/access/rag.py",
        "backend/app/infrastructure/kg/session_kg.py",
        "backend/app/infrastructure/kg/dlq.py",
        "backend/app/infrastructure/kg/interface.py",
        "backend/app/infrastructure/kg/manager.py",
        "backend/app/infrastructure/kg/memory.py",
        "backend/app/infrastructure/kg/process_worker.py",
        "backend/app/infrastructure/kg/service.py",
        "backend/app/infrastructure/kg/spatial_store.py",
        "backend/app/infrastructure/kg/builder",
        "backend/app/infrastructure/kg/enrichment",
        "backend/app/infrastructure/kg/gazetteer",
        "backend/app/infrastructure/kg/queries",
        "backend/app/infrastructure/kg/adapters/spatial_query_adapter.py",
        "backend/app/infrastructure/kg/adapters/semantic_query_adapter.py",
        "backend/app/infrastructure/kg/adapters/gazetteer_adapter.py",
        "backend/app/contracts/cognition/shadow_diff.py",
        "backend/app/infrastructure/cognition_runtime/shadow_compare.py",
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
        "backend/app/data/catalog/catalog.py",
        "backend/app/data/catalog/config.py",
        "backend/app/data/catalog/sources.yaml",
        "backend/app/data/model/location_parser.py",
        "backend/app/data/model/village_name_registry.py",
        "backend/app/data/ports/ingest.py",
        "backend/app/data/ports/__init__.py",
        "backend/app/data/ports",
    )
    assert all(_retired_path_is_absent(relative) for relative in retired)


def test_active_data_import_boundary_has_no_typed_ingest_exports():
    import importlib

    ingestion = importlib.import_module("app.data.ingestion")
    importlib.import_module("app.data.ingestion.sources")
    importlib.import_module("app.modules.data.application")

    assert not hasattr(ingestion, "ingest_landuse")
    assert not hasattr(ingestion, "result_to_parcels")


def test_world_model_has_no_shadow_compatibility_surface():
    runtime_files = (
        ROOT / "backend/app/infrastructure/context_runtime/runtime.py",
        ROOT / "backend/app/infrastructure/context_runtime/manager.py",
        ROOT / "backend/app/infrastructure/evidence_runtime/v2_catalog.py",
        ROOT / "backend/app/infrastructure/evidence_runtime/source_semantic_runtime.py",
        ROOT / "backend/app/modules/evidence/application.py",
        ROOT / "backend/app/modules/ground/application.py",
        ROOT / "backend/app/workflow/layers/context_bootstrap.py",
        ROOT / "backend/app/workflow/stages/support.py",
        ROOT / "backend/app/workflow/state.py",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    assert "world_model_shadow" not in text
    assert "shadow_compare" not in text


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
