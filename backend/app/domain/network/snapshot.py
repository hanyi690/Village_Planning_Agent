"""Typed, replayable network metadata contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NetworkRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    network_id: str = Field(min_length=1)
    source_binding: str = ""
    crs: str = ""
    metric_crs: str = ""
    version: str = ""
    digest: str = ""
    source_refs: tuple[str, ...] = ()
    availability: Literal["ready", "pending", "blocked"] = "pending"

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def readiness(self) -> Literal["ready", "pending", "blocked"]:
        if (
            not self.source_binding
            or not self.crs
            or not self.metric_crs
            or not self.version
            or not self.digest
            or not self.source_refs
        ):
            return "blocked"
        return self.availability


class NetworkNodeRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str = Field(min_length=1)


class NetworkEdgeRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    edge_id: str = Field(min_length=1)
    from_node: str = Field(min_length=1)
    to_node: str = Field(min_length=1)


class NetworkSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    network_ref: NetworkRef
    crs: str = Field(min_length=1)
    metric_crs: str = Field(min_length=1)
    nodes: tuple[NetworkNodeRef, ...] = ()
    edges: tuple[NetworkEdgeRef, ...] = ()
    time_slice: str = ""
    source_binding: str = ""
    availability: Literal["ready", "pending", "blocked"] = "pending"
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot(self) -> "NetworkSnapshot":
        diagnostics = set(self.diagnostics)
        if not self.nodes:
            diagnostics.add("network_nodes_missing")
        if not self.edges:
            diagnostics.add("network_edges_missing")
        if not self.source_binding:
            diagnostics.add("network_source_binding_missing")
        if self.network_ref.source_binding != self.source_binding:
            diagnostics.add("network_source_binding_mismatch")
        if self.network_ref.crs != self.crs or self.network_ref.metric_crs != self.metric_crs:
            diagnostics.add("network_crs_mismatch")
        if self.network_ref.readiness != "ready":
            diagnostics.add("network_ref_incomplete")
        node_ids = {item.node_id for item in self.nodes}
        for edge in self.edges:
            if edge.from_node not in node_ids:
                diagnostics.add(f"network_edge_from_node_missing:{edge.edge_id}")
            if edge.to_node not in node_ids:
                diagnostics.add(f"network_edge_to_node_missing:{edge.edge_id}")
        body = {
            "nodes": [item.model_dump(mode="json") for item in self.nodes],
            "edges": [item.model_dump(mode="json") for item in self.edges],
        }
        expected_digest = "sha256:" + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.network_ref.digest != expected_digest:
            diagnostics.add("network_digest_mismatch")
        object.__setattr__(self, "diagnostics", tuple(sorted(diagnostics)))
        if self.availability == "ready" and diagnostics:
            object.__setattr__(self, "availability", "blocked")
        return self

    @property
    def readiness(self) -> Literal["ready", "pending", "blocked"]:
        return self.availability

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_network_snapshot(
    network_id: str,
    *,
    nodes: Iterable[NetworkNodeRef],
    edges: Iterable[NetworkEdgeRef],
    crs: str,
    metric_crs: str,
    version: str = "",
    source_binding: str = "",
    source_refs: Iterable[str] = (),
    time_slice: str = "",
) -> NetworkSnapshot:
    node_rows = tuple(sorted(nodes, key=lambda item: item.node_id))
    edge_rows = tuple(sorted(edges, key=lambda item: item.edge_id))
    body = {"nodes": [item.model_dump(mode="json") for item in node_rows], "edges": [item.model_dump(mode="json") for item in edge_rows]}
    digest = "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    refs = tuple(sorted(set(source_refs)))
    ref = NetworkRef(
        network_id=network_id,
        source_binding=source_binding,
        crs=crs,
        metric_crs=metric_crs,
        version=version,
        digest=digest,
        source_refs=refs,
        availability="ready",
    )
    return NetworkSnapshot(network_ref=ref, crs=crs, metric_crs=metric_crs, nodes=node_rows, edges=edge_rows, time_slice=time_slice, source_binding=source_binding, availability="ready")


def network_readiness(value: object, expected_ref: str = "") -> tuple[str, tuple[str, ...]]:
    """Return a fail-closed readiness result for typed or legacy graph inputs."""

    if isinstance(value, NetworkSnapshot):
        diagnostics = tuple(value.diagnostics)
        network_id = value.network_ref.network_id
        if expected_ref and network_id != expected_ref:
            diagnostics = (*diagnostics, "network_ref_mismatch")
        return value.readiness, tuple(sorted(set(diagnostics)))
    try:
        from app.spatial.network.network_graph import NetworkGraphSnapshot
    except ImportError:
        NetworkGraphSnapshot = ()  # type: ignore[assignment]
    if isinstance(value, NetworkGraphSnapshot):
        diagnostics: set[str] = set()
        if expected_ref and value.network_ref != expected_ref:
            diagnostics.add("network_ref_mismatch")
        if not value.source_binding:
            diagnostics.add("network_source_binding_missing")
        if not value.crs or not value.metric_crs:
            diagnostics.add("network_crs_missing")
        if not value.version:
            diagnostics.add("network_version_missing")
        if not value.digest or value.digest != f"sha256:{value.fingerprint}":
            diagnostics.add("network_digest_mismatch")
        if not value.source_refs:
            diagnostics.add("network_source_refs_missing")
        node_ids = {item.node_id for item in value.nodes}
        if not value.nodes:
            diagnostics.add("network_nodes_missing")
        if not value.edges:
            diagnostics.add("network_edges_missing")
        for edge in value.edges:
            if edge.from_node not in node_ids:
                diagnostics.add(f"network_edge_from_node_missing:{edge.edge_id}")
            if edge.to_node not in node_ids:
                diagnostics.add(f"network_edge_to_node_missing:{edge.edge_id}")
        return (
            "ready" if not diagnostics else "blocked",
            tuple(sorted(diagnostics)),
        )
    network_id = str(getattr(value, "network_ref", "") or "")
    nodes = tuple(getattr(value, "nodes", None) or ())
    edges = tuple(getattr(value, "edges", None) or ())
    if expected_ref and network_id != expected_ref:
        return "blocked", ("network_ref_mismatch",)
    if not network_id or not nodes or not edges or not str(getattr(value, "fingerprint", "") or ""):
        return "blocked", ("legacy_network_snapshot_incomplete",)
    return "blocked", ("legacy_network_snapshot_untyped",)


__all__ = [
    "NetworkEdgeRef",
    "NetworkNodeRef",
    "NetworkRef",
    "NetworkSnapshot",
    "build_network_snapshot",
    "network_readiness",
]
