"""Deterministic reference-graph closure checks for verified decisions."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Literal

from pydantic import Field

from app.contracts.llm.decision_contracts import (
    ClosedSetRef,
    SemanticIssue,
    StrictDecisionModel,
)


class ReferenceGraphNode(StrictDecisionModel):
    """One decision record and the closed-set references it depends on."""

    ref: ClosedSetRef
    dependency_refs: list[ClosedSetRef] = Field(default_factory=list)
    status: Literal["accepted", "quarantined", "pending"] = "accepted"


def _issue(
    *,
    stage: str,
    code: str,
    object_ref: str,
    dependency_refs: Iterable[str] = (),
    fatal_scope: str = "record",
    message: str,
) -> SemanticIssue:
    return SemanticIssue(
        stage=stage,
        code=code,
        severity="error",
        fatal_scope=fatal_scope,
        object_ref=object_ref,
        dependency_refs=sorted(set(dependency_refs)),
        message=message,
    )


def validate_reference_graph(
    nodes: Iterable[ReferenceGraphNode],
    *,
    stage: str = "reference_graph",
) -> list[SemanticIssue]:
    """Return sorted closure findings without mutating graph input.

    The validator deliberately treats references as ``namespace:id`` pairs.
    It can therefore distinguish a missing target from an ID present under the
    wrong namespace, and it never converts either condition into a guess.
    """
    ordered_nodes = sorted(nodes, key=lambda node: node.ref.key)
    by_key: dict[str, ReferenceGraphNode] = {}
    id_namespaces: dict[str, set[str]] = defaultdict(set)
    issues: list[SemanticIssue] = []

    for node in ordered_nodes:
        key = node.ref.key
        id_namespaces[node.ref.ref_id].add(node.ref.namespace)
        if key in by_key:
            issues.append(
                _issue(
                    stage=stage,
                    code="duplicate_reference_id",
                    object_ref=key,
                    dependency_refs=[key],
                    message="reference graph contains more than one node with the same namespace and id",
                )
            )
            continue
        by_key[key] = node

    adjacency: dict[str, list[str]] = defaultdict(list)
    for key, node in sorted(by_key.items()):
        for dependency in sorted(node.dependency_refs, key=lambda ref: ref.key):
            dependency_key = dependency.key
            target = by_key.get(dependency_key)
            if target is None:
                known_namespaces = id_namespaces.get(dependency.ref_id, set())
                code = (
                    "reference_namespace_mismatch"
                    if known_namespaces
                    else "dangling_reference"
                )
                issues.append(
                    _issue(
                        stage=stage,
                        code=code,
                        object_ref=key,
                        dependency_refs=[dependency_key],
                        message=(
                            "reference id exists only in a different namespace"
                            if known_namespaces
                            else "reference graph dependency does not exist"
                        ),
                    )
                )
                continue
            adjacency[key].append(dependency_key)
            if node.status == "accepted" and target.status == "quarantined":
                issues.append(
                    _issue(
                        stage=stage,
                        code="accepted_references_quarantined",
                        object_ref=key,
                        dependency_refs=[dependency_key],
                        fatal_scope="dependency_subgraph",
                        message="an accepted record may not depend on a quarantined record",
                    )
                )

    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()
    cycles: set[tuple[str, ...]] = set()

    def visit(key: str) -> None:
        visited.add(key)
        active.append(key)
        active_set.add(key)
        for dependency_key in sorted(adjacency.get(key, [])):
            if dependency_key in active_set:
                start = active.index(dependency_key)
                cycle = active[start:] + [dependency_key]
                rotations = [tuple(cycle[index:-1] + cycle[:index] + [cycle[index]]) for index in range(len(cycle) - 1)]
                cycles.add(min(rotations))
            elif dependency_key not in visited:
                visit(dependency_key)
        active.pop()
        active_set.remove(key)

    for key in sorted(by_key):
        if key not in visited:
            visit(key)

    for cycle in sorted(cycles):
        issues.append(
            _issue(
                stage=stage,
                code="dependency_cycle",
                object_ref=cycle[0],
                dependency_refs=list(cycle),
                fatal_scope="dependency_subgraph",
                message="reference graph contains a dependency cycle",
            )
        )

    return sorted(issues, key=lambda issue: (issue.code, issue.object_ref, issue.fingerprint))


__all__ = ["ReferenceGraphNode", "validate_reference_graph"]
