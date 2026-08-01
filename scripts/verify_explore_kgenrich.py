"""EXPLORE KG-enrichment end-to-end verification.

Reads persisted memory states (data/kg_memory) for a session, checks the
binding loop produced real village bindings, and writes a report JSON.

Usage:
    python scripts/verify_explore_kgenrich.py [--session-id SID]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.resolve()
backend_root = project_root / "backend"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

# 村内 12 自然村 + 公王河（不含 八社村/上举村/符坑村/文贵村 —— 村外毗邻行政村，不得作为本村绑定匹配项）
_REAL_NAMES = ("田坑", "黄竹", "园寨", "塘笃", "社前", "分水", "清明",
               "长塘", "炉池", "肩丰", "营仔", "新山", "公王河")
_MIN_BINDINGS = 5


def _latest_session() -> str:
    from app.modules.kg.memory import get_memory_dir

    files = sorted(get_memory_dir().glob("*_round_3.json"))
    if not files:
        raise SystemExit("No round-3 memory state found. Run scripts/run_pipeline_real_jintian.py first.")
    return files[-1].name.removesuffix("_round_3.json")


def report(session_id: str) -> Dict[str, Any]:
    from app.modules.kg.memory import diff_round, load_memory_state

    rounds: List[Dict[str, Any]] = []
    previous = None
    for r in [1, 2, 3]:
        store = load_memory_state(session_id, r)
        diff = diff_round(previous, store)
        previous = store
        anns = list(store.entity_annotations.values())
        rounds.append(
            {
                "round": r,
                "annotation_count": len(anns),
                "diff": diff,
                "descriptions": sorted({a.description for a in anns if a.description})[:40],
            }
        )

    final = load_memory_state(session_id, 3)
    bound_descriptions = {a.description for a in final.entity_annotations.values() if a.description}
    matched = [n for n in _REAL_NAMES if any(n in d for d in bound_descriptions)]
    total = len(final.entity_annotations)

    return {
        "session_id": session_id,
        "generated_at": datetime.now().isoformat(),
        "total_bindings": total,
        "real_entities_matched": matched,
        "threshold": _MIN_BINDINGS,
        "passed": total >= _MIN_BINDINGS,
        "rounds": rounds,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="")
    args = parser.parse_args()

    session_id = args.session_id or _latest_session()
    result = report(session_id)

    out_dir = project_root / "docs" / "explore"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"jintian-kgenrich-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nsession={session_id} total_bindings={result['total_bindings']} matched={result['real_entities_matched']} passed={result['passed']}")
    print(f"report -> {out_path}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
