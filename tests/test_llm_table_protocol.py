import pytest

from app.infrastructure.llm.table_protocol import (
    build_llm_table,
    validate_flat_llm_rows,
)


def test_build_llm_table_is_bounded_and_tabular():
    rows, table = build_llm_table(
        ["row_ref", "value"],
        [{"row_ref": "r1", "value": "x"}],
        max_rows=1,
    )
    assert rows == [{"row_ref": "r1", "value": "x"}]
    assert table.splitlines()[0] == "| row_ref | value |"


def test_validate_flat_llm_rows_rejects_nested_large_payloads():
    with pytest.raises(ValueError):
        validate_flat_llm_rows(
            [{"row_ref": "r1", "value": {"nested": {"too": "deep"}}}],
            required_columns=["row_ref", "value"],
            max_depth=2,
        )
    with pytest.raises(ValueError):
        validate_flat_llm_rows(
            [{"row_ref": "r1"}, {"row_ref": "r2"}],
            required_columns=["row_ref"],
            max_rows=1,
        )
