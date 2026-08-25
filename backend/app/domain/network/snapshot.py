"""Typed, replayable network metadata contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NetworkRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    network_id: str = Field(min_length=1)
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
        if not self.version or not self.digest or not self.source_refs:
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
        if self.network_ref.readiness != "ready":
            diagnostics.add("network_ref_incomplete")
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
    ref = NetworkRef(network_id=network_id, version=version, digest=digest, source_refs=tuple(sorted(set(source_refs))), availability="ready")
    return NetworkSnapshot(network_ref=ref, crs=crs, metric_crs=metric_crs, nodes=node_rows, edges=edge_rows, time_slice=time_slice, source_binding=source_binding, availability="ready")
