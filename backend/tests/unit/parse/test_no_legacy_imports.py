"""Guardrail: the PARSE package must not import the legacy select.parse_agent.

Wave F requires the top-level PARSE subgraph to be bridge-layer isolated.
Any import of app.agent.select (or app.agent.select.parse_agent) would couple
PARSE back to the legacy orchestrator.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import sys

_SUBMODULES = ("compile_node", "route_node", "merge_node", "gate_node", "aggregate", "review")


def _all_package_modules():
    pkg = importlib.import_module("app.agent.parse")
    mods = [pkg]
    for sub in _SUBMODULES:
        mods.append(importlib.import_module(f"app.agent.parse.{sub}"))
    for name in list(sys.modules):
        if name.startswith("app.agent.parse") and sys.modules[name] not in mods:
            mods.append(sys.modules[name])
    return mods


def _forbidden_import_refs(node):
    refs = []
    if isinstance(node, ast.Import):
        refs.extend(a.name for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        refs.append(node.module)
        refs.extend(a.name for a in node.names)
    for ref in refs:
        if ref.startswith("app.agent.select") or ref.startswith("app.agent.select.parse_agent"):
            yield ref


def test_parse_package_never_imports_legacy_parse_agent():
    for mod in _all_package_modules():
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            for ref in _forbidden_import_refs(node):
                raise AssertionError(
                    f"{mod.__name__} contains forbidden import {ref!r}"
                )


def test_importing_parse_does_not_load_select_parse_agent():
    before = {name for name in sys.modules if name.startswith("app.agent.select")}
    for mod in _all_package_modules():
        assert mod is not None
    after = {name for name in sys.modules if name.startswith("app.agent.select")}
    assert after == before
