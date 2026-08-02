"""Full-suite regression runner vs failed_baseline.json.

Usage (from backend/):
    python scripts/run_regression.py            # run full suite, diff vs baseline
    python scripts/run_regression.py --list     # print baseline contents

Exit codes:
    0  no new failures/errors vs baseline
    1  new failures/errors introduced
    2  baseline file missing (run --update after first full run)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASELINE = Path(__file__).resolve().parent / "failed_baseline.json"


def collect_junit(xml_path: Path) -> tuple:
    root = ET.parse(xml_path).getroot()
    failed, errored = set(), set()
    for tc in root.iter("testcase"):
        nodeid = f"{tc.get('classname')}::{tc.get('name')}"
        for child in tc:
            if child.tag == "failure":
                failed.add(nodeid)
            elif child.tag == "error":
                errored.add(nodeid)
    return failed, errored


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="print baseline contents")
    ap.add_argument("--update", action="store_true", help="update baseline from current run")
    ap.add_argument("--pytest-args", default="", help="extra args to pytest (default: -q --tb=no)")
    args = ap.parse_args()

    if args.list:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        print(f"baseline: {BASELINE}")
        print(f"failures={len(data['failed'])} errors={len(data['errors'])}")
        for n in data["failed"]:
            print("  F:", n)
        for n in data["errors"]:
            print("  E:", n)
        return 0

    if not BASELINE.exists():
        print("baseline missing; run --update after a full run", file=sys.stderr)
        return 2

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        xml_path = Path(tmp.name)

    pytest_args = (args.pytest_args or "-q --tb=no").split()
    cmd = [sys.executable, "-m", "pytest", *pytest_args,
           "--junitxml", str(xml_path)]
    print("running:", " ".join(cmd))
    proc = subprocess.run(cmd)
    xml_path = Path(xml_path)

    failed, errored = collect_junit(xml_path)
    xml_path.unlink(missing_ok=True)

    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    base_failed, base_errors = set(base["failed"]), set(base["errors"])

    new_failed = failed - base_failed
    new_errors = errored - base_errors
    fixed = (base_failed - failed) | (base_errors - errored)

    print(f"\nrun summary: failures={len(failed)} errors={len(errored)} "
          f"(baseline failures={len(base_failed)} errors={len(base_errors)})")
    if new_failed:
        print(f"\nNEW FAILURES ({len(new_failed)}):")
        for n in sorted(new_failed):
            print("  F:", n)
    if new_errors:
        print(f"\nNEW ERRORS ({len(new_errors)}):")
        for n in sorted(new_errors):
            print("  E:", n)
    if fixed:
        print(f"\nFIXED vs baseline ({len(fixed)}):")
        for n in sorted(fixed):
            print("  -", n)

    if args.update:
        out = {"run_at": "now", "summary": {"failures": len(failed), "errors": len(errored)},
               "failed": sorted(failed), "errors": sorted(errored)}
        BASELINE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nbaseline updated: {BASELINE}")

    return 1 if (new_failed or new_errors) else 0


if __name__ == "__main__":
    sys.exit(main())
