from types import SimpleNamespace

from app.agent.deliver.aggregate import _build_planned_view
from app.modules.spatial_ops.land_balance import check_delivery_gate


def test_planned_view_preserves_serialized_current_parcels_and_closes_balance():
    current = [
        {
            "bsm": "parcel-1",
            "dlbm": "0101",
            "area_sqm": 10000,
        },
        {
            "bsm": "parcel-2",
            "dlbm": "0201",
            "area_sqm": 20000,
        },
    ]
    planned_state = SimpleNamespace(parcels=[])

    planned = _build_planned_view(current, planned_state)
    gate = check_delivery_gate(current, planned)

    assert len(planned) == 2
    assert {row["bsm"] for row in planned} == {"parcel-1", "parcel-2"}
    assert gate.land_balance_closed is True


def test_planned_view_does_not_count_unbound_planned_parcel():
    current = [{"bsm": "parcel-1", "dlbm": "0101", "area_sqm": 10000}]
    planned_state = SimpleNamespace(
        parcels=[
            {
                "bsm": "synthetic-new",
                "planning_land_use": "0201",
                "area_ha": 50,
                "derived_from_bsms": [],
            }
        ]
    )

    planned = _build_planned_view(current, planned_state)

    assert [row["bsm"] for row in planned] == ["parcel-1"]
