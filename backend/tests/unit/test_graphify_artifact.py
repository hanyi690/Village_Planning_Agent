"""Graphify dependency graph artifact verification.

Wave M2: produces a deterministic AST-based dependency graph of
backend/app/ as a review-package artifact. The graph is generated
from the existing _import_graph.py AST scanner (no LLM cost).
"""

import json
import pathlib

import pytest


def test_dependency_graph_artifact_exists():
    """Verify the AST-based dependency graph can be generated and is valid JSON."""
    from tests.unit._import_graph import build_imports

    imports = build_imports()
    assert isinstance(imports, dict)
    assert len(imports) > 0

    # Verify the graph contains the new Wave M1/M2 modules
    bootstrap_files = [f for f in imports if "agent/bootstrap/" in f]
    assert any("post_l3_main_nodes" in f for f in bootstrap_files)
    assert any("layer_aggregate_node" in f for f in bootstrap_files)

    # Verify no kg->data reverse dependency remains
    for src, deps in imports.items():
        if src.startswith("app/modules/kg/"):
            for dep in deps:
                assert not dep.startswith("app/modules/data/"), (
                    f"kg->data reverse dep: {src} -> {dep}"
                )

    # Verify no parse_agent.py in the graph (deleted)
    assert not any("parse_agent" in f for f in imports), "parse_agent.py should be deleted"

    # Verify no explore/node.py in the graph (deleted)
    assert not any("explore/node" in f for f in imports), "explore/node.py should be deleted"

    # Serialize as graph JSON (NetworkX-compatible format)
    graph_json = {
        "directed": True,
        "multigraph": False,
        "nodes": [{"id": f} for f in sorted(imports.keys())],
        "adjacency": {
            src: [{"id": dst} for dst in sorted(deps)]
            for src, deps in sorted(imports.items())
        },
        "metadata": {
            "generator": "tests.unit._import_graph.build_imports",
            "wave": "M2",
            "node_count": len(imports),
            "edge_count": sum(len(deps) for deps in imports.values()),
        },
    }

    # Write to graphify-out/ for the review package
    output_dir = pathlib.Path("graphify-out")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "ast_dependency_graph.json"
    output_path.write_text(json.dumps(graph_json, indent=2, ensure_ascii=False), encoding="utf-8")

    assert output_path.exists()
    assert graph_json["metadata"]["node_count"] > 50
    assert graph_json["metadata"]["edge_count"] > 100
