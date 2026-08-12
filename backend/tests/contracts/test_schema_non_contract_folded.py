"""Guardrail: schema types/output/provenance/layers are folded into blueprint homes.

After Phase 5-T8, the former ``app.modules.schema`` subtrees must not be referenced
from anywhere under ``app/``:

- ``schema.types``        → ``app.data.model`` (canonical, spatial_types, ...)
- ``schema.output``       → ``app.infrastructure.export`` + ``app.infrastructure.rendering``
- ``schema.provenance``   → ``app.data.model.audit``
- ``schema.layers``       → ``app.workflow.layers.layers``

This test scans every ``.py`` under ``app/`` and asserts none of the folded module
paths appear (in imports, docstrings, or comments).
"""

import pathlib


FORBIDDEN = (
    "schema.types",
    "schema.output",
    "schema.provenance",
    "schema.layers",
)


def test_schema_non_contract_folded():
    root = pathlib.Path("app")
    offenders = []
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for fragment in FORBIDDEN:
            if fragment in text:
                offenders.append(f"{p}: contains {fragment!r}")
    assert not offenders, f"folded schema subtrees still referenced: {offenders}"
