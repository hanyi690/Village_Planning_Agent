"""Integration test: DEM raster layer loads into bundle and appears in KG.

Task 8 of V4 Audit Plan: integrate data/gis/广东DEM30M.zip as a usable DEM
raster layer. Verifies the end-to-end path:
    GeoTIFF file -> ingest_raster() -> DEMInput -> VillageBundle.rasters.dem
                                                -> PlanningKG (RasterDataset entity)
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent.parent
DEM_PATH = REPO_ROOT / "data" / "gis" / "jintian" / "terrain" / "dem.tif"


class TestDEMLayerIntegration:
    """Verify DEM raster integration end-to-end."""

    @pytest.fixture(scope="module")
    def dem_raster(self):
        """Load DEM via ingest_raster."""
        if not DEM_PATH.exists():
            pytest.skip(f"DEM file not found: {DEM_PATH}. "
                        f"Run: python backend/scripts/clip_dem_to_aoi.py")
        from app.modules.data.ingest import ingest_raster
        return ingest_raster(str(DEM_PATH), raster_type="dem")

    def test_dem_file_exists(self):
        """The clipped DEM GeoTIFF should exist at the sources.yaml path."""
        assert DEM_PATH.exists(), (
            f"DEM file missing: {DEM_PATH}. "
            f"Run: python backend/scripts/clip_dem_to_aoi.py --input "
            f"data/gis/广东DEM30M.zip --aoi "
            f"data/gis/jintian/current/boundary.geojson --output {DEM_PATH}"
        )

    def test_dem_raster_loads(self, dem_raster):
        """DEM raster should load successfully via ingest_raster()."""
        assert dem_raster is not None
        # DEMInput is a subclass of RasterDataset
        from app.modules.schema.types.base import RasterDataset
        assert isinstance(dem_raster, RasterDataset)
        assert dem_raster.layer_type == "dem"
        assert dem_raster.path  # path must be populated
        assert dem_raster.crs  # CRS must be populated
        # width/height require rasterio; without it the loader returns minimal metadata
        try:
            import rasterio  # noqa: F401
            assert dem_raster.width > 0, "width should be >0 when rasterio is installed"
            assert dem_raster.height > 0, "height should be >0 when rasterio is installed"
        except ImportError:
            pytest.skip("rasterio not installed - width/height not populated")

    def test_dem_raster_path_matches_sources_yaml(self, dem_raster):
        """The loaded DEM path should match the dem_local source in sources.yaml."""
        import yaml
        sources_yaml = (
            Path(__file__).parent.parent.parent
            / "app" / "modules" / "data" / "catalog" / "sources.yaml"
        )
        with open(sources_yaml, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        dem_source = cfg.get("sources", {}).get("dem_local")
        assert dem_source is not None, "dem_local source missing from sources.yaml"
        declared_path = dem_source.get("path", "")
        assert declared_path.endswith("jintian/terrain/dem.tif"), \
            f"Unexpected dem_local path: {declared_path}"
        # The dem_raster.path is absolute or relative; compare by suffix
        assert dem_raster.path.replace("\\", "/").endswith(
            "jintian/terrain/dem.tif"
        ), f"Loaded path {dem_raster.path} != sources.yaml {declared_path}"

    def test_dem_appears_in_kg(self, dem_raster):
        """DEM raster should become a RasterDataset entity in the KG."""
        from rdflib import RDF
        from app.modules.kg.ontology import EntityTypes
        from app.modules.kg.builder import KGBuilder, PlanningKG
        from app.modules.schema.types.canonical import VillageBundle, RasterLayerGroup

        # Build minimal bundle with DEM attached
        bundle = VillageBundle(village_name="金田村委会")
        # RasterLayerGroup.dem is a scalar field, not a list
        bundle.rasters = RasterLayerGroup(dem=dem_raster)

        kg = KGBuilder(village_name="金田村委会").build_from_bundle(bundle=bundle)
        raster_count = len(list(kg.g.subjects(RDF.type, EntityTypes.RasterDataset)))
        assert raster_count >= 1, (
            "DEM should appear as RasterDataset in KG. "
            f"Got {raster_count} RasterDataset entities."
        )

    def test_dem_kg_entity_has_geometry_kind(self, dem_raster):
        """The DEM KG entity should carry the raster geometry_kind predicate."""
        from rdflib import RDF
        from app.modules.kg.ontology import EntityTypes, SemanticPredicates
        from app.modules.kg.builder import KGBuilder, PlanningKG
        from app.modules.schema.types.canonical import VillageBundle, RasterLayerGroup

        bundle = VillageBundle(village_name="金田村委会")
        bundle.rasters = RasterLayerGroup(dem=dem_raster)

        kg = KGBuilder(village_name="金田村委会").build_from_bundle(bundle=bundle)

        dem_uris = list(kg.g.subjects(RDF.type, EntityTypes.RasterDataset))
        assert dem_uris, "No RasterDataset entity in KG"
        # Check the geometry_kind predicate is set to "raster"
        from rdflib import Literal
        has_raster_kind = any(
            (uri, SemanticPredicates.geometry_kind, Literal("raster")) in kg.g
            for uri in dem_uris
        )
        assert has_raster_kind, "DEM entity missing geometry_kind='raster' predicate"
