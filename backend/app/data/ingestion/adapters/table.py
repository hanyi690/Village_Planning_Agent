"""Table adapter — lossless CSV/Excel rows without fixed field names."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.data.model.layer_registry import GisLayerTypeEntry
from app.contracts.data.dlq import DlqCategory, DlqEntry
from app.infrastructure.logging import get_logger

from app.data.model.table_types import (
    ConstructionProjectTable,
    ControlRuleTable,
    FacilityInventory,
    IndustryTable,
    LandUseStructureTable,
    PlanningIndicatorTable,
    PopulationTable,
    TableDataset,
)
from . import AdapterResult, IngestAdapter

logger = get_logger(__name__)


class TableAdapter(IngestAdapter):
    """Convert table payloads to typed row containers.

    ``feature_type`` is only used to select an optional convenience subclass;
    row and column names are never required or renamed.  This keeps the
    adapter useful for unknown spreadsheets while preserving the existing
    registry contract for known planning tables.
    """

    _TYPE_MAP = {
        "population": PopulationTable,
        "industry": IndustryTable,
        "facility_inventory": FacilityInventory,
        "construction_projects": ConstructionProjectTable,
        "control_rules": ControlRuleTable,
        "planning_indicators": PlanningIndicatorTable,
        "land_use_structure": LandUseStructureTable,
    }

    @staticmethod
    def _json_value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if hasattr(value, "item"):
            try:
                return TableAdapter._json_value(value.item())
            except Exception:
                pass
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:
                pass
        return str(value)

    @classmethod
    def _payload(cls, data: Any) -> list[tuple[str, list[dict[str, Any]]]]:
        if isinstance(data, (str, Path)):
            path = Path(data)
            suffix = path.suffix.casefold()
            if suffix in {".xlsx", ".xls"}:
                import pandas as pd

                workbook = pd.ExcelFile(path)
                return [
                    (
                        str(sheet),
                        [
                            {
                                str(key): cls._json_value(value)
                                for key, value in row.items()
                            }
                            for row in pd.read_excel(workbook, sheet_name=sheet).to_dict("records")
                        ],
                    )
                    for sheet in workbook.sheet_names
                ]
            import pandas as pd

            frame = pd.read_csv(path, sep="\t" if suffix == ".tsv" else None, engine="python")
            return [("default", [
                {str(key): cls._json_value(value) for key, value in row.items()}
                for row in frame.to_dict("records")
            ])]
        if isinstance(data, dict):
            if data.get("type") == "TableResource":
                return [
                    (
                        str(table.get("name") or "default"),
                        [dict(row) for row in table.get("rows") or [] if isinstance(row, dict)],
                    )
                    for table in data.get("tables") or []
                    if isinstance(table, dict)
                ]
            if isinstance(data.get("tables"), list):
                return cls._payload({"type": "TableResource", "tables": data["tables"]})
            if isinstance(data.get("rows"), list):
                return [(str(data.get("name") or "default"), [
                    dict(row) for row in data["rows"] if isinstance(row, dict)
                ])]
            # A single mapping is a valid one-row table; do not iterate keys.
            return [("default", [dict(data)])]
        if isinstance(data, list):
            return [("default", [dict(row) for row in data if isinstance(row, dict)])]
        raise ValueError("table payload must be a path, mapping, or list of mappings")

    @staticmethod
    def _columns(rows: list[dict[str, Any]]) -> list[Any]:
        from app.data.model.table_types import ColumnSpec

        names = sorted({str(key) for row in rows for key in row})
        columns = []
        for name in names:
            values = [row.get(name) for row in rows if row.get(name) is not None]
            dtype = "string"
            if values and all(isinstance(value, bool) for value in values):
                dtype = "boolean"
            elif values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
                dtype = "number"
            columns.append(ColumnSpec(name=name, dtype=dtype))
        return columns

    def load(
        self,
        data: dict,
        entry: GisLayerTypeEntry,
        *,
        strict: bool = False,
    ) -> AdapterResult:
        feature_type = str(entry.ingest.feature_type if entry.ingest else "").strip().casefold()
        model_cls = self._TYPE_MAP.get(feature_type, TableDataset)
        warnings: list[str] = []
        dlq: list[DlqEntry] = []
        try:
            tables = self._payload(data)
        except Exception as exc:
            if strict:
                raise
            return AdapterResult(
                warnings=[f"table decode failed: {type(exc).__name__}: {exc}"],
                dlq=[DlqEntry(
                    category=DlqCategory.MAPPING,
                    reason=f"table decode failed: {type(exc).__name__}",
                    source_layer=entry.gis_type_ref,
                    raw_feature={},
                )],
            )
        features = []
        for sheet_name, rows in tables:
            try:
                normalized = [
                    {str(key): self._json_value(value) for key, value in row.items()}
                    for row in rows
                ]
                features.append(model_cls(
                    rows=normalized,
                    columns=self._columns(normalized),
                    layer_type=str(entry.gis_type_ref),
                    source_sheet=sheet_name,
                ))
            except Exception as exc:
                reason = f"table model validation failed: {type(exc).__name__}"
                if strict:
                    raise ValueError(reason) from exc
                warnings.append(reason)
                dlq.append(DlqEntry(
                    category=DlqCategory.MAPPING,
                    reason=reason,
                    source_layer=str(entry.gis_type_ref),
                    raw_feature={"sheet": sheet_name, "row_count": len(rows)},
                ))
        return AdapterResult(features=features, warnings=warnings, dlq=dlq)
