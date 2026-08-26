"""Focused tests for deterministic generic reference graph closure."""

from app.contracts.llm.decision_contracts import ClosedSetRef
from app.domain.validation.reference_graph import ReferenceGraphNode, validate_reference_graph


def _node(namespace, ref_id, *, status="accepted", dependencies=()):
    return ReferenceGraphNode(
        ref=ClosedSetRef(namespace=namespace, ref_id=ref_id),
        status=status,
        dependency_refs=[ClosedSetRef(namespace=item[0], ref_id=item[1]) for item in dependencies],
    )


def test_reference_graph_accepts_closed_references_without_findings():
    nodes = [
        _node("claim", "claim-1", dependencies=[("source_segment", "segment-1")]),
        _node("source_segment", "segment-1"),
    ]

    assert validate_reference_graph(nodes) == []


def test_reference_graph_reports_duplicate_dangling_and_namespace_mismatch_deterministically():
    nodes = [
        _node("claim", "claim-1"),
        _node("claim", "claim-1"),
        _node("target", "target-1", dependencies=[("claim", "missing"), ("target", "claim-1")]),
    ]

    findings = validate_reference_graph(nodes, stage="unit")

    assert [item.code for item in findings] == [
        "dangling_reference",
        "duplicate_reference_id",
        "reference_namespace_mismatch",
    ]
    assert findings == validate_reference_graph(list(reversed(nodes)), stage="unit")


def test_reference_graph_reports_cycles_and_accepted_to_quarantined_dependencies():
    nodes = [
        _node("claim", "a", dependencies=[("claim", "b")]),
        _node("claim", "b", dependencies=[("claim", "a")]),
        _node("target", "target-1", dependencies=[("constraint", "constraint-1")]),
        _node("constraint", "constraint-1", status="quarantined"),
    ]

    findings = validate_reference_graph(nodes)

    assert {item.code for item in findings} == {"dependency_cycle", "accepted_references_quarantined"}
    cycle = next(item for item in findings if item.code == "dependency_cycle")
    assert cycle.dependency_refs == ["claim:a", "claim:b"]
