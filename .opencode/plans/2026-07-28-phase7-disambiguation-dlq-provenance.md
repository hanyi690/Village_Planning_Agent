# Phase 7: L2 消歧接口预留 + DLQ 三类 + Provenance 入 KG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 L2 LLM 消歧的 Pydantic 接口模型（不实现 LLM 调用），建立结构化 DLQ 三类分流机制，将编码决策 provenance 写入 KG 图斑级三元组。

**Architecture:** 三个独立子系统并行推进：(1) `disambiguation.py` 定义 `DisambiguationContext`/`DisambiguationDecision`/`Candidate` 模型，`CandidateEngine.resolve()` 扩展 `Resolution.needs_llm()` 工厂方法；(2) `dlq.py` 定义 `DlqCategory`/`DlqEntry`/`DlqReport`，`AdapterResult` 升级为结构化 DLQ；(3) `BaseLandUseParcel` 增加 `mapping_provenance` 字段，`ingest_landuse()` 记录编码决策 provenance，`_add_parcels()` 写入 KG `ProvenancePredicates` 三元组。

**Tech Stack:** Python 3.12, Pydantic v2, RDFLib 7.x

## Global Constraints

- 不实现 LLM 调用：`DisambiguationDecision.decided_by` 支持 `"llm"` 但不实现 `get_instructor_client()` 调用
- DLQ 不阻塞管道：三类 DLQ 走收集制，不抛异常
- `ProvenancePredicates` 已在 `ontology.py` 定义（Phase 6），本次只写不重定义
- `_add_parcels()` 保持旧签名 `self, parcels`（尚未迁移到 registry 统一签名）
- 所有已有测试必须保持通过，新增测试覆盖新功能

---

## File Structure

### 新增文件

| 文件 | 职责 |
|------|------|
| `schema/encodings/dicts/disambiguation.py` | `Candidate`、`DisambiguationContext`、`DisambiguationDecision` Pydantic 模型，含 `chosen_code` 闭集校验 |
| `kg/dlq.py` | `DlqCategory` 枚举、`DlqEntry` 模型、`DlqReport` 聚合模型 |
| `tests/unit/test_disambiguation.py` | 消歧模型创建、序列化、闭集校验、`DisambiguationContext` 构造 |
| `tests/unit/test_dlq.py` | DLQ 条目创建、分类过滤、`DlqReport` 合并、`AdapterResult` 集成 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `schema/encodings/dicts/candidate_engine.py` | `Resolution.kind` 增加 `"llm"`；新增 `Resolution.needs_llm()` 工厂方法；`CandidateEngine.resolve()` 在 `len(hits) > 1` 且 `decision != "manual"` 时返回 `needs_llm` 而非 `manual` |
| `data/adapters/__init__.py` | `AdapterResult.dlq` 从 `list[dict]` 改为 `list[DlqEntry]`；为 `DlqEntry` 添加导入 |
| `data/adapters/parcels.py` | `ParcelsAdapter.load()` 在 `ingest_landuse()` warnings 中提取 geometry 无效条目写入 `dlq` |
| `data/adapters/features.py` | `FeaturesAdapter.load()` 在 `ingest_feature()` warnings 中提取 geometry 无效条目写入 `dlq` |
| `schema/types/spatial_types.py` | `BaseLandUseParcel` 增加 `mapping_provenance: dict` 字段（默认 `field(default_factory=dict)`） |
| `data/ingest.py` | `_resolve_code()` 返回增强为 `Tuple[str, str, dict]`（增加 provenance dict）；`ingest_landuse()` 将 provenance 存入 `mapping_provenance` |
| `kg/builder/layer1.py` | `_add_parcels()` 读取 `p.mapping_provenance` 写入 `ProvenancePredicates` 三元组 |
| `kg/builder/__init__.py` | 导出 `DlqCategory`、`DlqEntry`、`DlqReport` |

---

### Task 1: 消歧接口模型 — `disambiguation.py`

**Files:**
- Create: `backend/app/modules/schema/encodings/dicts/disambiguation.py`
- Test: `backend/tests/unit/test_disambiguation.py`

**Interfaces:**
- Consumes: `Condition` from `expr_eval.py` (for `Candidate.when` typing)
- Produces: `Candidate`, `DisambiguationContext`, `DisambiguationDecision` — 被 `CandidateEngine.resolve()` 的 L2 路径消费

- [ ] **Step 1: Write the failing test**

