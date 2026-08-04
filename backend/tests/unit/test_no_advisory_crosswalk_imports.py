import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_DIRS = [
    "app/agent/l1_observe", "app/agent/l2_strategize", "app/agent/l3_plan",
    "app/agent/ground", "app/agent/select", "app/agent/execute", "app/agent/validate",
]
PATTERN = re.compile(r"^\s*from app\.modules\.schema\.advisory_crosswalks")

KNOWN_VIOLATIONS = [
    "app/tools/gis/_generation/optimizer/mip_allocator.py",
    "app/tools/gis/_generation/optimizer/mip_solver.py",
    "app/tools/gis/_generation/optimizer/planning_zone_mapper.py",
    "app/tools/gis/generate.py",
    "app/tools/gis/_generation/zone_generator.py",
    "app/tools/gis/_generation/land_use_zone_generator.py",
    "app/tools/gis/_generation/space_control_generator.py",
    "app/tools/gis/_generation/zone_type_deriver.py",
]

def test_no_advisory_crosswalk_in_forbidden_stages():
    offenders = []
    for dir_rel in FORBIDDEN_DIRS:
        target = BACKEND_ROOT / dir_rel
        if not target.exists():
            continue
        for py_file in target.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            content = py_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), 1):
                if PATTERN.match(line):
                    offenders.append(f"{py_file.relative_to(BACKEND_ROOT)}:{i}")
    assert not offenders, "forbidden stages import advisory_crosswalks:\n" + "\n".join(offenders)

def test_known_violations_still_exist():
    for v in KNOWN_VIOLATIONS:
        assert (BACKEND_ROOT / v).exists(), f"Known violation file disappeared: {v}"
