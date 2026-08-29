"""Canonical closed catalog for typed L1 facts consumed by L2.

The snapshot owns fact identities.  This module only projects existing
    canonical identities into the closed candidate-set primitives; it never
    creates an identity for a missing ``fact_id``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.contracts.llm.closed_set_contracts import (
    CandidateDescriptor,
    ExactBatchMembershipResult,
    candidate_set_digest,
    validate_exact_batch_membership,
)


CANONICAL_L1_FACT_PREFIX = "l1:fact:"
SPATIAL_L1_FACT_KINDS = frozenset(
    {"spatial_observation", "gis_observation", "kg_canonical_fact"}
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def is_canonical_l1_fact_id(value: Any) -> bool:
    """Return whether ``value`` is exactly in the canonical L1 namespace."""

    text = _text(value)
    if not text.startswith(CANONICAL_L1_FACT_PREFIX):
        return False
    suffix = text[len(CANONICAL_L1_FACT_PREFIX):]
    return bool(suffix) and not any(character.isspace() for character in suffix)


def require_canonical_l1_fact_id(value: Any) -> str:
    """Normalize one existing ID or fail without deriving a replacement."""

    text = _text(value)
    if not is_canonical_l1_fact_id(text):
        raise ValueError("l1_fact_id_must_use_canonical_namespace")
    return text


@dataclass(frozen=True)
class L1FactCatalog:
    """The current L1 fact candidate set and its deterministic projections."""

    candidates: tuple[CandidateDescriptor, ...]
    _allowed_fact_ids: tuple[str, ...]
    _spatial_fact_ids: tuple[str, ...]
    digest: str
    invalid_fact_ids: tuple[str, ...] = ()
    duplicate_fact_ids: tuple[str, ...] = ()

    @property
    def allowed_fact_ids(self) -> list[str]:
        """Return the canonical IDs that may be copied into L2 references."""

        return list(self._allowed_fact_ids)

    @property
    def spatial_fact_ids(self) -> list[str]:
        """Return the canonical spatial subset of ``allowed_fact_ids``."""

        return list(self._spatial_fact_ids)

    @property
    def usable_allowed_fact_ids(self) -> list[str]:
        """Return IDs only when the catalog has no ambiguous duplicate ID."""

        if self.duplicate_fact_ids:
            return []
        return self.allowed_fact_ids

    @property
    def usable_spatial_fact_ids(self) -> list[str]:
        """Return the spatial subset only when the catalog is unambiguous."""

        if self.duplicate_fact_ids:
            return []
        return self.spatial_fact_ids

    @property
    def is_unambiguous(self) -> bool:
        return not self.duplicate_fact_ids

    @classmethod
    def from_fact_records(cls, fact_records: Iterable[Any] | None) -> "L1FactCatalog":
        return build_l1_fact_catalog(fact_records)


def empty_l1_fact_catalog() -> L1FactCatalog:
    """Return the deterministic empty catalog used by fail-closed callers."""

    return L1FactCatalog(
        candidates=(),
        _allowed_fact_ids=(),
        _spatial_fact_ids=(),
        digest=candidate_set_digest(()),
    )


def build_l1_fact_catalog(fact_records: Iterable[Any] | None) -> L1FactCatalog:
    """Project existing snapshot records into a canonical L1 fact catalog.

    Records with missing or non-canonical IDs are deliberately not candidates.
    Their statements remain the caller's responsibility for display, and no
    canonical, default, or derived ID is produced for them.  Duplicate
    canonical IDs are recorded as ambiguous and are not usable by L2.
    """

    candidates: list[CandidateDescriptor] = []
    allowed_ids: list[str] = []
    spatial_ids: list[str] = []
    invalid_ids: list[str] = []
    duplicate_ids: list[str] = []
    seen_ids: set[str] = set()

    for record in fact_records or ():
        raw_fact_id = _text(_value(record, "fact_id"))
        if not is_canonical_l1_fact_id(raw_fact_id):
            if raw_fact_id:
                invalid_ids.append(raw_fact_id)
            continue
        if raw_fact_id in seen_ids:
            duplicate_ids.append(raw_fact_id)
            continue
        seen_ids.add(raw_fact_id)

        fact_kind = _text(_value(record, "fact_kind"))
        dimension_key = _text(_value(record, "dimension_key"))
        statement = _text(_value(record, "statement"))
        fact_status = _text(_value(record, "status")) or "observed"
        uncertainty = _text(_value(record, "uncertainty"))
        is_spatial = fact_kind in SPATIAL_L1_FACT_KINDS
        candidates.append(
            CandidateDescriptor(
                candidate_id=raw_fact_id,
                kind=fact_kind,
                label=statement,
                metadata={
                    "dimension_key": dimension_key,
                    "fact_kind": fact_kind,
                    "spatial": is_spatial,
                    "status": fact_status,
                    "uncertainty": uncertainty,
                },
            )
        )
        allowed_ids.append(raw_fact_id)
        if is_spatial:
            spatial_ids.append(raw_fact_id)

    candidates.sort(key=lambda item: (item.candidate_id, item.kind, item.label))
    allowed_ids = sorted(allowed_ids)
    spatial_ids = sorted(spatial_ids)
    invalid_ids = list(dict.fromkeys(invalid_ids))
    duplicate_ids = sorted(set(duplicate_ids))
    return L1FactCatalog(
        candidates=tuple(candidates),
        _allowed_fact_ids=tuple(allowed_ids),
        _spatial_fact_ids=tuple(spatial_ids),
        digest=candidate_set_digest(candidates),
        invalid_fact_ids=tuple(invalid_ids),
        duplicate_fact_ids=tuple(duplicate_ids),
    )


def validate_l1_fact_catalog(catalog: L1FactCatalog) -> ExactBatchMembershipResult:
    """Require the catalog's candidate IDs to exactly match its ID projection."""

    candidate_ids = [item.candidate_id for item in catalog.candidates]
    result = validate_exact_batch_membership(catalog.allowed_fact_ids, candidate_ids)
    if catalog.duplicate_fact_ids:
        return result.model_copy(update={
            "accepted": False,
            "duplicate_ids": tuple(sorted({
                *result.duplicate_ids,
                *catalog.duplicate_fact_ids,
            })),
        })
    if any(not is_canonical_l1_fact_id(item) for item in candidate_ids):
        return result.model_copy(update={"accepted": False})
    return result