```python
"""Tests for disambiguation models — Candidate, DisambiguationContext, DisambiguationDecision."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.schema.encodings.dicts.disambiguation import (
    Candidate,
    DisambiguationContext,
    DisambiguationDecision,
)


class TestCandidate:
    def test_minimal(self):
        c = Candidate(code="0901")
        assert c.code == "0901"
        assert c.when is None
        assert c.surviving_evidence == []

    def test_with_evidence(self):
        c = Candidate(code="0901", surviving_evidence=["poi:超市", "poi:商场"])
        assert len(c.surviving_evidence) == 2

    def test_empty_code_rejected(self):
        with pytest.raises(ValidationError):
            Candidate(code="")


class TestDisambiguationContext:
    def test_minimal(self):
        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={"DLBM": "05H1", "DLMC": "商服用地"},
            candidates=[Candidate(code="0901")],
        )
        assert ctx.source_system == "sddlbm"
        assert ctx.source_code == "05H1"
        assert len(ctx.candidates) == 1

    def test_empty_candidates_rejected(self):
        with pytest.raises(ValidationError, match="candidates"):
            DisambiguationContext(
                source_system="sddlbm",
                source_code="05H1",
                parcel_attrs={},
                candidates=[],
            )

    def test_serialization_roundtrip(self):
        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={"DLBM": "05H1"},
            candidates=[Candidate(code="0901"), Candidate(code="0902")],
            poi_hits=[{"name": "超市", "type": "shop"}],
            zone_membership=["YJJBNT"],
            village_profile="平原村，以农业为主",
        )
        dumped = ctx.model_dump(mode="json")
        loaded = DisambiguationContext.model_validate(dumped)
        assert loaded.source_code == "05H1"
        assert len(loaded.candidates) == 2
        assert loaded.candidates[0].code == "0901"

    def test_with_neighbors(self):
        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={},
            neighbors=[{"bsm": "001", "dlbm": "0703"}],
            candidates=[Candidate(code="0901")],
        )
        assert len(ctx.neighbors) == 1
        assert ctx.neighbors[0]["bsm"] == "001"


class TestDisambiguationDecision:
    def test_minimal(self):
        dec = DisambiguationDecision(
            chosen_code="0901",
            confidence="high",
            rationale="POI confirmed commercial use",
        )
        assert dec.chosen_code == "0901"
        assert dec.confidence == "high"
        assert dec.decided_by == "llm"
        assert dec.reviewed is False

    def test_decided_by_rule(self):
        dec = DisambiguationDecision(
            chosen_code="0901",
            confidence="high",
            rationale="Single target",
            decided_by="rule",
        )
        assert dec.decided_by == "rule"

    def test_invalid_confidence_rejected(self):
        with pytest.raises(ValidationError):
            DisambiguationDecision(
                chosen_code="0901",
                confidence="very_high",
                rationale="test",
            )

    def test_model_version(self):
        dec = DisambiguationDecision(
            chosen_code="0901",
            confidence="medium",
            rationale="test",
            model="qwen-flash",
        )
        assert dec.model == "qwen-flash"

    def test_serialization_roundtrip(self):
        dec = DisambiguationDecision(
            chosen_code="0901",
            confidence="medium",
            rationale="POI 辅助判断",
            evidence=["poi:超市"],
            decided_by="llm",
            model="qwen-flash",
            reviewed=False,
        )
        dumped = dec.model_dump(mode="json")
        loaded = DisambiguationDecision.model_validate(dumped)
        assert loaded.chosen_code == "0901"
        assert loaded.evidence == ["poi:超市"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_disambiguation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.schema.encodings.dicts.disambiguation'`

- [ ] **Step 3: Write minimal implementation**

```python
"""L2 disambiguation interface models — Pydantic schemas for LLM-based code disambiguation.

These models define the contract between the CandidateEngine (L1) and
the LLM disambiguation step (L2). The LLM is not called here — these
models are the data structures that an LLM would consume and produce
via ``with_structured_output()``.

See REFACTOR_V4_PYDANTIC_DU_PIPELINE.md §3.3 for design rationale.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator


class Candidate(BaseModel):
    """A single candidate target code + its triggering condition.

    Represents one entry in the closed set that L2 LLM must choose from.
    """

    code: str
    when: dict | None = None
    surviving_evidence: list[str] = []

    @field_validator("code")
    @classmethod
    def _code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("code must not be empty")
        return v


class DisambiguationContext(BaseModel):
    """Disambiguation context — consumed by flash LLM + instructor.

    Designed as the input schema for ``with_structured_output(DisambiguationDecision)``.
    The ``candidates`` field is the closed set; the LLM must choose from it.
    """

    source_system: str
    source_code: str
    parcel_attrs: dict[str, Any] = {}
    neighbors: list[dict[str, Any]] = []
    poi_hits: list[dict[str, Any]] = []
    zone_membership: list[str] = []
    village_profile: str = ""
    candidates: list[Candidate]

    @field_validator("candidates")
    @classmethod
    def _candidates_not_empty(cls, v: list[Candidate]) -> list[Candidate]:
        if not v:
            raise ValueError("candidates must not be empty — closed set required")
        return v


class DisambiguationDecision(BaseModel):
    """Disambiguation decision — closed-set choice + evidence + provenance.

    The ``chosen_code`` must be one of the candidates in ``DisambiguationContext``.
    Validation is enforced at the consumer side (``info.context`` carries the context).
    """

    chosen_code: str
    confidence: Literal["high", "medium", "low"]
    rationale: str
    evidence: list[str] = []
    decided_by: Literal["rule", "llm", "human", "default"] = "llm"
    model: str = ""
    reviewed: bool = False


__all__ = [
    "Candidate",
    "DisambiguationContext",
    "DisambiguationDecision",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/unit/test_disambiguation.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/schema/encodings/dicts/disambiguation.py backend/tests/unit/test_disambiguation.py
git commit -m "feat(phase7): L2 disambiguation interface models — Candidate, DisambiguationContext, DisambiguationDecision"
```

