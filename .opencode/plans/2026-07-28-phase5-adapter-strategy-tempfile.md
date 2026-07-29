# Phase 5: Adapter Strategy + 消除 tempfile 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建 6 标准 IngestAdapter 策略模式，消除 `result_to_parcels()` 和 `result_to_features()` 中的 `NamedTemporaryFile` 轮转，将 `catalog.py` 中的硬编码 string switch 替换为适配器注册表。

**Architecture:** 新增 `data/adapters/` 包，包含 `AdapterResult` / `IngestAdapter` 协议 / `ADAPTERS` 注册表。两个核心适配器（`ParcelsAdapter`、`FeaturesAdapter`）直接包装现有的 `ingest_landuse()` 和 `ingest_feature()` 函数，通过传递内存中的 GeoJSON 字典来消除临时文件轮转，因为 `_read_geojson()` 已经接受字典。`RasterAdapter` 包装 `ingest_raster()`（无 tempfile 问题）。`TableAdapter` 和 `DocumentAdapter` 是用于未来使用的存根。`catalog.py` 用 `ADAPTERS[adapter_name].load(data, entry)` 替换 `if adapter_name == "parcels": ... elif adapter_name == "features": ...` 链。

**Tech Stack:** Python 3.12, typing.Protocol, pytest

## 全局约束

- 不引入新的第三方依赖
- 对所有现有 `result_to_*` 函数保持向后兼容 —— 它们成为委托给适配器的薄包装器
- `_read_geojson()` 已经接受字典（第 159-164 行），因此临时文件消除可以直接传递字典
- 遵循现有代码约定：`from __future__ import annotations`，使用 `logger = get_logger(__name__)`
- 所有现有测试必须通过：`python -m pytest tests/unit/ -v --tb=short -q --ignore=tests/unit/test_gis_unit.py`

---

## 文件结构

| 文件 | 职责 |
|------|----------|
| **Create** `data/adapters/__init__.py` | `AdapterResult` 数据类，`IngestAdapter` 协议，`ADAPTERS` 注册表，`register_adapter()` 函数，`_register_builtin_adapters()` |
| **Create** `data/adapters/parcels.py` | `ParcelsAdapter` —— 包装 `ingest_landuse()`，传递字典，不写临时文件 |
| **Create** `data/adapters/features.py` | `FeaturesAdapter` —— 包装 `ingest_feature()`，传递字典，不写临时文件 |
| **Create** `data/adapters/raster.py` | `RasterAdapter` —— 包装 `ingest_raster()` |
| **Create** `data/adapters/table.py` | `TableAdapter` —— 仅存根，返回空的 `AdapterResult` |
| **Create** `data/adapters/document.py` | `DocumentAdapter` —— 仅存根，返回空的 `AdapterResult` |
| **Modify** `data/ingest.py:653-724` | 消除临时文件：`result_to_parcels()` 和 `result_to_features()` 直接传递字典，并委托给适配器 |
| **Modify** `data/catalog/catalog.py:346-364` | 用 `ADAPTERS[adapter_name].load(data, entry)` 替换 `if adapter_name == "parcels": ... elif ...` |
| **Modify** `data/__init__.py` | 导出 `adapters` 子包 |
| **Create** `tests/unit/test_adapters.py` | 适配器的单元测试 |

---

### Task 1: 适配器基础设施（AdapterResult、IngestAdapter、ADAPTERS）

**Files:**
- Create: `backend/app/modules/data/adapters/__init__.py`
- Test: `backend/tests/unit/test_adapters.py`（部分）

**Interfaces:**
- Consumes: `GisLayerTypeEntry`（来自 `layer_registry.py`，已存在）
- Produces: `AdapterResult` 数据类，`IngestAdapter` 协议，`ADAPTERS: dict[str, IngestAdapter]`，`register_adapter()`

- [ ] **Step 1: 创建 `data/adapters/` 包目录**

```bash
mkdir -p backend/app/modules/data/adapters
```

- [ ] **Step 2: 为适配器基础设施编写失败的测试**

