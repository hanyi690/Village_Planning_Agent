# EXPLORE KG-Enrichment 闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 EXPLORE 在每轮报告生成后把报告中的自然村地名绑定到 KG 地块 BSM 并持久化，同时把空间认知 brief 注入 L1 prompt，形成"报告 → binding → KG 语义记忆"的强化闭环。

**Architecture:** 7 个子任务按 H→B→D→C→E→A→G 顺序落地。H 为 SemanticMemoryStore 增加轮次持久化；B 新增 BridgeAdvisor 产出自然语言 SpatialCognitionBrief（含村内/村外区分）；D 在 `_build_prompt` L1 分支把 brief 注入到 `**输出骨架**` 之前（不改 L1 模板）；C 在 PARSE agent 新增 `extract_bindings`（Flash LLM + kgg 三重 write-gate 含村界包含校验 + pending_review 队列）；E 在 completion node 的 wave 完成点触发 C；A 用真实金田村数据跑全流程；G 输出端到端验证报告。

**Tech Stack:** Python 3 (pydantic v2, langchain ChatOpenAI via `create_llm`), rdflib-based PlanningKG, SQLite ReportStore, pytest。零新依赖。

## Global Constraints

- 测试一律在 `backend/` 目录下运行：`python -m pytest tests/unit/<file> -v`（有 `tests/conftest.py`）。
- 单元测试禁止网络调用：LLM 一律传 `llm=None` 或 monkeypatch；KG/bundle 一律注入 fake。
- 管线永不因 enrichment 失败而中断：所有 EXPLORE/PARSE 调用点必须 try/except + `logger.warning`，失败返回空串/空 stats。
- 不改任何 L1 prompt 模板（`backend/app/modules/prompts/l1/*.py`），注入只发生在 `_build_prompt` 返回字符串之后。
- BSM 一律匹配 `\d{15,25}`（真实数据 18 位如 `441426211000049104`，KG 模板 20 位如 `44142611020200000563`）。
- commit message 用 conventional 风格：`feat(scope): 描述`（见 git log 既有风格）。
- 当前分支：`feature/flash-llm-explore-agent`（所有 commit 都落在此分支）。
- **村内/村外铁律（已用 point-in-polygon 实测验证）：**
  * `annotation.geojson` 中 分类='村名' 的 4 个注记点（八社村/上举村/符坑村/文贵村）全部位于
    金田村村界（MultiPolygon）之外 → 它们是毗邻的行政村（村外），严禁绑定到金田村地块；
  * 金田村内部居民点/自然村共 12 个（规划文本 L160）：园寨、田坑、社前、分水、清明、
    塘笃、长塘、炉池、肩丰、营仔、新山、黄竹 —— 在 bundle 中无注记点，空间基座=村界内地块集合；
  * 任何"村名↔BSM"绑定必须通过 村界包含 校验（point-in-polygon，非 bbox）；村界 geometry 取
    `bundle.polygons.get("admin_areas")`，缺失时回退 `planning_scope`。
- `VillageBundle.add(feature)` 单参数：按几何类型自动路由到 points/lines/polygons，
  LayerGroup 再按 `feature.layer_type` 经 registry 落 key（`admin_area`→`admin_areas`，
  `current_annotation`→`annotations_current`，`landuse_current`→`landuse_current`）。
  测试里构造特征必须用 Pydantic 特征对象（PolygonFeature/CurrentAnnotation），不能传 GeoJSON dict；
  地块特征的 layer_type 必须写 `landuse_current`（写 `landuse` 会落到 "inferred" key，查不到）。
- 测试 fake 村界矩形取 `[116.00..116.10]×[24.80..24.84]`（y 上界 24.84）：保证村内点
  `(116.05, 24.835)` 在界内、真实村外点八社村 `(116.047, 24.850)` 与上举村 `(115.996, 24.812)` 在界外。

---

### Task 1: H — SemanticMemoryStore 轮次持久化

**Files:**
- Modify: `backend/app/modules/kg/memory.py`
- Test: `backend/tests/unit/test_memory_persistence.py` (new)

**Interfaces:**
- Consumes: 现有 `EntityAnnotation`/`SemanticMemoryStore`/`get_semantic_memory()`；`app.core.settings.DATA_DIR`。
- Produces（后续 C/A/G 依赖）:
  - `EntityAnnotation` 新增字段 `round_added: int = 1`, `valid_from_round: int = 1`, `valid_until_round: Optional[int] = None`, `confidence: float = 1.0`
  - `SemanticMemoryStore.from_dict(cls, data) -> SemanticMemoryStore`
  - `SemanticMemoryStore.supersede(self, annotation: EntityAnnotation) -> bool`
  - `diff_round(previous, current) -> Dict[str, Any]` 返回 `{"added": list[str], "superseded": list[str], "unchanged": int}`
  - `get_memory_dir() -> Path`（`<DATA_DIR>/kg_memory`，自动创建）
  - `memory_state_path(session_id: str, round_num: int) -> Path`
  - `save_memory_state(session_id, round_num, store=None) -> Path`（默认用单例）
  - `load_memory_state(session_id, round_num) -> SemanticMemoryStore`（文件缺失返回空 store）

- [ ] **Step 1: 写失败测试** `backend/tests/unit/test_memory_persistence.py`

```python
"""H 子任务：SemanticMemoryStore 轮次持久化单测。"""
from pathlib import Path

import pytest

from app.modules.kg.memory import (
    EntityAnnotation,
    SemanticMemoryStore,
    diff_round,
    load_memory_state,
    save_memory_state,
)


@pytest.fixture
def tmp_memory_dir(monkeypatch, tmp_path: Path):
    import app.modules.kg.memory as mem
    monkeypatch.setattr(mem, "get_memory_dir", lambda: tmp_path)
    return tmp_path


def test_entity_annotation_round_defaults():
    ann = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel")
    assert ann.round_added == 1
    assert ann.valid_from_round == 1
    assert ann.valid_until_round is None
    assert ann.confidence == 1.0


def test_from_dict_round_trip_all_fields():
    data = {
        "entity_annotations": {
            "pln:parcel_1": {
                "entity_type": "Parcel",
                "description": "田坑自然村耕地",
                "source_text_refs": ["land_use"],
                "intent_refs": [],
                "round_added": 2,
                "valid_from_round": 2,
                "valid_until_round": None,
                "confidence": 0.9,
            }
        },
        "relation_annotations": {},
    }
    store = SemanticMemoryStore.from_dict(data)
    ann = store.entity_annotations["pln:parcel_1"]
    assert ann.round_added == 2
    assert ann.valid_from_round == 2
    assert ann.confidence == 0.9


def test_from_dict_backward_compat_old_format():
    # 旧 to_dict 输出没有 round/confidence 字段 → 默认值补齐
    old = {
        "entity_annotations": {
            "pln:parcel_1": {
                "entity_type": "Parcel",
                "description": "旧注解",
                "source_text_refs": [],
                "intent_refs": [],
            }
        },
        "relation_annotations": {},
    }
    store = SemanticMemoryStore.from_dict(old)
    ann = store.entity_annotations["pln:parcel_1"]
    assert ann.round_added == 1
    assert ann.valid_until_round is None
    assert ann.confidence == 1.0


def test_supersede_marks_old_valid_until():
    store = SemanticMemoryStore()
    old = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="旧", confidence=0.5, round_added=1)
    store.add_entity_annotation(old)
    new = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="新", confidence=0.9, round_added=2)
    assert store.supersede(new) is True
    ann = store.entity_annotations["pln:parcel_1"]
    assert ann.description == "新"
    assert old.valid_until_round == 2


def test_supersede_rejects_lower_or_equal_confidence():
    store = SemanticMemoryStore()
    old = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="旧", confidence=0.9, round_added=1)
    store.add_entity_annotation(old)
    new = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="低置信", confidence=0.5, round_added=2)
    assert store.supersede(new) is False
    assert store.entity_annotations["pln:parcel_1"].description == "旧"


def test_diff_round_counts():
    prev = SemanticMemoryStore()
    prev.add_entity_annotation(EntityAnnotation(entity_uri="pln:a", entity_type="Parcel", round_added=1))
    cur = SemanticMemoryStore()
    cur.add_entity_annotation(EntityAnnotation(entity_uri="pln:a", entity_type="Parcel", round_added=2, confidence=0.9))
    cur.add_entity_annotation(EntityAnnotation(entity_uri="pln:b", entity_type="Parcel", round_added=2))
    diff = diff_round(prev, cur)
    assert "pln:b" in diff["added"]
    assert isinstance(diff["unchanged"], int)


def test_save_load_round_trip(tmp_memory_dir):
    store = SemanticMemoryStore()
    store.add_entity_annotation(
        EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="田坑", round_added=3, confidence=0.8)
    )
    path = save_memory_state("sess_x", 3, store)
    assert path.name == "sess_x_round_3.json"
    assert path.exists()

    loaded = load_memory_state("sess_x", 3)
    ann = loaded.entity_annotations["pln:parcel_1"]
    assert ann.description == "田坑"
    assert ann.round_added == 3
    assert ann.confidence == 0.8


def test_load_missing_round_returns_empty_store(tmp_memory_dir):
    store = load_memory_state("sess_missing", 9)
    assert isinstance(store, SemanticMemoryStore)
    assert store.entity_annotations == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run (workdir `backend`): `python -m pytest tests/unit/test_memory_persistence.py -v`
Expected: FAIL — `ImportError` / AttributeError（`from_dict`、`supersede`、`diff_round` 等不存在；`EntityAnnotation` 无 `round_added` 字段）。

- [ ] **Step 3: 实现** — patch `backend/app/modules/kg/memory.py`

文件头加 `import json`、`from pathlib import Path`。

```python
@dataclass
class EntityAnnotation:
    """实体注解 — 附着于空间实体的语义说明"""
    entity_uri: str
    entity_type: str
    description: str = ""
    source_text_refs: List[str] = field(default_factory=list)
    intent_refs: List[str] = field(default_factory=list)
    round_added: int = 1
    valid_from_round: int = 1
    valid_until_round: Optional[int] = None
    confidence: float = 1.0
