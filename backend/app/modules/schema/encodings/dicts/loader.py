"""Code Dictionary Center — metadata-driven encoding lookup system.

Directory layout:
  encodings/   — 编码体系：标准原文照录
  rules/       — 工程规则：派生配置
  mappings/    — 跨体系映射表 (统一 1:N schema)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from app.utils.logger import get_logger

logger = get_logger(__name__)

_DICTS_DIR = Path(__file__).parent

_ENCODINGS_DIR = "encodings"
_RULES_DIR = "rules"
_REFERENCES_DIR = "references"
_MAPPINGS_DIR = "mappings"

# Advisory cross-system mappings live outside encodings/dicts (encodings/../.. level).
# loader.py is at encodings/dicts/ so advisory_crosswalks is at dicts.parent.parent.
_ADVISORY_DIR = _DICTS_DIR.parent.parent / "advisory_crosswalks" / "yaml"


# ============================================================
# Data classes
# ============================================================

@dataclass
class CodeDictionary:
    """Loaded code dictionary with version, standard, and lookup tables."""

    name: str
    version: str
    standard: str
    category: str
    raw: Dict[str, Any]
    _lookup: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        for entry in self.raw.get("classes", []):
            code = str(entry.get("code", ""))
            if code:
                self._lookup[code] = entry

    def lookup(self, code: str) -> Optional[Dict[str, Any]]:
        return self._lookup.get(str(code).strip())

    def to_dict(self, key_field: str = "code", value_field: str = "name") -> Dict[str, str]:
        return {
            str(e.get(key_field, "")): str(e.get(value_field, ""))
            for e in self.raw.get("classes", [])
            if e.get(key_field) is not None
        }

    def to_set(self, field: str = "code", filter_tag: Optional[str] = None) -> Set[str]:
        result: Set[str] = set()
        for entry in self.raw.get("classes", []):
            if filter_tag:
                tags = entry.get("categories", [])
                if filter_tag not in tags:
                    continue
            val = entry.get(field)
            if val is not None:
                result.add(str(val))
        return result

    def to_prompt_table(self) -> str:
        classes = self.raw.get("classes", [])
        if not classes:
            return ""
        sample = classes[0]
        columns = [k for k in sample.keys() if k in (
            "code", "name", "zone_type", "planning_zone", "primary_zone", "gb_ref"
        )]
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join(["------"] * len(columns)) + " |"
        rows = []
        seen = set()
        for entry in sorted(classes, key=lambda e: str(e.get("code", ""))):
            key = (str(entry.get("code", "")), str(entry.get("name", "")))
            if key in seen:
                continue
            seen.add(key)
            rows.append("| " + " | ".join(str(entry.get(c, "")) for c in columns) + " |")
        return header + "\n" + sep + "\n" + "\n".join(rows)

    def to_land_use_classes(self) -> list:
        from ..classification import LandUseClass
        result = []
        for entry in self.raw.get("classes", []):
            result.append(LandUseClass(
                system=self.name,
                code=str(entry.get("code", "")),
                name=str(entry.get("name", "")),
                zone_type=str(entry.get("zone_type", "")),
                planning_zone=str(entry.get("planning_zone", "")),
                primary_zone=str(entry.get("primary_zone", "")),
                category_sets=tuple(entry.get("categories", [])),
                gb_ref=str(entry.get("gb_ref", "")),
                description=str(entry.get("description", "")),
            ))
        return result


@dataclass
class MappingTable:
    """Cross-system mapping table — unified 1:N schema.

    Replaces the old ProposalTable. YAML schema:
      mappings:
        - source: "0602"
          default: "2130"
          decision: context
          basis: "..."
          targets:
            - code: "2130"
              when: {kind: comparison, field: QSXZ, op: "==", value: "10"}
              confidence: conditional
    """

    name: str
    version: str
    standard: str = ""
    source_system: str = ""
    target_system: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    _by_source: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        for entry in self.raw.get("mappings", []):
            source = str(entry.get("source", ""))
            if source:
                self._by_source[source] = entry

    def propose(self, source_code: str) -> Optional[Dict[str, Any]]:
        return self._by_source.get(str(source_code).strip())

    def to_dict(self) -> Dict[str, Tuple[str, str]]:
        result: Dict[str, Tuple[str, str]] = {}
        for entry in self.raw.get("mappings", []):
            source = str(entry.get("source", ""))
            default = str(entry.get("default", ""))
            decision = str(entry.get("decision", "auto"))
            if source and default:
                result[source] = (default, decision)
        return result


# ============================================================
# DictionaryCenter
# ============================================================

class DictionaryCenter:
    """Singleton registry of dictionaries organized by functional category.

    Scans subdirectories automatically — no manual registration needed.
    """

    def __init__(self):
        self._dictionaries: Dict[str, CodeDictionary] = {}
        self._mappings: Dict[str, MappingTable] = {}
        self._loaded = False

    def load(self, dict_dir: Optional[Path] = None) -> "DictionaryCenter":
        if self._loaded:
            return self
        base = dict_dir or _DICTS_DIR

        self._scan_dir(base / _ENCODINGS_DIR, "encoding")
        self._scan_dir(base / _RULES_DIR, "rule")
        self._scan_dir(base / _REFERENCES_DIR, "reference")
        self._scan_mappings(base / _MAPPINGS_DIR)

        # Advisory cross-system mappings (see _ADVISORY_DIR) — scanned for both
        # rule dictionaries (get_center().get("ghytbm_to_planning_zone")) and
        # cross-system mappings (get_mapping("gbt21010_to_planning_zones")).
        self._scan_dir(_ADVISORY_DIR, "rule")
        self._scan_mappings(_ADVISORY_DIR)

        self._loaded = True
        return self

    def _scan_dir(self, dirpath: Path, category: str) -> None:
        if not dirpath.is_dir():
            return
        for fp in sorted(dirpath.glob("*.yaml")):
            self._load_dict(fp, category)

    def _scan_mappings(self, dirpath: Path) -> None:
        if not dirpath.is_dir():
            return
        for fp in sorted(dirpath.glob("*.yaml")):
            self._load_mapping(fp)

    def _load_dict(self, filepath: Path, category: str) -> None:
        name = filepath.stem
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        version = data.get("version", "unknown")
        standard = data.get("standard", "")
        self._dictionaries[name] = CodeDictionary(
            name=name, version=version, standard=standard, category=category, raw=data
        )
        logger.info("[DictionaryCenter] Loaded %s/%s v=%s", category, name, version)

    def _load_mapping(self, filepath: Path) -> None:
        name = filepath.stem
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        version = data.get("version", "unknown")
        standard = data.get("standard", "")
        source_system = data.get("source_system", "")
        target_system = data.get("target_system", "")
        self._mappings[name] = MappingTable(
            name=name,
            version=version,
            standard=standard,
            source_system=source_system,
            target_system=target_system,
            raw=data,
        )
        logger.info("[DictionaryCenter] Loaded mapping %s v=%s (%s->%s)", name, version, source_system, target_system)

    # ── Public API ──────────────────────────────────────────

    _ALIASES = {"ghytbm": "appendix5", "dlbm": "gbt21010"}

    def get(self, name: str) -> CodeDictionary:
        if not self._loaded:
            self.load()
        name = self._ALIASES.get(name, name)
        d = self._dictionaries.get(name)
        if d is None:
            raise KeyError(f"Dictionary '{name}' not found. Available: {list(self._dictionaries.keys())}")
        return d

    def encoding(self, name: str) -> CodeDictionary:
        return self.get(name)

    def rule(self, name: str) -> CodeDictionary:
        return self.get(name)

    def get_mapping(self, name: str) -> MappingTable:
        if not self._loaded:
            self.load()
        m = self._mappings.get(name)
        if m is None:
            raise KeyError(f"Mapping '{name}' not found. Available: {list(self._mappings.keys())}")
        return m

    @property
    def encodings(self) -> List[str]:
        if not self._loaded:
            self.load()
        return [n for n, d in self._dictionaries.items() if d.category == "encoding"]

    @property
    def rules(self) -> List[str]:
        if not self._loaded:
            self.load()
        return [n for n, d in self._dictionaries.items() if d.category == "rule"]

    @property
    def mappings(self) -> List[str]:
        if not self._loaded:
            self.load()
        return list(self._mappings.keys())

    @property
    def versions(self) -> Dict[str, str]:
        if not self._loaded:
            self.load()
        v = {n: d.version for n, d in self._dictionaries.items()}
        v.update({n: m.version for n, m in self._mappings.items()})
        return v


# ============================================================
# Singleton
# ============================================================

_center: Optional[DictionaryCenter] = None


def get_center() -> DictionaryCenter:
    global _center
    if _center is None:
        _center = DictionaryCenter()
        _center.load()
    return _center


__all__ = [
    "CodeDictionary",
    "MappingTable",
    "DictionaryCenter",
    "get_center",
]
