"""Bounded persistence for source semantic classification snapshots."""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

from app.contracts.evidence.source_semantic_contracts import (
    SourceSemanticClassificationSnapshot,
)


class SourceSemanticStore:
    """Small LRU store; optional JSON persistence keeps resume deterministic."""

    def __init__(self, path: str | Path | None = None, *, max_entries: int = 128) -> None:
        self.path = Path(path) if path else None
        self.max_entries = max(1, int(max_entries))
        self._items: OrderedDict[str, SourceSemanticClassificationSnapshot] = OrderedDict()
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for key, value in (raw.items() if isinstance(raw, dict) else []):
                self._items[str(key)] = SourceSemanticClassificationSnapshot.model_validate(value)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
        except Exception:
            self._items.clear()

    def _flush(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {key: value.model_dump(mode="json") for key, value in self._items.items()},
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def get(self, key: str) -> SourceSemanticClassificationSnapshot | None:
        value = self._items.get(str(key))
        if value is not None:
            self._items.move_to_end(str(key))
        return value

    def put(self, snapshot: SourceSemanticClassificationSnapshot) -> None:
        key = str(snapshot.fingerprint)
        self._items[key] = snapshot
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)
        self._flush()

    def clear(self) -> None:
        self._items.clear()
        self._flush()


__all__ = ["SourceSemanticStore"]
