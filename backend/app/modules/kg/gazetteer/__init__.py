"""Gazetteer package — village-name → spatial entity resolution (KG sub-module)."""
from .gazetteer import (
    Gazetteer,
    GazetteerEntry,
    build_gazetteer,
    confirm_with_llm,
    spatial_check,
    spatial_score,
)

__all__ = [
    "Gazetteer",
    "GazetteerEntry",
    "build_gazetteer",
    "confirm_with_llm",
    "spatial_check",
    "spatial_score",
]