```python
# backend/tests/unit/test_adapters.py
from __future__ import annotations

from typing import Any, Dict

import pytest

from app.modules.data.adapters import (
    ADAPTERS,
    AdapterResult,
    IngestAdapter,
    register_adapter,
)
from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec


def test_adapter_result_defaults():
    result = AdapterResult()
    assert result.features == []
    assert result.warnings == []
    assert result.dlq == []


def test_adapter_result_with_data():
    result = AdapterResult(
        features=["f1", "f2"],
        warnings=["w1"],
        dlq=[{"bsm": "123"}],
    )
    assert len(result.features) == 2
    assert len(result.warnings) == 1
    assert len(result.dlq) == 1


def test_register_adapter():
    class FakeAdapter(IngestAdapter):
        def load(self, data: dict, entry: GisLayerTypeEntry, *, strict: bool = False) -> AdapterResult:
            return AdapterResult(features=[data.get("msg", "ok")])

    register_adapter("test_fake", FakeAdapter())
    assert "test_fake" in ADAPTERS
    entry = GisLayerTypeEntry(gis_type_ref="test", ingest=IngestSpec(adapter="test_fake"))
    result = ADAPTERS["test_fake"].load({"msg": "hello"}, entry)
    assert result.features == ["hello"]
    ADAPTERS.pop("test_fake", None)


def test_ingest_adapter_is_protocol():
    import inspect
    assert inspect.isclass(IngestAdapter)
```

- [ ] **Step 3: 运行测试以验证它们失败**

```bash
cd backend
python -m pytest tests/unit/test_adapters.py -v
```

预期：ModuleNotFoundError 或 ImportError（包还不存在）

- [ ] **Step 4: 编写最小实现**

```python
# backend/app/modules/data/adapters/__init__.py
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

from app.modules.schema.types.layer_registry import GisLayerTypeEntry


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
    dlq: list[dict] = field(default_factory=list)


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
```

- [ ] **Step 5: 运行测试以验证它们通过**

```bash
cd backend
python -m pytest tests/unit/test_adapters.py -v
```

预期：4 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/modules/data/adapters/__init__.py backend/tests/unit/test_adapters.py
git commit -m "feat(phase5): adapter infrastructure — AdapterResult, IngestAdapter protocol, ADAPTERS registry"
```

---

### Task 2: ParcelsAdapter + FeaturesAdapter（消除临时文件）

**Files:**
- Create: `backend/app/modules/data/adapters/parcels.py`
- Create: `backend/app/modules/data/adapters/features.py`
- Test: `backend/tests/unit/test_adapters.py`（追加）

**Interfaces:**
- Consumes: `AdapterResult`, `IngestAdapter`（来自 Task 1），`ingest_landuse()`, `ingest_feature()`（来自 `ingest.py`），`GisLayerTypeEntry`（来自 `layer_registry.py`）
- Produces: `ParcelsAdapter`, `FeaturesAdapter` 已注册到 `ADAPTERS`

**关键洞察：** `_read_geojson()`（第 159-164 行）已经接受字典。`ingest_landuse()` 和 `ingest_feature()` 将它们的第一个参数传递给 `_read_geojson()`，因此它们已经可以使用字典调用。临时文件轮转是不必要的 —— 适配器直接传递 GeoJSON 字典。

- [ ] **Step 1: 为 ParcelsAdapter 和 FeaturesAdapter 编写测试**

```python
# 追加到 backend/tests/unit/test_adapters.py

def test_parcels_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "parcels" in ADAPTERS


def test_features_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "features" in ADAPTERS


def test_parcels_adapter_current_landuse():
    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec

    adapter = ADAPTERS["parcels"]
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {"BSM": "001", "DLBM": "0703", "DLMC": "宅基地"},
            }
        ],
    }
    entry = GisLayerTypeEntry(
        gis_type_ref="landuse_current",
        ingest=IngestSpec(adapter="parcels", feature_type="current_landuse"),
    )
    result = adapter.load(geojson, entry)
    assert len(result.features) >= 1
    p = result.features[0]
    assert p.bsm == "001"
    assert p.layer_type == "landuse_current"


def test_features_adapter_admin_area():
    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec

    adapter = ADAPTERS["features"]
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {"BSM": "A001", "NAME": "金田村"},
            }
        ],
    }
    entry = GisLayerTypeEntry(
        gis_type_ref="admin_area",
        ingest=IngestSpec(adapter="features", feature_type="admin_area"),
    )
    result = adapter.load(geojson, entry)
    assert len(result.features) >= 1
    f = result.features[0]
    assert f.bsm == "A001"
    assert f.layer_type == "admin_area"
