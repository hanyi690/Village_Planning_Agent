"""Tests for the upload flow: file classification, parsing, type inference,
and persistence to the database.

Three layers are covered:
  1. `classify_file_type` / type-inference helpers (pure functions)
  2. `_parse_file_in_memory` / `_process_uploaded_file_db` (in-memory parse + DB payload)
  3. Real SQLite roundtrip via `create_uploaded_file_async` and read-back helpers
     (temp-file DB, engine globals patched to an isolated database)

NOTE: this module imports `app.api.session_routes` which requires `fastapi`;
run with the project environment that has it installed.
"""

import json

import pytest

pytest.importorskip("fastapi")


class _FakeUploadFile:
    def __init__(self, filename, content, content_type="application/octet-stream"):
        self.filename = filename
        self.content_type = content_type
        self._content = content if isinstance(content, bytes) else content.encode("utf-8")

    async def read(self):
        return self._content


class _StubLoader:
    """Deterministic stand-in for MarkItDownLoader in document-parse tests."""

    def __init__(self, file_path, category=None):
        self._file_path = file_path
        self._text = file_path.read_text(encoding="utf-8")

    def load(self):
        from langchain_core.documents import Document

        return [Document(page_content=self._text, metadata={"source": self._file_path.name})]


def _geojson(features_props):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }
            for props in features_props
        ],
    }


# ============================================================
# 1. file type classification
# ============================================================

@pytest.mark.parametrize(
    "filename,expected",
    [
        ("village.geojson", "geojson"),
        ("roads.shp", "shapefile"),
        ("roads.zip", "shapefile"),
        ("boundary.kml", "kml"),
        ("boundary.kmz", "kml"),
        ("data.gpkg", "gis_file"),
        ("track.gpx", "gis_file"),
        ("parcel.gml", "gis_file"),
        ("notes.md", "document"),
        ("input.docx", "document"),
        ("text.txt", "document"),
        ("report.pdf", "document"),
        ("LANDUSE.GEOJSON", "geojson"),
    ],
)
def test_classify_file_type(filename, expected):
    from app.utils.document_loader import classify_file_type

    assert classify_file_type(filename) == expected


# ============================================================
# 2. GIS data type inference
# ============================================================

@pytest.mark.parametrize(
    "props,expected",
    [
        ({"name": "金田村边界"}, "boundary"),
        ({"layer": "boundary"}, "boundary"),
        ({"DJZQMC": "金田村委会"}, "boundary"),
        ({"name": "道路"}, "road"),
        ({"layer": "road"}, "road"),
        ({"name": "河流"}, "water"),
        ({"name": "水域"}, "water"),
        ({"layer": "water"}, "water"),
        ({"name": "住宅用地"}, "residential"),
        ({"layer": "residential"}, "residential"),
        ({"name": "建设用地"}, "landuse_current"),
        ({"layer": "landuse"}, "landuse_current"),
        ({"name": "其他"}, None),
        ({}, None),
    ],
)
def test_infer_geojson_data_type(props, expected):
    from app.api.session_routes import _infer_geojson_data_type

    assert _infer_geojson_data_type(_geojson([props])) == expected


def test_infer_geojson_data_type_empty_features():
    from app.api.session_routes import _infer_geojson_data_type

    assert _infer_geojson_data_type({"type": "FeatureCollection", "features": []}) is None
    assert _infer_geojson_data_type({"type": "Point", "coordinates": [0, 0]}) is None
    assert _infer_geojson_data_type(None) is None


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("金田村边界.geojson", "boundary"),
        ("boundary.geojson", "boundary"),
        ("现状用地.geojson", "landuse_current"),
        ("landuse.geojson", "landuse_current"),
        ("道路.geojson", "road"),
        ("annotation.geojson", "current_annotation"),
        ("water.geojson", "water"),
        ("居民点.geojson", "residential"),
        ("地块.geojson", None),
    ],
)
def test_infer_data_type_from_filename(filename, expected):
    from app.api.session_routes import _infer_data_type_from_filename

    assert _infer_data_type_from_filename(filename) == expected


# ============================================================
# 3. in-memory parse (_parse_file_in_memory)
# ============================================================

@pytest.mark.asyncio
async def test_parse_valid_geojson_boundary():
    from app.api.session_routes import _parse_file_in_memory

    data = _geojson([{"name": "金田村边界"}])
    file = _FakeUploadFile("boundary.geojson", json.dumps(data, ensure_ascii=False))
    parsed = await _parse_file_in_memory(file, file._content)

    assert parsed["file_type"] == "geojson"
    assert parsed["parse_status"] == "success"
    assert parsed["gis_data"] == data
    assert parsed["gis_data_type"] == "boundary"
    assert parsed["parsed_text"] is None


