"""Features adapter — 一般点/线/面要素，DU 自动路由。"""

from __future__ import annotations

from app.modules.schema.types.layer_registry import GisLayerTypeEntry

from ..ingest import ingest_feature
from . import AdapterResult, IngestAdapter


class FeaturesAdapter(IngestAdapter):
    """将 GeoJSON FeatureCollection 转换为类型化的空间要素。

    委托给 ``ingest_feature()``，传递内存中的字典而不是文件路径。
    ``feature_type`` 来自 ``entry.ingest.feature_type``。
    """

    def load(
        self,
        data: dict,
        entry: GisLayerTypeEntry,
        *,
        strict: bool = False,
    ) -> AdapterResult:
        feature_type = entry.ingest.feature_type if entry.ingest else ""
        features, warnings = ingest_feature(data, feature_type)
        return AdapterResult(features=features, warnings=warnings)