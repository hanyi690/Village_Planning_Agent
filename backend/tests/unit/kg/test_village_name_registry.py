"""Unit tests for app.modules.kg.village_name_registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.kg.village_name_registry import (
    clear_cache,
    find_village_yaml,
    load_all_village_names,
    load_village_names,
    resolve_village_key,
)


_YAML_TEMPLATE = """\
village:
  name: "金田村委会"
  code: "441426108004"
  province: "广东省"

natural_villages:
  - 园寨
  - 田坑
  - 社前
"""


@pytest.fixture(autouse=True)
def _isolate_cache_and_cwd(tmp_path, monkeypatch):
    clear_cache()
    monkeypatch.chdir(tmp_path)
    yield
    clear_cache()


def test_load_village_names_returns_names_from_yaml(tmp_path):
    village_dir = tmp_path / "data" / "gis" / "jintian"
    village_dir.mkdir(parents=True)
    (village_dir / "villages.yaml").write_text(_YAML_TEMPLATE, encoding="utf-8")

    names = load_village_names("jintian")

    assert names == ("园寨", "田坑", "社前")


def test_load_village_names_missing_yaml_returns_empty(tmp_path):
    names = load_village_names("does_not_exist")

    assert names == ()


def test_load_village_names_caches_result(tmp_path):
    village_dir = tmp_path / "data" / "gis" / "jintian"
    village_dir.mkdir(parents=True)
    cfg = village_dir / "villages.yaml"
    cfg.write_text(_YAML_TEMPLATE, encoding="utf-8")

    first = load_village_names("jintian")

    cfg.write_text("natural_villages:\n  - 其他\n", encoding="utf-8")

    second = load_village_names("jintian")

    assert first == second
    assert second == ("园寨", "田坑", "社前")


def test_resolve_village_key_strips_suffix():
    assert resolve_village_key("金田村委会") == "金田"
    assert resolve_village_key("金田村") == "金田"
    assert resolve_village_key("金田") == "金田"
    assert resolve_village_key("园寨村委会") == "园寨"


def test_find_village_yaml_matches_configured_administrative_name(tmp_path):
    village_dir = tmp_path / "data" / "gis" / "jintian"
    village_dir.mkdir(parents=True)
    cfg = village_dir / "villages.yaml"
    cfg.write_text(_YAML_TEMPLATE, encoding="utf-8")

    assert find_village_yaml("金田村委会") == cfg
    assert find_village_yaml("missing-village") is None


def test_load_all_village_names_has_no_fixed_village_fallback(tmp_path):
    village_dir = tmp_path / "data" / "gis" / "other"
    village_dir.mkdir(parents=True)
    (village_dir / "villages.yaml").write_text(
        "village:\n  name: '其他村委会'\nnatural_villages:\n  - 新村\n",
        encoding="utf-8",
    )
    assert load_all_village_names() == ("新村",)


def test_catalog_meta_does_not_guess_another_village(tmp_path, monkeypatch):
    from app.modules.data.catalog.catalog import DataCatalog

    monkeypatch.chdir(tmp_path)
    village_dir = tmp_path / "data" / "gis" / "jintian"
    village_dir.mkdir(parents=True)
    (village_dir / "villages.yaml").write_text(_YAML_TEMPLATE, encoding="utf-8")

    catalog = object.__new__(DataCatalog)
    assert catalog._load_village_yaml_meta("unknown-village") == {}
    assert catalog._load_village_yaml_meta("金田村委会")["province"] == "广东省"
    anchors = catalog._load_village_anchors("金田村委会")
    assert "园寨" in anchors
