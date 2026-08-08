"""Backend pytest bootstrap when tests run from the backend directory."""

import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# pytest's rootdir is selected from backend/pytest.ini even when the command
# is launched from the repository root.  Fixture discovery must therefore not
# depend on the caller's current directory.
pytest_plugins = ["tests.fixtures.db"]


def pytest_collection_modifyitems(items):
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
