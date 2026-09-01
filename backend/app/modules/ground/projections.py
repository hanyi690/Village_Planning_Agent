"""Bounded GROUND projection for shared context construction."""

from __future__ import annotations

import hashlib
from typing import Any

from app.infrastructure.context_runtime import ContextBudget, build_bounded_table


def _mention_source_ref(mention: Any, index: int) -> str:
    provenance = getattr(mention, "provenance", None)
    material = "|".join((
        str(getattr(mention, "source_report_ref", "") or ""),
        str(getattr(mention, "dimension_key", "") or ""),
        str(getattr(mention, "source_span", "") or ""),
        str(getattr(provenance, "observation_id", "") or ""),
        str(index),
    ))
    return "l1-source-mention:" + hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:20]


def _scope_ref(scope: Any) -> str:
    """Build an identifier from an explicit structured L1 scope.

    The role/name pair is already an L1 product.  This helper does not infer
    an administrative level from a label or inspect a GIS field name.
    """

    role = str(getattr(scope, "role", "unknown") or "unknown").strip()
    name = str(
        getattr(scope, "normalized_name", "")
        or getattr(scope, "name", "")
        or ""
    ).strip()
    if not name:
        return ""
    material = f"{role}|{name}"
    return "l1-scope:" + hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:20]


def build_l1_identity_work_items(
    mentions: list[Any],
) -> tuple[list[Any], list[Any]]:
    """Collapse repeated L1 rows into identity work items, not entities.

    The same physical name may appear in several L1 dimensions.  One work
    item reuses one Evidence packet and one identity decision while retaining
    every source mention ref.  Scope remains part of the key, so equal labels
    in different villages are never collapsed.
    """

    from app.contracts.evidence.identity_contracts import EvidenceObservation
    from app.modules.evidence.requirements import l1_location_work_item_key

    grouped: dict[str, list[tuple[int, Any]]] = {}
    for index, mention in enumerate(mentions):
        grouped.setdefault(
            l1_location_work_item_key(mention),
            [],
        ).append((index, mention))

    representatives: list[Any] = []
    observations: list[EvidenceObservation] = []
    for work_item_ref in sorted(grouped):
        members = grouped[work_item_ref]
        first = members[0][1]

        def merged_values(field: str) -> list[Any]:
            values: list[Any] = []
            seen: set[str] = set()
            for _index, member in members:
                for value in list(getattr(member, field, None) or []):
                    key = str(
                        getattr(value, "descriptor_digest", "") or value
                    )
                    if key and key not in seen:
                        seen.add(key)
                        values.append(value)
            return values

        representative = first.model_copy(deep=True, update={
            "work_item_ref": work_item_ref,
            "aliases": merged_values("aliases"),
            "related_mentions": merged_values("related_mentions"),
            "evidence_refs": merged_values("evidence_refs"),
            "evidence_artifact_refs": merged_values(
                "evidence_artifact_refs"
            ),
            "source_feature_ids": merged_values("source_feature_ids"),
            "confidence": max(
                float(getattr(member, "confidence", 0.0) or 0.0)
                for _index, member in members
            ),
        })
        source_mention_refs = [
            _mention_source_ref(member, index)
            for index, member in members
        ]
        source_refs = list(dict.fromkeys([
            *source_mention_refs,
            *[
                str(getattr(member, "source_report_ref", "") or "")
                for _index, member in members
                if str(getattr(member, "source_report_ref", "") or "")
            ],
            *[
                str(value)
                for _index, member in members
                for value in (
                    getattr(
                        getattr(member, "provenance", None),
                        "source_refs",
                        None,
                    )
                    or []
                )
                if str(value).strip()
            ],
        ]))
        representatives.append(representative)
        observations.append(EvidenceObservation(
            observation_id=work_item_ref,
            work_item_ref=work_item_ref,
            source_mention_refs=source_mention_refs,
            dimension_keys=list(dict.fromkeys(
                str(getattr(member, "dimension_key", "") or "")
                for _index, member in members
                if str(getattr(member, "dimension_key", "") or "")
            )),
            mention=str(getattr(representative, "mention", "") or ""),
            normalized_name=str(
                getattr(representative, "normalized_name", "")
                or getattr(representative, "mention", "")
                or ""
            ),
            aliases=[str(value) for value in representative.aliases],
            observed_type=str(
                getattr(representative, "mention_kind", "target")
                or "target"
            ),
            role=str(getattr(representative, "role", "") or "unknown"),
            source_document_ref=str(
                getattr(representative, "source_report_ref", "") or ""
            ),
            source_refs=source_refs,
            evidence_refs=[
                str(value) for value in representative.evidence_refs
            ],
            source_span=str(
                getattr(representative, "source_span", "") or ""
            ),
            spatial_hint=str(
                getattr(representative, "spatial_hint", "") or ""
            ),
            location_relation=str(
                getattr(representative, "relation", "") or ""
            ),
            relation_mentions=[
                str(value) for value in representative.related_mentions
            ],
            scope_mentions=list(
                getattr(representative, "scopes", None) or []
            ),
            scope_refs=list(dict.fromkeys(
                value
                for value in (
                    _scope_ref(scope)
                    for scope in list(
                        getattr(representative, "scopes", None) or []
                    )
                )
                if value
            )),
            confidence=float(
                getattr(representative, "confidence", 0.0) or 0.0
            ),
            extraction_method="l1_v2_identity_work_item",
        ))
    return representatives, observations


def build_ground_projection(result: Any, *, budget: ContextBudget | None = None) -> dict[str, Any]:
    rows = [
        {
            "candidate_id": str(getattr(item, "candidate_id", "")),
            "target_ref": str(getattr(item, "target_ref", "")),
            "status": str(getattr(item, "status", "")),
            "source_ref_count": len(getattr(item, "source_refs", []) or []),
        }
        for item in list(getattr(result, "candidates", []) or [])
    ]
    rows, table = build_bounded_table(
        ("candidate_id", "target_ref", "status", "source_ref_count"),
        rows,
        max_rows=(budget.max_rows if budget is not None else 80),
        max_chars=(budget.max_chars if budget is not None else 12000),
    )
    return {"rows": rows, "table": table, "count": len(rows)}


__all__ = ["build_ground_projection", "build_l1_identity_work_items"]
