from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.modules.ports.gazetteer import GazetteerPort
from app.modules.schema.contracts.gazetteer_contracts import GazetteerEntryLike


class KGGazetteerAdapter(GazetteerPort):
    def __init__(self, gazetteer: "Gazetteer"):
        self._gazetteer = gazetteer

    def resolve(self, run_id: str, name: str, fuzzy: bool = False) -> GazetteerEntryLike | None:
        entry = self._gazetteer.resolve(name, fuzzy=fuzzy)
        if entry is None:
            return None
        centroid = None
        c = getattr(entry, "centroid", None)
        if isinstance(c, (tuple, list)) and len(c) == 2:
            try:
                centroid = (float(c[0]), float(c[1]))
            except (TypeError, ValueError):
                centroid = None
        return GazetteerEntryLike(
            name=getattr(entry, "name", "") or "",
            aliases=list(getattr(entry, "aliases", None) or []),
            entity_uri=getattr(entry, "entity_uri", "") or "",
            bsms=list(getattr(entry, "bsms", None) or []),
            centroid=centroid,
            source=getattr(entry, "source", "") or "",
            confidence=float(getattr(entry, "confidence", 0.0) or 0.0),
            description=getattr(entry, "description", "") or "",
        )

    def resolve_place_name(self, run_id: str, name: str) -> dict[str, Any] | None:
        entry = self.resolve(run_id, name, fuzzy=True)
        if entry is None:
            return None
        return asdict(entry)

    def get_cluster_by_name(self, run_id: str, cluster_name: str) -> dict[str, Any] | None:
        entry = self.resolve(run_id, cluster_name, fuzzy=True)
        if entry is None or entry.source != "kg_cluster":
            return None
        return asdict(entry)

    def load_for_village(self, run_id: str, village_name: str) -> "GazetteerPort | None":
        try:
            from app.modules.kg.gazetteer import load_gazetteer
            return KGGazetteerAdapter(load_gazetteer(village_name))
        except Exception:
            return None
