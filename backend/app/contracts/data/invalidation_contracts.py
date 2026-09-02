"""Immutable DATA dependency graph and invalidation plan contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DependencyNodeKind = Literal[
    "source",
    "normalized",
    "representation",
    "capability",
    "catalog",
]


class DataDependencyNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    node_ref: str = Field(min_length=1)
    node_kind: DependencyNodeKind
    digest: str = ""
    depends_on: tuple[str, ...] = ()


class DataDependencyGraph(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_digest: str
    nodes: tuple[DataDependencyNode, ...] = ()
    graph_digest: str


class DataChangeSet(BaseModel):
    """Immutable DATA publication for changes in DATA-owned products.

    Cross-module consumers intentionally do not appear here.  The unified
    Dependency Runtime consumes this publication and decides which World
    Model, Evidence, or Ground rows become stale.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    previous_graph_digest: str = ""
    current_graph_digest: str
    changed_nodes: tuple[str, ...] = ()
    affected_data_nodes: tuple[str, ...] = ()
    conservative: bool = False
    reason_codes: tuple[str, ...] = ()


__all__ = ["DataChangeSet", "DataDependencyGraph", "DataDependencyNode", "DependencyNodeKind"]
