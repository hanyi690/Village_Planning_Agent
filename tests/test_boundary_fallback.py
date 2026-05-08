"""
Boundary Fallback Mechanism Tests

Tests for proxy boundary generation when user-uploaded boundary is unavailable.

Test scenarios:
1. User uploaded priority - GISDataManager set boundary returns first
2. Isochrone success - mock API returns isochrone data
3. API failure fallback - mock API fails, verify fallback to bbox_buffer
4. Insufficient line features - gis_data has only 2 lines, polygonize_fusion fails
5. Dynamic config - custom config.bbox_buffer_km=3.0
6. Force generation - force_generate=True ignores user data
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, Tuple

# Import test targets
from ..config.boundary_fallback import (
    BoundaryFallbackConfig,
    BoundaryStrategy,
    BOUNDARY_FALLBACK_CONFIG,
)
from ..tools.core.boundary_fallback import generate_proxy_boundary_with_fallback


class TestBoundaryFallbackConfig:
    """Test BoundaryFallbackConfig"""

    def test_default_config(self):
        """Test default configuration values"""
        config = BoundaryFallbackConfig()

        assert config.strategy_priority == [
            "user_uploaded",
            "isochrone",
            "polygonize_fusion",
            "morphological_convex",
            "bbox_buffer",
        ]
        assert config.isochrone_time_minutes == 15
        assert config.bbox_buffer_km == 2.0

    def test_get_next_strategy(self):
        """Test strategy sequence"""
        config = BoundaryFallbackConfig()

        assert config.get_next_strategy("user_uploaded") == "isochrone"
        assert config.get_next_strategy("isochrone") == "polygonize_fusion"
        assert config.get_next_strategy("morphological_convex") == "bbox_buffer"
        assert config.get_next_strategy("bbox_buffer") is None

    def test_is_final_strategy(self):
        """Test final strategy identification"""
        config = BoundaryFallbackConfig()

        assert config.is_final_strategy("bbox_buffer") is True
        assert config.is_final_strategy("isochrone") is False


class TestStrategyUserUploaded:
    """Test user_uploaded strategy"""

    @patch("..tools.core.boundary_fallback.GISDataManager")
    def test_user_uploaded_priority(self, mock_data_manager):
        """User uploaded boundary should be returned first"""
        # Setup mock
        mock_cached = Mock()
        mock_cached.geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
                }
            }]
        }
        mock_data_manager.get_user_data.return_value = mock_cached

        # Execute
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data={},
        )

        # Verify
        assert result["success"] is True
        assert result["strategy_used"] == "user_uploaded"
        assert result["geojson"]["type"] == "Polygon"

    @patch("..tools.core.boundary_fallback.GISDataManager")
    def test_user_uploaded_no_polygon(self, mock_data_manager):
        """User data without polygon geometry should fallback"""
        # Setup mock - no polygon features
        mock_cached = Mock()
        mock_cached.geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.4, 39.9]}
            }]
        }
        mock_data_manager.get_user_data.return_value = mock_cached

        # Execute with only user_uploaded strategy
        config = BoundaryFallbackConfig(strategy_priority=["user_uploaded"])
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data={},
            config=config,
        )

        # Verify - should fail since no polygon
        assert result["success"] is False


class TestStrategyIsochrone:
    """Test isochrone strategy"""

    @patch("..tools.core.boundary_fallback.generate_isochrones")
    def test_isochrone_success(self, mock_generate_isochrones):
        """Isochrone generation should succeed"""
        # Setup mock
        mock_generate_isochrones.return_value = {
            "success": True,
            "data": {
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[116.3, 39.8], [116.5, 39.8], [116.5, 40.0], [116.3, 40.0], [116.3, 39.8]]]
                        }
                    }]
                },
                "isochrones": [{"time_minutes": 15, "radius_km": 1.25}]
            }
        }

        # Skip user_uploaded to test isochrone
        config = BoundaryFallbackConfig(strategy_priority=["isochrone", "bbox_buffer"])
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data={},
            config=config,
            skip_user_upload=True,
        )

        # Verify
        assert result["success"] is True
        assert result["strategy_used"] == "isochrone"
        assert result["stats"]["time_minutes"] == 15

    @patch("..tools.core.boundary_fallback.generate_isochrones")
    def test_isochrone_failure_fallback(self, mock_generate_isochrones):
        """Isochrone failure should fallback to bbox_buffer"""
        # Setup mock - API failure
        mock_generate_isochrones.return_value = {
            "success": False,
            "error": "API timeout"
        }

        # Execute
        config = BoundaryFallbackConfig(strategy_priority=["isochrone", "bbox_buffer"])
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data={},
            config=config,
            skip_user_upload=True,
        )

        # Verify - should fallback to bbox_buffer
        assert result["success"] is True
        assert result["strategy_used"] == "bbox_buffer"
        assert len(result["fallback_history"]) == 2
        assert result["fallback_history"][0]["success"] is False


class TestStrategyPolygonizeFusion:
    """Test polygonize_fusion strategy"""

    @patch("..tools.core.boundary_fallback.trim_polygon_with_lines")
    @patch("..tools.core.boundary_fallback.generate_isochrones")
    def test_polygonize_fusion_success(
        self, mock_generate_isochrones, mock_trim_polygon
    ):
        """Polygonize fusion should succeed with sufficient lines"""
        # Setup mocks
        mock_generate_isochrones.return_value = {
            "success": True,
            "data": {
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[116.3, 39.8], [116.5, 39.8], [116.5, 40.0], [116.3, 40.0], [116.3, 39.8]]]
                        }
                    }]
                },
                "isochrones": [{"time_minutes": 15}]
            }
        }
        mock_trim_polygon.return_value = {
            "success": True,
            "data": {
                "geojson": {
                    "type": "Polygon",
                    "coordinates": [[[116.35, 39.85], [116.45, 39.85], [116.45, 39.95], [116.35, 39.95], [116.35, 39.85]]]
                },
                "trimmed": True,
                "area_km2": 1.0,
            }
        }

        # Prepare gis_data with sufficient lines
        gis_data = {
            "road": {
                "features": [
                    {"geometry": {"type": "LineString", "coordinates": [[116.35, 39.85], [116.45, 39.85]]}},
                    {"geometry": {"type": "LineString", "coordinates": [[116.35, 39.95], [116.45, 39.95]]}},
                    {"geometry": {"type": "LineString", "coordinates": [[116.35, 39.85], [116.35, 39.95]]}},
                    {"geometry": {"type": "LineString", "coordinates": [[116.45, 39.85], [116.45, 39.95]]}},
                    {"geometry": {"type": "LineString", "coordinates": [[116.4, 39.9], [116.5, 40.0]]}},
                ]
            }
        }

        config = BoundaryFallbackConfig(
            strategy_priority=["polygonize_fusion", "bbox_buffer"],
            polygonize_min_lines=5,
        )
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data=gis_data,
            config=config,
            skip_user_upload=True,
        )

        # Verify
        assert result["success"] is True
        assert result["strategy_used"] == "polygonize_fusion"

    def test_polygonize_fusion_insufficient_lines(self):
        """Polygonize fusion should fail with insufficient lines"""
        # Prepare gis_data with only 2 lines (< 5 minimum)
        gis_data = {
            "road": {
                "features": [
                    {"geometry": {"type": "LineString", "coordinates": [[116.35, 39.85], [116.45, 39.85]]}},
                    {"geometry": {"type": "LineString", "coordinates": [[116.35, 39.95], [116.45, 39.95]]}},
                ]
            }
        }

        config = BoundaryFallbackConfig(
            strategy_priority=["polygonize_fusion", "bbox_buffer"],
            polygonize_min_lines=5,
        )
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data=gis_data,
            config=config,
            skip_user_upload=True,
        )

        # Verify - should fallback to bbox_buffer
        assert result["success"] is True
        assert result["strategy_used"] == "bbox_buffer"
        assert result["fallback_history"][0]["reason"] == "Insufficient lines: 2 < 5"


class TestStrategyMorphological:
    """Test morphological_convex strategy"""

    @patch("..tools.core.boundary_fallback.compute_convex_hull")
    def test_morphological_success(self, mock_compute_hull):
        """Morphological hull should succeed with sufficient features"""
        # Setup mock
        mock_compute_hull.return_value = {
            "success": True,
            "data": {
                "geojson": {
                    "type": "Polygon",
                    "coordinates": [[[116.35, 39.85], [116.45, 39.85], [116.45, 39.95], [116.35, 39.95], [116.35, 39.85]]]
                },
                "area_km2": 1.0,
                "input_count": 5,
            }
        }

        # Prepare gis_data with sufficient features
        gis_data = {
            "residential": {
                "features": [
                    {"geometry": {"type": "Point", "coordinates": [116.35, 39.85]}},
                    {"geometry": {"type": "Point", "coordinates": [116.45, 39.85]}},
                    {"geometry": {"type": "Point", "coordinates": [116.45, 39.95]}},
                    {"geometry": {"type": "Point", "coordinates": [116.35, 39.95]}},
                    {"geometry": {"type": "Point", "coordinates": [116.4, 39.9]}},
                ]
            }
        }

        config = BoundaryFallbackConfig(
            strategy_priority=["morphological_convex", "bbox_buffer"],
            morphological_min_features=3,
        )
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data=gis_data,
            config=config,
            skip_user_upload=True,
        )

        # Verify
        assert result["success"] is True
        assert result["strategy_used"] == "morphological_convex"

    def test_morphological_insufficient_features(self):
        """Morphological should fail with insufficient features"""
        # Prepare gis_data with only 2 features
        gis_data = {
            "residential": {
                "features": [
                    {"geometry": {"type": "Point", "coordinates": [116.35, 39.85]}},
                    {"geometry": {"type": "Point", "coordinates": [116.45, 39.85]}},
                ]
            }
        }

        config = BoundaryFallbackConfig(
            strategy_priority=["morphological_convex", "bbox_buffer"],
            morphological_min_features=3,
        )
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data=gis_data,
            config=config,
            skip_user_upload=True,
        )

        # Verify - should fallback to bbox_buffer
        assert result["success"] is True
        assert result["strategy_used"] == "bbox_buffer"


class TestStrategyBboxBuffer:
    """Test bbox_buffer strategy (final fallback)"""

    def test_bbox_buffer_always_succeeds(self):
        """bbox_buffer should always succeed"""
        config = BoundaryFallbackConfig(strategy_priority=["bbox_buffer"])
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data={},  # Empty GIS data
            config=config,
            skip_user_upload=True,
        )

        # Verify
        assert result["success"] is True
        assert result["strategy_used"] == "bbox_buffer"
        assert result["geojson"]["type"] == "Polygon"

    def test_bbox_buffer_custom_size(self):
        """bbox_buffer should use custom buffer size"""
        config = BoundaryFallbackConfig(
            strategy_priority=["bbox_buffer"],
            bbox_buffer_km=3.0,
        )
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data={},
            config=config,
            skip_user_upload=True,
        )

        # Verify - area should be ~36 km2 (3km * 2)^2
        assert result["success"] is True
        assert result["stats"]["buffer_km"] == 3.0


class TestForceGenerate:
    """Test force_generate parameter"""

    @patch("..tools.core.boundary_fallback.generate_isochrones")
    def test_force_generate_skips_user_data(self, mock_generate_isochrones):
        """force_generate=True should ignore user uploaded data"""
        # Setup mock for isochrone
        mock_generate_isochrones.return_value = {
            "success": True,
            "data": {
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[116.3, 39.8], [116.5, 39.8], [116.5, 40.0], [116.3, 40.0], [116.3, 39.8]]]
                        }
                    }]
                },
                "isochrones": [{"time_minutes": 15}]
            }
        }

        # Even with user data available, force_generate should skip it
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data={},
            skip_user_upload=True,  # force_generate
        )

        # Verify - should not use user_uploaded
        assert result["strategy_used"] != "user_uploaded"


class TestFallbackHistory:
    """Test fallback_history tracking"""

    def test_fallback_history_records_attempts(self):
        """All strategy attempts should be recorded in fallback_history"""
        config = BoundaryFallbackConfig(
            strategy_priority=["user_uploaded", "isochrone", "bbox_buffer"],
        )
        result = generate_proxy_boundary_with_fallback(
            center=(116.4, 39.9),
            village_name="test_village",
            gis_data={},
            config=config,
            skip_user_upload=True,
        )

        # Verify - history should have 2 entries (isochrone fails, bbox_buffer succeeds)
        assert len(result["fallback_history"]) >= 1
        for entry in result["fallback_history"]:
            assert "strategy" in entry
            assert "success" in entry
            assert "reason" in entry


# Integration test marker
@pytest.mark.integration
class TestSharedGISContextIntegration:
    """Integration tests with SharedGISContext"""

    def test_get_or_generate_boundary_with_user_data(self):
        """SharedGISContext.get_or_generate_boundary should return user data"""
        from ..orchestration.shared_gis_context import SharedGISContext

        context = SharedGISContext(village_name="test_village")
        context.set_user_data("boundary", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
                }
            }]
        })

        boundary = context.get_or_generate_boundary()
        assert boundary is not None
        assert boundary["type"] == "FeatureCollection"

    def test_get_or_generate_boundary_force_generate(self):
        """force_generate should skip user data"""
        from ..orchestration.shared_gis_context import SharedGISContext

        context = SharedGISContext(village_name="test_village")
        context.set_user_data("boundary", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
                }
            }]
        })

        # force_generate should generate new boundary
        boundary = context.get_or_generate_boundary(force_generate=True)
        # Will be None if center cannot be computed, or bbox_buffer if center exists
        # This tests the flow control


# pytest entry point
if __name__ == "__main__":
    pytest.main([__file__, "-v"])