def validate_l1_fact_references(
    fact_ids: Iterable[Any] | None,
    *,
    catalog: L1FactCatalog,
) -> ExactBatchMembershipResult:
    """Validate one L2 reference batch as an exact subset of the catalog.

    Every supplied reference must be canonical, present in the catalog, and
    unique within the batch.  The whole catalog need not be cited by one L2
    object, so ``missing_ids`` is intentionally empty for this subset check.
    """

    actual_values = tuple(_text(value) for value in (fact_ids or ()))
    probe = validate_exact_batch_membership(actual_values, actual_values)
    allowed = tuple(catalog.usable_allowed_fact_ids)
    actual_ids = tuple(dict.fromkeys(actual_values))
    extra_ids = tuple(sorted(
        {
            *set(actual_ids) - set(allowed),
            *{
                value for value in allowed
                if not is_canonical_l1_fact_id(value)
            },
        }
    ))
    has_empty = any(not value for value in actual_values)
    accepted = (
        not extra_ids
        and not probe.duplicate_ids
        and not has_empty
        and all(is_canonical_l1_fact_id(value) for value in allowed)
    )
    return ExactBatchMembershipResult(
        accepted=accepted,
        expected_ids=allowed,
        actual_ids=actual_ids,
        missing_ids=(),
        extra_ids=extra_ids,
        duplicate_ids=probe.duplicate_ids,
    )


__all__ = [
    "CANONICAL_L1_FACT_PREFIX",
    "SPATIAL_L1_FACT_KINDS",
    "L1FactCatalog",
    "build_l1_fact_catalog",
    "empty_l1_fact_catalog",
    "is_canonical_l1_fact_id",
    "require_canonical_l1_fact_id",
    "validate_l1_fact_catalog",
    "validate_l1_fact_references",
]
