"""GROUND business module with lazy public exports."""

__all__ = ["GroundApplication", "GroundRunRequest", "GroundRunResult", "run_ground", "ground_aggregate"]


def __getattr__(name: str):
    if name in __all__:
        from .application import GroundApplication, GroundRunRequest, GroundRunResult, ground_aggregate, run_ground
        return {
            "GroundApplication": GroundApplication,
            "GroundRunRequest": GroundRunRequest,
            "GroundRunResult": GroundRunResult,
            "run_ground": run_ground,
            "ground_aggregate": ground_aggregate,
        }[name]
    raise AttributeError(name)
