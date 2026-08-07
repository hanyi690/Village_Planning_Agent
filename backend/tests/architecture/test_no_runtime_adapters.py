"""Guardrail: runtime-path modules must not reference legacy adapter bridges.

P2-6 (ADR-001..005) established canonical typed models and removed the
adapter bridges from the runtime path. This test asserts the forbidden legacy
symbols do not appear in the source of the runtime modules that previously
used them.

The checkpoint-import boundary (``app.agent.bootstrap.artifact_runtime``) is
intentionally excluded: ``migrate_legacy_artifacts`` legitimately lives there
per ADR-005.

No production source is modified by this test.
"""


def test_no_runtime_adapters():
    import importlib
    import inspect

    FORBIDDEN = [
        "_build_legacy_intent",
        "get_impact_tree_compat",
        "migrate_legacy_artifacts",
    ]
    RUNTIME_MODULES = [
        "app.agent.bootstrap.post_l3_main_nodes",
        "app.agent.execute.execute_agent",
        "app.agent.validate.checks",
        "app.agent.parse.compile_node",
        "app.agent.conversation_router.edges",
        "app.agent.bootstrap.context_bootstrap",
    ]
    violations = []
    for mod_name in RUNTIME_MODULES:
        mod = importlib.import_module(mod_name)
        source = inspect.getsource(mod)
        for pattern in FORBIDDEN:
            if pattern in source:
                violations.append(f"{mod_name}: {pattern}")
    assert not violations