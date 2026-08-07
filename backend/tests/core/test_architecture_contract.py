from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_state_and_graph_contract():
    state = (ROOT / "app/agent/plan_state/state.py").read_text(encoding="utf-8")
    graph = (ROOT / "app/agent/bootstrap/graph.py").read_text(encoding="utf-8")
    assert "context_ref" in state and "artifact_refs" in state
    for node in ("parse", "ground", "select", "execute", "validate", "reconcile", "deliver"):
        assert f'add_node("{node}"' in graph
    assert "human_review_prepare" in graph and "human_review_wait" in graph


def test_deleted_wrapper_is_not_referenced_by_active_code():
    forbidden = ("gis_agent_entry", "PostL3ChainState")
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), path


def test_real_session_contract_is_isolated_and_in_ci():
    """P1 guard: the real chain may not reuse a repository .run-tmp/s1."""
    integration = ROOT / "tests/integration/test_real_llm_session_full.py"
    core = ROOT / "tests/core/test_real_session_backend.py"
    workflow = ROOT.parent / ".github/workflows/gis-engine-ci.yml"
    for path in (integration, core):
        text = path.read_text(encoding="utf-8")
        assert ".run-tmp/s1" not in text
        assert "tmp_path" in text and "monkeypatch.chdir(tmp_path)" in text
    ci = workflow.read_text(encoding="utf-8")
    assert "tests/integration/test_real_llm_session_full.py" in ci


def test_graph_has_bootstrap_context_node():
    graph = (ROOT / "app/agent/bootstrap/graph.py").read_text(encoding="utf-8")
    assert 'add_node("bootstrap_context"' in graph
    assert "bootstrap_context_node" in graph


def test_post_l3_nodes_do_not_call_resolve_context():
    nodes = (ROOT / "app/agent/bootstrap/post_l3_main_nodes.py").read_text(encoding="utf-8")
    assert "_resolve_context" not in nodes
    assert "_context_patch" not in nodes
