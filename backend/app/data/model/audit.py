from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ProvenanceSource(str, Enum):
    GBT21010 = "gbt21010"
    PRACTICAL_APPENDIX5 = "practical:appendix5"
    TUGUI = "tugui"
    VNE = "vne"
    DERIVED_DLBM_TO_ZONE_TYPE = "derived:dlbm_to_zone_type"
    DERIVED_THREE_LINE_OVERLAY = "derived:three_line_overlay"
    DERIVED_UPPER_PLAN_OVERLAY = "derived:upper_plan_overlay"
    CUSTOM_VOCABULARY = "custom:vocabulary"
    MISSING_UPPER_PLAN = "missing:upper_plan_transmission"
    MISSING_URBAN_DEV_BOUNDARY = "missing:gd_urban_dev_boundary"
    MISSING_THREE_LINE = "missing:three_line"


@dataclass
class AuditEntry:
    layer: str
    source: str
    parcel_count: int
    note: Optional[str] = None


class ProvenanceAudit:
    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def record(self, layer: str, source: ProvenanceSource, parcel_count: int, note: Optional[str] = None) -> None:
        self._entries.append(AuditEntry(layer=layer, source=source.value, parcel_count=parcel_count, note=note))

    def report(self) -> List[AuditEntry]:
        return list(self._entries)

    def missing_layers(self) -> List[AuditEntry]:
        return [e for e in self._entries if e.source.startswith("missing:")]
