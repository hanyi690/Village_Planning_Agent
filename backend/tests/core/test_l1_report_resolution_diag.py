"""Deterministic diagnostic: which places the current-state report names, and
whether each one resolves to a spatial extent/entity in the real fixture KG.

Hard constraints honored:
  - Only input: the current-state report (current_report.md).
  - NO preset place names (no _KNOWN_NATURAL_VILLAGES): every token is pulled
    from the report text/tables.
  - Deterministic, no LLM, no graph, no L3.
"""
from __future__ import annotations

import asyncio
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.db import make_session_with_uploads  # noqa: E402

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village"

_LAYER_TYPES = {
    "admin_boundary_line.geojson": "admin_boundary_line",
    "annotation.geojson": "annotation",
    "boundary.geojson": "boundary",
    "construction_zone.geojson": "construction_zone",
    "ecological_protection.geojson": "ecological_protection",
    "farmland_protection.geojson": "farmland_protection",
    "geological_hazard_points.geojson": "geological_hazard_points",
    "historical_protection.geojson": "historical_protection",
    "landuse.geojson": "landuse_current",
    "road.geojson": "road",
}


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _report_tables(report_text: str) -> list[list[str]]:
    rows = []
    for block in re.findall(r"<table\b[^>]*>.*?</table>", report_text, flags=re.I | re.S):
        parser = _TableParser()
        parser.feed(block)
        rows.extend(parser.rows)
    return rows


def extract_report_places(report_text: str) -> list[dict]:
    """Pull place names from the report only. No preset lists."""
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, role: str) -> None:
        name = (name or "").strip(" 、,，;；.")
        key = (role, name)
        if name and name not in {"全村", "/", "-", "—"} and key not in seen:
            seen.add(key)
            found.append({"name": name, "role": role})

    # Villages: the report's own enumerations and X村/X自然村 tokens.
    for m in re.finditer(
        r"[\u4e00-\u9fff]{2,6}(?:自然村|村)", report_text or ""
    ):
        add(m.group(0), "village")
    for m in re.finditer(
        r"(?:下辖|包括|分别为|分别是)[^。\n]{0,40}?([\u4e00-\u9fff、,，]{2,60})(?:。|；|$)",
        report_text or "",
    ):
        for tok in re.split(r"[、,，]", m.group(1)):
            add(tok, "village")

    # Roads.
    for m in re.finditer(
        r"[A-Za-z0-9\u4e00-\u9fff]{1,12}(?:乡道|县道|省道|国道|公路|大道|古驿道)",
        report_text or "",
    ):
        add(m.group(0), "road")

    # Water.
    for m in re.finditer(
        r"[\u4e00-\u9fff]{2,5}(?:河|溪|塘|湖|水库|圳)", report_text or ""
    ):
        add(m.group(0), "water")

    # Facilities: 现状台账 tables (设施名称 at index 2, 所在空间位置 at index 7).
    for row in _report_tables(report_text):
        if len(row) < 8:
            continue
        name = row[2]
        if not name or name in {"设施名称", "序号"} or len(name) < 2:
            continue
        add(name, "facility")
        location = row[7]
        if location:
            for tok in re.split(r"[、,，;；/1-9]+", location):
                add(tok.strip(), "village")

    return found


def _uploads() -> list[dict]:
    ups = [{
        "file_category": "village_data",
        "filename": "current_report.md",
        "original_filename": "current_report.md",
        "content_type": "text/markdown",
        "file_type": "md",
        "parsed_text": (FIXTURE / "current_report.md").read_text(encoding="utf-8"),
    }]
    for path in sorted((FIXTURE / "gis").glob("*.geojson")):
        ups.append({
            "file_category": "gis_data",
            "filename": path.name,
            "original_filename": path.name,
            "content_type": "application/geo+json",
            "file_type": "geojson",
            "file_size": path.stat().st_size,
            "gis_data": json.loads(path.read_text(encoding="utf-8")),
            "gis_data_type": _LAYER_TYPES[path.name],
        })
    return ups


@pytest.mark.asyncio
async def test_report_place_resolution_diagnostic(sqlite_db, pipeline_reset):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-l1-diag"
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from rdflib import RDF

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)

        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")
        places = extract_report_places(report)
        print(f"\n=== extracted places ({len(places)}) ===")
        for p in places:
            print(f"  {p['role']:<8} {p['name']}")

        print(f"\n=== gazetteer entries ({len(gazetteer.entries)}) ===")
        for e in list(gazetteer.entries)[:60]:
            print(
                f"  name={e.name!r} aliases={getattr(e, 'aliases', [])} "
                f"bsms={len(getattr(e, 'bsms', []) or [])} source={getattr(e, 'source', '')}"
            )

        from app.infrastructure.kg.ontology import PLN

        print("\n=== KG named entities (name / type / bsm) ===")
        for s, _, o in kg.g.triples((None, RDF.type, None)):
            name = str(kg.g.value(s, PLN.name) or "")
            if not name:
                continue
            type_frag = str(o).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            bsm = str(kg.g.value(s, PLN.bsm) or "")
            print(f"  {type_frag:<24} {name!r:<20} bsm={bsm or '-'}")

        from app.infrastructure.kg.enrichment.name_backfill import (
            NameMention,
            backfill_kg_names_sync,
        )
        result = backfill_kg_names_sync(kg, gazetteer, [
            NameMention(name=p["name"], role=p["role"], location=p["name"], source_dimension="diag")
            for p in places
        ])
        print(f"\n=== name backfill: applied={result.applied} unresolved={len(result.unresolved)} ===")
        for d in result.decisions:
            print(f"  {d['name']} -> {d['entity_uri']}")
        if result.unresolved:
            print("  unresolved:", result.unresolved[:40])

        from app.contracts.domain.l1_contracts import L1LocationFact

        facts = [
            L1LocationFact(
                mention=p["name"], normalized_name=p["name"], role=p["role"],
                aliases=[p["name"]], spatial_hint=p["name"],
                source_report_ref="current_report.md", dimension_key="diag",
                source_span="", confidence=1.0,
            )
            for p in places
        ]
        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1,
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=facts,
        )
        context.current_parcels = lambda: list(bundle.polygons.get("landuse_current") or [])

        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

        index = PlaceEvidenceIndex.build(context)

        print(f"\n=== evidence index entries ({len(index.entries)}) ===")
        for e in index.entries:
            print(
                f"  {e.canonical_name!r:<20} role={e.role:<8} "
                f"bsms={len(e.source_bsms)} prov={e.provenance} "
                f"entity={e.entity_refs[0] if e.entity_refs else '-'}"
            )

        print("\n=== per-place resolution ===")
        unresolved_names = []
        for p in places:
            res = index.resolve_mention(p["name"], role=p["role"])
            cand = res.candidates[0] if res.candidates else None
            ok = res.status == "resolved" and cand and cand.source_bsms
            if not ok:
                unresolved_names.append(p["name"])
            print(
                f"  {p['role']:<8} {p['name']!r:<18} status={res.status:<10} "
                f"bsms={len(cand.source_bsms) if cand else 0} "
                f"entity={cand.entity_ref if cand else '-'}"
            )
        print(f"\nunresolved({len(unresolved_names)}): {unresolved_names}", flush=True)
    finally:
        await teardown()
