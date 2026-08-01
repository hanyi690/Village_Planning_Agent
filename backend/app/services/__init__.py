"""Services module exports."""
from typing import Any

__all__ = ["RagService"]

_LAZY = {
    "RagService": "app.modules.rag.service",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        import importlib
        mod = importlib.import_module(_LAZY[name], __package__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
