from pathlib import Path
from functools import lru_cache

import yaml

from app.contracts.domain.custom_zone_contracts import (
    CustomZoneTarget,
    Vocabulary,
    VocabularyCategory,
)


_VOCAB_DIR = Path(__file__).parent

_REGISTERED: dict[str, Vocabulary] = {}


@lru_cache(maxsize=None)
def load_vocabulary(name: str) -> Vocabulary:
    p = _VOCAB_DIR / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"vocabulary not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return Vocabulary(**data)


def register_vocabulary(name: str, vocab: Vocabulary) -> Vocabulary:
    """Register an in-memory vocabulary (e.g. LLM-extracted from L3 reports).

    Takes precedence over YAML files with the same name; valid for the
    lifetime of the process (session-scoped by caller-chosen name).
    """
    _REGISTERED[name] = vocab
    return vocab


def get_vocabulary(name: str) -> Vocabulary:
    """Return registered in-memory vocab first, then the YAML loader."""
    if name in _REGISTERED:
        return _REGISTERED[name]
    return load_vocabulary(name)


def list_vocabularies() -> list[str]:
    return sorted(p.stem for p in _VOCAB_DIR.glob("*.yaml")) + sorted(_REGISTERED.keys())


__all__ = [
    "Vocabulary",
    "VocabularyCategory",
    "TypingRule",
    "CustomZoneTarget",
    "load_vocabulary",
    "register_vocabulary",
    "get_vocabulary",
    "list_vocabularies",
]