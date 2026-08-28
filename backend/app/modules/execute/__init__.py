"""EXECUTE business module with lazy public exports."""

__all__ = ["ExecuteApplication", "ExecuteRunRequest", "ExecuteRunResult", "run_execute"]


def __getattr__(name: str):
    if name in __all__:
        from .application import ExecuteApplication, ExecuteRunRequest, ExecuteRunResult, run_execute
        return {
            "ExecuteApplication": ExecuteApplication,
            "ExecuteRunRequest": ExecuteRunRequest,
            "ExecuteRunResult": ExecuteRunResult,
            "run_execute": run_execute,
        }[name]
    raise AttributeError(name)
