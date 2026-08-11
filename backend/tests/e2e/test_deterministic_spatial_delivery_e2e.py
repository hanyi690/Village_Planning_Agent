"""Deterministic spatial delivery closure on the real unified planning graph.

This test intentionally starts from a typed PlanningProgram artifact and runs
the production main graph through PARSE, GROUND, SELECT, EXECUTE, VALIDATE,
RECONCILE, and DELIVER. The only injected boundary is a local spatial query
port backed by three synthetic BSM parcels; no LLM, network, or remote GIS
provider is involved.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.bootstrap.artifact_runtime import load_artifact, store_artifact
from app.agent.bootstrap.graph import create_unified_planning_graph
from app.agent.plan_state.state import create_initial_state
from app.modules.context.planning_context import PlanningContext
from app.modules.kg.manager import get_kg_manager
from app.modules.ports.planning_ports import PlanningPorts
from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest
from app.modules.schema.contracts.l3_contracts import PlanningIntervention, PlanningProgram
from app.modules.schema.contracts.spatial_reference_contracts import CandidateSet
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import AdminArea, CurrentLandUseParcel
from app.modules.spatial_ops import build_constraint_index


pytestmark = pytest.mark.e2e


def _rect(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def _bundle() -> VillageBundle:
    bundle = VillageBundle(village_name="deterministic-village")
    bundle.polygons.set(
        "admin_areas",
        [
            AdminArea(
                bsm="boundary-1",
                geometry=_rect(0, 0, 1000, 3000),
                djzqmc="deterministic-village",
            )
        ],
    )
    # Metre-unit synthetic geometry makes the deterministic land-design split
    # and delivery land-balance calculations use the same area convention.
    bundle.polygons.set(
        "landuse_current",
        [
            CurrentLandUseParcel(
                bsm="P001",
                dlbm="0702",
                area_sqm=50000.0,
                area_ha=5.0,
                geometry=_rect(0, 2000, 100, 2500),
            ),
            CurrentLandUseParcel(
                bsm="P002",
                dlbm="0101",
                area_sqm=100000.0,
                area_ha=10.0,
                geometry=_rect(0, 500, 500, 700),
            ),
            CurrentLandUseParcel(
                bsm="P003",
                dlbm="0301",
                area_sqm=100000.0,
                area_ha=10.0,
                geometry=_rect(500, 500, 1000, 700),
            ),
        ],
    )
    # These layers make the real export package satisfy its statutory layer
    # contract without depending on a remote GIS fixture.
    for layer_name, code in (
        ("ecological_redline", "ECO"),
        ("farmland_protection", "FARMLAND"),
        ("construction_zone", "CONSTRUCTION"),
    ):
        bundle.polygons.set(
            layer_name,
            [
                CurrentLandUseParcel(
                    bsm=f"{code}-1",
                    dlbm=code,
                    area_sqm=10000.0,
                    geometry=_rect(0, 0, 100, 100),
                )
            ],
        )
    return bundle


class _TargetBoundSpatialQuery:
    """Resolve each closed-set spec to its explicitly bound BSM pool."""

    def resolve_candidates(self, _run_id: str, spec) -> CandidateSet:
        target_id = str(getattr(spec, "target_id", "") or "")
        if target_id == "project-north":
            return CandidateSet(bsms=["P001"])
        if target_id == "zone-south":
            return CandidateSet(bsms=["P002", "P003"])
        return CandidateSet(bsms=[])


def _context(session_id: str, bundle: VillageBundle) -> PlanningContext:
    context = PlanningContext(
        session_id=session_id,
        village_name=bundle.village_name,
        version=1,
        bundle=bundle,
        ports=PlanningPorts(spatial_query=_TargetBoundSpatialQuery()),
    )
    context.snapshot_meta = lambda: {
        "session_id": session_id,
        "village_name": bundle.village_name,
        "version": 1,
        "parcel_bsms": [p.bsm for p in bundle.polygons.get("landuse_current")],
    }
    return context


def _program() -> PlanningProgram:
    return PlanningProgram(
        artifact_id="deterministic-program-v1",
        interventions=[
            PlanningIntervention(
                intervention_id="project-north",
                name="村北农产品加工产业园",
                category="project",
                expected_output_kind="parcel",
                area_range_ha=(5.0, 5.0),
                scale="5公顷",
                functions=["产业项目"],
                spatial_requirements={"location": "村北"},
            ),
            PlanningIntervention(
                intervention_id="zone-south",
                name="村南农业保育区",
                category="zone",
                expected_output_kind="polygon",
                area_range_ha=(10.0, 10.0),
                functions=["农业保育区"],
                spatial_requirements={"location": "村南"},
            ),
        ],
    )


def _initial_state(session_id: str, program: PlanningProgram) -> dict:
    state = create_initial_state(
        session_id,
        "deterministic-village",
        "local deterministic GIS fixture",
        village_name="deterministic-village",
        rag_enabled=False,
    )
    state["context_version"] = "1"
    state["context_fingerprint"] = "sha256:deterministic-context"
    state["context_ref"] = {"session_id": session_id, "version": "1"}
    state["bootstrap_context_done"] = True
    state["artifact_refs"] = {
        "planning_program": store_artifact(
            state,
            "planning_program",
            "l3",
            "PlanningProgram",
            program.model_dump(mode="json"),
        )
    }
    state["messages"] = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "gis_analysis",
                    "args": {},
                    "id": "local-tool",
                    "type": "tool_call",
                }
            ],
        )
    ]
    return state


@pytest.mark.asyncio
async def test_real_main_graph_deterministic_spatial_delivery_closure(monkeypatch, tmp_path):
    session_id = f"deterministic-spatial-{uuid4().hex}"
    run_root = tmp_path / "run-tmp"
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_root))

    bundle = _bundle()
    context = _context(session_id, bundle)
    manager = get_kg_manager()
    manager.get_or_build_kg(
        bundle.village_name,
        bundle=bundle,
        session_id=session_id,
    )
    context.kg = manager.get_session_kg(session_id)
    context.kg_session_ref = session_id
    context.constraint_index = build_constraint_index(bundle)

    async def _bootstrap(_state):
        return {
            "context_version": "1",
            "context_fingerprint": "sha256:deterministic-context",
            "context_ref": {"session_id": session_id, "version": "1"},
            "bootstrap_context_done": True,
        }

    async def _skip_stage_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_main_nodes._get_cached_context",
        lambda _state: context,
    )
    monkeypatch.setattr("app.agent.bootstrap.graph.bootstrap_context_node", _bootstrap)
    monkeypatch.setattr("app.agent.bootstrap.stage_audit._save", _skip_stage_audit)

    from app.agent.parse.aggregate import compile_program_async as real_compile_program_async

    async def _compile_with_local_target_bindings(*args, **kwargs):
        result, specs, gate = await real_compile_program_async(*args, **kwargs)
        for target in result.typed_intent.project_targets:
            if target.target_id == "project-north":
                target.candidate_bsms = ["P001"]
        for target in result.typed_intent.zone_targets:
            if target.target_id == "zone-south":
                target.candidate_bsms = ["P002"]
        result.intent = result.typed_intent
        return result, specs, gate

    monkeypatch.setattr(
        "app.agent.parse.aggregate.compile_program_async",
        _compile_with_local_target_bindings,
    )

    state = _initial_state(session_id, _program())
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    result = await graph.ainvoke(
        state,
        config={"configurable": {"thread_id": session_id}},
    )

    assert result["select_gate"]["passed"] is True
    assert result["validate_gate"]["passed"] is True, repr(result["validate_gate"])
    assert result["reconcile_gate"]["passed"] is True
    assert result["deliver_gate"]["passed"] is True

    selection = load_artifact(result, "site_selection")
    assert selection["decision_factors"]["placed_count"] == 1
    assert selection["full_ranking"][0]["candidate_id"] == "P001"

    planned_state = load_artifact(result, "planned_state")
    assert planned_state["parcels"], "EXECUTE must produce the latest PlannedState parcels"
    assert any(parcel["derived_from_bsms"] for parcel in planned_state["parcels"])

    render_layers = load_artifact(result, "render_layers")
    assert render_layers, "DELIVER must persist non-empty RenderLayers"
    feature_collections = [layer.get("data") or layer.get("geojson") for layer in render_layers]
    assert all(collection["type"] == "FeatureCollection" for collection in feature_collections)
    assert sum(len(collection["features"]) for collection in feature_collections) > 0

    manifest = load_artifact(result, "delivery_manifest", DeliveryManifest)
    assert manifest.delivery_status == "complete", manifest.model_dump(mode="json")
    assert manifest.delivery_gate is not None and manifest.delivery_gate.passed
    assert manifest.render_layer_count == len(render_layers)
    assert manifest.expected_spatial_output_count >= 1
    assert not [item for item in manifest.pending_human_items if item.blocking]

    from app.modules.ports.artifact_store import ArtifactRef
    from app.services.artifact_store import FilesystemArtifactStore

    store = FilesystemArtifactStore(run_root)
    refs = result["artifact_refs"]
    for key in (
        "site_selection",
        "execution_plan",
        "planned_state",
        "render_layers",
        "delivery_manifest",
    ):
        ref = ArtifactRef(**refs[key])
        manifest_json = store.read_manifest(ref)
        payload = store.retrieve(ref)
        assert manifest_json["checksum"] == ref.checksum
        assert manifest_json["semantic_checksum"] == ref.semantic_checksum
        assert manifest_json["checksum"]
        assert payload is not None

    planned_refs = [
        ref
        for ref in store.list_by_module("execute", session_id)
        if ref.artifact_type == "PlannedState"
    ]
    assert len(planned_refs) == 1
    assert planned_refs[0].artifact_id == refs["planned_state"]["artifact_id"]
    assert planned_refs[0].checksum == refs["planned_state"]["checksum"]

    static_preview = result["render_artifacts"]["static_preview"]
    interactive_map = result["render_artifacts"]["interactive_map"]
    assert static_preview["status"] == "completed"
    assert interactive_map["status"] == "completed"
    assert Path(static_preview["path"]).is_file()
    assert Path(interactive_map["path"]).is_file()

    manager.remove_session(session_id)
