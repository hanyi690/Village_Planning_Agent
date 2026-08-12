"""Ingest adapter strategy pattern — protocol + registry.

Each GIS layer type declares an adapter name in gis_layer_registry.yaml
(``ingest.adapter``). The adapter registry maps that name to a callable
that converts raw fetch data (dict) into typed schema models.

Adding a new adapter:
    1. Create ``adapters/<name>.py`` implementing ``IngestAdapter``
    2. Import and register in ``_register_builtin_adapters()`` below
    3. Reference ``adapter: <name>`` in gis_layer_registry.yaml
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from app.data.model.layer_registry import GisLayerTypeEntry
from app.infrastructure.kg.dlq import DlqEntry


@dataclass
class AdapterResult:
    """统一适配器结果信封。

    Attributes:
        features: 类型化的模型实例列表（SpatialFeature、RasterDataset 等）
        warnings: 验证警告，不阻塞管道
        dlq: 死信队列条目 —— 验证失败的原始要素，带有原因
    """
    features: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dlq: list[DlqEntry] = field(default_factory=list)


@runtime_checkable
class IngestAdapter(Protocol):
    """将原始获取数据（dict）转换为类型化模式模型的协议。

    Args:
        data: 来自 DataResult.data 的原始有效载荷 —— 通常是 GeoJSON
              FeatureCollection 字典，或栅格路径字符串。
        entry: 来自注册表的 GisLayerTypeEntry，包含 ingest.feature_type 等。
        strict: 如果为 True，验证失败时引发异常而不是警告。

    Returns:
        AdapterResult，包含类型化要素、警告和 DLQ 条目。
    """
    def load(
        self,
        data: dict,
        entry: GisLayerTypeEntry,
        *,
        strict: bool = False,
    ) -> AdapterResult:
        ...


ADAPTERS: dict[str, IngestAdapter] = {}


def register_adapter(name: str, adapter: IngestAdapter) -> None:
    """按名称注册一个适配器，以便 YAML 中的 ``ingest.adapter`` 可以找到它。"""
    ADAPTERS[name] = adapter


def _register_builtin_adapters() -> None:
    from .parcels import ParcelsAdapter
    from .features import FeaturesAdapter
    from .raster import RasterAdapter
    from .table import TableAdapter
    from .document import DocumentAdapter

    register_adapter("parcels", ParcelsAdapter())
    register_adapter("features", FeaturesAdapter())
    register_adapter("raster", RasterAdapter())
    register_adapter("table", TableAdapter())
    register_adapter("document", DocumentAdapter())


_register_builtin_adapters()


__all__ = [
    "ADAPTERS",
    "AdapterResult",
    "IngestAdapter",
    "register_adapter",
]