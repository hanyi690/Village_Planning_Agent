"""Real bundle acceptance for the public evidence query transport.

This stays provider-free: the session and GIS bundle are real, while source
semantic classification remains disabled.  The test proves the public HTTP
boundary keeps ambiguity explicit instead of promoting every raw facility
label to a unique location.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from tests.fixtures.db import make_session_with_uploads


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village"
_LAYER_TYPES = {
    "admin_boundary_line.geojson": "admin_boundary_line",
    "annotation.geojson": "annotation",
    "boundary.geojson": "boundary",
    "construction_zone.geojson": "construction_zone",
    "ecological_protection.geojson": "ecological_protection",
    "farmland_protection.geojson": "farmland_protection",
    "geological_hazard_points.geojson": "geological_hazard_points",
    "historical_protection.geojson": "historical_protection",
    "landuse.geojson": "landuse_current",
    "road.geojson": "road",
}


def _uploads() -> list[dict]:
    uploads = [{
        "file_category": "village_data",
        "filename": "current_report.md",
        "original_filename": "current_report.md",
        "content_type": "text/markdown",
        "file_type": "md",
        "parsed_text": (FIXTURE / "current_report.md").read_text(encoding="utf-8"),
    }]
    for path in sorted((FIXTURE / "gis").glob("*.geojson")):
        uploads.append({
            "file_category": "gis_data",
            "filename": path.name,
            "original_filename": path.name,
            "content_type": "application/geo+json",
            "file_type": "geojson",
            "file_size": path.stat().st_size,
            "gis_data": json.loads(path.read_text(encoding="utf-8")),
            "gis_data_type": _LAYER_TYPES[path.name],
        })
    return uploads


@pytest.mark.asyncio
async def test_real_bundle_public_evidence_query_preserves_ambiguity(
    sqlite_db,
    pipeline_reset,
    monkeypatch,
):
    setup, teardown = sqlite_db
    await setup()
    try:
        session_id = "real-evidence-http-" + uuid.uuid4().hex[:8]
        await make_session_with_uploads(
            session_id,
            "金田村",
            uploads=_uploads(),
        )

        async def no_db_init() -> bool:
            return True

        monkeypatch.setattr("app.database.init_async_db", no_db_init)
        monkeypatch.setenv("SOURCE_SEMANTIC_LLM_ENABLED", "false")
        monkeypatch.setenv("RAG_ENABLED", "false")
        monkeypatch.setenv("EVIDENCE_EXTERNAL_PROVIDER", "disabled")

        from fastapi.testclient import TestClient

        import app.main as main

        with TestClient(main.app) as client:
            response = client.post(
                f"/api/v1/sessions/{session_id}/evidence/query",
                json={
                    "query": "金田村祠堂的BSM",
                    "village_name": "金田村",
                    "request_type": "spatial_lookup",
                    "entity_scope": ["facilities"],
                },
            )
            hazard_response = client.post(
                f"/api/v1/sessions/{session_id}/evidence/query",
                json={
                    "query": "金田村下村组吴德芳地质灾害点",
                    "village_name": "金田村",
                    "request_type": "spatial_lookup",
                    "entity_scope": ["hazards"],
                },
            )
            furnace_response = client.post(
                f"/api/v1/sessions/{session_id}/evidence/query",
                json={
                    "query": "炉池自然村在哪里",
                    "village_name": "金田村",
                    "request_type": "spatial_lookup",
                },
            )
            unresolved_facility_response = client.post(
                f"/api/v1/sessions/{session_id}/evidence/query",
                json={
                    "query": "金田村设施点",
                    "village_name": "金田村",
                    "request_type": "spatial_lookup",
                    "entity_scope": ["facilities"],
                },
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        packet = payload["evidence_packet"]
        candidates = packet["candidate_refs"]
        assert candidates, json.dumps(packet, ensure_ascii=False, indent=2)
        assert len(candidates) > 1
        assert packet["ambiguity_status"] == "multiple"
        assert all(
            str(candidate["geometry_ref"]).startswith("bundle://feature/")
            for candidate in candidates
        )
        assert all(float(candidate["source_authority_score"]) == 1.0 for candidate in candidates)
        assert all(candidate["selection_confidence"] is None for candidate in candidates)
        assert any(float(candidate["semantic_match_score"]) < 1.0 for candidate in candidates)
        assert all(
            "POINT(" not in json.dumps(candidate, ensure_ascii=False)
            and "POLYGON(" not in json.dumps(candidate, ensure_ascii=False)
            for candidate in candidates
        )
        traces = packet["query_trace"]
        semantic_traces = [
            trace
            for trace in traces
            if trace.get("step") in {
                "source_semantic_runtime",
                "source_semantic_overlay",
            }
        ]
        assert semantic_traces
        assert any(
            diagnostic.get("code") == "SOURCE_SEMANTIC_LLM_DISABLED"
            for diagnostic in semantic_traces[-1].get("diagnostics", [])
        )
        assert hazard_response.status_code == 200, hazard_response.text
        hazard_packet = hazard_response.json()["evidence_packet"]
        assert hazard_packet["candidate_refs"], json.dumps(
            hazard_packet, ensure_ascii=False, indent=2
        )
        assert any(
            candidate["identity"]["role"] == "hazard"
            for candidate in hazard_packet["candidate_refs"]
        )
        assert all(
            str(candidate["geometry_ref"]).startswith("bundle://feature/")
            for candidate in hazard_packet["candidate_refs"]
        )
        assert furnace_response.status_code == 200, furnace_response.text
        furnace_packet = furnace_response.json()["evidence_packet"]
        furnace_candidates = furnace_packet["candidate_refs"]
        assert len(furnace_candidates) == 4, json.dumps(
            furnace_packet,
            ensure_ascii=False,
            indent=2,
        )
        assert all(candidate["identity"]["role"] == "hazard" for candidate in furnace_candidates)
        assert all("炉池" in candidate["identity"]["canonical_name"] for candidate in furnace_candidates)
        assert len({
            parcel_bsm
            for candidate in furnace_candidates
            for parcel_bsm in candidate["related_parcel_bsms"]
        }) == 26
        furnace_payload = furnace_response.json()
        furnace_sources = furnace_payload["evidence_bundle"]["sources"]
        furnace_source_types = {
            source["source_type"]
            for source in furnace_sources
        }
        assert {"local_text", "gis_layer", "kg"}.issubset(furnace_source_types), json.dumps(
            furnace_sources,
            ensure_ascii=False,
            indent=2,
        )
        furnace_fact_types = {
            fact["fact_type"]
            for fact in furnace_payload["evidence_bundle"]["facts"]
        }
        assert {"planning_text", "bundle_feature_identity"}.issubset(
            furnace_fact_types
        ), json.dumps(
            furnace_payload["evidence_bundle"]["facts"],
            ensure_ascii=False,
            indent=2,
        )
        parcel_facts = [
            fact
            for fact in furnace_payload["evidence_bundle"]["facts"]
            if fact.get("fact_type") == "bundle_parcel_identity"
        ]
        assert parcel_facts, json.dumps(
            furnace_payload["evidence_bundle"]["facts"],
            ensure_ascii=False,
        )
        assert all(
            str(fact.get("source_locator") or "").startswith("bundle://feature/")
            and float((fact.get("fields") or {}).get("source_area_ha") or 0) > 0
            and (fact.get("fields") or {}).get("planning_geometry_policy")
            == "select_subgeometry_from_bundle_ref"
            for fact in parcel_facts
        )
        assert any(
            trace.get("step") == "retriever_plan"
            and {
                "local_text",
                "report",
                "kg",
                "bundle",
                "artifact",
                "history",
            }.issubset(set(trace.get("retrievers", [])))
            for trace in furnace_packet["query_trace"]
        )
        assert unresolved_facility_response.status_code == 200
        unresolved_packet = unresolved_facility_response.json()["evidence_packet"]
        assert unresolved_packet["candidate_refs"] == []
        assert unresolved_packet["sufficiency"] == "partial"
        assert "spatial_candidates_unresolved" in unresolved_packet["missing_evidence"]
        assert any(
            trace.get("step") == "spatial_result_status"
            and trace.get("status") == "partial"
            for trace in unresolved_packet["query_trace"]
        )
        assert any(
            diagnostic.get("code") == "SOURCE_SEMANTIC_LLM_DISABLED"
            for trace in unresolved_packet["query_trace"]
            for diagnostic in trace.get("diagnostics", [])
        )
        scope_trace = next(
            trace
            for trace in furnace_packet["query_trace"]
            if trace.get("step") == "semantic_candidate_scope"
        )
        assert scope_trace["status"] == "unscoped_exact_evidence"
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_real_bundle_public_evidence_query_paginates_all_facility_candidates(
    sqlite_db,
    pipeline_reset,
    monkeypatch,
):
    setup, teardown = sqlite_db
    await setup()
    try:
        session_id = "real-evidence-page-" + uuid.uuid4().hex[:8]
        await make_session_with_uploads(session_id, "金田村", uploads=_uploads())

        async def no_db_init() -> bool:
            return True

        monkeypatch.setattr("app.database.init_async_db", no_db_init)
        monkeypatch.setenv("SOURCE_SEMANTIC_LLM_ENABLED", "false")
        monkeypatch.setenv("RAG_ENABLED", "false")
        monkeypatch.setenv("EVIDENCE_EXTERNAL_PROVIDER", "disabled")

        from fastapi.testclient import TestClient

        import app.main as main

        with TestClient(main.app) as client:
            page_zero_response = client.post(
                f"/api/v1/sessions/{session_id}/evidence/query",
                json={
                    "query": "金田村祠堂的BSM",
                    "village_name": "金田村",
                    "request_type": "spatial_lookup",
                    "entity_scope": ["facilities"],
                    "candidate_offset": 0,
                    "candidate_limit": 2,
                },
            )
            page_one_response = client.post(
                f"/api/v1/sessions/{session_id}/evidence/query",
                json={
                    "query": "金田村祠堂的BSM",
                    "village_name": "金田村",
                    "request_type": "spatial_lookup",
                    "entity_scope": ["facilities"],
                    "candidate_offset": 2,
                    "candidate_limit": 2,
                },
            )

        assert page_zero_response.status_code == 200, page_zero_response.text
        assert page_one_response.status_code == 200, page_one_response.text
        page_zero = page_zero_response.json()["evidence_packet"]
        page_one = page_one_response.json()["evidence_packet"]
        assert page_zero["candidate_total"] > 2, json.dumps(
            page_zero, ensure_ascii=False, indent=2
        )
        assert page_zero["candidate_offset"] == 0
        assert page_zero["candidate_limit"] == 2
        assert page_zero["candidates_truncated"] is True
        assert page_zero["next_candidate_offset"] == 2
        assert len(page_zero["candidate_refs"]) == 2
        assert page_one["candidate_total"] == page_zero["candidate_total"]
        assert page_one["candidate_offset"] == 2
        assert page_one["next_candidate_offset"] is not None
        assert len(page_one["candidate_refs"]) == 2
        assert {
            candidate["identity"]["bundle_feature_bsm"]
            for candidate in page_zero["candidate_refs"]
        }.isdisjoint({
            candidate["identity"]["bundle_feature_bsm"]
            for candidate in page_one["candidate_refs"]
        })
    finally:
        await teardown()
