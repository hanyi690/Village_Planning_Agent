"""BundleAssemblyPort — kg must not import from app.modules.data.

Wave M1: the kg->data reverse dependency (kg/service.py lazy import of
`_merge_geojson_into_bundle`) is eliminated by injecting a BundleAssemblyPort
through PlanningPorts. These tests verify the port exists, the data-layer
adapter implements it, and kg/service.py no longer imports app.modules.data.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.modules.ports.bundle_assembly import BundleAssemblyPort
from app.modules.ports.planning_ports import PlanningPorts


def test_bundle_assembly_port_protocol_exists():
    assert callable(getattr(BundleAssemblyPort, "merge_geojson_into_bundle", None))


def test_planning_ports_has_bundle_assembly_field():
    ports = PlanningPorts()
    assert hasattr(ports, "bundle_assembly")
    assert ports.bundle_assembly is None


def test_data_adapter_implements_port():
    from app.modules.data.bundle_assembly_adapter import DataBundleAssemblyAdapter

    adapter = DataBundleAssemblyAdapter()
    assert isinstance(adapter, BundleAssemblyPort)
    assert callable(adapter.merge_geojson_into_bundle)


def test_data_adapter_merges_geojson_into_bundle():
    from app.modules.data.bundle_assembly_adapter import DataBundleAssemblyAdapter
    from app.modules.schema.types.canonical import VillageBundle

    bundle = VillageBundle(village_name="test")
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}, "properties": {"BSM": "P1", "DLBM": "1100"}},
        ],
    }
    adapter = DataBundleAssemblyAdapter()
    merged = adapter.merge_geojson_into_bundle(bundle, "landuse_current", geojson)
    assert merged == 1


def test_kg_service_has_no_data_import():
    """AST scan: kg/service.py must not contain `from app.modules.data`."""
    backend_root = pathlib.Path(__file__).resolve().parents[3]
    service_path = backend_root / "app" / "modules" / "kg" / "service.py"
    tree = ast.parse(service_path.read_text(encoding="utf-8-sig"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "app.modules.data" or node.module.startswith("app.modules.data."):
                offenders.append(node.module)
    assert not offenders, f"kg/service.py imports app.modules.data: {offenders}"
