"""L3 PLAN business module with lazy public exports."""

__all__ = ["L3Application", "L3RunRequest", "L3RunResult", "run_l3"]


def __getattr__(name: str):
    if name in __all__:
        from .application import L3Application, L3RunRequest, L3RunResult, run_l3
        return {
            "L3Application": L3Application,
            "L3RunRequest": L3RunRequest,
            "L3RunResult": L3RunResult,
            "run_l3": run_l3,
        }[name]
    raise AttributeError(name)
