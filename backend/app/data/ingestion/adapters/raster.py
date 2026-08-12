"""Raster adapter — DEM/DOM/slope 栅格元数据。"""

from __future__ import annotations

from app.modules.schema.types.layer_registry import GisLayerTypeEntry

from ..ingest import ingest_raster
from . import AdapterResult, IngestAdapter


class RasterAdapter(IngestAdapter):
    """将栅格路径（来自 DataResult.data）转换为类型化的栅格数据集。

    委托给 ``ingest_raster()``，``raster_type`` 来自
    ``entry.ingest.feature_type``（"dem" 或 "dom"）。
    """

    def load(
        self,
        data: dict,
        entry: GisLayerTypeEntry,
        *,
        strict: bool = False,
    ) -> AdapterResult:
        raster_type = entry.ingest.feature_type if entry.ingest else "dem"
        path = data if isinstance(data, str) else data.get("path", "")
        raster = ingest_raster(path, raster_type=raster_type)
        if raster is None:
            return AdapterResult(warnings=["Raster not found or unreadable"])
        return AdapterResult(features=[raster])