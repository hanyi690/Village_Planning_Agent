"""Guardrail: PARSE and spec_mapper must not import advisory_crosswalks.

Wave F keeps the parsing stack decoupled from the advisory crosswalk data
service. Any import of advisory_crosswalks would couple PARSE to the legacy
advisory layer.
"""
from __future__ import annotations

import ast
import pathlib

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[3] / "app"
_PARSE_DIR = _PACKAGE_ROOT / "agent" / "parse"
_SPEC_MAPPER = _PACKAGE_ROOT / "modules" / "parsing" / "compiler" / "spec_mapper.py"


def _target_files():
    files = sorted(_PARSE_DIR.glob("*.py"))
    files.append(_SPEC_MAPPER)
    return files


def _forbidden_import_refs(node):
    refs = []
    if isinstance(node, ast.Import):
        refs.extend(a.name for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        refs.append(node.module)
        refs.extend(a.name for a in node.names)
    for ref in refs:
        if "advisory_crosswalks" in ref:
            yield ref


def test_parse_and_spec_mapper_never_import_advisory_crosswalks():
    for file in _target_files():
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for ref in _forbidden_import_refs(node):
                raise AssertionError(
                    f"{file} contains forbidden import {ref!r}"
                )
