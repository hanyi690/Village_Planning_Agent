"""Repository-level pytest bootstrap."""

import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest_plugins = ["tests.fixtures.db"]


def pytest_collection_modifyitems(items):
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
        elif "/tests/acceptance/" in path:
            item.add_marker(pytest.mark.acceptance)
        elif "/tests/characterization/" in path:
            item.add_marker(pytest.mark.characterization)
        elif "/tests/contracts/" in path:
            item.add_marker(pytest.mark.contracts)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/tests/core/" in path:
            item.add_marker(pytest.mark.unit)
