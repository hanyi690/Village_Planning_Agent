"""Shared in-memory state for one L1 -> GROUND grounding pass.

The grounding pass is a collective evidence operation.  A location work item
may depend on a village scope, source semantic decision, or feature identity
discovered while another work item is being prepared.  This context keeps
those bounded joins together without turning inferred scope into exact
feature identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GroundingSharedContext:
    """Session-local evidence state shared by all L1 grounding work items."""

    session_id: str = ""
    facts: list[Any] = field(default_factory=list)
    fact_scopes: dict[str, list[str]] = field(default_factory=dict)
    scope_support: dict[str, dict[str, Any]] = field(default_factory=dict)
    recovery_candidates: dict[str, list[Any]] = field(default_factory=dict)
    resolved_anchors: list[Any] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)

    def add_resolved(self, value: Any) -> None:
        """Register one source-backed resolution without duplicating identities."""

        if value is None:
            return
        identity = tuple(
            str(getattr(value, field_name, "") or "").strip()
            for field_name in (
                "feature_bsm",
                "source_feature_id",
                "entity_ref",
                "geometry_ref",
            )
        )
        if not any(identity):
            return
        for existing in self.resolved_anchors:
            existing_identity = tuple(
                str(getattr(existing, field_name, "") or "").strip()
                for field_name in (
                    "feature_bsm",
                    "source_feature_id",
                    "entity_ref",
                    "geometry_ref",
                )
            )
            if existing_identity == identity:
                return
        self.resolved_anchors.append(value)

    def set_fact_scopes(self, fact: Any, scopes: list[str] | tuple[str, ...]) -> None:
        """Keep scopes inferred from hints/graph trace available to siblings."""

        key = self.fact_key(fact)
        self.fact_scopes[key] = list(dict.fromkeys(
            str(value).strip()
            for value in (scopes or ())
            if str(value).strip()
        ))

    @staticmethod
    def fact_key(fact: Any) -> str:
        """Return a stable in-memory key that keeps same-name instances apart."""

        name = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        ).strip()
        role = str(getattr(fact, "role", "") or "unknown").strip()
        scopes = ",".join(
            sorted({
                str(value).strip()
                for value in [
                    *(getattr(fact, "village_scopes", None) or []),
                    *(getattr(fact, "place_scopes", None) or []),
                ]
                if str(value).strip()
            })
        )
        instance = str(getattr(fact, "instance_label", "") or "").strip()
        source = str(getattr(fact, "source_span", "") or "").strip()
        return "|".join((role, name, scopes, instance, source))

    def prompt_view(
        self,
        fact: Any,
        *,
        extra_scopes: list[str] | tuple[str, ...] = (),
        max_scopes: int = 12,
    ) -> str:
        """Return compact shared evidence context safe for the selector prompt."""

        current_key = self.fact_key(fact)
        scopes = [
            str(value).strip()
            for value in [
                *(getattr(fact, "village_scopes", None) or []),
                *(getattr(fact, "place_scopes", None) or []),
            ]
            if str(value).strip()
        ]
        scopes.extend(
            str(value).strip()
            for value in (extra_scopes or ())
            if str(value).strip()
        )
        scopes = list(dict.fromkeys(scopes))
        scope_rows = []
        for scope in list(dict.fromkeys(scopes))[:max_scopes]:
            support = self.scope_support.get(scope, {})
            scope_rows.append({
                "scope": scope,
                "status": support.get("status", "unknown"),
                "source_bsm_count": len(support.get("source_bsms", []) or []),
                "entity_refs": list(support.get("entity_refs", []) or [])[:4],
            })

        sibling_rows = []
        for sibling in self.facts:
            if self.fact_key(sibling) == current_key:
                continue
            sibling_key = self.fact_key(sibling)
            sibling_scopes = {
                str(value).strip()
                for value in [
                    *(getattr(sibling, "village_scopes", None) or []),
                    *(getattr(sibling, "place_scopes", None) or []),
                    *self.fact_scopes.get(sibling_key, []),
                ]
                if str(value).strip()
            }
            if scopes and not sibling_scopes.intersection(scopes):
                continue
            sibling_rows.append({
                "mention": str(
                    getattr(sibling, "normalized_name", "")
                    or getattr(sibling, "mention", "")
                    or ""
                ).strip(),
                "role": str(getattr(sibling, "role", "") or "unknown").strip(),
                "scopes": sorted(sibling_scopes)[:4],
            })

        anchor_rows = []
        for anchor in self.resolved_anchors[:12]:
            anchor_rows.append({
                "mention": str(
                    getattr(anchor, "normalized_name", "")
                    or getattr(anchor, "canonical_name", "")
                    or getattr(anchor, "mention", "")
                    or ""
                ).strip(),
                "role": str(getattr(anchor, "role", "") or "unknown").strip(),
                "feature_bsm": str(
                    getattr(anchor, "feature_bsm", "")
                    or getattr(anchor, "source_feature_id", "")
                    or ""
                ).strip(),
                "source_feature_id": str(
                    getattr(anchor, "source_feature_id", "") or ""
                ).strip(),
                "source_bsms": list(
                    getattr(anchor, "source_bsms", None) or []
                )[:4],
                "related_parcels": list(
                    getattr(anchor, "related_parcel_bsms", None) or []
                )[:4],
                "entity_ref": str(
                    getattr(anchor, "entity_ref", "") or ""
                ).strip(),
                "topology": list(
                    getattr(anchor, "topology_evidence", None) or []
                )[:4],
            })

        unresolved_rows = []
        for item in self.unresolved[:8]:
            unresolved_rows.append({
                "mention": str(item.get("mention", "") or "").strip(),
                "role": str(item.get("role", "") or "unknown").strip(),
                "reason": str(item.get("reason", "") or "").strip(),
                "supporting_scope": list(
                    (item.get("supporting_scope") or {}).keys()
                )[:4],
            })

        return (
            f"scopes={scope_rows}; "
            f"same_scope_work_items={sibling_rows[:12]}; "
            f"already_resolved_source_features={anchor_rows}; "
            f"previous_unresolved={unresolved_rows}"
        )


__all__ = ["GroundingSharedContext"]
