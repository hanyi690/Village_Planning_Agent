"""L2 STRATEGIZE business module with lazy public exports."""

__all__ = ["L2Application", "L2RunRequest", "L2RunResult", "analyze_l2_dimension", "run_l2"]


def __getattr__(name: str):
    if name in __all__:
        from .application import (
            L2Application,
            L2RunRequest,
            L2RunResult,
            analyze_l2_dimension,
            run_l2,
        )
        return {
            "L2Application": L2Application,
            "L2RunRequest": L2RunRequest,
            "L2RunResult": L2RunResult,
            "analyze_l2_dimension": analyze_l2_dimension,
            "run_l2": run_l2,
        }[name]
    raise AttributeError(name)
