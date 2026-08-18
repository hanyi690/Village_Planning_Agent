from types import SimpleNamespace

from app.contracts.ports.place_resolution_contracts import PlaceEvidenceEntry
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex


def _entry(entity_ref: str, geometry_ref: str | None) -> PlaceEvidenceEntry:
    return PlaceEvidenceEntry(
        canonical_name="公交站",
        entity_refs=[entity_ref],
        entity_types=["facility"],
        role="facility",
        source_bsms=[entity_ref.rsplit(":", 1)[-1]],
        geometry_ref=geometry_ref,
        provenance=["kg"],
        confidence=0.9,
    )


def _index() -> PlaceEvidenceIndex:
    return PlaceEvidenceIndex(SimpleNamespace(session_id="test"), version=(1, 1))


def test_same_name_different_source_points_remain_ambiguous_candidates():
    index = _index()
    index._add_entry(_entry("kg:facility:1", "POINT (113.1 23.1)"))
    index._add_entry(_entry("kg:facility:2", "POINT (113.2 23.2)"))

    result = index.resolve_mention("公交站", role="facility")

    assert len(index.entries) == 2
    assert {candidate.entity_ref for candidate in result.candidates} == {
        "kg:facility:1",
        "kg:facility:2",
    }
    assert {candidate.geometry_ref for candidate in result.candidates} == {
        "POINT (113.1 23.1)",
        "POINT (113.2 23.2)",
    }
    assert result.status == "ambiguous"
    assert result.selected_entity_ref is None
    assert index.candidate_bsms("公交站") == []


def test_same_name_same_source_geometry_still_merges_evidence():
    index = _index()
    index._add_entry(_entry("kg:facility:1", "POINT (113.1 23.1)"))
    index._add_entry(_entry("kg:facility:1-alias", "kg_wkt:POINT (113.1 23.1)"))

    assert len(index.entries) == 1
    assert index.entries[0].entity_refs == [
        "kg:facility:1",
        "kg:facility:1-alias",
    ]


def test_generic_same_name_entry_does_not_attach_to_first_source_geometry():
    index = _index()
    index._add_entry(_entry("kg:facility:1", "POINT (113.1 23.1)"))
    index._add_entry(_entry("kg:facility:2", "POINT (113.2 23.2)"))
    index._add_entry(_entry("poi:公交站", None))

    assert len(index.entries) == 3
    assert index.entries[-1].entity_refs == ["poi:公交站"]


def test_source_arrival_order_does_not_assign_geometry_to_generic_entry():
    index = _index()
    index._add_entry(_entry("poi:公交站", None))
    index._add_entry(_entry("kg:facility:1", "POINT (113.1 23.1)"))
    index._add_entry(_entry("kg:facility:2", "POINT (113.2 23.2)"))

    assert len(index.entries) == 3
    assert {entry.entity_refs[0] for entry in index.entries} == {
        "poi:公交站",
        "kg:facility:1",
        "kg:facility:2",
    }
