"""Document adapter — 规划文本、L3 报告等。"""

from __future__ import annotations

from app.data.model.layer_registry import GisLayerTypeEntry
from app.utils.logger import get_logger

from . import AdapterResult, IngestAdapter

logger = get_logger(__name__)


class DocumentAdapter(IngestAdapter):
    """文档适配器（存根 — 在 v4.1 管道中实现）。

    当前没有文档类型有 ``ingest`` 块，因此该适配器尚未被调用。
    """

    def load(
        self,
        data: dict,
        entry: GisLayerTypeEntry,
        *,
        strict: bool = False,
    ) -> AdapterResult:
        logger.warning("DocumentAdapter.load() called but not yet implemented for %s", entry.gis_type_ref)
        return AdapterResult()