from types import SimpleNamespace

from app.contracts.domain.l1_contracts import L1Fact, L1LocationFact
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex


def _index(context: object | None = None) -> PlaceEvidenceIndex:
    return PlaceEvidenceIndex(
        context or SimpleNamespace(session_id="test"),
        version=(1, 1),
    )


def test_location_fact_without_fact_id_stays_a_place_entry_without_synthetic_identity():
    index = _index()

    index._register_from_l1_fact(
        L1LocationFact(
            mention="祠堂",
            normalized_name="祠堂",
            role="facility",
        )
    )

    assert len(index.entries) == 1
    entry = index.entries[0]
    assert entry.canonical_name == "祠堂"
    assert entry.entity_refs == []
    assert entry.l1_fact_refs == []


def test_canonical_fact_id_stays_in_fact_refs_without_replacing_spatial_identity():
    source_feature = SimpleNamespace(
        bsm="road-bsm-1",
        geometry={
            "type": "LineString",
            "coordinates": [[113.1, 23.1], [113.2, 23.2]],
        },
        _raw={"source_feature_id": "source:road:1"},
    )
    context = SimpleNamespace(
        session_id="test",
        workspace=SimpleNamespace(
            points={},
            lines={"roads_current": [source_feature]},
            polygons={},
        ),
    )
    index = _index(context)

    index._register_from_l1_fact(
        L1Fact(
            fact_id="l1:fact:road",
            statement="现状有一条村道",
            fact_kind="spatial_observation",
            semantic_type="road",
            attributes={"normalized_name": "村道", "role": "road"},
            source_refs=["report:traffic"],
            source_feature_ids=["source:road:1"],
        )
    )

    assert len(index.entries) == 1
    entry = index.entries[0]
    assert entry.entity_refs == ["l1_source_feature:source:road:1"]
    assert entry.l1_fact_refs == ["report:traffic", "l1:fact:road"]
    assert entry.geometry_ref == "bundle://feature/road-bsm-1"
    assert entry.feature_bsm == "road-bsm-1"
    assert entry.source_bsm == "road-bsm-1"
