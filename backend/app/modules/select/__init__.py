"""SELECT business module with lazy public exports."""

__all__ = ["SelectApplication", "SelectRunRequest", "SelectRunResult", "run_select"]


def __getattr__(name: str):
    if name in __all__:
        from .application import SelectApplication, SelectRunRequest, SelectRunResult, run_select
        return {
            "SelectApplication": SelectApplication,
            "SelectRunRequest": SelectRunRequest,
            "SelectRunResult": SelectRunResult,
            "run_select": run_select,
        }[name]
    raise AttributeError(name)
