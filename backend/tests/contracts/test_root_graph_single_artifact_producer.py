import pathlib
import re


def test_root_graph_does_not_directly_write_domain_artifacts():
    src = pathlib.Path("app/workflow/root_graph.py").read_text(encoding="utf-8")
    forbidden = re.compile(
        r"store_artifact\(\s*state\s*,\s*\"(?:planning_program|deferral_ledger|site_selection|execution_plan|delivery_manifest)\""
    )
    assert not forbidden.search(src), "root_graph still directly writes domain artifacts via store_artifact"
