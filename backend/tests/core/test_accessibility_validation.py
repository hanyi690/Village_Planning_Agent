from types import SimpleNamespace

from app.domain.validation.validate_checks import check_accessibility


def test_distributed_facilities_are_not_compared_with_village_centroid():
    planned_state = SimpleNamespace(
        parcels=[
            SimpleNamespace(
                geometry_wkt=(
                    "POLYGON ((113 23, 113.01 23, 113.01 23.01, "
                    "113 23.01, 113 23))"
                )
            )
        ],
        facilities=[
            SimpleNamespace(
                name="north-settlement-clinic",
                lon=113.08,
                lat=23.08,
                service_radius=300,
            )
        ],
    )

    result = check_accessibility(planned_state)

    assert result[0].passed is True
    assert "typed coverage relations" in result[0].expected_value


def test_zero_coordinate_facility_still_fails_coordinate_check():
    result = check_accessibility(
        SimpleNamespace(
            facilities=[SimpleNamespace(name="missing-location", lon=0, lat=0)]
        )
    )

    assert result[0].passed is False
    assert result[0].affected_target_ids == ["missing-location"]