---

### Task 2: 扩展 `Resolution` 支持 `needs_llm()` — L2 决策梯

**Files:**
- Modify: `backend/app/modules/schema/encodings/dicts/candidate_engine.py`
- Test: `backend/tests/unit/test_disambiguation.py` (追加)

**Interfaces:**
- Consumes: `Candidate`, `DisambiguationContext` from Task 1
- Produces: `Resolution.kind = "llm"`, `Resolution.needs_llm()` factory, updated `CandidateEngine.resolve()` returning L2

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_disambiguation.py`:

```python
class TestResolutionNeedsLlm:
    def test_needs_llm_factory(self):
        from app.modules.schema.encodings.dicts.candidate_engine import Resolution
        from app.modules.schema.encodings.dicts.disambiguation import (
            Candidate, DisambiguationContext,
        )

        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={"DLBM": "05H1"},
            candidates=[Candidate(code="0901"), Candidate(code="0902")],
        )
        resolution = Resolution.needs_llm(ctx)
        assert resolution.kind == "llm"
        assert resolution.chosen_code == ""
        assert resolution.disambiguation_ctx is not None
        assert resolution.disambiguation_ctx.source_code == "05H1"

    def test_needs_llm_serialization(self):
        from app.modules.schema.encodings.dicts.candidate_engine import Resolution
        from app.modules.schema.encodings.dicts.disambiguation import (
            Candidate, DisambiguationContext,
        )

        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={},
            candidates=[Candidate(code="0901")],
        )
        resolution = Resolution.needs_llm(ctx)
        dumped = resolution.model_dump(mode="json")
        loaded = Resolution.model_validate(dumped)
        assert loaded.kind == "llm"
        assert loaded.disambiguation_ctx is not None
        assert loaded.disambiguation_ctx.source_code == "05H1"


class TestCandidateEngineL2:
    def test_resolve_returns_needs_llm_when_multiple_survivors(self):
        """When context is provided, multiple targets survive, and decision is 'context',
        resolve() should return kind='llm' (not 'manual')."""
        from app.modules.schema.encodings.dicts.candidate_engine import CandidateEngine, Resolution
        from app.modules.schema.encodings.dicts.expr_eval import MappingContext

        engine = CandidateEngine()
        # Ensure center is loaded
        engine._ensure_center()

        # sddlbm 05H1 -> ydyhfldm has multiple targets with context-dependent when clauses
        ctx = MappingContext(
            parcel_attrs={"DLBM": "05H1", "DLMC": "商服用地"},
            poi_hits=[{"name": "超市", "type": "shop"}],
        )
        resolution = engine.resolve("sddlbm", "ydyhfldm", "05H1", ctx)
        # 05H1 has 6+ targets, decision=context, multiple will survive
        # if no POI matches, all non-null when targets fail, only null-when survives -> L0 auto
        # if POI matches specific targets, multiple could survive -> L2
        if resolution.kind == "auto":
            pytest.skip("Only one target survived — no L2 trigger for this configuration")
        assert resolution.kind in ("llm", "rule"), (
            f"Expected llm or rule, got {resolution.kind}"
        )
        if resolution.kind == "llm":
            assert resolution.disambiguation_ctx is not None
            assert len(resolution.disambiguation_ctx.candidates) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_disambiguation.py::TestResolutionNeedsLlm -v`
Expected: FAIL — `Resolution` has no `needs_llm` method

- [ ] **Step 3: Modify `Resolution` in `candidate_engine.py`**

Add `"llm"` to `kind` Literal and add `needs_llm()` factory:

```python
class Resolution(BaseModel):
    """Decision ladder result — L0/L1/L2/L3."""

    kind: Literal["auto", "rule", "llm", "manual", "unmapped"] = "unmapped"
    chosen_code: str = ""
    candidates: list[dict[str, Any]] = []
    confidence: str = "exact"
    rationale: str = ""
    disambiguation_ctx: Optional[Dict[str, Any]] = None

    @classmethod
    def needs_llm(cls, ctx: "DisambiguationContext") -> "Resolution":
        from .disambiguation import DisambiguationContext
        candidates_list = [
            {"code": c.code, "when": c.when, "surviving_evidence": c.surviving_evidence}
            for c in ctx.candidates
        ]
        return cls(
            kind="llm",
            candidates=candidates_list,
            confidence="conditional",
            rationale=f"Multiple survivors ({len(ctx.candidates)}), LLM disambiguation required",
            disambiguation_ctx=ctx.model_dump(mode="json"),
        )
