"""Evidence-runtime boundary for snapshot-scoped source semantics.

Source labels are classified against current, durable source identities. The
business stages consume only this typed capability; classifier and graph
implementation details remain behind the evidence runtime.
"""

from __future__ import annotations

from typing import Any


def collect_authoritative_source_features(context: Any) -> dict[str, list[object]]:
    from app.infrastructure.evidence_runtime.source_semantic_runtime import (
        collect_authoritative_source_features as collect,
    )

    return collect(context)


def source_descriptors(
    source_features: dict[str, list[object]],
) -> tuple[list[Any], int]:
    from app.infrastructure.evidence_runtime.source_semantic_runtime import source_descriptors as describe

    return describe(source_features)


def install_source_semantic_snapshot(
    context: Any,
    snapshot: Any,
) -> None:
    from app.infrastructure.evidence_runtime.source_semantic_runtime import (
        install_source_semantic_snapshot as install,
    )

    install(context, snapshot)


async def classify_source_semantics(
    context: Any,
    **kwargs: Any,
) -> tuple[Any | None, dict[str, Any], list[dict[str, str]]]:
    from app.infrastructure.evidence_runtime.source_semantic_runtime import (
        classify_source_semantics as classify,
    )

    return await classify(context, **kwargs)


def accepted_semantic_decisions(snapshot: Any) -> dict[str, Any]:
    from app.infrastructure.evidence_runtime.source_semantic_classifier import (
        accepted_semantic_decisions as accepted,
    )

    return accepted(snapshot)


def install_intent_layer(kg: Any, intent: Any) -> None:
    """Install the typed L3 intent overlay through the KG infrastructure."""

    from app.infrastructure.kg.builder.layer3 import build_intent_layer

    build_intent_layer(kg, intent)


__all__ = [
    "accepted_semantic_decisions",
    "classify_source_semantics",
    "collect_authoritative_source_features",
    "install_intent_layer",
    "install_source_semantic_snapshot",
    "source_descriptors",
]
