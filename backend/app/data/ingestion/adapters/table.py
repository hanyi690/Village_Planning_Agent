"""Table adapter — 属性表（人口、建设项目等）。"""

from __future__ import annotations

from app.data.model.layer_registry import GisLayerTypeEntry
from app.utils.logger import get_logger

from . import AdapterResult, IngestAdapter

logger = get_logger(__name__)


class TableAdapter(IngestAdapter):
    """表数据适配器（存根 — 在 v4.1 管道中实现）。

    当前没有表数据有 ``ingest`` 块，因此该适配器尚未被调用。
    """

    def load(
        self,
        data: dict,
        entry: GisLayerTypeEntry,
        *,
        strict: bool = False,
    ) -> AdapterResult:
        logger.warning("TableAdapter.load() called but not yet implemented for %s", entry.gis_type_ref)
        return AdapterResult()