```

`to_dict()` 的 entity 分支改为（新增 4 个 key）：

```python
            "entity_annotations": {
                uri: {
                    "entity_type": ann.entity_type,
                    "description": ann.description,
                    "source_text_refs": ann.source_text_refs,
                    "intent_refs": ann.intent_refs,
                    "round_added": ann.round_added,
                    "valid_from_round": ann.valid_from_round,
                    "valid_until_round": ann.valid_until_round,
                    "confidence": ann.confidence,
                }
                for uri, ann in self.entity_annotations.items()
            },
```

`SemanticMemoryStore` 类内追加两个方法（放在 `to_dict` 之后）：

```python
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SemanticMemoryStore":
        """Restore a store from ``to_dict()`` output (old format tolerated)."""
        store = cls()
        for uri, raw in (data.get("entity_annotations") or {}).items():
            store.entity_annotations[uri] = EntityAnnotation(
                entity_uri=uri,
                entity_type=raw.get("entity_type", ""),
                description=raw.get("description", ""),
                source_text_refs=list(raw.get("source_text_refs") or []),
                intent_refs=list(raw.get("intent_refs") or []),
                round_added=int(raw.get("round_added", 1)),
                valid_from_round=int(raw.get("valid_from_round", 1)),
                valid_until_round=int(raw["valid_until_round"]) if raw.get("valid_until_round") else None,
                confidence=float(raw.get("confidence", 1.0)),
            )
        for key, raw in (data.get("relation_annotations") or {}).items():
            store.relation_annotations[key] = RelationAnnotation(
                subject_uri=raw.get("subject", ""),
                predicate=raw.get("predicate", ""),
                object_uri=raw.get("object", ""),
                description=raw.get("description", ""),
                derived_from=raw.get("derived_from", ""),
                quantitative_detail=dict(raw.get("quantitative_detail") or {}),
            )
        return store

    def supersede(self, annotation: EntityAnnotation) -> bool:
        """Replace an annotation only when the new confidence is higher."""
        existing = self.entity_annotations.get(annotation.entity_uri)
        if existing is None or existing.confidence >= annotation.confidence:
            return False
        existing.valid_until_round = annotation.round_added
        self.entity_annotations[annotation.entity_uri] = annotation
        return True
```

模块级追加（放在 `__all__` 之前）：

```python
# ── Round persistence (data/kg_memory/{session_id}_round_{N}.json) ──


def get_memory_dir() -> Path:
    from app.core.settings import DATA_DIR

    d = DATA_DIR / "kg_memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_state_path(session_id: str, round_num: int) -> Path:
    return get_memory_dir() / f"{session_id}_round_{round_num}.json"


