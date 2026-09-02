from app.contracts.data import DataChangeSet
from app.modules.data import invalidation

from tests.test_data_dependency_invalidation import _catalog


def test_data_change_set_contains_only_data_owned_nodes():
    old = invalidation.build_data_dependency_graph(_catalog())
    new = invalidation.build_data_dependency_graph(_catalog("feature-change"))

    change_set = invalidation.plan_data_change_set(old, new)

    assert isinstance(change_set, DataChangeSet)
    assert all(node.startswith("data:") for node in change_set.changed_nodes)
    assert all(node.startswith("data:") for node in change_set.affected_data_nodes)
    assert all(
        node.node_kind in {"catalog", "source", "normalized", "representation", "capability"}
        for node in new.nodes
    )


def test_data_module_has_no_downstream_invalidation_writer():
    assert not hasattr(invalidation, "apply_data_dependency_invalidation")
    assert not hasattr(invalidation, "plan_data_dependency_invalidation")
