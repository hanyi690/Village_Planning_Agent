"""TARGET_PROJECTION business module with lazy public exports."""

__all__ = [
    "TargetProjectionApplication",
    "TargetProjectionRunRequest",
    "TargetProjectionRunResult",
    "run_target_projection",
]


def __getattr__(name: str):
    if name in __all__:
        from .application import (
            TargetProjectionApplication,
            TargetProjectionRunRequest,
            TargetProjectionRunResult,
            run_target_projection,
        )
        return {
            "TargetProjectionApplication": TargetProjectionApplication,
            "TargetProjectionRunRequest": TargetProjectionRunRequest,
            "TargetProjectionRunResult": TargetProjectionRunResult,
            "run_target_projection": run_target_projection,
        }[name]
    raise AttributeError(name)
