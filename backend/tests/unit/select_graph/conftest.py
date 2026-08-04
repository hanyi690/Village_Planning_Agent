"""Shared fixtures for the SELECT subgraph unit tests."""

import pytest
from types import SimpleNamespace

POLY = {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]}


class _Polygons:
    def __init__(self, parcels):
        self._parcels = parcels

    def get(self, key, default=None):
        return self._parcels if key == "landuse_current" else default


class _Bundle:
    def __init__(self, parcels):
        self.polygons = _Polygons(parcels)


def make_parcel(bsm, dlbm="0101", area_sqm=12000.0):
    return SimpleNamespace(bsm=bsm, geometry=POLY, dlbm=dlbm, area_sqm=area_sqm)


@pytest.fixture
def make_bundle():
    def _make_bundle(parcels=None):
        parcels = parcels if parcels is not None else [make_parcel("P001"), make_parcel("P002")]
        return _Bundle(parcels)

    return _make_bundle
