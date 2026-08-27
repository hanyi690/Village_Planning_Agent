from app.data.catalog import DataCatalog


def test_default_vector_layers_exclude_planning_outputs() -> None:
    layer_types = set(DataCatalog()._default_vector_layer_types())

    assert "landuse_current" in layer_types
    assert "current_road" in layer_types
    assert "landuse_planned" not in layer_types
    assert "planned_road" not in layer_types
    assert "planned_annotation" not in layer_types
