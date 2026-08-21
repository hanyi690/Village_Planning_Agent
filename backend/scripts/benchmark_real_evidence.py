"""Benchmark the local evidence stack on the checked-in JinTian GIS bundle.

This script never calls MiniMax, RAG, Exa, or another network provider.  It
measures the local ingestion -> bundle -> KG -> EvidenceGraph path and
verifies that the last session release drops an unreferenced Layer-1 cache
entry.  Run from the repository root with::

    python backend/scripts/benchmark_real_evidence.py
"""

from __future__ import annotations

import gc
import json
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

import psutil
from rdflib import RDF

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.ingestion.adapters import ADAPTERS  # noqa: E402
from app.data.model.canonical import VillageBundle  # noqa: E402
from app.data.model.layer_registry import GIS_LAYER_REGISTRY  # noqa: E402
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex  # noqa: E402
from app.evidence.retrieval.evidence_graph import EvidenceGraph  # noqa: E402
from app.infrastructure.context.planning_context import PlanningContext  # noqa: E402
from app.infrastructure.kg.manager import KGManager  # noqa: E402
from app.infrastructure.kg.ontology import EntityTypes  # noqa: E402
from app.spatial.model.workspace import SpatialWorkspace  # noqa: E402


LAYER_MAP = {
    "admin_boundary_line.geojson": "admin_boundary_line",
    "annotation.geojson": "current_annotation",
    "boundary.geojson": "boundary",
    "construction_zone.geojson": "conditional_construction_zone",
    "ecological_protection.geojson": "ecological_protection",
    "farmland_protection.geojson": "farmland_protection",
    "geological_hazard_points.geojson": "geological_hazard_point",
    "historical_protection.geojson": "historical_protection",
    "landuse.geojson": "landuse_current",
    "road.geojson": "current_road",
}


def _rss_mb(process: psutil.Process) -> float:
    return round(process.memory_info().rss / (1024 * 1024), 2)


def _elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 3)


def _load_bundle() -> tuple[VillageBundle, dict[str, int]]:
    bundle = VillageBundle(village_name="金田村")
    counts: dict[str, int] = {}
    source_root = PROJECT_ROOT / "data" / "gis" / "jintian" / "current"
    for filename, layer_type in LAYER_MAP.items():
        path = source_root / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        entry = GIS_LAYER_REGISTRY[layer_type]
        adapter = ADAPTERS[entry.ingest.adapter]
        if entry.ingest.adapter == "parcels":
            result = adapter.load(payload, entry)
        else:
            result = adapter.load(
                payload,
                entry,
                source_uri=path.resolve().as_uri(),
            )
        counts[layer_type] = len(result.features)
        for feature in result.features:
            bundle.add(feature)
    return bundle, counts


def run() -> dict[str, Any]:
    process = psutil.Process()
    metrics: dict[str, Any] = {"rss_start_mb": _rss_mb(process)}
    tracemalloc.start()
    manager = KGManager()
    bundle: VillageBundle | None = None
    workspace: SpatialWorkspace | None = None
    kg: Any = None
    cached_kg: Any = None
    context: PlanningContext | None = None
    index: Any = None
    try:
        start = time.perf_counter()
        bundle, counts = _load_bundle()
        metrics.update({"bundle_ingest_seconds": _elapsed(start), "feature_counts": counts})

        workspace = SpatialWorkspace.from_bundle(
            bundle,
            session_id="benchmark-jintian",
            source="local_benchmark",
        )
        start = time.perf_counter()
        kg = manager.get_or_build_kg(
            "金田村",
            bundle=bundle,
            session_id="benchmark-jintian-a",
        )
        metrics["kg_cold_build_seconds"] = _elapsed(start)
        start = time.perf_counter()
        cached_kg = manager.get_or_build_kg(
            "金田村",
            bundle=bundle,
            session_id="benchmark-jintian-b",
        )
        metrics["kg_cache_build_seconds"] = _elapsed(start)
        metrics["rss_after_kg_mb"] = _rss_mb(process)
        metrics["kg"] = {
            "triples": kg.get_triple_count(),
            "entities": len(kg.find_entities(limit=100000)),
            "relations": len(kg.find_relations(limit=100000)),
        }
        road_subjects = set(kg.g.subjects(RDF.type, EntityTypes.Road))
        admin_boundary_subjects = set(
            kg.g.subjects(RDF.type, EntityTypes.AdministrativeBoundary)
        )
        metrics["kg"]["spatial_type_partition"] = {
            "Road": len(road_subjects),
            "AdministrativeBoundary": len(admin_boundary_subjects),
            "admin_boundary_also_Road": len(
                road_subjects & admin_boundary_subjects
            ),
        }

        context = PlanningContext(
            session_id="benchmark-jintian",
            village_name="金田村",
            version=1,
            workspace=workspace,
            data_snapshot=workspace.snapshot,
            kg=kg,
            kg_session_ref="benchmark-jintian-a",
            kg_version=1,
        )
        start = time.perf_counter()
        index = PlaceEvidenceIndex.build(context)
        context.evidence_graph = EvidenceGraph(context, index=index)
        metrics["evidence_index_build_seconds"] = _elapsed(start)

        start = time.perf_counter()
        candidate_counts = []
        for _ in range(1000):
            result = context.evidence_graph.resolve_mention(
                "祠",
                role="facility",
                hints="社前村",
            )
            candidate_counts.append(len(result.candidates))
        metrics["evidence_query_1000_seconds"] = _elapsed(start)
        metrics["evidence_candidate_count"] = {
            "first": candidate_counts[0] if candidate_counts else 0,
            "last": candidate_counts[-1] if candidate_counts else 0,
        }

        start = time.perf_counter()
        for _ in range(10000):
            kg.find_entities(name="祠堂", limit=12)
            kg.find_relations(limit=12)
        metrics["kg_query_10000_mixed_seconds"] = _elapsed(start)
        current, peak = tracemalloc.get_traced_memory()
        metrics["tracemalloc_mb"] = {
            "current": round(current / (1024 * 1024), 2),
            "peak": round(peak / (1024 * 1024), 2),
        }
        metrics["rss_before_release_mb"] = _rss_mb(process)
        return metrics
    finally:
        manager.remove_session("benchmark-jintian-a")
        manager.remove_session("benchmark-jintian-b")
        del context, index, kg, cached_kg, workspace, bundle
        for _ in range(3):
            gc.collect()
        metrics["rss_after_release_mb"] = _rss_mb(process)
        metrics["kg_cache_after_release"] = manager.stats()
        tracemalloc.stop()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