```

- [ ] **Step 2: 运行测试以验证它们失败**

```bash
cd backend
python -m pytest tests/unit/test_adapters.py -v
```

预期：FAIL — ImportError，因为 `parcels.py` 和 `features.py` 还不存在

- [ ] **Step 3: 编写 ParcelsAdapter**

```python
# backend/app/modules/data/adapters/parcels.py
"""Parcels adapter — 地类图斑（现状/规划），通过编码验证链。"""

from __future__ import annotations

from typing import Any, Dict

from app.modules.schema.types.layer_registry import GisLayerTypeEntry
from app.utils.logger import get_logger

from ..ingest import ingest_landuse
from . import AdapterResult, IngestAdapter

logger = get_logger(__name__)


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
```

- [ ] **Step 4: 编写 FeaturesAdapter**

```python
# backend/app/modules/data/adapters/features.py
"""Features adapter — 一般点/线/面要素，DU 自动路由。"""

from __future__ import annotations

from typing import Any, Dict

from app.modules.schema.types.layer_registry import GisLayerTypeEntry
from app.utils.logger import get_logger

from ..ingest import ingest_feature
from . import AdapterResult, IngestAdapter

logger = get_logger(__name__)


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
```

- [ ] **Step 5: 运行测试以验证它们通过**

```bash
cd backend
python -m pytest tests/unit/test_adapters.py -v
```

预期：6 passed（4 来自 Task 1 + 2 新注册检查 + 2 集成测试）

- [ ] **Step 6: 提交**

```bash
git add backend/app/modules/data/adapters/parcels.py backend/app/modules/data/adapters/features.py backend/tests/unit/test_adapters.py
git commit -m "feat(phase5): ParcelsAdapter + FeaturesAdapter — eliminate tempfile roundtrip"
```

---

### Task 3: RasterAdapter + TableAdapter + DocumentAdapter 存根

**Files:**
- Create: `backend/app/modules/data/adapters/raster.py`
- Create: `backend/app/modules/data/adapters/table.py`
- Create: `backend/app/modules/data/adapters/document.py`
- Test: `backend/tests/unit/test_adapters.py`（追加）

**Interfaces:**
- Consumes: `AdapterResult`, `IngestAdapter`（来自 Task 1），`ingest_raster()`（来自 `ingest.py`），`GisLayerTypeEntry`
- Produces: 注册到 `ADAPTERS` 的 `RasterAdapter`, `TableAdapter`, `DocumentAdapter`

- [ ] **Step 1: 为 RasterAdapter 和存根编写测试**

```python
# 追加到 backend/tests/unit/test_adapters.py

def test_raster_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "raster" in ADAPTERS


def test_table_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "table" in ADAPTERS


def test_document_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "document" in ADAPTERS


def test_table_adapter_returns_empty():
    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry

    adapter = ADAPTERS["table"]
    entry = GisLayerTypeEntry(gis_type_ref="population")
    result = adapter.load({}, entry)
    assert result.features == []
    assert result.warnings == []


def test_document_adapter_returns_empty():
    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry

    adapter = ADAPTERS["document"]
    entry = GisLayerTypeEntry(gis_type_ref="planning_text")
    result = adapter.load({}, entry)
    assert result.features == []
    assert result.warnings == []
```

- [ ] **Step 2: 运行测试以验证它们失败**

```bash
cd backend
python -m pytest tests/unit/test_adapters.py -v
```

预期：FAIL — ImportError for raster/table/document 模块

- [ ] **Step 3: 编写 RasterAdapter**

```python
# backend/app/modules/data/adapters/raster.py
"""Raster adapter — DEM/DOM/slope 栅格元数据。"""

from __future__ import annotations

from app.modules.schema.types.layer_registry import GisLayerTypeEntry
from app.utils.logger import get_logger

from ..ingest import ingest_raster
from . import AdapterResult, IngestAdapter

