"""Guardrails: folded modules.ports / modules.prompts must stay folded."""

from __future__ import annotations

import pathlib


def _offenders_for(substring: str) -> list[str]:
    root = pathlib.Path("app")
    offenders = [
        str(p)
        for p in root.rglob("*.py")
        if substring in p.read_text(encoding="utf-8")
    ]
    return sorted(offenders)


def test_no_modules_ports_import() -> None:
    offenders = _offenders_for("app.modules.ports")
    assert not offenders, f"app.modules.ports still referenced: {offenders}"


def test_no_modules_prompts_import() -> None:
    offenders = _offenders_for("app.modules.prompts")
    assert not offenders, f"app.modules.prompts still referenced: {offenders}"
