"""Unit tests for the resolution coverage audit helper."""

from types import SimpleNamespace

from app.evidence.index.resolution_coverage import resolution_coverage


def _fact(name: str, role: str = "village"):
    return SimpleNamespace(normalized_name=name, mention=name, role=role)


def test_empty_context_yields_zero_total():
    cov = resolution_coverage(SimpleNamespace(evidence_graph=None, location_facts=[]))
    assert cov.total == 0
    assert cov.rate == 0.0
    assert cov.extent_rate == 0.0


def test_unresolved_facts_tally_unresolved():
    cov = resolution_coverage(SimpleNamespace(
        evidence_graph=None,
        location_facts=[_fact("甲村"), _fact("乙村")],
    ))
    assert cov.total == 2
    assert cov.unresolved == 2
    assert cov.resolved == 0


def test_resolved_entity_extent_and_geometry_classification():
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    class _Index:
        def __init__(self, results):
            self.results = results

        def resolve_mention(self, name, role="unknown"):
            return self.results[name]

    resolved_entity = SimpleNamespace(
        status="resolved",
        candidates=[SimpleNamespace(
            source_bsms=["bsm-1"], entity_ref="pln:cluster_1", geometry_ref=None,
        )],
    )
    resolved_extent = SimpleNamespace(
        status="resolved",
        candidates=[SimpleNamespace(
            source_bsms=["bsm-2"], entity_ref="", geometry_ref=None,
        )],
    )
    geometry_only = SimpleNamespace(
        status="resolved",
        candidates=[SimpleNamespace(
            source_bsms=[], entity_ref="pln:road_1", geometry_ref="POINT(113 23)",
        )],
    )
    unresolved = SimpleNamespace(status="unresolved", candidates=[])

    context = SimpleNamespace(
        evidence_graph=None,
        location_facts=[
            _fact("甲村"),
            _fact("乙村", "facility"),
            _fact("丙路", "road"),
            _fact("丁地"),
        ],
    )
    context.evidence_graph = EvidenceGraph(
        context,
        index=SimpleNamespace(
            resolve_mention=lambda name, role="unknown", hints="": {
                "甲村": resolved_entity,
                "乙村": resolved_extent,
                "丙路": geometry_only,
                "丁地": unresolved,
            }[name]
        ),
    )
    cov = resolution_coverage(context)
    assert cov.total == 4
    assert cov.resolved_entity == 1
    assert cov.resolved_extent == 1
    assert cov.entity_geometry == 1
    assert cov.unresolved == 1
    assert cov.resolved == 3
    assert cov.rate == 0.75
    assert cov.extent_rate == 0.5
    assert cov.by_role["road"]["entity_geometry"] == 1


def test_ambiguous_result_counts_unresolved():
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    ambiguous = SimpleNamespace(
        status="ambiguous",
        candidates=[SimpleNamespace(
            source_bsms=[], entity_ref="", geometry_ref=None,
        )],
    )
    cov = resolution_coverage(SimpleNamespace(
        evidence_graph=EvidenceGraph(
            SimpleNamespace(),
            index=SimpleNamespace(
                resolve_mention=lambda name, role="unknown": ambiguous
            ),
        ),
        location_facts=[_fact("甲村")],
    ))
    assert cov.total == 1
    assert cov.unresolved == 1
