"""Bounded projections used by L1 observation calls."""

from __future__ import annotations

from app.contracts.l1.l1_contracts import (
    L1DimensionInput,
    L1InputContext,
    L1SourceIndex,
)
from .context import build_l1_input_context

_MAX_PAGE_CHARS = 6200


def _pages(source_index: L1SourceIndex | None) -> list[L1SourceIndex | None]:
    if source_index is None or not source_index.source_segments:
        return [source_index]
    pages: list[L1SourceIndex] = []
    current = []
    chars = 0
    for segment in source_index.source_segments:
        length = max(1, len(segment.text))
        if current and chars + length > _MAX_PAGE_CHARS:
            pages.append(source_index.model_copy(update={"source_segments": current}))
            current = []
            chars = 0
        current.append(segment)
        chars += length
    if current:
        pages.append(source_index.model_copy(update={"source_segments": current}))
    return pages or [source_index]


class L1ProjectionBuilder:
    """Build one validated, bounded source-page input for an L1 provider."""

    def build_context(
        self,
        *,
        dimension_key: str,
        source_index: L1SourceIndex | None,
        session_id: str,
        source_index_ref: str = "",
        source_section_hints: tuple[str, ...] | list[str] | None = None,
    ) -> L1InputContext:
        return build_l1_input_context(
            dimension_key=dimension_key,
            source_index=source_index,
            session_id=session_id,
            source_index_ref=source_index_ref,
            source_section_hints=source_section_hints,
        )

    def build_dimension_input(
        self,
        *,
        context: L1InputContext,
        source_index: L1SourceIndex | None,
        page_index: int,
    ) -> L1DimensionInput:
        pages = _pages(source_index)
        if page_index < 0 or page_index >= len(pages):
            raise IndexError(f"L1 page index out of range: {page_index}")
        page = pages[page_index]
        segment_ids = tuple(
            segment.segment_id for segment in (page.source_segments if page else ())
        )
        return L1DimensionInput(
            context=context,
            page_index=page_index,
            page_segment_ids=segment_ids,
            source_page=page,
        )


__all__ = ["L1ProjectionBuilder"]
