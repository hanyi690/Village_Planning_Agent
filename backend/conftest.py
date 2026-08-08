"""Backend pytest bootstrap when tests run from the backend directory."""

import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if Path.cwd().resolve() == BACKEND_ROOT.resolve():
    pytest_plugins = ["tests.fixtures.db"]


def pytest_collection_modifyitems(items):
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