logger = get_logger(__name__)


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
```

- [ ] **Step 4: 编写 TableAdapter 存根**

```python
# backend/app/modules/data/adapters/table.py
"""Table adapter — 属性表（人口、建设项目等）。"""

from __future__ import annotations

from app.modules.schema.types.layer_registry import GisLayerTypeEntry
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
```

- [ ] **Step 5: 编写 DocumentAdapter 存根**

```python
# backend/app/modules/data/adapters/document.py
"""Document adapter — 规划文本、L3 报告等。"""

from __future__ import annotations

from app.modules.schema.types.layer_registry import GisLayerTypeEntry
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
```

- [ ] **Step 6: 运行测试以验证它们通过**

```bash
cd backend
python -m pytest tests/unit/test_adapters.py -v
```

预期：10 passed（4 基础设施 + 2 parcels/features + 3 注册 + 2 存根）

- [ ] **Step 7: 提交**

```bash
git add backend/app/modules/data/adapters/raster.py backend/app/modules/data/adapters/table.py backend/app/modules/data/adapters/document.py backend/tests/unit/test_adapters.py
git commit -m "feat(phase5): RasterAdapter + TableAdapter + DocumentAdapter stubs"
```

---

### Task 4: 消除临时文件 + 更新 catalog.py 以使用适配器

**Files:**
- Modify: `backend/app/modules/data/ingest.py:653-724`
- Modify: `backend/app/modules/data/catalog/catalog.py:346-364`

**Interfaces:**
- Consumes: `ADAPTERS`（来自 Task 1），`ParcelsAdapter`, `FeaturesAdapter`, `RasterAdapter`（来自 Tasks 2-3）
- Produces: 更新的 `result_to_parcels()` 和 `result_to_features()` 委托给适配器；更新的 `catalog.py` 使用适配器注册表

- [ ] **Step 1: 为临时文件消除编写测试**

```python
# 添加到 backend/tests/unit/test_adapters.py

def test_result_to_parcels_no_tempfile():
    from app.modules.data.ingest import result_to_parcels
    from app.modules.data.contracts import DataResult

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {"BSM": "001", "DLBM": "0703", "DLMC": "宅基地"},
            }
        ],
    }
    result = DataResult.ok(data=geojson, data_type="geojson")
    parcels, warnings = result_to_parcels(result, layer_type="current_landuse")
    assert len(parcels) >= 1
    assert parcels[0].bsm == "001"


def test_result_to_features_no_tempfile():
    from app.modules.data.ingest import result_to_features
    from app.modules.data.contracts import DataResult

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {"BSM": "A001", "NAME": "金田村"},
            }
        ],
    }
    result = DataResult.ok(data=geojson, data_type="geojson")
    features, warnings = result_to_features(result, "admin_area")
    assert len(features) >= 1
    assert features[0].bsm == "A001"
```

- [ ] **Step 2: 消除 result_to_parcels 中的临时文件**

将 `result_to_parcels()`（第 653-684 行）替换为：

```python
def result_to_parcels(
    result: DataResult,
    layer_type: str = "current_landuse",
    strict: bool = False,
) -> Tuple[List[BaseLandUseParcel], List[str]]:
    """将 DataResult（geojson）转换为通过编码验证的类型化地块。

    使用 ParcelsAdapter 直接解析内存中的字典，无需临时文件。
    """
    geojson = _geojson_from_result(result)
    if geojson is None:
        return [], [result.error or "no geojson data"]

    from .adapters import ADAPTERS
    entry = _make_parcel_entry(layer_type)
    adapter_result = ADAPTERS["parcels"].load(geojson, entry, strict=strict)
    return adapter_result.features, adapter_result.warnings


def _make_parcel_entry(layer_type: str) -> Any:
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec
    return GisLayerTypeEntry(
        gis_type_ref=layer_type,
        ingest=IngestSpec(adapter="parcels", feature_type=layer_type),
    )
```

- [ ] **Step 3: 消除 result_to_features 中的临时文件**

将 `result_to_features()`（第 687-712 行）替换为：

```python
def result_to_features(
    result: DataResult,
    feature_type: str,
) -> Tuple[List[SpatialFeature], List[str]]:
    """将 DataResult（geojson）转换为类型化的空间要素。

    使用 FeaturesAdapter 直接解析内存中的字典，无需临时文件。
    """
    geojson = _geojson_from_result(result)
    if geojson is None:
        return [], [result.error or "no geojson data"]

    from .adapters import ADAPTERS
    entry = _make_feature_entry(feature_type)
    adapter_result = ADAPTERS["features"].load(geojson, entry)
    return adapter_result.features, adapter_result.warnings


