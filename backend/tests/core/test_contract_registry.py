"""Guard the cross-module contract index and structured-output boundary."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path


def test_registry_has_one_identity_for_each_production_boundary() -> None:
    from app.contracts.registry import CONTRACT_REGISTRY, contract_context

    required = {
        "l1.observe",
        "l1.report",
        "l2.decision",
        "l2.report",
        "l3.claims",
        "l3.report",
        "ground.candidate_selection",
        "artifact.delivery_manifest",
        "api.public_event",
        "api.map_layers",
    }
    assert required <= set(CONTRACT_REGISTRY)
    assert len(CONTRACT_REGISTRY) == len({item.key for item in CONTRACT_REGISTRY.values()})
    assert contract_context("l3.claims")["contract_version"] == "2"


def test_registered_model_paths_resolve() -> None:
    from app.contracts.registry import CONTRACT_REGISTRY

    failures: list[str] = []
    for key, registration in CONTRACT_REGISTRY.items():
        module_name, attribute_name = registration.model_path.split(":", 1)
        try:
            module = import_module(module_name)
            getattr(module, attribute_name)
        except Exception as exc:
            failures.append(f"{key}: {type(exc).__name__}: {exc}")
    assert failures == []


def test_provider_structured_calls_have_one_runtime_boundary() -> None:
    root = Path(__file__).resolve().parents[2] / "app"
    direct = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "chat.completions.create" in text:
            direct.append(path.relative_to(root).as_posix())
    assert direct == ["infrastructure/llm/structured.py"]


def test_production_structured_calls_declare_a_contract_key() -> None:
    root = Path(__file__).resolve().parents[2] / "app"
    missing: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "structured.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = ""
            if isinstance(function, ast.Name):
                name = function.id
            elif isinstance(function, ast.Attribute):
                name = function.attr
            if name not in {"run_structured_output", "run_structured_output_sync"}:
                continue
            if not any(keyword.arg == "contract_key" for keyword in node.keywords):
                missing.append(f"{path.relative_to(root)}:{node.lineno}")
    assert missing == []
