"""Session document source resolution for the bundle retrieval boundary."""

from __future__ import annotations

import hashlib
import re
from typing import Any

_MARKDOWN_MEDIA_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

CURRENT_EVIDENCE_ROLE = "current_evidence"
PLANNING_BRIEF_ROLE = "planning_brief"
PLANNING_INSTRUCTION_ROLE = "planning_instruction"
REFERENCE_PLAN_ROLE = "reference_plan"
PLANNED_OUTPUT_ROLE = "planned_output"
UNCLASSIFIED_ROLE = "unclassified"

_ROLE_ALIASES = {
    CURRENT_EVIDENCE_ROLE: CURRENT_EVIDENCE_ROLE,
    "evidence": CURRENT_EVIDENCE_ROLE,
    "current": CURRENT_EVIDENCE_ROLE,
    "baseline": CURRENT_EVIDENCE_ROLE,
    PLANNING_BRIEF_ROLE: PLANNING_BRIEF_ROLE,
    "task": PLANNING_BRIEF_ROLE,
    "task_description": PLANNING_BRIEF_ROLE,
    PLANNING_INSTRUCTION_ROLE: PLANNING_INSTRUCTION_ROLE,
    "constraint": PLANNING_INSTRUCTION_ROLE,
    "constraints": PLANNING_INSTRUCTION_ROLE,
    REFERENCE_PLAN_ROLE: REFERENCE_PLAN_ROLE,
    "historical_plan": REFERENCE_PLAN_ROLE,
    PLANNED_OUTPUT_ROLE: PLANNED_OUTPUT_ROLE,
    "planning_result": PLANNED_OUTPUT_ROLE,
    UNCLASSIFIED_ROLE: UNCLASSIFIED_ROLE,
}

_SOURCE_ROLES = {
    "village_data": CURRENT_EVIDENCE_ROLE,
    "task_description": PLANNING_BRIEF_ROLE,
    "constraints": PLANNING_INSTRUCTION_ROLE,
}

_CONTROL_CATEGORIES = {
    "task_description": PLANNING_BRIEF_ROLE,
    "constraint": PLANNING_INSTRUCTION_ROLE,
    "constraints": PLANNING_INSTRUCTION_ROLE,
}


def typed_source_input_role(*, source: Any = "", category: Any = "") -> str:
    """Return an authoritative typed channel, never a guessed evidence role.

    Session fields carry their own type.  Upload categories may only preserve
    the two control channels: a ``village_data`` category still needs the API
    to persist an explicit current-evidence role before it can be admitted.
    """

    source_role = _SOURCE_ROLES.get(str(source or "").strip().casefold())
    if source_role:
        return source_role
    if str(source or "").strip().casefold() == "upload":
        return _CONTROL_CATEGORIES.get(str(category or "").strip().casefold(), "")
    return ""

def normalize_document_input_role(
    value: Any = "",
    *,
    source: str = "",
    category: str = "",
) -> str:
    """Resolve only explicit admission metadata, never document contents.

    The three persisted session fields are typed sources.  An upload category
    is not admission authority: uploads must persist an explicit ``input_role``
    and matching status before any body can enter current-world DATA.
    Arbitrary filenames, layer names, Markdown contents, and business fields
    are deliberately unable to grant admission here.
    """

    explicit = str(value or "").strip().casefold()
    if explicit and explicit != UNCLASSIFIED_ROLE:
        return _ROLE_ALIASES.get(explicit, UNCLASSIFIED_ROLE)
    source_role = typed_source_input_role(source=source, category=category)
    if source_role:
        return source_role
    return UNCLASSIFIED_ROLE


def document_admission_status(input_role: str) -> str:
    role = normalize_document_input_role(input_role)
    if role == CURRENT_EVIDENCE_ROLE:
        return "admitted"
    if role in {PLANNING_BRIEF_ROLE, PLANNING_INSTRUCTION_ROLE}:
        return "control_only"
    if role == REFERENCE_PLAN_ROLE:
        return "reference_only"
    if role == PLANNED_OUTPUT_ROLE:
        return "excluded"
    return "quarantined"


