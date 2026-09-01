"""Common schema validation boundary for structured provider output."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from app.infrastructure.llm.table_protocol import validate_flat_llm_rows

ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_output(model_type: type[ModelT], value: Any) -> ModelT:
    """Validate one provider result without adding stage-specific semantics."""

    return model_type.model_validate(value)


def validate_provider_page(contract_key: str, value: BaseModel) -> BaseModel:
    """Apply the shared flat, bounded row protocol to semantic L1/L2/L3 output."""

    payload = value.model_dump(mode="json")
    contracts: dict[str, tuple[tuple[str, str], ...]] = {
        "l1.observe": (("observations", "fact_type"),),
        "l2.decision": (
            ("objectives", "objective_id"),
            ("metrics", "metric_id"),
            ("strategies", "strategy_id"),
            ("priorities", "priority_id"),
            ("spatial_structures", "structure_id"),
            ("conflicts", "conflict_id"),
            ("evidence_gaps", "gap_id"),
        ),
        "l3.claims": (("claims", "statement"),),
        "cognition.schema_mapping": (("proposals", "collection_ref"),),
        "data.temporal_role": (("proposals", "profile_ref"),),
    }
    row_fields = contracts.get(str(contract_key).strip().casefold())
    if row_fields is None:
        return value
    total_rows = 0
    try:
        for field_name, required_column in row_fields:
            rows = payload.get(field_name, [])
            validate_flat_llm_rows(
                rows,
                required_columns=(required_column,),
                max_rows=32,
                max_depth=2,
            )
            total_rows += len(rows)
        if total_rows > 32:
            raise ValueError("LLM output exceeds the 32-row provider page budget")
    except (TypeError, ValueError) as exc:
        error = ValueError(f"structured output row protocol rejected {contract_key}: {exc}")
        setattr(error, "structured_failure_code", "OUTPUT_PROTOCOL_VIOLATION")
        raise error from exc
    return value


__all__ = ["validate_output", "validate_provider_page"]