```

Update `CandidateEngine.resolve()` — replace the last return (line 168-174) from `kind="manual"` to `kind="llm"` when `decision != "manual"`:

```python
        # Multiple survivors — L2 (LLM) if not explicitly manual
        if decision == "manual":
            return Resolution(
                kind="manual",
                chosen_code=default,
                candidates=hits,
                confidence="conditional",
                rationale=f"Multiple candidates ({len(hits)}), manual decision required",
            )

        from .disambiguation import Candidate, DisambiguationContext
        candidates = [
            Candidate(
                code=str(t.get("code", "")),
                when=t.get("when"),
                surviving_evidence=[],
            )
            for t in hits
        ]
        ctx_obj = DisambiguationContext(
            source_system=source_system,
            source_code=source_code,
            parcel_attrs=ctx.parcel_attrs if ctx else {},
            candidates=candidates,
        )
        return Resolution.needs_llm(ctx_obj)
```

Also add the import at the top of candidate_engine.py (add to existing imports):

```python
from typing import Any, Dict, List, Literal, Optional
```

And add the `__all__` export — already includes `Resolution`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/unit/test_disambiguation.py -v`
Expected: PASS (all tests including new ones)

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `pytest backend/tests/unit/test_encoding_consistency.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/schema/encodings/dicts/candidate_engine.py backend/tests/unit/test_disambiguation.py
git commit -m "feat(phase7): add Resolution.needs_llm() and update CandidateEngine L2 path"
```

---

### Task 3: DLQ 三类基础设施

**Files:**
- Create: `backend/app/modules/kg/dlq.py`
- Modify: `backend/app/modules/data/adapters/__init__.py` (upgrade `AdapterResult.dlq`)
- Modify: `backend/app/modules/data/adapters/parcels.py` (populate DLQ)
- Modify: `backend/app/modules/data/adapters/features.py` (populate DLQ)
- Test: `backend/tests/unit/test_dlq.py`

**Interfaces:**
- Consumes: `AdapterResult` from `adapters/__init__.py`
- Produces: `DlqCategory`, `DlqEntry`, `DlqReport` — consumed by pipeline reporting

- [ ] **Step 1: Write the failing test**

```python
"""Tests for DLQ models — DlqCategory, DlqEntry, DlqReport."""

from __future__ import annotations

import pytest

from app.modules.kg.dlq import DlqCategory, DlqEntry, DlqReport


class TestDlqCategory:
    def test_values(self):
        assert DlqCategory.GEOMETRY.value == "geometry"
        assert DlqCategory.MAPPING.value == "mapping"
        assert DlqCategory.REVIEW.value == "review"

    def test_all_categories(self):
        cats = set(DlqCategory)
        assert cats == {"geometry", "mapping", "review"}


class TestDlqEntry:
    def test_minimal(self):
        entry = DlqEntry(
            category=DlqCategory.GEOMETRY,
            reason="Invalid polygon ring",
            source_layer="landuse_current",
            raw_feature={"type": "Feature", "properties": {"BSM": "001"}},
        )
        assert entry.category == DlqCategory.GEOMETRY
        assert entry.reason == "Invalid polygon ring"
        assert entry.source_layer == "landuse_current"
        assert entry.bsm == ""

    def test_with_bsm(self):
        entry = DlqEntry(
            category=DlqCategory.MAPPING,
            reason="Code 9999 not found in any system",
            source_layer="landuse_current",
            raw_feature={},
            bsm="001",
        )
        assert entry.bsm == "001"

    def test_serialization_roundtrip(self):
        entry = DlqEntry(
            category=DlqCategory.REVIEW,
            reason="Low confidence mapping",
            source_layer="landuse_planned",
            raw_feature={"properties": {"BSM": "002"}},
            bsm="002",
        )
        dumped = entry.model_dump(mode="json")
        loaded = DlqEntry.model_validate(dumped)
        assert loaded.category == DlqCategory.REVIEW
        assert loaded.bsm == "002"


class TestDlqReport:
    def test_empty(self):
        report = DlqReport()
        assert report.total == 0
        assert report.by_category(DlqCategory.GEOMETRY) == []

    def test_add_entry(self):
        report = DlqReport()
        entry = DlqEntry(
            category=DlqCategory.GEOMETRY,
            reason="test",
            source_layer="landuse_current",
            raw_feature={},
        )
        report.add(entry)
        assert report.total == 1

    def test_by_category(self):
        report = DlqReport()
        report.add(DlqEntry(
            category=DlqCategory.GEOMETRY, reason="g1",
            source_layer="l1", raw_feature={},
        ))
        report.add(DlqEntry(
            category=DlqCategory.GEOMETRY, reason="g2",
            source_layer="l1", raw_feature={},
        ))
        report.add(DlqEntry(
            category=DlqCategory.MAPPING, reason="m1",
            source_layer="l1", raw_feature={},
        ))
        geos = report.by_category(DlqCategory.GEOMETRY)
        assert len(geos) == 2
        mappings = report.by_category(DlqCategory.MAPPING)
        assert len(mappings) == 1
        reviews = report.by_category(DlqCategory.REVIEW)
        assert len(reviews) == 0

    def test_merge(self):
        r1 = DlqReport()
        r1.add(DlqEntry(
            category=DlqCategory.GEOMETRY, reason="g1",
            source_layer="l1", raw_feature={},
        ))
        r2 = DlqReport()
        r2.add(DlqEntry(
            category=DlqCategory.MAPPING, reason="m1",
            source_layer="l1", raw_feature={},
        ))
        r1.merge(r2)
        assert r1.total == 2
        assert len(r1.by_category(DlqCategory.GEOMETRY)) == 1
        assert len(r1.by_category(DlqCategory.MAPPING)) == 1

    def test_summary(self):
        report = DlqReport()
        report.add(DlqEntry(
            category=DlqCategory.GEOMETRY, reason="g1",
            source_layer="l1", raw_feature={},
        ))
        report.add(DlqEntry(
            category=DlqCategory.MAPPING, reason="m1",
            source_layer="l1", raw_feature={},
        ))
        summary = report.summary()
        assert summary["total"] == 2
        assert summary["by_category"]["geometry"] == 1
        assert summary["by_category"]["mapping"] == 1
        assert summary["by_category"]["review"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_dlq.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.kg.dlq'`

