"""2024年全国5级行政区划数据加载与查询。

数据来源: 国家统计局 (data/gis/china_area-2024/area_code_2024.csv.gz)
5级: 省(1)、市(2)、县(3)、镇(4)、村(5)

用法:
    service = AdminCodeService()
    prov = service.get_by_code("440000000000")
    children = service.get_children("440000000000")
    chain = service.get_parent_chain("440103001001")
    results = service.search("金田", level=5)
"""

from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.settings import GIS_DATA_DIR
from app.utils.logger import get_logger

logger = get_logger(__name__)

CHINA_AREA_DIR = GIS_DATA_DIR / "china_area-2024"
CSV_GZ_PATH = CHINA_AREA_DIR / "area_code_2024.csv.gz"


@dataclass
class AdminCodeRecord:
    code: str
    name: str
    level: int
    pcode: str
    category: int = 0

    @property
    def level_name(self) -> str:
        return {1: "province", 2: "city", 3: "county", 4: "town", 5: "village"}.get(self.level, "unknown")

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "level": self.level,
            "level_name": self.level_name,
            "pcode": self.pcode,
            "category": self.category,
        }


class AdminCodeService:
    """Singleton service for loading and querying the 2024 administrative code dataset."""

    _instance: Optional[AdminCodeService] = None

    def __new__(cls) -> AdminCodeService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_loaded", False):
            return
        self._loaded = False
        self._code_index: Dict[str, AdminCodeRecord] = {}
        self._name_index: Dict[str, List[AdminCodeRecord]] = {}
        self._parent_index: Dict[str, List[AdminCodeRecord]] = {}
        self._provinces: List[AdminCodeRecord] = []

    # ── Public Query API ──────────────────────────────────────────────

    def get_by_code(self, code: str) -> Optional[AdminCodeRecord]:
        self._ensure_loaded()
        return self._code_index.get(code)

    def get_by_name(self, name: str, level: Optional[int] = None) -> List[AdminCodeRecord]:
        self._ensure_loaded()
        results = self._name_index.get(name, [])
        if level is not None:
            results = [r for r in results if r.level == level]
        return results

    def get_children(self, code: str) -> List[AdminCodeRecord]:
        self._ensure_loaded()
        return self._parent_index.get(code, [])

    def get_parent_chain(self, code: str) -> List[AdminCodeRecord]:
        """Return the full hierarchy from province down to the given code."""
        self._ensure_loaded()
        chain: List[AdminCodeRecord] = []
        record = self._code_index.get(code)
        while record and record.pcode and record.pcode != "0":
            chain.insert(0, record)
            record = self._code_index.get(record.pcode)
        if record:
            chain.insert(0, record)
        return chain

    def get_parent_chain_with_names(self, code: str) -> List[Tuple[str, str, int]]:
        """Return [(code, name, level), ...] from province down to the given code."""
        return [(r.code, r.name, r.level) for r in self.get_parent_chain(code)]

    def search(self, keyword: str, level: Optional[int] = None, limit: int = 20) -> List[AdminCodeRecord]:
        """Search by name substring match."""
        self._ensure_loaded()
        results: List[AdminCodeRecord] = []
        for name, records in self._name_index.items():
            if keyword in name:
                for r in records:
                    if level is None or r.level == level:
                        results.append(r)
                        if len(results) >= limit:
                            return results
        return results

    def get_provinces(self) -> List[AdminCodeRecord]:
        self._ensure_loaded()
        return self._provinces

    def get_cities(self, province_code: str) -> List[AdminCodeRecord]:
        return self.get_children(province_code)

    def get_counties(self, city_code: str) -> List[AdminCodeRecord]:
        return self.get_children(city_code)

    def get_towns(self, county_code: str) -> List[AdminCodeRecord]:
        return self.get_children(county_code)

    def get_villages(self, town_code: str) -> List[AdminCodeRecord]:
        return self.get_children(town_code)

    def resolve_hierarchy(self, province: str = "", city: str = "", county: str = "",
                          town: str = "", village: str = "") -> dict:
        """Resolve administrative hierarchy names to codes.

        Returns dict with matched codes and names at each level.
        """
        self._ensure_loaded()
        result: dict = {
            "province": {"code": "", "name": province},
            "city": {"code": "", "name": city},
            "county": {"code": "", "name": county},
            "town": {"code": "", "name": town},
            "village": {"code": "", "name": village},
        }

        if province:
            matches = self.get_by_name(province, level=1)
            if matches:
                result["province"]["code"] = matches[0].code
                pcode = matches[0].code
                if city:
                    cmatches = [r for r in self.get_children(pcode) if city in r.name]
                    if cmatches:
                        result["city"]["code"] = cmatches[0].code
                        ccode = cmatches[0].code
                        if county:
                            ctmatches = [r for r in self.get_children(ccode) if county in r.name]
                            if ctmatches:
                                result["county"]["code"] = ctmatches[0].code
                                ctcode = ctmatches[0].code
                                if town:
                                    tmatches = [r for r in self.get_children(ctcode) if town in r.name]
                                    if tmatches:
                                        result["town"]["code"] = tmatches[0].code
                                        tcode = tmatches[0].code
                                        if village:
                                            vmatches = [r for r in self.get_children(tcode) if village in r.name]
                                            if vmatches:
                                                result["village"]["code"] = vmatches[0].code
        return result

    def stats(self) -> dict:
        self._ensure_loaded()
        counts = {}
        for rec in self._code_index.values():
            counts[rec.level] = counts.get(rec.level, 0) + 1
        return {
            "total": len(self._code_index),
            "by_level": {k: v for k, v in sorted(counts.items())},
            "year": 2024,
        }

    # ── Internal ──────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not CSV_GZ_PATH.exists():
            logger.warning("[admin_code] CSV not found at %s", CSV_GZ_PATH)
            return
        logger.info("[admin_code] Loading 2024 administrative codes from %s ...", CSV_GZ_PATH)
        self._load_csv()
        self._loaded = True
        logger.info("[admin_code] Loaded %d records (%d provinces, %d cities, %d counties, %d towns, %d villages)",
                     len(self._code_index),
                     len([r for r in self._code_index.values() if r.level == 1]),
                     len([r for r in self._code_index.values() if r.level == 2]),
                     len([r for r in self._code_index.values() if r.level == 3]),
                     len([r for r in self._code_index.values() if r.level == 4]),
                     len([r for r in self._code_index.values() if r.level == 5]))

    def _load_csv(self) -> None:
        with gzip.open(str(CSV_GZ_PATH), "rt", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 5:
                    continue
                code, name, level_str, pcode, category_str = row
                try:
                    level = int(level_str)
                    category = int(category_str) if category_str else 0
                except ValueError:
                    continue
                record = AdminCodeRecord(
                    code=code,
                    name=name,
                    level=level,
                    pcode=pcode,
                    category=category,
                )
                self._code_index[code] = record
                self._name_index.setdefault(name, []).append(record)
                if pcode and pcode != "0":
                    self._parent_index.setdefault(pcode, []).append(record)
                if level == 1:
                    self._provinces.append(record)


def get_admin_code_service() -> AdminCodeService:
    return AdminCodeService()