def _make_feature_entry(feature_type: str) -> Any:
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec
    return GisLayerTypeEntry(
        gis_type_ref=feature_type,
        ingest=IngestSpec(adapter="features", feature_type=feature_type),
    )
```

- [ ] **Step 4: 从 ingest.py 中删除不再需要的导入**

从 `ingest.py` 的导入中删除 `import tempfile`（第 42 行），如果其他地方没有使用的话。检查是否还有其他引用：

```bash
rg "tempfile" backend/app/modules/data/ingest.py
```

如果没有其他引用，删除 `import tempfile`。

- [ ] **Step 5: 更新 catalog.py 以使用适配器注册表**

将 `catalog.py` 第 346-364 行（`if adapter_name == "parcels": ... elif ...` 链）替换为：

```python
            adapter_name = entry.ingest.adapter
            from ..adapters import ADAPTERS
            adapter = ADAPTERS.get(adapter_name)
            if adapter is None:
                logger.warning(
                    "[DataCatalog] No adapter registered for '%s' (layer '%s')",
                    adapter_name, lt,
                )
                continue
            adapter_result = adapter.load(result.data, entry)
            for feat in adapter_result.features:
                bundle.add(feat)
            if adapter_result.warnings:
                bundle.metadata.crs_warnings.extend(adapter_result.warnings[:5])
```

- [ ] **Step 6: 运行测试**

```bash
cd backend
python -m pytest tests/unit/test_adapters.py -v
```

预期：所有 14 测试通过

```bash
cd backend
python -m pytest tests/unit/ -v --tb=short -q --ignore=tests/unit/test_gis_unit.py
```

预期：全部 ~147 通过（135 现有 + 12 新）

- [ ] **Step 7: 提交**

```bash
git add backend/app/modules/data/ingest.py backend/app/modules/data/catalog/catalog.py backend/tests/unit/test_adapters.py
git commit -m "feat(phase5): eliminate tempfile, replace catalog.py hardcoded switch with ADAPTERS registry"
```

---

### Task 5: 更新 `__init__.py` 导出 + 最终验证

**Files:**
- Modify: `backend/app/modules/data/__init__.py`

- [ ] **Step 1: 从 data/__init__.py 导出适配器子包**

在 `data/__init__.py` 的导入部分（第 32 行附近）添加：

```python
from . import adapters
```

在 `__all__` 列表中添加：

```python
    # Adapters
    "adapters",
```

- [ ] **Step 2: 运行完整测试套件**

```bash
cd backend
python -m pytest tests/unit/ -v --tb=short -q --ignore=tests/unit/test_gis_unit.py
```

预期：所有测试通过

- [ ] **Step 3: 通过 linting 验证导入**

```bash
cd backend
python -c "from app.modules.data import adapters; print('adapters:', list(adapters.ADAPTERS.keys()))"
```

预期：`adapters: ['parcels', 'features', 'raster', 'table', 'document']`

- [ ] **Step 4: 提交**

```bash
git add backend/app/modules/data/__init__.py
git commit -m "feat(phase5): export adapters subpackage from data module"
```

---

## 自检

**1. 规范覆盖：**
- §5.2 adapter 策略模式（6 标准适配器）→ Task 1（基础设施）+ Task 2-3（实现）
- §5.5 消除 tempfile → Task 4（`result_to_parcels`/`result_to_features` 使用字典直接调用 `ingest_*`）
- `field_mapping` 用 alias 替代 → 已在 Phase 3 完成，无需操作
- 类型路由：`catalog.py` 中的硬编码 switch 被替换 → Task 4 步骤 5

**2. 占位符扫描：** 无占位符——所有代码块都是完整的最小实现。

**3. 类型一致性：** `AdapterResult` 在所有任务中一致使用，`IngestAdapter` 协议签名在所有实现中匹配（`load(self, data, entry, *, strict=False) -> AdapterResult`）。