"""Run the static DATA production gate.

The dynamic Jintian chain is executed by pytest; this command is the
deployment preflight for repository permissions, stale legacy files, and
credential material.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.data.production_acceptance import scan_data_repository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None, help="repository root")
    args = parser.parse_args()
    root = Path(args.root).resolve() if args.root else PROJECT_ROOT
    result = scan_data_repository(root)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
