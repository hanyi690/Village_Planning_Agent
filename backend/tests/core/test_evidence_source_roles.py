from types import SimpleNamespace


def test_source_role_metadata_separates_geometry_topology_and_context() -> None:
    from app.contracts.evidence.evidence_contracts import EvidenceSource
    from app.evidence.retrieval.evidence_service import _annotate_sources

    sources = _annotate_sources(
        [
            EvidenceSource(source_type="bundle", reference="bundle:landuse"),
            EvidenceSource(source_type="kg", reference="kg:session"),
            EvidenceSource(source_type="report", reference="report:traffic"),
            EvidenceSource(source_type="external", reference="https://example.test"),
        ],
        context=SimpleNamespace(
            data_snapshot=SimpleNamespace(digest="bundle-digest"),
            l1_snapshot_ref="artifact://l1/snapshot",
        ),
    )

    by_type = {source.source_type: source for source in sources}
    assert by_type["bundle"].evidence_role == "spatial_identity"
    assert by_type["bundle"].authority == "geometry_authoritative"
    assert by_type["bundle"].snapshot_ref == "bundle:snapshot:bundle-digest"
    assert "execution_geometry" in by_type["bundle"].supports
    assert by_type["kg"].evidence_role == "spatial_topology"
    assert by_type["kg"].authority == "topology_authoritative"
    assert by_type["report"].evidence_role == "planning_background"
    assert by_type["report"].authority == "document_context"
    assert by_type["external"].authority == "advisory"
    assert "location_binding" not in by_type["external"].supports
