from __future__ import annotations

import json
from pathlib import Path

from app.contracts.ports.planning_ports import PlanningPorts
from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.planning_semantics import RoadPlanningParameters
from app.contracts.spatial.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
)
from app.data.ingestion.adapters import ADAPTERS
from app.data.model.canonical import VillageBundle
from app.infrastructure.kg.adapters.spatial_query_adapter import KGSpatialQueryAdapter
from app.infrastructure.kg.builder import KGBuilder
from app.infrastructure.kg.ontology import GeoPredicates, PLN
from app.spatial.grounding.resolver import SpatialResolver
from app.spatial.model.workspace import SpatialWorkspace
from app.infrastructure.context.planning_context import PlanningContext
from app.domain.ground.aggregate import ground_aggregate
from app.domain.program.assembler import assemble_planning_program
from app.domain.program.target_projection.aggregate import project_program


ROOT = Path(__file__).resolve().parents[3]
ROAD_PATH = ROOT / "data/gis/jintian/current/road.geojson"


def _source_road_bundle() -> VillageBundle:
    from app.data.model.layer_registry import GIS_LAYER_REGISTRY

    bundle = VillageBundle(village_name="金田")
    payload = json.loads(ROAD_PATH.read_text(encoding="utf-8"))
    entry = GIS_LAYER_REGISTRY["current_road"]
    result = ADAPTERS[entry.ingest.adapter].load(
        payload,
        entry,
        source_uri=ROAD_PATH.resolve().as_uri(),
    )
    for feature in result.features:
        bundle.add(feature)
    return bundle


def test_real_source_road_line_reaches_ground_without_parcel_union() -> None:
    bundle = _source_road_bundle()
    source_feature = bundle.lines.get("roads_current")[0]
    source_id = source_feature._raw["source_feature_id"]

    kg = KGBuilder.build("金田", bundle)
    road_uri = next(
        subject
        for subject in kg.g.subjects(PLN.source_feature_id, None)
        if str(kg.g.value(subject, PLN.source_feature_id)) == source_id
    )
    geometry_node = kg.g.value(road_uri, GeoPredicates.hasGeometry)
    assert geometry_node is not None
    assert str(kg.g.value(geometry_node, GeoPredicates.asWKT)).startswith(
        "MULTILINESTRING"
    )

    spec = SpatialReferenceSpec(
        type="directional",
        target_id="road-source-0",
        spec_id="spatial-ref:road-source-0",
        reference=RefObject(
            kind="entity_type",
            filter={
                "rdf_type": "Road",
                "source_feature_ids": [source_id],
            },
        ),
    )
    workspace = SpatialWorkspace.from_bundle(
        bundle,
        session_id="real-source-line-grounding",
    )
    context = PlanningContext(
        session_id="real-source-line-grounding",
        village_name="金田",
        workspace=workspace,
        kg=kg,
        kg_session_ref="real-source-line-grounding",
        ports=PlanningPorts(spatial_query=KGSpatialQueryAdapter(kg)),
    )

    resolved = SpatialResolver(context).resolve_spec(spec)
    assert resolved.reference_geometry_wkt is not None
    assert resolved.reference_geometry_wkt.startswith("MULTILINESTRING")
    assert resolved.reference_geometries[0].source_ref == source_id

    grounded = ground_aggregate(
        [spec],
        context,
        target_metadata={
            "road-source-0": {
                "target_kind": "road",
                "expected_output_kind": "line",
            }
        },
    )
    assert len(grounded.candidates) == 1
    candidate = grounded.candidates[0]
    assert candidate.geometry is not None
    assert candidate.geometry.kind == "line"
    assert candidate.geometry.granularity == "exact_feature"
    assert candidate.geometry.role == "execution_geometry"
    assert candidate.geometry.source_ref == source_id
    assert candidate.geometry.generation_operation == "grounded_source_feature"
    # ``source_bsms`` is provenance for the road feature itself when the
    # provider supplies BSM; it is not a parcel-union input.  The decisive
    # contract here is exact line granularity plus source-backed WKT.
    assert candidate.geometry.source_bsms == [source_feature.bsm]


def test_real_source_road_id_survives_target_projection_before_ground() -> None:
    bundle = _source_road_bundle()
    source_id = bundle.lines.get("roads_current")[0]._raw["source_feature_id"]
    intervention = PlanningIntervention(
        intervention_id="road-existing-real-source",
        target_id="road-existing-real-source",
        name="现状道路提升",
        category="road",
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        intervention_action="upgrade",
        spatial_requirements={"existing_road_feature_ids": [source_id]},
        road_parameters=RoadPlanningParameters(action="upgrade", length_m=100.0),
    )
    program = assemble_planning_program([intervention], [], claims=[])

    _, specs, gate = project_program(
        program,
        source_features={"road": bundle.lines.get("roads_current")},
    )

    assert gate.passed
    assert len(specs) == 1
    assert specs[0].type == "directional"
    assert specs[0].reference.filter["source_feature_ids"] == [source_id]