@pytest.mark.asyncio
async def test_parse_geojson_without_inferable_type():
    from app.api.session_routes import _parse_file_in_memory

    file = _FakeUploadFile("地块.geojson", json.dumps(_geojson([{"name": "地块A"}])))
    parsed = await _parse_file_in_memory(file, file._content)

    assert parsed["parse_status"] == "success"
    assert parsed["gis_data_type"] is None


@pytest.mark.asyncio
async def test_parse_invalid_json():
    from app.api.session_routes import _parse_file_in_memory

    file = _FakeUploadFile("bad.geojson", "{not json")
    parsed = await _parse_file_in_memory(file, file._content)

    assert parsed["parse_status"] == "failed"
    assert parsed["parse_error"]
    assert parsed["gis_data"] is None


@pytest.mark.asyncio
async def test_parse_json_not_feature_collection():
    from app.api.session_routes import _parse_file_in_memory

    file = _FakeUploadFile("point.geojson", json.dumps({"type": "Point", "coordinates": [1, 2]}))
    parsed = await _parse_file_in_memory(file, file._content)

    assert parsed["parse_status"] == "failed"
    assert "FeatureCollection" in parsed["parse_error"]


@pytest.mark.asyncio
async def test_parse_markdown_document(monkeypatch):
    from app.api import session_routes
    from app.api.session_routes import _parse_file_in_memory

    monkeypatch.setattr(session_routes, "MarkItDownLoader", _StubLoader)
    file = _FakeUploadFile("input.md", "## 现状\n人口 500 人，耕地 120 公顷。")
    parsed = await _parse_file_in_memory(file, file._content)

    assert parsed["file_type"] == "document"
    assert parsed["parse_status"] == "success"
    assert "人口 500 人" in parsed["parsed_text"]
    assert parsed["gis_data"] is None


@pytest.mark.asyncio
async def test_parse_raw_shapefile_zip():
    from app.api.session_routes import _parse_file_in_memory

    file = _FakeUploadFile("roads.zip", b"PK\x03\x04 fake zip bytes")
    parsed = await _parse_file_in_memory(file, file._content)

    assert parsed["file_type"] == "shapefile"
    assert parsed["parse_status"] == "success"
    assert parsed["gis_data"] is None
    assert parsed["parsed_text"] is None


@pytest.mark.asyncio
async def test_parse_unknown_file_type_raw():
    from app.api.session_routes import _parse_file_in_memory

    # `.bin` is classified as "document" (default); no extractable text -> failed
    file = _FakeUploadFile("data.bin", b"\x00\x01\x02")
    parsed = await _parse_file_in_memory(file, file._content)

    assert parsed["file_type"] == "document"
    assert parsed["parse_status"] == "failed"
    assert parsed["parse_error"]
    assert parsed["parsed_text"] is None


# ============================================================
# 4. DB payload contract (_process_uploaded_file_db)
# ============================================================

@pytest.mark.asyncio
async def test_process_uploaded_file_db_geojson(monkeypatch):
    from app.api import session_routes
    from app.api.session_routes import _process_uploaded_file_db

    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return 42

    monkeypatch.setattr(session_routes, "create_uploaded_file_async", fake_create)

    data = _geojson([{"name": "金田村边界"}])
    file = _FakeUploadFile(
        "boundary.geojson", json.dumps(data, ensure_ascii=False),
        content_type="application/geo+json",
    )
    result = await _process_uploaded_file_db(file, "sess-upload", "village_data")

    assert result["id"] == 42
    assert captured["session_id"] == "sess-upload"
    assert captured["file_category"] == "village_data"
    assert captured["file_type"] == "geojson"
    assert captured["gis_data"] == data
    assert captured["gis_data_type"] == "boundary"
    assert captured["parse_status"] == "success"
    assert captured["file_size"] == len(file._content)


@pytest.mark.asyncio
async def test_process_uploaded_file_db_uses_filename_type_fallback(monkeypatch):
    from app.api import session_routes
    from app.api.session_routes import _process_uploaded_file_db

    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return 43

    monkeypatch.setattr(session_routes, "create_uploaded_file_async", fake_create)
    data = _geojson([{"name": "地块A"}])
    file = _FakeUploadFile("landuse.geojson", json.dumps(data, ensure_ascii=False))

    result = await _process_uploaded_file_db(file, "sess-upload", "village_data")

    assert result["gis_data_type"] == "landuse_current"
    assert captured["gis_data_type"] == "landuse_current"


@pytest.mark.asyncio
async def test_process_uploaded_file_db_normalizes_placeholder_type(monkeypatch):
    """Placeholder gis_data_type (upload/auto/unknown) falls back to filename inference."""
    from app.api import session_routes
    from app.api.session_routes import _process_uploaded_file_db

    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return 44

    monkeypatch.setattr(session_routes, "create_uploaded_file_async", fake_create)
    monkeypatch.setattr(
        session_routes, "_infer_geojson_data_type", lambda geojson: "upload"
    )
    data = _geojson([{"name": "地块A"}])
    file = _FakeUploadFile("road.geojson", json.dumps(data, ensure_ascii=False))

    result = await _process_uploaded_file_db(file, "sess-upload", "village_data")

    assert result["gis_data_type"] == "road"
    assert captured["gis_data_type"] == "road"


