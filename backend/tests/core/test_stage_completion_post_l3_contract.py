from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2] / "app" / "workflow" / "stages"


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def _literal_dict_keys(tree: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys.update(
            key.value
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        )
    return keys


def test_post_l3_stages_use_the_shared_completion_boundary() -> None:
    for name, output_keys in {
        "validate.py": {"validation_report"},
        "reconcile.py": {"reconciliation_report"},
        "deliver.py": {
            "delivery_manifest",
            "render_layers",
            "delivery_spatial_snapshot",
            "export_result",
            "render_artifacts",
        },
    }.items():
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        assert len(_calls(tree, "stage_completion_patch")) == 1, name
        assert len(_calls(tree, "persist_stage_artifact")) >= len(output_keys), name
        assert not {"artifact_refs", "validate_gate", "reconcile_gate", "deliver_gate"}.intersection(
            _literal_dict_keys(tree)
        ), name


def test_post_l3_completion_call_passes_refs_and_gate() -> None:
    for name in ("validate.py", "reconcile.py", "deliver.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        call = _calls(tree, "stage_completion_patch")[0]
        keyword_names = {keyword.arg for keyword in call.keywords}
        assert {"output_refs", "gate", "context_patch", "retry_patch"} <= keyword_names, name