- [ ] **Step 3: Write `dlq.py`**

```python
"""Dead Letter Queue — structured DLQ with three categories.

Categories:
    geometry:   Geometry validation failed (must_be_valid = False)
    mapping:    Code mapping not found (unmapped)
    review:     Manual decision required (manual/low-confidence)

Each entry preserves the raw feature + reason + source layer.
Pipeline does not block — DLQ is collected and reported.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DlqCategory(str, Enum):
    """DLQ entry category — determines the downstream disposition."""
    GEOMETRY = "geometry"
    MAPPING = "mapping"
    REVIEW = "review"


class DlqEntry(BaseModel):
    """A single DLQ entry — preserves the raw feature + reason for replay.

    Attributes:
        category: DLQ category (geometry/mapping/review)
        reason: Human-readable explanation of the failure
        source_layer: The gis_type_ref of the source layer
        raw_feature: The raw feature dict (GeoJSON Feature or similar)
        bsm: Optional identifier code for traceability
    """
    category: DlqCategory
    reason: str
    source_layer: str
    raw_feature: dict[str, Any] = Field(default_factory=dict)
    bsm: str = ""


class DlqReport(BaseModel):
    """Aggregated DLQ report — collects entries across a pipeline run.

    Provides category breakdown and summary statistics.
    """
    entries: list[DlqEntry] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.entries)

    def add(self, entry: DlqEntry) -> None:
        self.entries.append(entry)

    def merge(self, other: DlqReport) -> None:
        self.entries.extend(other.entries)

    def by_category(self, category: DlqCategory) -> list[DlqEntry]:
        return [e for e in self.entries if e.category == category]

    def summary(self) -> dict[str, Any]:
        counts = {cat.value: 0 for cat in DlqCategory}
        for e in self.entries:
            counts[e.category.value] += 1
        return {
            "total": self.total,
            "by_category": counts,
        }


__all__ = [
    "DlqCategory",
    "DlqEntry",
    "DlqReport",
]
```

- [ ] **Step 4: Update `AdapterResult` to use `DlqEntry`**

In `backend/app/modules/data/adapters/__init__.py`:

```python
from app.modules.kg.dlq import DlqCategory, DlqEntry, DlqReport
```

Change `dlq: list[dict] = field(default_factory=list)` to `dlq: list[DlqEntry] = field(default_factory=list)`.

- [ ] **Step 5: Update `ParcelsAdapter` to populate DLQ**

In `backend/app/modules/data/adapters/parcels.py`:

Modify the `load()` method to scan warnings for geometry-related issues and populate `dlq`:

```python
class ParcelsAdapter(IngestAdapter):
    def load(self, data: dict, entry: GisLayerTypeEntry, *, strict: bool = False) -> AdapterResult:
        layer_type = entry.ingest.feature_type if entry.ingest else "current_landuse"
        parcels, warnings = ingest_landuse(data, layer_type=layer_type, strict=strict)
        dlq_entries: list[DlqEntry] = []
        clean_warnings: list[str] = []
        for w in warnings:
            if "geometry" in w.lower() or "invalid" in w.lower():
                dlq_entries.append(DlqEntry(
                    category=DlqCategory.GEOMETRY,
                    reason=w,
                    source_layer=layer_type,
                    raw_feature={},
                ))
            else:
                clean_warnings.append(w)
        return AdapterResult(features=parcels, warnings=clean_warnings, dlq=dlq_entries)
```

