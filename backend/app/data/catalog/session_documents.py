"""Session document source resolution for the bundle retrieval boundary."""

from __future__ import annotations

import hashlib
from typing import Any


def _document(
    *,
    source: str,
    name: str,
    content: str,
    locator: str = "",
    category: str = "",
    record_id: str = "",
    document_type: str = "text",
) -> dict[str, Any]:
    text = str(content or "")
    return {
        "source": source,
        "name": name,
        "category": category,
        "type": document_type,
        "record_id": record_id,
        "locator": locator,
        "content": text,
        "content_digest": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "char_count": len(text),
    }


async def load_session_documents(
    session_id: str,
    village_name: str = "",
    *,
    session: dict[str, Any] | None = None,
    uploaded: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Load canonical session text sources for a runtime query.

    This is deliberately the only body-loading helper used by the bundle
    retrieval adapters.  Only content owned by the current session (the
    persisted request and explicit uploads) is included.  Repository-local
    reference documents are never implicitly promoted to session input;
    callers must explicitly ingest/bind one before it can enter the bundle.
    Callers that persist a bundle must pass the returned records through
    ``to_document_refs`` first.
    """
    from app.database.operations import (
        get_planning_session_async,
        get_uploaded_files_by_session_async,
    )

    documents: list[dict[str, Any]] = []
    if session is None:
        session = await get_planning_session_async(session_id)
    if session:
        for source, name, field in (
            ("village_data", "村庄基础数据", "village_data"),
            ("task_description", "任务描述", "task_description"),
            ("constraints", "约束条件", "constraints"),
        ):
            content = str(session.get(field) or "")
            if content.strip():
                documents.append(_document(
                    source=source,
                    name=name,
                    content=content,
                    locator=f"planning-session://{session_id}/{field}",
                    record_id=session_id,
                ))

    if uploaded is None:
        try:
            uploaded = await get_uploaded_files_by_session_async(session_id)
        except Exception:
            uploaded = []
    for item in uploaded:
        content = str(item.get("parsed_text") or "")
        if not content.strip():
            continue
        upload_id = str(item.get("id") or "")
        name = str(item.get("original_filename") or item.get("filename") or "")
        documents.append(_document(
            source="upload",
            name=name,
            content=content,
            category=str(item.get("file_category") or ""),
            locator=f"upload://{upload_id}/{name}" if upload_id or name else "",
            record_id=upload_id,
        ))

    return documents


def to_document_refs(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip text bodies into the compact refs persisted inside a bundle."""
    refs: list[dict[str, Any]] = []
    for document in documents:
        ref = {
            key: document.get(key, "")
            for key in (
                "source", "name", "category", "type", "record_id", "locator",
                "content_digest", "char_count",
            )
        }
        if ref["source"] and ref["content_digest"]:
            refs.append(ref)
    return refs


__all__ = ["load_session_documents", "to_document_refs"]
