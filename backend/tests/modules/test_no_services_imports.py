"""Architecture guard: no module may import from app.services.

Modules depend on Port Protocols (or the neutral ports registry), not the
concrete services layer. Reverse imports from ``modules -> services`` are a
dependency-direction violation.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = BACKEND_ROOT / "app" / "modules"


def test_no_module_imports_services():
    violations = []
    for root, dirs, files in os.walk(MODULES_DIR):
        for f in files:
            if not f.endswith(".py"):
                continue
            filepath = os.path.join(root, f)
            with open(filepath, "r", encoding="utf-8") as fh:
                source = fh.read()
            if "from app.services" in source:
                violations.append(filepath)
    assert not violations, (
        "modules may not import from app.services:\n" + "\n".join(violations)
    )