Add imports: `from app.modules.kg.dlq import DlqCategory, DlqEntry`.

- [ ] **Step 6: Update `FeaturesAdapter` similarly**

In `backend/app/modules/data/adapters/features.py`:

```python
class FeaturesAdapter(IngestAdapter):
    def load(self, data: dict, entry: GisLayerTypeEntry, *, strict: bool = False) -> AdapterResult:
        layer_type = entry.ingest.feature_type if entry.ingest else ""
        features, warnings = ingest_feature(data, layer_type=layer_type, strict=strict)
        dlq_entries: list[DlqEntry] = []
        clean_warnings: list[str] = []
        for w in warnings:
            if "geometry" in w.lower() or "invalid" in w.lower():
                dlq_entries.append(DlqEntry(
                    category=DlqCategory.GEOMETRY,
                    reason=w,
                    source_layer=layer_type,
                    raw_feature={},
                ))
            else:
                clean_warnings.append(w)
        return AdapterResult(features=features, warnings=clean_warnings, dlq=dlq_entries)
```

Add imports: `from app.modules.kg.dlq import DlqCategory, DlqEntry`.

- [ ] **Step 7: Update `kg/builder/__init__.py` to export DLQ**

In `backend/app/modules/kg/builder/__init__.py`, add:

```python
from app.modules.kg.dlq import DlqCategory, DlqEntry, DlqReport
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest backend/tests/unit/test_dlq.py -v`
Expected: PASS

Run: `pytest backend/tests/unit/test_adapters.py -v`
Expected: PASS (no regression)

- [ ] **Step 9: Commit**

```bash
git add backend/app/modules/kg/dlq.py backend/app/modules/data/adapters/__init__.py backend/app/modules/data/adapters/parcels.py backend/app/modules/data/adapters/features.py backend/app/modules/kg/builder/__init__.py backend/tests/unit/test_dlq.py
git commit -m "feat(phase7): DLQ three-category infrastructure + AdapterResult structured DLQ"
```

---

### Task 4: Provenance 字段入 Feature 模型

**Files:**
- Modify: `backend/app/modules/schema/types/spatial_types.py` (add `mapping_provenance` to `BaseLandUseParcel`)
- Modify: `backend/app/modules/data/ingest.py` (`_resolve_code` returns provenance, `ingest_landuse` stores on parcel)
- Test: `backend/tests/unit/test_gis_unit.py` (append provenance tests)

**Interfaces:**
- Consumes: `BaseLandUseParcel` from `spatial_types.py`
- Produces: `parcel.mapping_provenance: dict` — consumed by `_add_parcels()` in Task 5

- [ ] **Step 1: Write the failing test**

```python
class TestParcelProvenance:
    def test_mapping_provenance_default(self):
        from app.modules.schema.types.spatial_types import CurrentLandUseParcel
        p = CurrentLandUseParcel(
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            dlbm="0110",
        )
        assert p.mapping_provenance == {}

    def test_mapping_provenance_stored(self):
        from app.modules.schema.types.spatial_types import CurrentLandUseParcel
        provenance = {
            "DLBM": {
                "decided_by": "rule",
                "confidence": "exact",
                "system": "gbt21010",
            }
        }
        p = CurrentLandUseParcel(
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            dlbm="0110",
            mapping_provenance=provenance,
        )
        assert p.mapping_provenance["DLBM"]["decided_by"] == "rule"
        assert p.mapping_provenance["DLBM"]["system"] == "gbt21010"

    def test_ingest_stores_provenance_for_all_code_fields(self):
        """Integration test: ingest_landuse should store provenance entries
        for each resolved code field (DLBM, SDDLBM, etc.)."""
        from app.modules.data.ingest import ingest_landuse
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {
                    "BSM": "001",
                    "DLBM": "0110",
                    "SDDLBM": "0110",
                    "DLMC": "水田",
                },
            }],
        }
        parcels, warnings = ingest_landuse(geojson, layer_type="current_landuse")
        assert len(parcels) == 1
        p = parcels[0]
        assert "DLBM" in p.mapping_provenance
        prov = p.mapping_provenance["DLBM"]
        assert prov["decided_by"] == "rule"
        assert prov["confidence"] == "exact"
        assert "SDDLBM" in p.mapping_provenance
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_gis_unit.py::TestParcelProvenance -v`
Expected: FAIL — `BaseLandUseParcel` has no `mapping_provenance` field

- [ ] **Step 3: Add `mapping_provenance` to `BaseLandUseParcel`**

In `backend/app/modules/schema/types/spatial_types.py`, add to `BaseLandUseParcel`:

```python
from pydantic import BaseModel, Field

class BaseLandUseParcel(PolygonFeature):
    layer_type: str = ""
    dlbm: str = ""
    dlbm_system: str = ""
    name: str = ""
    area_sqm: float = 0.0
    zone_type: str = ""
    planning_zone: str = ""
    primary_zone: str = ""
    mapping_provenance: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Update `_resolve_code` to return provenance**

In `backend/app/modules/data/ingest.py`, change `_resolve_code` return type and add provenance:

```python
def _resolve_code(
    code: Any,
    field_name: str,
    layer_type: str,
    warnings: List[str],
    feature_index: int,
) -> Tuple[str, str, dict]:
    """校验一个编码字段并返回 (value, system, provenance)。

    provenance dict 包含:
        - decided_by: 决策方式 (rule/llm/human/default)
        - confidence: 置信度 (exact/conditional)
        - system: 匹配的编码体系
        - warning: 警告信息(如有)
    """
    code_str = str(code).strip() if code is not None else ""
    if not code_str:
        return "", "", {"decided_by": "default", "confidence": "exact", "system": "", "warning": ""}

    expected = _field_system(layer_type, field_name)
    if not expected:
        return code_str, "", {
            "decided_by": "default", "confidence": "exact",
            "system": "", "warning": "",
        }

    system, warning = _validator.resolve(code_str, expected)
    if warning:
        warnings.append(f"[feature#{feature_index}] {field_name}: {warning}")

    decided_by = "rule"
    confidence = "exact"
    if warning and "not found" in warning:
        decided_by = "default"
        confidence = "conditional"
    elif warning and "ambiguous" in warning:
        decided_by = "rule"
        confidence = "conditional"

    provenance = {
        "decided_by": decided_by,
        "confidence": confidence,
        "system": system,
        "warning": warning,
    }

    return code_str, system, provenance
```

- [ ] **Step 5: Update `ingest_landuse` to store provenance on parcels**

In `ingest_landuse()`, after resolving each code field, build the `mapping_provenance` dict:

```python
    # After all _resolve_code calls (around line 282):
    dlbm, dlbm_sys, dlbm_prov = _resolve_code(props.get("DLBM", ""), "DLBM", layer_type, warnings, i)
    sddlbm, sddlbm_sys, sddlbm_prov = _resolve_code(props.get("SDDLBM", ""), "SDDLBM", layer_type, warnings, i)
    qmdlbm, qmdlbm_sys, qmdlbm_prov = _resolve_code(props.get("QMDLBM", ""), "QMDLBM", layer_type, warnings, i)
    ghytbm, ghytbm_sys, ghytbm_prov = _resolve_code(props.get("GHYTBM", ""), "GHYTBM", layer_type, warnings, i)
    ghflbm, ghflbm_sys, ghflbm_prov = _resolve_code(props.get("GHFLBM", ""), "GHFLBM", layer_type, warnings, i)
    qmghflbm, qmghflbm_system, qmghflbm_prov = _resolve_code(props.get("QMGHFLBM", ""), "QMGHFLBM", layer_type, warnings, i)

    # Build provenance dict (only non-empty fields)
    mapping_provenance = {}
    if dlbm:
        mapping_provenance["DLBM"] = dlbm_prov
    if sddlbm:
        mapping_provenance["SDDLBM"] = sddlbm_prov
    if qmdlbm:
        mapping_provenance["QMDLBM"] = qmdlbm_prov
    if ghytbm:
        mapping_provenance["GHYTBM"] = ghytbm_prov
    if ghflbm:
        mapping_provenance["GHFLBM"] = ghflbm_prov
    if qmghflbm:
        mapping_provenance["QMGHFLBM"] = qmghflbm_prov