@pytest.mark.asyncio
async def test_process_uploaded_file_db_document(monkeypatch):
    from app.api import session_routes
    from app.api.session_routes import _process_uploaded_file_db

    monkeypatch.setattr(session_routes, "MarkItDownLoader", _StubLoader)
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return 7

    monkeypatch.setattr(session_routes, "create_uploaded_file_async", fake_create)

    file = _FakeUploadFile("task.md", "任务描述：编制村庄规划，重点发展乡村旅游。")
    result = await _process_uploaded_file_db(file, "sess-upload", "task_description")

    assert result["id"] == 7
    assert captured["file_type"] == "document"
    assert captured["parse_status"] == "success"
    assert "乡村旅游" in captured["parsed_text"]
    assert captured["gis_data"] is None


# ============================================================
# 5. real SQLite roundtrip
# ============================================================

@pytest.mark.asyncio
async def test_upload_files_persist_to_db(sqlite_db):
    setup, teardown = sqlite_db
    await setup()
    try:
        from app.database.operations import (
            create_planning_session_async,
            create_uploaded_file_async,
            delete_uploaded_files_async,
            get_uploaded_files_by_session_async,
            get_uploaded_geojson_data_async,
        )

        sid = await create_planning_session_async({"session_id": "sess-up-1"})
        assert sid == "sess-up-1"

        boundary = _geojson([{"name": "金田村边界"}])
        road = _geojson([{"layer": "road", "name": "村道"}])

        fid_b = await create_uploaded_file_async(
            session_id=sid, file_category="village_data", file_type="geojson",
            filename="boundary.geojson", original_filename="boundary.geojson",
            file_size=len(json.dumps(boundary)), content_type="application/geo+json",
            gis_data=boundary, gis_data_type="boundary",
        )
        fid_r = await create_uploaded_file_async(
            session_id=sid, file_category="village_data", file_type="geojson",
            filename="road.geojson", original_filename="road.geojson",
            file_size=len(json.dumps(road)), content_type="application/geo+json",
            gis_data=road, gis_data_type="road",
        )
        fid_d = await create_uploaded_file_async(
            session_id=sid, file_category="task_description", file_type="document",
            filename="task.md", original_filename="task.md", file_size=32,
            content_type="text/markdown", parsed_text="任务：编制村庄规划。",
        )
        fid_z = await create_uploaded_file_async(
            session_id=sid, file_category="village_data", file_type="shapefile",
            filename="roads.zip", original_filename="roads.zip", file_size=10,
            content_type="application/zip", parse_status="success",
        )
        assert [fid_b, fid_r, fid_d, fid_z] == [1, 2, 3, 4]

        files = await get_uploaded_files_by_session_async(sid)
        assert len(files) == 4
        by_type = {f["file_type"] for f in files}
        assert by_type == {"geojson", "document", "shapefile"}
        assert all(f["session_id"] == sid for f in files)

        docs = await get_uploaded_files_by_session_async(sid, file_category="village_data")
        assert len(docs) == 3
        assert {d["file_type"] for d in docs} == {"geojson", "shapefile"}

        geojsons = await get_uploaded_geojson_data_async(sid)
        assert len(geojsons) == 2

        boundary_only = await get_uploaded_geojson_data_async(sid, data_type_hint="boundary")
        assert len(boundary_only) == 1
        assert boundary_only[0]["features"][0]["properties"]["name"] == "金田村边界"

        deleted = await delete_uploaded_files_async(sid)
        assert deleted == 4
        assert await get_uploaded_files_by_session_async(sid) == []
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_uploaded_files_cascade_on_session_delete(sqlite_db):
    setup, teardown = sqlite_db
    await setup()
    try:
        from app.database.operations import (
            create_planning_session_async,
            create_uploaded_file_async,
            delete_planning_session_async,
            get_uploaded_files_by_session_async,
        )

        sid = await create_planning_session_async({"session_id": "sess-up-2"})
        await create_uploaded_file_async(
            session_id=sid, file_category="village_data", file_type="geojson",
            filename="boundary.geojson", original_filename="boundary.geojson",
            file_size=8, content_type="application/geo+json",
            gis_data=_geojson([{"name": "边界"}]), gis_data_type="boundary",
        )
        assert len(await get_uploaded_files_by_session_async(sid)) == 1

        await delete_planning_session_async(sid)
        assert await get_uploaded_files_by_session_async(sid) == []
    finally:
        await teardown()