def save_memory_state(
    session_id: str,
    round_num: int,
    store: Optional[SemanticMemoryStore] = None,
) -> Path:
    store = store if store is not None else get_semantic_memory()
    path = memory_state_path(session_id, round_num)
    path.write_text(json.dumps(store.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_memory_state(session_id: str, round_num: int) -> SemanticMemoryStore:
    path = memory_state_path(session_id, round_num)
    if not path.exists():
        return SemanticMemoryStore()
    data = json.loads(path.read_text(encoding="utf-8"))
    return SemanticMemoryStore.from_dict(data)


def diff_round(
    previous: Optional[SemanticMemoryStore],
    current: SemanticMemoryStore,
) -> Dict[str, Any]:
    if previous is None:
        return {
            "added": list(current.entity_annotations.keys()),
            "superseded": [],
            "unchanged": 0,
        }
    added, superseded, unchanged = [], [], 0
    for uri, ann in current.entity_annotations.items():
        old = previous.entity_annotations.get(uri)
        if old is None:
            added.append(uri)
        elif old.valid_until_round is not None:
            superseded.append(uri)
        else:
            unchanged += 1
    return {"added": added, "superseded": superseded, "unchanged": unchanged}
```

`__all__` 追加：`"get_memory_dir", "memory_state_path", "save_memory_state", "load_memory_state", "diff_round"`。

- [ ] **Step 4: 跑测试确认通过**

Run (workdir `backend`): `python -m pytest tests/unit/test_memory_persistence.py -v`
Expected: PASS（8 个）；顺带跑 `python -m pytest tests/unit/test_explore_flash_agent.py -v` 确认 stage-0 未回归。

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/kg/memory.py backend/tests/unit/test_memory_persistence.py
git commit -m "feat(kg): add round-aware memory persistence (from_dict/supersede/diff/save/load)"
```

---

### Task 2: B — BridgeAdvisor 空间认知 brief（含村内/村外区分）

**Files:**
- Create: `backend/app/agent/explore/bridge_advisor.py`
- Modify: `backend/app/modules/spatial_ops/geometry.py`（新增 2 个公共 helper）
- Test: `backend/tests/unit/test_bridge_advisor.py` (new)

**Interfaces:**
- Consumes: `app.tools.access.shared.resolve_bundle/session_kg`（既有）；`app.modules.kg.queries.cognition.get_village_cognition`（既有）；`get_semantic_memory`（Task 1）；bundle `points.annotations_*` 的 `CurrentAnnotation`（`text`/`category` 字段，alias `注记`/`分类`）。
- Produces（D 依赖）:
  - `point_in_polygon(point: Tuple[float, float], geometry: Dict[str, Any]) -> bool`（ray-casting，支持 Polygon/MultiPolygon）
  - `village_boundary_geometry(bundle: Any) -> Optional[Dict[str, Any]]`（取 `admin_areas` 第一个，回退 `planning_scope`）
  - `@dataclass SpatialCognitionBrief`: `village_overview: str`, `spatial_pattern: str`, `spatial_constraints: str`, `relevant_entities: str`, `focus_hints: List[str]`, `kg_confidence: float`, `external_villages: List[str] = field(default_factory=list)`（村外毗邻行政村，明确标注）
  - `class BridgeAdvisor: __init__(self, session_id: str, llm: Any = None)`；`async compose_dim_brief(self, dim_key: str, dim_layer: int) -> SpatialCognitionBrief`（确定性合成，`llm` 仅预留 refinement 入口，默认 None 不调网络）
  - `format_brief_section(brief: SpatialCognitionBrief) -> str`（以 `**【EXPLORE 空间基础（供分析参考）】**` 开头的 markdown 段；村外村列表输出为 `- 毗邻行政村（村外，非本村居民点）：...`）

- [ ] **Step 1: 写失败测试** `backend/tests/unit/test_bridge_advisor.py`

```python
"""B 子任务：BridgeAdvisor 单测（llm=None 确定性路径，无网络）。"""
import asyncio

import pytest

from app.agent.explore.bridge_advisor import (
    BridgeAdvisor,
    SpatialCognitionBrief,
    format_brief_section,
)
from app.modules.schema.types.base import PolygonFeature
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import CurrentAnnotation


def _boundary_polygon():
    return PolygonFeature(
        geometry={
            "type": "MultiPolygon",
            "coordinates": [[[[116.00, 24.80], [116.10, 24.80], [116.10, 24.84], [116.00, 24.84], [116.00, 24.80]]]],
        },
        layer_type="admin_area",
    )


class _FakeKG:
    village_name = "金田村"


async def _fake_resolve_bundle(session_id: str):
    bundle = VillageBundle(village_name="金田村")
    bundle.add(_boundary_polygon())
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.047, 24.850]},
            layer_type="current_annotation", text="八社村", category="村名",
        ),
    )
    return bundle


def test_point_in_polygon_ray_casting():
    from app.modules.spatial_ops.geometry import point_in_polygon

    poly = {
        "type": "MultiPolygon",
        "coordinates": [[[[116.00, 24.80], [116.10, 24.80], [116.10, 24.84], [116.00, 24.84], [116.00, 24.80]]]],
    }
    assert point_in_polygon((116.05, 24.835), poly) is True    # 村内
    assert point_in_polygon((116.047, 24.850), poly) is False   # 村外（八社村实测点）
    assert point_in_polygon((115.996, 24.812), poly) is False   # 村外（上举村实测点）


def test_village_boundary_geometry_finds_admin_areas():
    from app.modules.spatial_ops.geometry import village_boundary_geometry

    bundle = VillageBundle(village_name="金田村")
    bundle.add(_boundary_polygon())
    assert village_boundary_geometry(bundle) is not None


def test_compose_dim_brief_separates_internal_and_external_villages(monkeypatch):
    import app.agent.explore.bridge_advisor as ba
    import app.tools.access.shared as shared

    monkeypatch.setattr(shared, "resolve_bundle", _fake_resolve_bundle)
    monkeypatch.setattr(shared, "session_kg", lambda sid: _FakeKG())

    advisor = BridgeAdvisor(session_id="sess-brief2")
    brief = asyncio.run(advisor.compose_dim_brief("land_use", 1))

    assert isinstance(brief, SpatialCognitionBrief)
    assert "八社村" not in brief.relevant_entities   # 村外不进 relevant
    assert brief.external_villages == ["八社村"]      # 明确标为村外
    section = format_brief_section(brief)
    assert "毗邻行政村（村外，非本村居民点）" in section


def test_compose_dim_brief_no_session_returns_empty_safe(monkeypatch):
    import app.agent.explore.bridge_advisor as ba
    import app.tools.access.shared as shared

    monkeypatch.setattr(shared, "resolve_bundle", _fake_resolve_bundle)
    monkeypatch.setattr(shared, "session_kg", lambda sid: None)

    advisor = BridgeAdvisor(session_id="sess-nokg")
    brief = asyncio.run(advisor.compose_dim_brief("traffic", 1))
    assert isinstance(brief, SpatialCognitionBrief)


def test_format_brief_section_contains_entities():
    brief = SpatialCognitionBrief(
        village_overview="金田村，总面积200公顷，共660个地块",
        spatial_pattern="村庄沿公王河呈组团式布局",
        spatial_constraints="永久基本农田81.43公顷",
        relevant_entities="田坑自然村、黄竹自然村",
        focus_hints=["关注田坑耕地集中区"],
        kg_confidence=0.8,
    )
    section = format_brief_section(brief)
    assert section.startswith("**【EXPLORE 空间基础（供分析参考）】**")
    assert "田坑自然村" in section
    assert "0.8" in section
```

- [ ] **Step 2: 跑测试确认失败**

Run (workdir `backend`): `python -m pytest tests/unit/test_bridge_advisor.py -v`
Expected: FAIL — `ModuleNotFoundError: app.agent.explore.bridge_advisor`。

- [ ] **Step 3: 实现**

(a) `backend/app/modules/spatial_ops/geometry.py` 末尾追加：

```python
def point_in_polygon(point: Tuple[float, float], geometry: Dict[str, Any]) -> bool:
    """Ray-casting point-in-polygon for GeoJSON Polygon/MultiPolygon (pure python)."""
    if not point or not geometry:
        return False
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        coords = [coords]
    px, py = float(point[0]), float(point[1])
    for poly in coords:
        if not poly:
            continue
        ring = poly[0] if isinstance(poly[0], list) else poly
        inside = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = float(ring[i][0]), float(ring[i][1])
            xj, yj = float(ring[j][0]), float(ring[j][1])
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        if inside:
            return True
    return False


def village_boundary_geometry(bundle: Any) -> Optional[Dict[str, Any]]:
    """First village boundary polygon (admin_areas, fallback planning_scope)."""
    if bundle is None:
        return None
    for key in ("admin_areas", "planning_scope"):
        for f in bundle.polygons.get(key) or []:
            geom = getattr(f, "geometry", None) or (f.get("geometry") if isinstance(f, dict) else None)
            if geom:
                return geom
    return None
```

（确认 `geometry.py` 已有 `Tuple`/`Optional`/`Dict`/`Any` 的 typing import；没有则补 `from typing import Any, Dict, Optional, Tuple`。`__all__` 如有则追加两个函数名。）

(b) `backend/app/agent/explore/bridge_advisor.py`（create）：

```python
"""BridgeAdvisor — 组合 EXPLORE 空间认知 brief（纯自然语言，供 L1 注入）。

Deterministic by default (no LLM): composes KG three-layer cognition, bundle
annotation points (村内自然村 vs 村外毗邻行政村) and semantic-memory
annotations into a ``SpatialCognitionBrief``.  An optional Flash ``llm`` is
accepted for future refinement but is never required for the baseline path.

村内/村外铁律：annotation.geojson 中 分类='村名' 的注记点若位于村界外（如
八社村/上举村/符坑村/文贵村）是毗邻行政村，归入 external_villages，绝不进
relevant_entities；村内 12 个自然村（田坑/黄竹/园寨等）无注记点，由 KG 语义
记忆与地块清单承载。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.utils.logger import get_logger

logger = get_logger(__name__)

_DIM_HINTS: Dict[str, List[str]] = {
    "land_use": ["关注田坑/黄竹等自然村的耕地集中区与建设用地形态"],
    "natural_environment": ["关注公王河水系与林地斑块的空间分布"],
    "ecological_green": ["关注生态保护红线与地块重叠的约束"],
    "traffic": ["关注通村道路走向、宽度与自然村连通性"],
    "public_services": ["关注设施点与自然村的服务半径覆盖"],
    "socio_economic": ["结合自然村人口分布核对经济数据"],
}


@dataclass
class SpatialCognitionBrief:
    """纯自然语言空间认知，注入 L1 prompt 的 reference 位置。"""
    village_overview: str
    spatial_pattern: str
    spatial_constraints: str
    relevant_entities: str
    focus_hints: List[str] = field(default_factory=list)
    kg_confidence: float = 0.0
    external_villages: List[str] = field(default_factory=list)


class BridgeAdvisor:
    """Deterministic composition of KG cognition + bundle stats + memory."""

    def __init__(self, session_id: str, llm: Any = None):
        self.session_id = session_id
        self.llm = llm  # reserved for Flash refinement; baseline is deterministic

    async def compose_dim_brief(self, dim_key: str, dim_layer: int) -> SpatialCognitionBrief:
        from app.tools.access.shared import resolve_bundle, session_kg

        bundle = await resolve_bundle(self.session_id)
        kg = session_kg(self.session_id)

        overview = ""
        pattern = ""
        constraints = ""
        kg_confidence = 0.0
        if kg is not None:
            try:
                from app.modules.kg.queries.cognition import get_village_cognition

                result = get_village_cognition(kg, bundle.village_name or "", mode="full")
                ctx = result.semantic.get("context_block") or {}
                overview = str(ctx.get("overview", ""))
                pattern = str(ctx.get("spatial_pattern", ""))
                cb = result.semantic.get("constraint_block") or {}
                constraints = str(cb.get("constraint_coverage", ""))
                kg_confidence = 0.8 if ctx.get("parcel_count") else 0.3
            except Exception as e:
                logger.warning("[BridgeAdvisor] KG cognition failed: %s", e)

        entities, external = self._build_entity_lines(bundle, kg)
        hints = list(_DIM_HINTS.get(dim_key, []))
        if not hints:
            hints.append("结合现状图核对空间布局描述")

        try:
            from app.modules.kg import get_semantic_memory

            bound = len(get_semantic_memory().entity_annotations)
            if bound:
                kg_confidence = min(1.0, kg_confidence + 0.1)
        except Exception:
            pass

        return SpatialCognitionBrief(
            village_overview=overview,
            spatial_pattern=pattern,
            spatial_constraints=constraints,
            relevant_entities="；".join(entities) if entities else "KG 尚未绑定村内自然村地名",
            focus_hints=hints,
            kg_confidence=kg_confidence,
            external_villages=external,
        )

    def _build_entity_lines(self, bundle: Any, kg: Any) -> List[str]:
        names: List[str] = []
        external: List[str] = []
        if bundle is not None:
            from app.modules.spatial_ops.geometry import (
                point_in_polygon,
                village_boundary_geometry,
            )

            boundary = village_boundary_geometry(bundle)
            for group in ("annotations_current", "annotations_planned"):
                for f in bundle.points.get(group) or []:
                    text = str(getattr(f, "text", "") or "")
                    category = str(getattr(f, "category", "") or "")
                    if category != "村名" or not text:
                        continue
                    geom = getattr(f, "geometry", {}) or {}
                    c = geom.get("coordinates") or []
                    if len(c) == 2:
                        point = (float(c[0]), float(c[1]))
                        inside = point_in_polygon(point, boundary) if boundary else True
                        (names if inside else external).append(text)
        names = list(dict.fromkeys(names))
        external = list(dict.fromkeys(external))
        try:
            from app.modules.kg import get_semantic_memory

            mem = get_semantic_memory()
            for uri, ann in mem.entity_annotations.items():
                label = (ann.description or uri)[:20]
                if label not in names:
                    names.append(label)
        except Exception:
            pass
        if kg is not None:
            try:
                from app.modules.kg import get_parcels_semantic_list

                for p in get_parcels_semantic_list(kg)[:5]:
                    desc = p.get("description", "")
                    if desc and desc not in names:
                        names.append(desc)
            except Exception as e:
                logger.debug("[BridgeAdvisor] parcel list failed: %s", e)
        return names, external


def format_brief_section(brief: SpatialCognitionBrief) -> str:
    """Render the brief as a markdown block for prompt injection."""
    lines = [
        "**【EXPLORE 空间基础（供分析参考）】**",
        f"- 村域概况：{brief.village_overview or '数据中未提供'}",
        f"- 空间格局：{brief.spatial_pattern or '数据中未提供'}",
        f"- 空间约束：{brief.spatial_constraints or '数据中未提供'}",
        f"- 关键实体（村内）：{brief.relevant_entities}",
        f"- 参考提示：{'；'.join(brief.focus_hints[:3])}",
        f"- KG 置信度：{brief.kg_confidence:.2f}",
    ]
    if brief.external_villages:
        lines.append(f"- 毗邻行政村（村外，非本村居民点）：{'、'.join(brief.external_villages[:6])}")
    return "\n".join(lines)


__all__ = ["SpatialCognitionBrief", "BridgeAdvisor", "format_brief_section"]
```

- [ ] **Step 4: 跑测试确认通过**

Run (workdir `backend`): `python -m pytest tests/unit/test_bridge_advisor.py -v`
Expected: PASS（5 个）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/geometry.py backend/app/agent/explore/bridge_advisor.py backend/tests/unit/test_bridge_advisor.py
git commit -m "feat(explore): add BridgeAdvisor spatial cognition brief with internal/external village split"
```

---

### Task 3: D — L1 prompt 注入 EXPLORE brief

**Files:**
- Modify: `backend/app/agent/analysis/node.py`（`analyze_dimension` step 5.6 附近、`_build_prompt` L1 分支）
- Test: `backend/tests/unit/test_brief_prompt_injection.py` (new)

**Interfaces:**
- Consumes: Task 2 的 `BridgeAdvisor`/`format_brief_section`；`get_layer1_prompt`（既有）。
- Produces: `_build_explore_brief(state) -> str`（async，失败返回 ""）；`_build_prompt(..., explore_brief_section: str = "")`（新末位参数，L1 分支把 brief 插到 `**输出骨架**` 之前；L2/L3 不注入）。

- [ ] **Step 1: 写失败测试** `backend/tests/unit/test_brief_prompt_injection.py`

```python
"""D 子任务：L1 prompt 注入 EXPLORE brief 单测。"""
import pytest

from app.agent.analysis.node import _build_prompt
from app.config import get_dimension_config

BRIEF_SECTION = (
    "**【EXPLORE 空间基础（供分析参考）】**\n"
    "- 村域概况：金田村，总面积200公顷\n"
    "- 关键实体（村内）：田坑自然村\n"
)


def test_build_prompt_l1_injects_brief_before_skeleton():
    cfg = get_dimension_config("land_use")
    prompt = _build_prompt(
        cfg,
        {"dimension_key": "land_use", "config": {}},
        "",
        "",
        "",
        explore_brief_section=BRIEF_SECTION,
    )
    assert "**输出骨架**" in prompt
    assert prompt.index(BRIEF_SECTION) < prompt.index("**输出骨架**")


def test_build_prompt_l1_empty_brief_is_noop():
    cfg = get_dimension_config("land_use")
    prompt_a = _build_prompt(cfg, {"dimension_key": "land_use", "config": {}}, "", "", "")
    prompt_b = _build_prompt(
        cfg, {"dimension_key": "land_use", "config": {}}, "", "", "",
        explore_brief_section="",
    )
    assert prompt_a == prompt_b
    assert "EXPLORE 空间基础" not in prompt_a


def test_build_prompt_l2_ignores_brief():
    cfg = get_dimension_config("development_goals")
    layer = getattr(cfg, "layer", 2)
    if layer != 2:
        pytest.skip("dimension not L2")
    prompt = _build_prompt(
        cfg,
        {"dimension_key": "development_goals", "config": {}},
        "",
        "",
        "",
        explore_brief_section=BRIEF_SECTION,
    )
    assert "EXPLORE 空间基础" not in prompt
```

- [ ] **Step 2: 跑测试确认失败**

Run (workdir `backend`): `python -m pytest tests/unit/test_brief_prompt_injection.py -v`
Expected: FAIL — `TypeError: _build_prompt() got an unexpected keyword argument 'explore_brief_section'`。

- [ ] **Step 3: 实现** — patch `backend/app/agent/analysis/node.py`

(a) `_build_prompt` 签名（第 812 行）改为：

```python
def _build_prompt(cfg, state, rag_context, deps: str = "", same_layer_contexts: str = "", professional_data_section: str = "", explore_brief_section: str = "") -> str:
```

L1 分支（`if layer == 1:` 内）改为：

```python
    if layer == 1:
        prompt = get_layer1_prompt(
            dimension_key=dim_key,
            raw_data=village_data + professional_data_section,
            village_name=village_name,
            task_description=task_desc,
            constraints=constraints,
            knowledge_context=rag_context or "",
            revision_instruction=revision_instruction,
            has_images=bool(state.get("image_ids")),
        )
        # D: EXPLORE brief 注入到 输出骨架 之前（不改 L1 模板）
        if explore_brief_section:
            prompt = prompt.replace(
                "**输出骨架**",
                f"\n\n{explore_brief_section}\n\n**输出骨架**",
                1,
            )
        return prompt
```

(b) `analyze_dimension` step 5.5 之后（第 479 行后）追加 step 5.6：

```python
    # 5.6: EXPLORE 空间认知 brief（纯自然语言，注入 reference 位置）
    explore_brief_section = ""
    try:
        explore_brief_section = await _build_explore_brief(state)
        if explore_brief_section:
            logger.info(f"[analyze_dimension] {dim_key}: EXPLORE brief injected ({len(explore_brief_section)} chars)")
    except Exception as e:
        logger.warning(f"[analyze_dimension] {dim_key}: EXPLORE brief failed: {e}")
```

`_build_prompt(...)` 调用（第 481 行）末尾追加 `explore_brief_section=explore_brief_section`。

(c) `_optimize_semantics` 之后新增模块级函数：

```python
async def _build_explore_brief(state) -> str:
    """Build the EXPLORE spatial cognition brief section (L1 injection).

    Non-fatal: returns "" when the session is unknown or the advisor fails.
    """
    session_id = state.get("session_id", "") if isinstance(state, dict) else ""
    if not session_id:
        return ""
    from app.agent.explore.bridge_advisor import BridgeAdvisor, format_brief_section

    advisor = BridgeAdvisor(session_id=session_id)
    brief = await advisor.compose_dim_brief(
        dim_key=state.get("dimension_key", ""),
        dim_layer=1,
    )
    return format_brief_section(brief)
```

- [ ] **Step 4: 跑测试确认通过**

Run (workdir `backend`): `python -m pytest tests/unit/test_brief_prompt_injection.py tests/unit/test_explore_flash_agent.py -v`
Expected: PASS（3 新 + 9 stage-0）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/analysis/node.py backend/tests/unit/test_brief_prompt_injection.py
git commit -m "feat(analysis): inject EXPLORE spatial cognition brief into L1 prompts"
```

---

### Task 4: C — PARSE `extract_bindings` + kgg write-gate（含村界包含）

**Files:**
- Modify: `backend/app/agent/gis/parse/agent.py`（文件尾追加，`__all__` 扩展）
- Test: `backend/tests/unit/test_parse_extract_bindings.py` (new)

**Interfaces:**
- Consumes: Task 1（`EntityAnnotation`/`get_semantic_memory`/`save_memory_state`/`get_memory_dir`）；Task 2（`point_in_polygon`/`village_boundary_geometry`）；既有 `get_entity_by_bsm`/`get_parcels_semantic_list`（`app.modules.kg` 导出）；`resolve_bundle`；`GIS_EXPLORE_*` settings。
- Produces（E 依赖）:
  - `@dataclass PendingBinding`: `natural_village: Optional[str]`, `feature_type: str`, `candidate_bsms: List[str]`, `description: str`, `confidence: float`, `source_report_keys: List[str]`
  - `async extract_bindings(session_id: str, wave: int, reports: Dict[str, str], llm: Any = None, kg: Any = None, bundle: Any = None) -> Dict[str, Any]`，返回 `{"wave", "extracted", "written", "skipped", "pending_review"}`
  - 内部：`_extract_bindings_deterministic(reports)`、`_extract_bindings_llm(llm, reports, candidate_bsms)`、`_validate_binding(binding, kg, bundle)`、`_find_annotation_point(bundle, name)`、`_point_in_annotation_parcel(point, bsm, bundle)`、`_parcel_inside_boundary(bsm, boundary, bundle)`、`_find_parcel_by_bsm(bundle, bsm)`、`_queue_review(session_id, wave, skipped)`

- [ ] **Step 1: 写失败测试** `backend/tests/unit/test_parse_extract_bindings.py`

```python
"""C 子任务：PARSE extract_bindings 单测（llm=None 确定性路径 + fake KG/bundle）。

村内/村外规则（实测验证）：
  - annotation.geojson 中 分类='村名' 的 4 个注记点（八社村/上举村/符坑村/文贵村）
    全部位于金田村村界外 → 是毗邻行政村（村外），禁止绑定；
  - 村内 12 个自然村（田坑/黄竹/园寨等）无注记点 → 以"地块中心点在村界内"为空间基座。
"""
from pathlib import Path

import pytest

from app.agent.gis.parse.agent import PendingBinding, extract_bindings
from app.modules.kg import get_kg_manager
from app.modules.schema.types.base import PolygonFeature
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import CurrentAnnotation


class _FakeKG:
    """只支持 get_entity_by_bsm 语义的 fake；get_parcels_semantic_list 抛错走 fallback。"""

    def __init__(self, known_bsms):
        self.known_bsms = set(known_bsms)

    def get_entity_by_bsm(self, bsm, entity_type=None):
        if bsm in self.known_bsms:
            return {"uri": f"pln:parcel_{bsm}", "type": "Parcel"}
        return None


_BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[116.00, 24.80], [116.10, 24.80], [116.10, 24.84], [116.00, 24.84], [116.00, 24.80]]]],
}


def _make_bundle_with_boundary() -> VillageBundle:
    bundle = VillageBundle(village_name="金田村")
    bundle.add(PolygonFeature(geometry=_BOUNDARY, layer_type="admin_area"))
    bundle.add(
        PolygonFeature(
            geometry={
                "type": "MultiPolygon",
                "coordinates": [[[[116.04, 24.83], [116.06, 24.83], [116.06, 24.84], [116.04, 24.84], [116.04, 24.83]]]],
            },
            bsm="441426211000049104", layer_type="landuse_current",
        ),
    )
    # 村外毗邻行政村注记点（实测在村界外）
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.047, 24.850]},
            layer_type="current_annotation", text="八社村", category="村名",
        ),
    )
    return bundle


REPORT = (
    "田坑自然村（BSM 441426211000049104）现有耕地12.5公顷，"
    "黄竹自然村依托南药种植发展林下经济。"
)


def test_deterministic_extractor_picks_village_bsm_pairs():
    from app.agent.gis.parse.agent import _extract_bindings_deterministic

    bindings = _extract_bindings_deterministic({"land_use": REPORT})
    assert len(bindings) >= 1
    b = bindings[0]
    assert b.natural_village == "田坑自然村"
    assert "441426211000049104" in b.candidate_bsms
    assert b.source_report_keys == ["land_use"]


def test_validate_accepts_internal_village_without_annotation():
    """田坑自然村无注记点，但地块中心在村界内 → 通过。"""
    from app.agent.gis.parse.agent import _validate_binding

    binding = PendingBinding(
        natural_village="田坑自然村", feature_type="parcel",
        candidate_bsms=["441426211000049104"], description="田坑耕地", confidence=0.8,
        source_report_keys=["land_use"],
    )
    ok, reason = _validate_binding(binding, _FakeKG({"441426211000049104"}), _make_bundle_with_boundary())
    assert ok, reason


def test_validate_rejects_external_admin_village():
    """八社村 注记点在村界外 → 拒绝（村外毗邻行政村，非本村居民点）。"""
    from app.agent.gis.parse.agent import _validate_binding

    binding = PendingBinding(
        natural_village="八社村", feature_type="parcel",
        candidate_bsms=["441426211000049104"], description="八社村", confidence=0.9,
        source_report_keys=["land_use"],
    )
    ok, reason = _validate_binding(binding, _FakeKG({"441426211000049104"}), _make_bundle_with_boundary())
    assert ok is False
    assert "村外" in reason


def test_validate_rejects_internal_name_bound_to_outside_parcel():
    """村内村名绑定到村界外地块 → 拒绝。"""
    from app.agent.gis.parse.agent import _validate_binding

    bundle = _make_bundle_with_boundary()
    bundle.add(
        PolygonFeature(
            geometry={
                "type": "MultiPolygon",
                "coordinates": [[[[116.12, 24.80], [116.13, 24.80], [116.13, 24.81], [116.12, 24.81], [116.12, 24.80]]]],
            },
            bsm="441426211000077777", layer_type="landuse_current",
        ),
    )
    binding = PendingBinding(
        natural_village="田坑自然村", feature_type="parcel",
        candidate_bsms=["441426211000077777"], description="", confidence=0.8,
        source_report_keys=["land_use"],
    )
    ok, reason = _validate_binding(binding, _FakeKG({"441426211000077777"}), bundle)
    assert ok is False


def test_validate_rejects_unknown_bsm():
    from app.agent.gis.parse.agent import _validate_binding

    binding = PendingBinding(
        natural_village="田坑自然村", feature_type="parcel",
        candidate_bsms=["441426211000099999"], description="", confidence=0.9,
        source_report_keys=[],
    )
    ok, reason = _validate_binding(binding, _FakeKG(set()), _make_bundle_with_boundary())
    assert ok is False
    assert "not in KG" in reason


def test_extract_bindings_full_flow(monkeypatch, tmp_path: Path):
    import asyncio

    import app.agent.gis.parse.agent as parse_mod
    import app.modules.kg.memory as mem_mod

    fake_store = mem_mod.SemanticMemoryStore()
    monkeypatch.setattr(mem_mod, "get_memory_dir", lambda: tmp_path)
    monkeypatch.setattr(parse_mod, "_get_semantic_memory", lambda: fake_store)

    manager = get_kg_manager()
    kg = _FakeKG({"441426211000049104"})
    manager.register_session("sess-extract", kg)

    try:
        stats = asyncio.run(
            extract_bindings(
                session_id="sess-extract",
                wave=1,
                reports={"land_use": REPORT},
                llm=None,
                kg=kg,
                bundle=_make_bundle_with_boundary(),
            )
        )
    finally:
        manager.remove_session("sess-extract")

    assert stats["extracted"] >= 1
    assert stats["written"] >= 1
    assert len(fake_store.entity_annotations) >= 1
    # 持久化文件已写入
    assert (tmp_path / "sess-extract_round_1.json").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run (workdir `backend`): `python -m pytest tests/unit/test_parse_extract_bindings.py -v`
Expected: FAIL — `ImportError`（`PendingBinding`/`extract_bindings` 不存在）。

- [ ] **Step 3: 实现** — 追加到 `backend/app/agent/gis/parse/agent.py` 文件尾

```python
# ── EXPLORE KG-enrichment: extract_bindings ──────────────────────────────


@dataclass
class PendingBinding:
    """Candidate village/BSM binding extracted from a wave of reports."""

    natural_village: Optional[str]
    feature_type: str
    candidate_bsms: List[str]
    description: str
    confidence: float
    source_report_keys: List[str]


def _get_semantic_memory():
    from app.modules.kg import get_semantic_memory

    return get_semantic_memory()


_VLL_RE = re.compile(r"([\u4e00-\u9fff]{2,8}村)")
_BSM_NUM_RE = re.compile(r"(\d{15,25})")


def _extract_bindings_deterministic(reports: Dict[str, str]) -> List[PendingBinding]:
    """Rule-based fallback: village mention followed by a BSM within 120 chars."""
    bindings: List[PendingBinding] = []
    for dim_key, content in (reports or {}).items():
        for m in _VLL_RE.finditer(content or ""):
            name = m.group(1)
            window = (content or "")[m.end(): m.end() + 120]
            bsms = _BSM_NUM_RE.findall(window)
            if not bsms or any(b.natural_village == name for b in bindings):
                continue
            bindings.append(
                PendingBinding(
                    natural_village=name,
                    feature_type="parcel",
                    candidate_bsms=list(dict.fromkeys(bsms))[:8],
                    description=window[:60],
                    confidence=0.7,
                    source_report_keys=[dim_key],
                )
            )
    return bindings


_BINDING_PROMPT = """你是村庄规划报告语义抽取助手。从下列报告中识别自然村/地名与地块BSM的绑定关系。

候选地块（BSM + 用地描述，前200条）：
{parcels}

报告原文：
{reports}

只输出 JSON（不要任何其他文字），格式：
{{"bindings": [{{"natural_village": "田坑自然村", "candidate_bsms": ["441426211000049104"], "feature_type": "parcel", "description": "田坑自然村现有耕地12.5公顷", "confidence": 0.85}}]}}
若没有可绑定的实体，输出 {{"bindings": []}}。
"""


async def _extract_bindings_llm(
    llm: Any,
    reports: Dict[str, str],
    candidate_bsms: List[str],
) -> List[PendingBinding]:
    """Flash LLM extraction with a constrained JSON schema."""
    import json

    parcels = "\n".join(candidate_bsms[:200]) or "（无候选地块）"
    reports_text = "\n\n".join(f"[{k}]\n{v}" for k, v in (reports or {}).items())
    prompt = _BINDING_PROMPT.format(parcels=parcels, reports=reports_text[:8000])

    resp = await llm.ainvoke(prompt)
    content = getattr(resp, "content", "") or ""
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        logger.warning("[PARSE-bindings] LLM output not JSON: %s", content[:200])
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.warning("[PARSE-bindings] JSON parse failed: %s", e)
        return []
    bindings: List[PendingBinding] = []
    for item in data.get("bindings") or []:
        bindings.append(
            PendingBinding(
                natural_village=item.get("natural_village") or None,
                feature_type=str(item.get("feature_type", "parcel")),
                candidate_bsms=[str(b) for b in (item.get("candidate_bsms") or [])],
                description=str(item.get("description", "")),
                confidence=float(item.get("confidence", 0.0)),
                source_report_keys=list(reports.keys()),
            )
        )
    return bindings


def _find_annotation_point(bundle: Any, name: str) -> Optional[tuple]:
    """Find the Point annotation whose 注记/text matches a village name."""
    if bundle is None:
        return None
    for group in ("annotations_current", "annotations_planned"):
        for f in (bundle.points.get(group) or []):
            if isinstance(f, dict):
                props = f.get("properties") or {}
                text = str(props.get("注记", "") or props.get("text", "") or "")
                geom = f.get("geometry") or {}
            else:
                text = str(getattr(f, "text", "") or "")
                geom = getattr(f, "geometry", {}) or {}
            if text and (text == name or text in name or name in text):
                if geom.get("type") == "Point":
                    c = geom.get("coordinates") or []
                    if len(c) == 2:
                        return (float(c[0]), float(c[1]))
    return None


def _find_parcel_by_bsm(bundle: Any, bsm: str) -> Any:
    for f in (bundle.polygons.get("landuse_current") or []) if bundle is not None else []:
        if str(getattr(f, "bsm", "") or "") == bsm:
            return f
    return None


def _point_in_annotation_parcel(point: tuple, bsm: str, bundle: Any) -> bool:
    """注记点在候选地块多边形内。"""
    from app.modules.spatial_ops.geometry import point_in_polygon

    parcel = _find_parcel_by_bsm(bundle, bsm)
    if parcel is None:
        return False
    return point_in_polygon(point, getattr(parcel, "geometry", {}) or {})


def _parcel_inside_boundary(bsm: str, boundary: Dict[str, Any], bundle: Any) -> bool:
    """地块中心点位于村界多边形内。"""
    from app.modules.spatial_ops.geometry import _compute_centroid, point_in_polygon

    parcel = _find_parcel_by_bsm(bundle, bsm)
    if parcel is None:
        return False
    centroid = _compute_centroid(
        {"type": "Feature", "properties": {}, "geometry": getattr(parcel, "geometry", {})}
    )
    if centroid is None:
        return False
    return point_in_polygon(centroid, boundary)


def _validate_binding(binding: PendingBinding, kg: Any, bundle: Any) -> tuple:
    """kgg write-gate: KG exists + 村界包含 + confidence >= 0.6.

    村内/村外规则（实测验证）：
      - annotation.geojson 中 分类='村名' 的 4 个注记点（八社村/上举村/符坑村/文贵村）
        全部位于金田村村界外 → 是毗邻行政村（村外），禁止绑定；
      - 村内 12 个自然村（田坑/黄竹/园寨/社前/分水/清明/塘笃/长塘/炉池/肩丰/营仔/新山）
        无注记点 → 以"地块中心点在村界内"作为空间基座。
    """
    from app.modules.kg import get_entity_by_bsm
    from app.modules.spatial_ops.geometry import point_in_polygon, village_boundary_geometry

    if binding.confidence < 0.6:
        return (False, f"confidence {binding.confidence} < 0.6")
    if not binding.candidate_bsms:
        return (False, "no candidate bsms")
    for bsm in binding.candidate_bsms:
        if get_entity_by_bsm(kg, bsm) is None:
            return (False, f"bsm {bsm} not in KG")

    boundary = village_boundary_geometry(bundle)
    point = _find_annotation_point(bundle, binding.natural_village) if binding.natural_village else None

    if point is not None:
        # 有注记点：必须先通过村界包含（村外行政村 → 拒绝）
        if boundary is not None and not point_in_polygon(point, boundary):
            return (False, f"{binding.natural_village} 为村外毗邻行政村，非本村居民点")
        # 再验注记点在候选地块内
        if not _point_in_annotation_parcel(point, binding.candidate_bsms[0], bundle):
            return (False, f"{binding.natural_village} point outside parcel {binding.candidate_bsms[0]}")
    elif binding.natural_village and boundary is not None:
        # 无注记点（村内自然村）：地块中心点必须在村界内
        if not _parcel_inside_boundary(binding.candidate_bsms[0], boundary, bundle):
            return (False, f"parcel {binding.candidate_bsms[0]} 不在村界内，疑似村外")
    return (True, "")


def _queue_review(session_id: str, wave: int, skipped: List[Dict[str, Any]]) -> None:
    from app.modules.kg.memory import get_memory_dir

    d = get_memory_dir() / "_review"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{session_id}_wave_{wave}.json"
    path.write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8")


async def extract_bindings(
    session_id: str,
    wave: int,
    reports: Dict[str, str],
    llm: Any = None,
    kg: Any = None,
    bundle: Any = None,
) -> Dict[str, Any]:
    """Extract village/BSM bindings from a wave of reports and write them to
    SemanticMemoryStore (round = wave).  Non-fatal: returns stats dict.
    """
    from app.modules.kg import (
        EntityAnnotation,
        get_entity_by_bsm,
        get_kg_manager,
        get_parcels_semantic_list,
        require_session_kg,
        save_memory_state,
    )
    from app.tools.access.shared import resolve_bundle

    kg = kg if kg is not None else require_session_kg(session_id)
    bundle = bundle if bundle is not None else await resolve_bundle(session_id)

    candidate_bsms: List[str] = []
    try:
        candidate_bsms = [p.get("bsm") for p in get_parcels_semantic_list(kg) if p.get("bsm")]
    except Exception as e:
        logger.warning("[PARSE-bindings] candidate list failed: %s", e)

    if llm is None:
        from app.core.settings import GIS_EXPLORE_LLM_ENABLED

        if GIS_EXPLORE_LLM_ENABLED:
            from app.core.llm import create_llm
            from app.core.settings import (
                GIS_EXPLORE_MAX_TOKENS,
                GIS_EXPLORE_MODEL,
                GIS_EXPLORE_TEMPERATURE,
            )

            llm = create_llm(
                model=GIS_EXPLORE_MODEL,
                temperature=GIS_EXPLORE_TEMPERATURE,
                max_tokens=GIS_EXPLORE_MAX_TOKENS,
                streaming=False,
            )

    raw = (
        await _extract_bindings_llm(llm, reports, candidate_bsms)
        if llm is not None
        else _extract_bindings_deterministic(reports)
    )

    written: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for binding in raw:
        ok, reason = _validate_binding(binding, kg, bundle)
        if not ok:
            skipped.append({"binding": binding.__dict__, "reason": reason})
            continue
        for bsm in binding.candidate_bsms:
            entity = get_entity_by_bsm(kg, bsm)
            if entity is None:
                continue
            _get_semantic_memory().add_entity_annotation(
                EntityAnnotation(
                    entity_uri=entity["uri"],
                    entity_type=entity["type"],
                    description=binding.description,
                    source_text_refs=[f"{k}" for k in binding.source_report_keys],
                    round_added=wave,
                    valid_from_round=wave,
                    confidence=binding.confidence,
                )
            )
            written.append(bsm)

    try:
        get_kg_manager().bump_version(session_id)
    except Exception as e:
        logger.warning("[PARSE-bindings] version bump failed: %s", e)

    try:
        save_memory_state(session_id, wave)
    except Exception as e:
        logger.warning("[PARSE-bindings] memory state save failed: %s", e)

    if skipped:
        try:
            _queue_review(session_id, wave, skipped)
        except Exception as e:
            logger.warning("[PARSE-bindings] review queue failed: %s", e)

    stats = {
        "wave": wave,
        "extracted": len(raw),
        "written": len(set(written)),
        "skipped": len(skipped),
        "pending_review": len(skipped),
    }
    logger.info("[PARSE-bindings] session=%s stats=%s", session_id, stats)
    return stats
```

`__all__` 追加：`"PendingBinding", "extract_bindings"`。（文件头已有 `from dataclasses import dataclass` 和 `from typing import Any, List, Optional`；`Dict` 需补进 typing import，或函数内局部 `import json` + 类型用 `dict`。）

- [ ] **Step 4: 跑测试确认通过**

Run (workdir `backend`): `python -m pytest tests/unit/test_parse_extract_bindings.py tests/unit/test_parse_agent.py -v`
Expected: PASS（6 新 + 既有 parse 测试）。若既有 3 个 pre-existing parse_agent 失败依旧存在（与本次无关），在 commit 信息里注明。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/gis/parse/agent.py backend/tests/unit/test_parse_extract_bindings.py
git commit -m "feat(parse): add extract_bindings with boundary-aware KG write-gate"
```

---

### Task 5: E — Wave 末尾触发 PARSE 抽取

**Files:**
- Modify: `backend/app/agent/completion/node.py`
- Test: `backend/tests/unit/test_completion_parse_trigger.py` (new)

**Interfaces:**
- Consumes: Task 4 的 `extract_bindings`；`ReportStore.get_layer_reports`。
- Produces: `_maybe_extract_bindings(session_id: str, layer: int) -> None`（async、非致命、记录 stats）；在 `layer_completion_check` 的 approve 分支（step_mode resume 后）与 auto 分支各调用一次。

- [ ] **Step 1: 写失败测试** `backend/tests/unit/test_completion_parse_trigger.py`

```python
"""E 子任务：wave 完成触发 PARSE binding 抽取。"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agent.state import get_layer_dimensions


def test_layer1_complete_triggers_extraction(monkeypatch):
    import app.agent.completion.node as node_mod

    calls = []

    async def fake_extract(session_id: str, layer: int) -> None:
        calls.append((session_id, layer))

    monkeypatch.setattr(node_mod, "_maybe_extract_bindings", fake_extract)
    monkeypatch.setattr(
        "app.utils.sse_publisher.SSEPublisher.send_layer_complete",
        lambda **kw: None,
    )
    monkeypatch.setattr(
        "app.utils.sse_publisher.SSEPublisher.send_layer_start",
        lambda **kw: None,
    )
    monkeypatch.setattr(node_mod, "_snapshot_bundle", AsyncMock(return_value=None))

    dims = get_layer_dimensions(1)
    state = {
        "phase": "layer1",
        "session_id": "sess-wave",
        "completed_dimensions": {"layer1": dims},
        "layer_char_counts": {1: 500},
        "pending_reports": [],
        "step_mode": False,
    }

    result = asyncio.run(node_mod.layer_completion_check(state))

    assert calls == [("sess-wave", 1)]
    assert result["phase"] == "layer2"


def test_maybe_extract_bindings_is_non_fatal(monkeypatch):
    """无 session KG 时 helper 必须吞掉一切异常，不冒泡。"""
    import app.agent.completion.node as node_mod
    from app.modules.kg import get_kg_manager

    get_kg_manager().remove_session("sess-nokg")

    async def run():
        await node_mod._maybe_extract_bindings("sess-nokg", 1)
        return "ok"

    assert asyncio.run(run()) == "ok"
```

- [ ] **Step 2: 跑测试确认失败**

Run (workdir `backend`): `python -m pytest tests/unit/test_completion_parse_trigger.py -v`
Expected: FAIL — `AttributeError: module 'app.agent.completion.node' has no attribute '_maybe_extract_bindings'`。

- [ ] **Step 3: 实现** — patch `backend/app/agent/completion/node.py`

(a) `_snapshot_bundle` 之后新增模块级 helper：

```python
async def _maybe_extract_bindings(session_id: str, layer: int) -> None:
    """Wave-end hook: extract village/BSM bindings from the completed layer.

    Non-fatal: extraction failures are logged and never break the pipeline.
    """
    if not session_id:
        return
    try:
        from app.services.report_store import ReportStore

        store = ReportStore.get_instance()
        reports = await store.get_layer_reports(session_id, layer)
        if not reports:
            logger.info("[layer_completion_check] No reports for L%d, skip extraction", layer)
            return
        from app.agent.gis.parse.agent import extract_bindings

        stats = await extract_bindings(session_id, wave=layer, reports=reports)
        logger.info("[layer_completion_check] PARSE bindings layer=%d stats=%s", layer, stats)
    except Exception as e:
        logger.warning("[layer_completion_check] PARSE bindings failed for %s L%d: %s", session_id, layer, e)
```

(b) approve 分支（step_mode 下 `action == "approve"`，`send_layer_complete` 之后、`_snapshot_bundle` 之前）插入：

```python
            await _maybe_extract_bindings(session_id, layer)
```

(c) auto 分支（`SSEPublisher.send_layer_complete(...)` 之后、`_snapshot_bundle` 之前）插入同样的调用。

- [ ] **Step 4: 跑测试确认通过**

Run (workdir `backend`): `python -m pytest tests/unit/test_completion_parse_trigger.py -v`
Expected: PASS（2 个）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/completion/node.py backend/tests/unit/test_completion_parse_trigger.py
git commit -m "feat(completion): trigger PARSE binding extraction at wave end"
```

---

### Task 6: A — 真实金田村数据全流程 runner

**Files:**
- Create: `scripts/run_pipeline_real_jintian.py`
- 无单测（脚本）；验证 = 运行 + 检查输出。

**Interfaces:**
- Consumes: `app.services.runtime.PlanningRuntimeService`、`app.services.sse.sse_manager`、`scripts.experiments.framework.sse_listener.InProcessEventListener`、`app.modules.data.catalog.DataCatalog`、`open_kg_session`（stage-0）、`load_memory_state`（Task 1）、Task 5 的 wave-end hook（随图运行自动触发）。
- Produces: `session_id`（`explore_kgenrich_<8hex>`）；`data/kg_memory/{session_id}_round_{1,2,3}.json`；stdout 汇总；最后以 subprocess 调 Task 7 报告脚本。

- [ ] **Step 1: 创建脚本** `scripts/run_pipeline_real_jintian.py`

```python
"""Real-data EXPLORE KG-enrichment runner for 金田村.

Runs the full planning graph (L1/L2/L3) with the wave-end PARSE binding
extraction enabled (completion node hook), a session KG opened up front, and
memory state persisted per round.

Usage:
    python scripts/run_pipeline_real_jintian.py [--session-id SID] [--skip-verify]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.resolve()
backend_root = project_root / "backend"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from scripts.experiments.framework.config import (
    DEFAULT_CONSTRAINTS,
    DEFAULT_TASK_DESCRIPTION,
    JINTIAN_VILLAGE_DATA,
    ensure_cascade_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


async def _open_session_kg(session_id: str) -> None:
    from app.modules.data.catalog import DataCatalog
    from app.modules.kg import open_kg_session

    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")
    bundle = await DataCatalog().load_village_bundle_async(village_name)
    snapshot = open_kg_session(
        session_id=session_id,
        village_name=bundle.village_name or village_name,
        bundle=bundle,
    )
    logger.info("[Runner] KG session opened: v%d (%d triples, cache_hit=%s)",
                snapshot.version, snapshot.triple_count, snapshot.cache_hit)


async def _run_graph(session_id: str, listener) -> None:
    """Port of scripts/experiments/cascade/baseline.py:_run_graph."""
    from app.agent.state import get_layer_dimensions, get_layer_name
    from app.services.runtime import PlanningRuntimeService
    from app.services.sse import sse_manager
    from app.utils.sse_publisher import SSEPublisher
    from app.utils.stats_collector import StatsCollector

    village_data = JINTIAN_VILLAGE_DATA.get("status_report", "")
    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")

    stats = StatsCollector.get_instance()
    stats.start_session(session_id, "金田村规划")

    initial_state = PlanningRuntimeService.build_initial_state(
        project_name="金田村规划",
        village_data=village_data,
        village_name=village_name,
        task_description=DEFAULT_TASK_DESCRIPTION,
        constraints=DEFAULT_CONSTRAINTS,
        session_id=session_id,
        stream_mode=True,
        step_mode=False,
    )

    sse_manager.init_session(session_id, {"session_id": session_id, "project_name": "金田村规划"})
    sse_manager.set_execution_active(session_id, True)
    await listener.connect()

    SSEPublisher.send_layer_start(
        session_id=session_id, layer=1,
        layer_name=get_layer_name(1),
        dimension_count=len(get_layer_dimensions(1)),
    )

    task = asyncio.create_task(
        PlanningRuntimeService._trigger_planning_execution(session_id, initial_state)
    )

    for layer in [1, 2, 3]:
        event = await listener.wait_for_any_event(
            event_types=["layer_completed", "error"],
            timeout=1200,
            filter_func=lambda e, l=layer: (
                e.get("type") == "error"
                or e.get("data", {}).get("layer") == l
            ),
        )
        if event.get("type") == "error":
            raise RuntimeError(f"Layer {layer} failed: {event.get('data', {}).get('message', 'unknown')}")
        logger.info("[Runner] Layer %d completed", layer)

    await task
    await listener.disconnect()


async def _summarize(session_id: str) -> Dict[str, Any]:
    from app.modules.kg.memory import load_memory_state

    summary: Dict[str, Any] = {"session_id": session_id, "rounds": {}}
    for round_num in [1, 2, 3]:
        store = load_memory_state(session_id, round_num)
        anns = list(store.entity_annotations.values())
        summary["rounds"][round_num] = {
            "annotations": len(anns),
            "names": sorted({a.description[:16] for a in anns if a.description}),
        }
        logger.info("[Runner] Round %d: %d annotations", round_num, len(anns))
    return summary


async def main(session_id: str, skip_verify: bool) -> None:
    from app.services.runtime import PlanningRuntimeService
    from scripts.experiments.framework.sse_listener import InProcessEventListener

    ensure_cascade_dirs()
    await PlanningRuntimeService.ensure_initialized()

    session_id = session_id or f"explore_kgenrich_{uuid.uuid4().hex[:8]}"
    logger.info("[Runner] session_id=%s", session_id)

    await _open_session_kg(session_id)
    listener = InProcessEventListener(session_id)
    await _run_graph(session_id, listener)
    summary = await _summarize(session_id)

    print("\n" + "=" * 60)
    print(f"[Runner] session={session_id}")
    for r, info in summary["rounds"].items():
        print(f"  round{r}: {info['annotations']} annotations {info['names']}")
    print("=" * 60)

    if not skip_verify:
        subprocess.run(
            [sys.executable, str(script_dir / "verify_explore_kgenrich.py"), "--session-id", session_id],
            check=False,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.session_id or None, args.skip_verify))
```

- [ ] **Step 2: 语法/导入冒烟测试**

Run (workdir 根目录): `python -c "import ast; ast.parse(open('scripts/run_pipeline_real_jintian.py', encoding='utf-8').read()); print('syntax ok')"`
Expected: `syntax ok`。

- [ ] **Step 3: 全量运行（真实 LLM，约 10-20 分钟）**

Run (workdir 根目录): `python scripts/run_pipeline_real_jintian.py --skip-verify`
Expected: 三个 layer 依次 completed；stdout 显示 `round1/2/3` annotations 数；日志含 `[layer_completion_check] PARSE bindings layer=1/2/3 stats=...`。
前提：`.env` 有 `DASHSCOPE_API_KEY`；`GIS_EXPLORE_LLM_ENABLED=true`（默认）。

- [ ] **Step 4: 检查产物**

Run: `Get-ChildItem data\kg_memory` → 应有 `explore_kgenrich_*_round_1.json`、`_round_2.json`、`_round_3.json`（及可能的 `_review/`）。
Run: `Get-ChildItem data\kg_memory\_review` → 记录未通过 write-gate 的候选（允许为空）。

- [ ] **Step 5: Commit**

```bash
git add scripts/run_pipeline_real_jintian.py
git commit -m "feat(scripts): add real-data EXPLORE KG-enrichment pipeline runner"
```

---

### Task 7: G — 端到端验证报告脚本

**Files:**
- Create: `scripts/verify_explore_kgenrich.py`
- 无单测；验证 = 运行 + 断言退出码。

**Interfaces:**
- Consumes: Task 1 `load_memory_state`/`diff_round`；Task 6 的 session_id；`docs/explore/` 输出目录。
- Produces: `report(session_id: str) -> Dict[str, Any]`；`docs/explore/jintian-kgenrich-{timestamp}.json`；stdout 摘要；`main()` 在绑定数 < 5 时退出码 1。

- [ ] **Step 1: 创建脚本** `scripts/verify_explore_kgenrich.py`

```python
"""EXPLORE KG-enrichment end-to-end verification.

Reads persisted memory states (data/kg_memory) for a session, checks the
binding loop produced real village bindings, and writes a report JSON.

Usage:
    python scripts/verify_explore_kgenrich.py [--session-id SID]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.resolve()
backend_root = project_root / "backend"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

# 村内 12 自然村 + 公王河（不含 八社村/上举村/符坑村/文贵村 —— 村外毗邻行政村，不得作为本村绑定匹配项）
_REAL_NAMES = ("田坑", "黄竹", "园寨", "塘笃", "社前", "分水", "清明",
               "长塘", "炉池", "肩丰", "营仔", "新山", "公王河")
_MIN_BINDINGS = 5


def _latest_session() -> str:
    from app.modules.kg.memory import get_memory_dir

    files = sorted(get_memory_dir().glob("*_round_3.json"))
    if not files:
        raise SystemExit("No round-3 memory state found. Run scripts/run_pipeline_real_jintian.py first.")
    return files[-1].name.removesuffix("_round_3.json")


def report(session_id: str) -> Dict[str, Any]:
    from app.modules.kg.memory import diff_round, load_memory_state

    rounds: List[Dict[str, Any]] = []
    previous = None
    for r in [1, 2, 3]:
        store = load_memory_state(session_id, r)
        diff = diff_round(previous, store)
        previous = store
        anns = list(store.entity_annotations.values())
        rounds.append(
            {
                "round": r,
                "annotation_count": len(anns),
                "diff": diff,
                "descriptions": sorted({a.description for a in anns if a.description})[:40],
            }
        )

    final = load_memory_state(session_id, 3)
    bound_descriptions = {a.description for a in final.entity_annotations.values() if a.description}
    matched = [n for n in _REAL_NAMES if any(n in d for d in bound_descriptions)]
    total = len(final.entity_annotations)

    return {
        "session_id": session_id,
        "generated_at": datetime.now().isoformat(),
        "total_bindings": total,
        "real_entities_matched": matched,
        "threshold": _MIN_BINDINGS,
        "passed": total >= _MIN_BINDINGS,
        "rounds": rounds,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="")
    args = parser.parse_args()

    session_id = args.session_id or _latest_session()
    result = report(session_id)

    out_dir = project_root / "docs" / "explore"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"jintian-kgenrich-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nsession={session_id} total_bindings={result['total_bindings']} matched={result['real_entities_matched']} passed={result['passed']}")
    print(f"report -> {out_path}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 无状态冒烟测试**

Run (workdir 根目录): `python scripts/verify_explore_kgenrich.py --session-id nonexistent_session_x`
Expected: 退出码 0，报告 `total_bindings=0, passed=False`（脚本自身不崩；验证脚本逻辑正确）。

- [ ] **Step 3: 对有真实产物的 session 验证**

Run: `python scripts/verify_explore_kgenrich.py`（自动取最新 round-3 session）
Expected: `total_bindings >= 5` 且 `matched` 含至少一个 `田坑`/`黄竹`/`园寨` 等村内名；退出码 0；`docs/explore/jintian-kgenrich-*.json` 生成。

- [ ] **Step 4: 更新台账文档**

- `docs/design/10_IMPLEMENTATION_STATUS.md`：把 EXPLORE KG-enrichment 相关条目从 `[PLANNED]` 更新为 `[IMPLEMENTED]`（A-G 全落地）。
- `docs/design/11_EXPLORE_KG_ENRICHMENT.md`：第 7 节验证标准逐项勾选。

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_explore_kgenrich.py docs/design/10_IMPLEMENTATION_STATUS.md docs/design/11_EXPLORE_KG_ENRICHMENT.md
git commit -m "feat(scripts): add KG-enrichment verification report and update design docs"
```

---

## Self-Review

**1. Spec coverage:** 设计文档 `docs/design/11_EXPLORE_KG_ENRICHMENT.md` 的每个子任务都有对应 Task：H→Task1、B→Task2、D→Task3、C→Task4、E→Task5、A→Task6、G→Task7。设计 4.1-4.7 决策全部体现。**村内/村外铁律** → Global Constraints + Task 2（external_villages 分离）+ Task 4（村界包含 write-gate + 无注记点回退）+ Task 7（`_REAL_NAMES` 剔除村外四村）。不变量（L1 模板 0 改动、单轮向后兼容、重启可恢复、失败不中断）在 Global Constraints + 各任务 try/except 落实。

**2. Placeholder scan:** 无 "TBD/TODO/implement later"。所有代码步骤含完整实现；两个脚本含完整可运行代码。

**3. Type consistency:** `extract_bindings(session_id, wave, reports, llm=None, kg=None, bundle=None)` 在 Task 4 定义、Task 5 以 `extract_bindings(session_id, wave=layer, reports=reports)` 调用 ✓；`save_memory_state`/`load_memory_state`/`diff_round`/`get_memory_dir` 签名在 Task 1 定义、Task 4/6/7 调用一致 ✓；`point_in_polygon`/`village_boundary_geometry` 在 Task 2 定义、Task 2/4 复用 ✓；`SpatialCognitionBrief`/`format_brief_section` 在 Task 2 定义、Task 3 调用一致 ✓；`_maybe_extract_bindings(session_id, layer)` 在 Task 5 定义并自测 ✓；`_compute_centroid` 为既有函数（入参 GeoJSON Feature dict）✓。测试构造统一走 `VillageBundle.add(feature, group="points"/"polygons")` + Pydantic 特征对象（PolygonFeature/CurrentAnnotation）✓。
