"""Common schema validation boundary for structured provider output."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_output(model_type: type[ModelT], value: Any) -> ModelT:
    """Validate one provider result without adding stage-specific semantics."""

    return model_type.model_validate(value)


__all__ = ["validate_output"]
