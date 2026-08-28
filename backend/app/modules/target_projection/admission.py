"""Target admission policy entry point."""

from .validation import evaluate_target_projection_gate


def admit_target_projection(result, *, run_id: str = "", context_version: str = ""):
    return evaluate_target_projection_gate(
        result,
        run_id=run_id,
        context_version=context_version,
    )


__all__ = ["admit_target_projection", "evaluate_target_projection_gate"]
