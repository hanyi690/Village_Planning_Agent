from app.spatial.allocation.selection import CandidateParcel, apply_hard_filters


class _ConstraintIndex:
    def __init__(self):
        self.calls = 0

    def geometry_in_constraint(self, geometry):
        self.calls += 1
        return []


def test_hard_filter_cache_reuses_geometry_and_constraint_work():
    candidates = [
        CandidateParcel(
            bsm="A",
            geometry={
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
            },
        ),
        CandidateParcel(
            bsm="B",
            geometry={
                "type": "Polygon",
                "coordinates": [[[2, 0], [3, 0], [3, 1], [2, 0]]],
            },
        ),
    ]
    constraint_index = _ConstraintIndex()
    cache = {}

    first, first_rejected = apply_hard_filters(
        candidates,
        constraint_index=constraint_index,
        filter_cache=cache,
    )
    second, second_rejected = apply_hard_filters(
        candidates,
        constraint_index=constraint_index,
        occupied=[(0.25, 0.25)],
        filter_cache=cache,
    )

    assert [candidate.bsm for candidate in first] == ["A", "B"]
    assert not first_rejected
    assert [candidate.bsm for candidate in second] == ["B"]
    assert second_rejected[0].bsm == "A"
    assert constraint_index.calls == 2
