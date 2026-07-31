from pathlib import Path
from functools import lru_cache

import yaml

from app.modules.schema.contracts.custom_zone_contracts import (
    CustomZoneTarget,
    Vocabulary,
    VocabularyCategory,
)


_VOCAB_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load_vocabulary(name: str) -> Vocabulary:
    p = _VOCAB_DIR / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"vocabulary not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return Vocabulary(**data)


def list_vocabularies() -> list[str]:
    return sorted(p.stem for p in _VOCAB_DIR.glob("*.yaml"))


__all__ = [
    "Vocabulary",
    "VocabularyCategory",
    "TypingRule",
    "CustomZoneTarget",
    "load_vocabulary",
    "list_vocabularies",
]