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
        cats = {c.value for c in DlqCategory}
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