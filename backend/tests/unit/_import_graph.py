"""Static import-graph scanner shared by architecture-budget tests.

Builds an AST-based import graph over ``backend/app`` (absolute + relative
imports, including function-level lazy imports) and answers two questions:

- ``reachable_modules(roots)``: the set of app modules reachable from a set
  of entry modules via ``import`` edges.
- ``count_crosswalk_imports(roots)``: number of files reachable from ``roots``
  that import ``app.modules.schema.advisory_crosswalks`` (and total count).

Design notes
------------
- Relative imports (``from .foo import x``, ``from ..bar import y``) are
  resolved against the importing file's *package* (directory), not its
  module name. A file ``a/b/c.py`` lives in package ``a.b``; a file
  ``a/b/__init__.py`` lives in package ``a.b``.
- ``roots`` are relative paths under ``backend/`` (e.g. ``app/agent/...``).
- The graph only contains modules under ``backend/app``; third-party/stdlib
  imports are ignored.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"

CROSSWALK_MODULE = "app.modules.schema.advisory_crosswalks"


def _norm(path: Path) -> str:
    return str(path.relative_to(BACKEND_ROOT)).replace("\\", "/")


def _package_of(file_path: Path) -> str:
    """Package (dotted) that the file lives in, excluding the file itself."""
    r = file_path.relative_to(BACKEND_ROOT)
    parts = r.parts
    if parts[-1] == "__init__.py":
        pkg = parts[:-1]
    else:
        pkg = parts[:-1]
    return ".".join(pkg)


def _module_to_path(mod: str) -> str | None:
    """Map a dotted app module to its file path (relative to backend)."""
    p = BACKEND_ROOT
    for part in mod.split("."):
        p = p / part
    if p.with_suffix(".py").exists():
        return _norm(p.with_suffix(".py"))
    if (p / "__init__.py").exists():
        return _norm(p / "__init__.py")
    return None


def _collect_imports() -> Dict[str, Set[str]]:
    """Return {file_path: set(imported app module file paths)} for all app files."""
    imports: Dict[str, Set[str]] = {}
    for f in APP_ROOT.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        pkg = _package_of(f)
        mods: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.level == 0:
                    if node.module.startswith("app"):
                        p = _module_to_path(node.module)
                        if p:
                            mods.add(p)
                else:
                    # relative import; base = package minus (level-1) segments
                    base = pkg.split(".") if pkg else []
                    if node.level > 1:
                        base = base[: -(node.level - 1)]
                    rel_mod = node.module or ""
                    target = ".".join(base + ([rel_mod] if rel_mod else []))
                    p = _module_to_path(target)
                    if p:
                        mods.add(p)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("app"):
                        p = _module_to_path(a.name)
                        if p:
                            mods.add(p)
        imports[_norm(f)] = mods
    return imports


def reachable_modules(roots: List[str], imports: Dict[str, Set[str]]) -> Set[str]:
    """BFS from root module paths over the import graph."""
    seen: Set[str] = set(roots)
    queue = list(roots)
    while queue:
        cur = queue.pop()
        for m in imports.get(cur, set()):
            if m not in seen:
                seen.add(m)
                queue.append(m)
    return seen


def count_crosswalk_imports(
    roots: List[str], imports: Dict[str, Set[str]]
) -> Tuple[Dict[str, int], int]:
    """Return ({file: direct_crosswalk_import_count}, total_count) among reachable."""
    seen = reachable_modules(roots, imports)
    crosswalk_path = _module_to_path(CROSSWALK_MODULE)
    per_file: Dict[str, int] = {}
    for f, mods in imports.items():
        if f not in seen:
            continue
        n = sum(1 for m in mods if crosswalk_path is not None and m == crosswalk_path)
        if n:
            per_file[f] = n
    return per_file, sum(per_file.values())


def build_imports() -> Dict[str, Set[str]]:
    return _collect_imports()
