"""Central bounded cognition projections for planning-stage LLM context."""

from __future__ import annotations

from typing import Any

from app.contracts.cognition.query import (
    IdentityBindingProjectionPage,
    IdentityBindingProjectionRequest,
    RenderedIdentityBindingProjection,
)
from app.infrastructure.llm.table_protocol import build_llm_table


_IDENTITY_COLUMNS = (
    "binding_ref",
    "work_item_ref",
    "source_dimensions",
    "scope_refs",
    "canonical_label",
    "entity_types",
    "identity_status",
    "candidate_count",
    "candidate_labels",
    "location_expression",
    "capability_summary",
    "gap_or_uncertainty",
)


def _joined(values: Any, *, limit: int = 8) -> str:
    return "; ".join(
        str(value)
        for value in list(values or [])[:limit]
        if str(value).strip()
    )


class ContextProjectionRuntime:
    """Build consumer-specific cognition pages without loading sidecars."""

    @staticmethod
    def build_identity_binding_table(
        context: Any,
        request: IdentityBindingProjectionRequest,
    ) -> RenderedIdentityBindingProjection:
        typed = IdentityBindingProjectionRequest.model_validate(request)
        port = getattr(getattr(context, "ports", None), "world_model", None)
        query = getattr(port, "query_identity_binding_page", None)
        if not callable(query):
            raise RuntimeError(
                "bounded World Model identity projection port is unavailable"
            )
        page = IdentityBindingProjectionPage.model_validate(query(typed))
        if (
            page.world_model_snapshot_ref
            != typed.world_model_snapshot_ref
            or page.world_model_snapshot_digest
            != typed.world_model_snapshot_digest
            or page.query_digest != typed.query_digest
        ):
            raise RuntimeError(
                "World Model identity projection authority mismatch"
            )
        raw_rows = [
            {
                "binding_ref": row.binding_ref,
                "work_item_ref": row.work_item_ref,
                "source_dimensions": _joined(row.source_dimensions),
                "scope_refs": _joined(row.scope_refs),
                "canonical_label": row.canonical_label,
                "entity_types": _joined(row.entity_types),
                "identity_status": row.identity_status,
                "candidate_count": row.candidate_count,
                "candidate_labels": _joined(row.candidate_labels, limit=3),
                "location_expression": (
                    "; ".join(
                        value
                        for value in (
                            f"status={row.location_expression_status}",
                            (
                                f"relation={row.spatial_relation}"
                                if row.spatial_relation else ""
                            ),
                            (
                                f"anchors={_joined(row.anchor_labels, limit=4)}"
                                if row.anchor_labels else ""
                            ),
                            (
                                "anchor_entities="
                                f"{_joined(row.anchor_entity_refs, limit=4)}"
                                if row.anchor_entity_refs else ""
                            ),
                            (
                                "anchor_work_items="
                                f"{_joined(row.anchor_work_item_refs, limit=4)}"
                                if row.anchor_work_item_refs else ""
                            ),
                            (
                                f"distance={row.distance_hint}"
                                if row.distance_hint else ""
                            ),
                            (
                                f"raw_hint={row.spatial_hint}"
                                if row.spatial_hint else ""
                            ),
                        )
                        if value
                    )
                ),
                "capability_summary": (
                    f"geometry={_joined(row.available_geometry_kinds)}; "
                    f"representations={row.representation_count}; "
                    f"resources={row.resource_count}; "
                    f"availability={row.resource_availability}"
                ),
                "gap_or_uncertainty": (
                    "; ".join(
                        value
                        for value in (row.gap_ref, row.uncertainty)
                        if value
                    )
                ),
            }
            for row in page.rows
        ]
        table_rows, table = build_llm_table(
            _IDENTITY_COLUMNS,
            raw_rows,
            max_rows=typed.requested_page_size,
            max_columns=12,
            max_chars=6200,
        )
        base_offset = 0
        if typed.cursor:
            _digest, _separator, offset = typed.cursor.rpartition("@")
            base_offset = int(offset)
        render_truncated = len(table_rows) < page.emitted_count
        continuation_cursor = ""
        if render_truncated:
            continuation_cursor = (
                f"{typed.query_digest}@{base_offset + len(table_rows)}"
            )
        elif page.truncated:
            continuation_cursor = page.next_cursor
        return RenderedIdentityBindingProjection(
            page=page,
            columns=_IDENTITY_COLUMNS,
            table_rows=tuple(table_rows),
            table=table,
            rendered_count=len(table_rows),
            render_truncated=render_truncated,
            continuation_cursor=continuation_cursor,
        )


__all__ = ["ContextProjectionRuntime"]