def is_evidence_document(document: dict[str, Any]) -> bool:
    return (
        normalize_document_input_role(document.get("input_role"))
        == CURRENT_EVIDENCE_ROLE
        and str(document.get("admission_status") or "").casefold()
        == "admitted"
    )


def evidence_documents(
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [document for document in documents if is_evidence_document(document)]


def _document(
    *,
    source: str,
    name: str,
    content: str,
    locator: str = "",
    category: str = "",
    record_id: str = "",
    document_type: str = "text",
    parser: str = "user_markdown",
    input_role: str = "",
    admission_status: str = "",
    admission_reason: str = "",
    admission_signals: list[str] | None = None,
) -> dict[str, Any]:
    text = str(content or "")
    from app.data.ingestion.source_admission import assess_source_admission

    assessment = assess_source_admission(
        input_role=input_role,
        source=source,
        category=category,
        filename=name,
        parsed_text=text,
    )
    resolved_role = assessment.input_role
    declared_status = str(admission_status or "").strip().casefold()
    if declared_status and declared_status != assessment.status:
        resolved_role = UNCLASSIFIED_ROLE
        resolved_status = "quarantined"
        resolved_reason = "persisted_admission_state_conflict"
    else:
        resolved_status = assessment.status
        resolved_reason = str(admission_reason or assessment.reason)
    resolved_signals = list(dict.fromkeys(
        list(admission_signals or []) + list(assessment.signals)
    ))
    return {
        "source": source,
        "name": name,
        "category": category,
        "type": document_type,
        "content_format": "markdown",
        "parser": parser,
        "input_role": resolved_role,
        "admission_status": resolved_status,
        "admission_reason": resolved_reason,
        "admission_signals": resolved_signals,
        "media_refs": [match.strip() for match in _MARKDOWN_MEDIA_RE.findall(text) if match.strip()],
        "media_policy": "deferred",
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
        for source, name, field, input_role in (
            ("village_data", "村庄基础数据", "village_data", CURRENT_EVIDENCE_ROLE),
            ("task_description", "任务描述", "task_description", PLANNING_BRIEF_ROLE),
            ("constraints", "约束条件", "constraints", PLANNING_INSTRUCTION_ROLE),
        ):
            content = str(session.get(field) or "")
            if content.strip():
                documents.append(_document(
                    source=source,
                    name=name,
                    content=content,
                    locator=f"planning-session://{session_id}/{field}",
                    record_id=session_id,
                    input_role=input_role,
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
        parser = "markdown_passthrough" if name.casefold().endswith((".md", ".markdown")) else "mineru"
        documents.append(_document(
            source="upload",
            name=name,
            content=content,
            category=str(item.get("file_category") or ""),
            locator=f"upload://{upload_id}/{name}" if upload_id or name else "",
            record_id=upload_id,
            parser=parser,
            input_role=str(
                item.get("input_role")
                or item.get("document_role")
                or item.get("source_role")
                or ""
            ),
            admission_status=str(item.get("admission_status") or ""),
            admission_reason=str(item.get("admission_reason") or ""),
            admission_signals=[
                str(value)
                for value in item.get("admission_signals") or []
                if str(value).strip()
            ],
        ))

    return documents


def to_document_refs(
    documents: list[dict[str, Any]],
    *,
    admitted_only: bool = True,
) -> list[dict[str, Any]]:
    """Persist compact refs; retrieval manifests contain evidence only."""
    refs: list[dict[str, Any]] = []
    for document in documents:
        if admitted_only and not is_evidence_document(document):
            continue
        ref = {
            key: document.get(key, "")
            for key in (
                "source", "name", "category", "type", "record_id", "locator",
                "content_digest", "char_count", "content_format", "parser", "media_refs", "media_policy",
                "input_role", "admission_status", "admission_reason", "admission_signals",
            )
        }
        if ref["source"] and ref["content_digest"]:
            refs.append(ref)
    return refs


__all__ = [
    "CURRENT_EVIDENCE_ROLE",
    "PLANNED_OUTPUT_ROLE",
    "REFERENCE_PLAN_ROLE",
    "UNCLASSIFIED_ROLE",
    "document_admission_status",
    "evidence_documents",
    "is_evidence_document",
    "load_session_documents",
    "normalize_document_input_role",
    "to_document_refs",
]
