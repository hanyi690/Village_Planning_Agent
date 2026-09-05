"""DATA dependency graph construction and downstream invalidation."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from threading import RLock
from typing import Any

from app.contracts.data.invalidation_contracts import (
    DataChangeSet,
    DataDependencyGraph,
    DataDependencyNode,
)


_DEPENDENCY_GRAPH_CACHE_LIMIT = 64
_DEPENDENCY_GRAPH_CACHE_LOCK = RLock()
_DEPENDENCY_GRAPH_CACHE: OrderedDict[str, DataDependencyGraph] = OrderedDict()


def _digest(value: Any) -> str:
    if not value:
        return ""
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _item_digest(item: Any, field: str = "") -> str:
    declared = str(getattr(item, field, "") or "").strip() if field else ""
    return declared or _digest(item)


def build_data_dependency_graph(
    catalog: Any,
) -> DataDependencyGraph:
    """Build a deterministic graph of DATA-owned products only."""

    snapshot = getattr(catalog, "snapshot", catalog)
    catalog_digest = str(getattr(snapshot, "digest", "") or _digest(snapshot))
    if catalog_digest:
        with _DEPENDENCY_GRAPH_CACHE_LOCK:
            cached = _DEPENDENCY_GRAPH_CACHE.get(catalog_digest)
            if cached is not None:
                _DEPENDENCY_GRAPH_CACHE.move_to_end(catalog_digest)
                return cached
    nodes: list[DataDependencyNode] = [
        DataDependencyNode(node_ref="data:catalog", node_kind="catalog", digest=catalog_digest),
    ]
    resource_dependencies: dict[str, list[str]] = {}
    source_representation_refs: list[str] = []
    source_refs: list[str] = []
    representation_refs: list[str] = []
    capability_refs: list[str] = []
    for item in getattr(snapshot, "features", ()) or ():
        ref = f"data:source:{item.dataset_ref}:{item.source_feature_ref}"
        source_refs.append(ref)
        source_representation_refs.append(ref)
        resource_dependencies.setdefault(
            f"{item.dataset_ref}:{item.source_feature_ref}",
            [],
        ).append(ref)
        nodes.append(DataDependencyNode(node_ref=ref, node_kind="source", digest=_item_digest(item, "source_feature_digest"), depends_on=("data:catalog",)))
        normalized_ref = f"data:normalized:{item.dataset_ref}:{item.source_feature_ref}"
        nodes.append(
            DataDependencyNode(
                node_ref=normalized_ref,
                node_kind="normalized",
                # SourceFeature.source_feature_digest already covers the
                # native geometry, normalized geometry, CRS transform and
                # topology audit.  Re-serializing the full coordinate tree
                # here made dependency construction repeat the most expensive
                # DATA hash for every feature.
                digest=_item_digest(item, "source_feature_digest"),
                depends_on=(ref,),
            )
        )
    for item in getattr(snapshot, "representations", ()) or ():
        ref = f"data:representation:{item.representation_ref}"
        representation_refs.append(ref)
        source_representation_refs.append(ref)
        resource_key = str(item.resource_ref or "").removeprefix("resource:")
        if resource_key:
            resource_dependencies.setdefault(resource_key, []).append(ref)
        normalized_ref = f"data:normalized:{item.dataset_ref}:{item.source_feature_ref}"
        nodes.append(DataDependencyNode(node_ref=ref, node_kind="representation", digest=_item_digest(item, "content_digest"), depends_on=(normalized_ref,)))
    for item in getattr(snapshot, "capabilities", ()) or ():
        ref = f"data:capability:{item.capability_ref}"
        capability_refs.append(ref)
        resource_ref = str(item.resource_ref or "")
        if resource_ref:
            dependencies = tuple(sorted(
                resource_dependencies.get(
                    resource_ref.removeprefix("resource:"),
                    (),
                )
            ))
        else:
            # Preserve the previous fail-closed behavior for a malformed
            # capability with no resource: it depended on every source or
            # representation node instead of silently becoming independent.
            dependencies = tuple(sorted(source_representation_refs))
        dependencies = dependencies or ("data:catalog",)
        nodes.append(DataDependencyNode(node_ref=ref, node_kind="capability", digest=_item_digest(item, "content_digest"), depends_on=dependencies))

    node_payload = [node.model_dump(mode="json") for node in sorted(nodes, key=lambda item: item.node_ref)]
    graph_digest = _digest({"catalog_digest": catalog_digest, "nodes": node_payload})
    result = DataDependencyGraph(
        catalog_digest=catalog_digest,
        nodes=tuple(sorted(nodes, key=lambda item: item.node_ref)),
        graph_digest=graph_digest,
    )
    if catalog_digest:
        with _DEPENDENCY_GRAPH_CACHE_LOCK:
            _DEPENDENCY_GRAPH_CACHE[catalog_digest] = result
            _DEPENDENCY_GRAPH_CACHE.move_to_end(catalog_digest)
            while len(_DEPENDENCY_GRAPH_CACHE) > _DEPENDENCY_GRAPH_CACHE_LIMIT:
                _DEPENDENCY_GRAPH_CACHE.popitem(last=False)
    return result


def plan_data_change_set(
    previous: DataDependencyGraph | None,
    current: DataDependencyGraph,
) -> DataChangeSet:
    if previous is None:
        affected = tuple(sorted(node.node_ref for node in current.nodes))
        return DataChangeSet(
            current_graph_digest=current.graph_digest,
            changed_nodes=affected,
            affected_data_nodes=affected,
            conservative=True,
            reason_codes=("no_previous_dependency_graph",),
        )
    old = {node.node_ref: node for node in previous.nodes}
    new = {node.node_ref: node for node in current.nodes}
    changed = set(old) | set(new)
    changed = {ref for ref in changed if old.get(ref) != new.get(ref)}
    if not changed:
        return DataChangeSet(previous_graph_digest=previous.graph_digest, current_graph_digest=current.graph_digest)
    reverse: dict[str, set[str]] = {}
    for node in current.nodes:
        for dependency in node.depends_on:
            reverse.setdefault(dependency, set()).add(node.node_ref)
    stale = set(changed)
    queue = list(changed)
    while queue:
        ref = queue.pop()
        for dependent in reverse.get(ref, ()):
            if dependent not in stale:
                stale.add(dependent)
                queue.append(dependent)
    return DataChangeSet(
        previous_graph_digest=previous.graph_digest,
        current_graph_digest=current.graph_digest,
        changed_nodes=tuple(sorted(changed)),
        affected_data_nodes=tuple(sorted(stale)),
    )


__all__ = ["build_data_dependency_graph", "plan_data_change_set"]
