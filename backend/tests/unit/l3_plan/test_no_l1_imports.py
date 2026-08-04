"""Guardrail: the L3 PLAN package must not import L1's analysis_node.

Wave E spec requires L3 to be an independent subgraph. Any import of
app.agent.l1_observe.analysis_node would couple L3 to L1's implementation.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import sys

_SUBMODULES = ("worker", "gate", "review", "aggregate")


def _all_package_modules():
    pkg = importlib.import_module("app.agent.l3_plan")
    mods = [pkg]
    for sub in _SUBMODULES:
        mods.append(importlib.import_module(f"app.agent.l3_plan.{sub}"))
    for name in list(sys.modules):
        if name.startswith("app.agent.l3_plan") and sys.modules[name] not in mods:
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
        if ref.startswith("app.agent.l1_observe") or ref.startswith("l1_observe"):
            yield ref


def test_l3_plan_package_never_imports_l1_observe():
    for mod in _all_package_modules():
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            for ref in _forbidden_import_refs(node):
                raise AssertionError(
                    f"{mod.__name__} contains forbidden import {ref!r}"
                )


def test_importing_l3_plan_does_not_load_l1_observe():
    before = {name for name in sys.modules if name.startswith("app.agent.l1_observe")}
    for mod in _all_package_modules():
        assert mod is not None
    after = {name for name in sys.modules if name.startswith("app.agent.l1_observe")}
    assert after == before
