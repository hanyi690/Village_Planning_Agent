"""Parcels adapter — 地类图斑（现状/规划），通过编码验证链。"""

from __future__ import annotations

from app.modules.schema.types.layer_registry import GisLayerTypeEntry

from ..ingest import ingest_landuse
from . import AdapterResult, IngestAdapter


class ParcelsAdapter(IngestAdapter):
    """将 GeoJSON FeatureCollection 转换为类型化的地类图斑。

    委托给 ``ingest_landuse()``，但传递内存中的字典而不是文件路径，
    从而消除临时文件轮转。``layer_type`` 来自 ``entry.ingest.feature_type``
    （"current_landuse" 或 "planned_landuse"）。
    """

    def load(
        self,
        data: dict,
        entry: GisLayerTypeEntry,
        *,
        strict: bool = False,
    ) -> AdapterResult:
        layer_type = entry.ingest.feature_type if entry.ingest else "current_landuse"
        parcels, warnings = ingest_landuse(data, layer_type=layer_type, strict=strict)
        return AdapterResult(features=parcels, warnings=warnings)