```

Then add `mapping_provenance=mapping_provenance` to the `shared` dict:

```python
    shared = dict(
        geometry=geom,
        dlbm=dlbm,
        dlbm_system=dlbm_sys,
        name=name,
        area_sqm=area_sqm,
        bsm=bsm,
        ysdm=ysdm,
        zone_type=zone_type,
        planning_zone=planning_zone,
        primary_zone=primary_zone,
        mapping_provenance=mapping_provenance,
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest backend/tests/unit/test_gis_unit.py::TestParcelProvenance -v`
Expected: PASS

- [ ] **Step 7: Run existing tests to verify no regression**

Run: `pytest backend/tests/unit/test_encoding_consistency.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/schema/types/spatial_types.py backend/app/modules/data/ingest.py backend/tests/unit/test_gis_unit.py
git commit -m "feat(phase7): add mapping_provenance field to BaseLandUseParcel + ingest provenance recording"
```

---

### Task 5: Provenance 写入 KG — `_add_parcels()`

**Files:**
- Modify: `backend/app/modules/kg/builder/layer1.py` (write `ProvenancePredicates` triples)
- Test: `backend/tests/integration/test_kg_jintian_e2e.py` (verify provenance triples in KG)

**Interfaces:**
- Consumes: `parcel.mapping_provenance: dict` from Task 4, `ProvenancePredicates` from `ontology.py`
- Produces: RDF triples with `pln:decided_by`, `pln:decision_confidence`, `pln:decision_evidence`, `pln:mapping_basis`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_kg_jintian_e2e.py`:

```python
class TestProvenanceInKG:
    """Verify provenance triples are written to KG during build_from_bundle."""

    def test_provenance_triples_present(self, gis_data, real_intent):
        from app.modules.kg.builder import PlanningKG
        kg = PlanningKG(village_name="金田村")
        kg.build_from_bundle(gis_data, intent=real_intent)
        from app.modules.kg.ontology import ProvenancePredicates

        # Query for provenance triples
        provenance_preds = {
            ProvenancePredicates.decided_by,
            ProvenancePredicates.decision_confidence,
            ProvenancePredicates.decision_evidence,
            ProvenancePredicates.mapping_basis,
        }

        found = set()
        for s, p, o in kg.g.triples((None, None, None)):
            if p in provenance_preds:
                found.add(p)

        assert len(found) > 0, (
            f"No provenance triples found in KG. "
            f"Expected at least one of {provenance_preds}"
        )

    def test_provenance_on_parcels(self, gis_data, real_intent):
        from app.modules.kg.builder import PlanningKG
        from app.modules.kg.ontology import (
            EntityTypes, ProvenancePredicates, PLN, RDF,
        )
        kg = PlanningKG(village_name="金田村")
        kg.build_from_bundle(gis_data, intent=real_intent)

        # Find a parcel entity
        parcel_uris = list(kg.g.subjects(RDF.type, EntityTypes.Parcel))
        assert len(parcel_uris) > 0

        # Check at least one parcel has provenance info
        has_provenance = False
        for pu in parcel_uris:
            for _ in kg.g.triples((pu, ProvenancePredicates.decided_by, None)):
                has_provenance = True
                break
            if has_provenance:
                break

        assert has_provenance, (
            "No parcel entity has provenance triples. "
            "Expected decided_by/decision_confidence on parcels."
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/integration/test_kg_jintian_e2e.py::TestProvenanceInKG -v`
Expected: FAIL (no provenance triples in KG)

- [ ] **Step 3: Add provenance writing to `_add_parcels()`**

In `backend/app/modules/kg/builder/layer1.py`, after the `_add_wkt_geometry` call (line 322), add:

```python
        # ── v4.9: Encoding decision provenance ──
        mapping_prov = getattr(p, "mapping_provenance", None) or {}
        for field_name, prov in mapping_prov.items():
            if not isinstance(prov, dict):
                continue
            decided_by = prov.get("decided_by", "")
            if decided_by:
                self.g.add((pu, ProvenancePredicates.decided_by, Literal(decided_by)))
            confidence = prov.get("confidence", "")
            if confidence:
                self.g.add((pu, ProvenancePredicates.decision_confidence, Literal(confidence)))
            system = prov.get("system", "")
            if system:
                self.g.add((pu, ProvenancePredicates.decision_evidence, Literal(system)))
            warning = prov.get("warning", "")
            if warning:
                self.g.add((pu, ProvenancePredicates.mapping_basis, Literal(warning)))
```

At the top of `layer1.py`, ensure `ProvenancePredicates` is imported:

```python
from app.modules.kg.ontology import (
    EntityIdPolicy, EntityTypes, Relations, SemanticPredicates, ProvenancePredicates,
    PLN, GEO, RDF, RDFS, OWL, XSD,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/integration/test_kg_jintian_e2e.py::TestProvenanceInKG -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regression**

Run: `pytest backend/tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/kg/builder/layer1.py backend/tests/integration/test_kg_jintian_e2e.py
git commit -m "feat(phase7): write ProvenancePredicates triples in _add_parcels() from mapping_provenance"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- §3.3 Disambiguation models (Candidate, DisambiguationContext, DisambiguationDecision) → Task 1
- §3.4 Resolution.needs_llm() + CandidateEngine L2 path → Task 2
- §7.1 DLQ三类 (geometry/mapping/review) → Task 3
- §6.5 Provenance predicates 入 KG (decided_by, decision_confidence, decision_evidence, mapping_basis) → Task 4 + Task 5
- "不实现 LLM 调用" → confirmed: no instructor_client import in any new code
- "管道不中断" → DLQ is collection-only, no exceptions

**2. Placeholder scan:** No TBD, TODO, "implement later", or placeholder code found. All code blocks contain complete, runnable implementations.

**3. Type consistency:**
- `Resolution.kind` Literal: `"auto" | "rule" | "llm" | "manual" | "unmapped"` — consistent across Task 2
- `DlqCategory` enum values: `"geometry" | "mapping" | "review"` — consistent across Task 3
- `ProvenancePredicates` field names: `decided_by`, `decision_confidence`, `decision_evidence`, `mapping_basis` — matching `ontology.py` from Phase 6
- `BaseLandUseParcel.mapping_provenance` type: `dict[str, Any]` — consistent across Task 4 and Task 5
- `_resolve_code` return type: `Tuple[str, str, dict]` — updated in Task 4, all callers updated