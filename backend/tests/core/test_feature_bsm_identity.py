from __future__ import annotations

from types import SimpleNamespace

from rdflib import Literal

from app.contracts.domain.l1_contracts import L1LocationFact
from app.contracts.evidence.source_semantic_contracts import SourceFeatureSemanticDecision
from app.data.model.canonical import (
    VillageBundle,
    VillageMetadata,
    from_bundle_dict,
    to_bundle_dict,
)
from app.data.model.spatial_types import CurrentAnnotation
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
from app.infrastructure.kg.builder import KGBuilder
from app.infrastructure.kg.ontology import PLN
from app.spatial.grounding.village_cluster_mapper import build_village_clusters


def _annotation() -> CurrentAnnotation:
    return CurrentAnnotation(
        geometry={"type": "Point", "coordinates": [116.0, 24.8]},
        text="祠",
        category="现状设施点",
        _raw={"source_feature_id": "fixture:annotation:1"},
    )


def test_generated_feature_bsm_survives_kg_evidence_and_bundle_restore() -> None:
    bundle = VillageBundle(
        village_name="金田村",
        metadata=VillageMetadata(adcode_12="441426110000"),
    )
    first = _annotation()
    bundle.add(first)

    assert first.bsm == "44142611000000000001"
    assert len(first.bsm) == 20

    kg = KGBuilder.build("金田村", bundle)
    facility_refs = list(kg.g.subjects(PLN.bsm, Literal(first.bsm)))
    assert facility_refs
    # Raw one-character labels remain raw in the base KG.  The semantic
    # classifier, not ingestion, owns any later "祠" -> "祠堂" decision.
    assert any(str(kg.g.value(ref, PLN.name) or "") == "祠" for ref in facility_refs)

    fact = L1LocationFact(
        mention="祠堂",
        normalized_name="祠堂",
        role="facility",
        aliases=["祠堂"],
        source_span="现状设施 | 祠堂 | 金田村",
        spatial_hint="金田村",
        source_report_ref="report:test",
        dimension_key="historical_culture",
        confidence=1.0,
    )
    context = SimpleNamespace(
        session_id="feature-bsm-test",
        version=1,
        kg_version=1,
        kg=kg,
        workspace=bundle,
        location_facts=[fact],
        current_parcels=lambda: [],
    )
    unresolved = PlaceEvidenceIndex.build(context).resolve_mention(
        "祠堂", role="facility", hints="金田村"
    )
    assert unresolved.status == "ambiguous"

    semantic_decisions = {
        "fixture:annotation:1": SourceFeatureSemanticDecision(
            source_feature_id="fixture:annotation:1",
            raw_label="祠",
            semantic_type="祠堂",
            status="accepted",
            authority="inferred_current",
            candidate_ref="l1:fixture:hall:entity",
            supporting_fact_refs=["report:test"],
        )
    }
    result = PlaceEvidenceIndex.build(
        context,
        semantic_decisions=semantic_decisions,
    ).resolve_mention("祠堂", role="facility", hints="金田村")
    assert result.status == "resolved"
    assert result.candidates[0].feature_bsm == first.bsm
    assert result.candidates[0].geometry_ref == f"bundle://feature/{first.bsm}"

    restored = from_bundle_dict(to_bundle_dict(bundle))
    restored.add(_annotation())
    bsms = [item.bsm for item in restored.points.get("annotations_current")]
    assert bsms == ["44142611000000000001", "44142611000000000002"]


def test_spatial_candidate_indexes_are_input_order_invariant() -> None:
    parcels = [
        SimpleNamespace(
            bsm=f"P{i}",
            dlbm="1340",
            area_sqm=100.0,
            geometry={"type": "Point", "coordinates": list(point)},
        )
        for i, point in enumerate(((116.0, 24.80), (116.0, 24.82), (116.02, 24.80)))
    ]

    def signature(items):
        return [
            (cluster.index, tuple(sorted(cluster.bsms)), cluster.centroid)
            for cluster in build_village_clusters(items)
        ]

    assert signature(parcels) == signature(list(reversed(parcels)))
