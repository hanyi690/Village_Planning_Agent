"""Markdown 表格解析 — 单位级列语义检测（零领域关键词白名单）。

设计原则（回应"死映射"质疑）：
  - 表格识别 = 纯结构（表头行 + 分隔行 `| :--- |`）
  - 列语义 = 单位/符号检测：`%` → 占比列；`公顷|ha|亩|㎡|m²` → 面积列；
    其余文本列取第一列为名称列
  - 分区表判定 = 名称列 + 存在面积/占比列 + 名称值域多数含"区"
    （排除地类结构调整表/指标表/设施表）
  - 项目表 = 表头含"项目名称"（真实报告【建设项目库】标准化格式，最小配置）

真实报告表头覆盖（L3 12 维实测）：
  分区表：`分区名称|面积(公顷)|占比(%)|管控要求`（land_use_planning）、
          `分区类型|面积(公顷)|位置|功能定位`（spatial_structure，无占比列）
  排除：`地类|现状(公顷)|占比(%)|规划(公顷)|占比(%)|变化(公顷)`（结构调整表，名称无"区"）、
        `指标名称|现状值|目标值|依据标准`（无单位列）、
        `设施类型|数量|位置`（无面积/占比列）
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.modules.schema.contracts.parse_contracts import (
    FacilityTarget,
    SpatialPreference,
    ZoneTarget,
)
from app.modules.schema.contracts.semantic_fields import SemanticMetadata

_AREA_UNIT_RE = re.compile(r"(公顷|ha|hm|亩|㎡|m²)")
_RATIO_RE = re.compile(r"%")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
# P8: 位置列识别（表头含位置/选址/所在位置/方位/位于）
_LOCATION_HEADER_RE = re.compile(r"(位置|选址|所在位置|方位|位于|布局)")
_PROJECT_NAME_HEADER_RE = re.compile(r"(项目名称|工程名称|设施名称|项目名)")


def _split_row(line: str) -> List[str]:
    return [c.strip() for c in line.strip("|").split("|")]


def _is_separator(cells: List[str]) -> bool:
    return bool(cells) and all(set(c) <= {"-", ":", " "} for c in cells)


def _iter_tables(text: str) -> List[Tuple[List[str], List[List[str]]]]:
    """结构识别：返回 [(header_cells, data_rows)]，无任何领域关键词。"""
    tables = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|"):
            header = _split_row(line)
            if i + 1 < len(lines) and _is_separator(_split_row(lines[i + 1].strip())):
                i += 2
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    cells = _split_row(lines[i].strip())
                    if not _is_separator(cells):
                        rows.append(cells)
                    i += 1
                tables.append((header, rows))
                continue
        i += 1
    return tables


def _classify_columns(header: List[str], rows: List[List[str]]) -> dict:
    """单位级列分类：name / area / ratio / location / 其余 text 列。"""
    cols = {"name": None, "area": None, "ratio": None, "location": None, "text": []}
    for idx, cell in enumerate(header):
        joined = "".join(row[idx] for row in rows if idx < len(row))
        if _AREA_UNIT_RE.search(cell):
            cols["area"] = idx
        elif _RATIO_RE.search(cell):
            cols["ratio"] = idx
        elif _LOCATION_HEADER_RE.search(cell) and not _NUMBER_RE.search(joined):
            # P8: 位置列（如 位置/选址位置/所在位置），数据无数字才判为位置列
            cols["location"] = idx
        elif _NUMBER_RE.search(cell) and not any(_NUMBER_RE.findall(joined)):
            # 表头带数字（如"隐患点数量"）但数据无数字 → 名称类
            cols["text"].append(idx)
        elif not _NUMBER_RE.search(joined):
            if cols["name"] is None:
                cols["name"] = idx
            else:
                cols["text"].append(idx)
    return cols


def _extract_zone_tables(text: str) -> List[ZoneTarget]:
    """功能分区表 → ZoneTarget(land_use=分区名, area_ratio, area_ha in hint)."""
    targets = []
    seen = set()
    for header, rows in _iter_tables(text):
        if not rows:
            continue
        cols = _classify_columns(header, rows)
        if cols["name"] is None or (cols["area"] is None and cols["ratio"] is None):
            continue
        # 名称值域"区"字校验 → 排除地类结构调整表（耕地/园地/林地…无"区"）
        names = [r[cols["name"]] for r in rows if cols["name"] < len(r)]
        names = [n for n in names if n and not _NUMBER_RE.search(n)]
        if not names or sum("区" in n for n in names) / len(names) < 0.6:
            continue
        for row in rows:
            if cols["name"] >= len(row):
                continue
            name = row[cols["name"]]
            if not name or "名称" in name or "合计" in name or name in seen:
                continue
            area_ratio = 0.0
            area_ha = None
            if cols["ratio"] is not None and cols["ratio"] < len(row):
                # 占比列已由表头 % 识别；数据行直接取数字（有无 % 后缀均可）
                m2 = _NUMBER_RE.search(row[cols["ratio"]])
                if m2:
                    area_ratio = float(m2.group()) / 100.0
            if cols["area"] is not None and cols["area"] < len(row):
                m2 = _NUMBER_RE.search(row[cols["area"]])
                if m2:
                    area_ha = float(m2.group())
            if area_ratio <= 0.0 and area_ha is None:
                continue
            # P8: 位置列 → spatial_hint（如"位于园寨自然村"）
            location = ""
            if cols["location"] is not None and cols["location"] < len(row):
                location = row[cols["location"]]
            seen.add(name)
            targets.append(
                ZoneTarget(
                    land_use=name,
                    area_ratio=area_ratio,
                    semantic=SemanticMetadata(
                        natural_language_description=f"功能分区{name}"
                        + (f"占比{area_ratio*100:.0f}%" if area_ratio > 0.0 else "")
                        + (f"，面积{area_ha}公顷" if area_ha is not None else ""),
                        spatial_hint=f"AREA:{area_ha}" if area_ha is not None else "",
                    ),
                    spatial_preference=SpatialPreference(
                        direction="",
                        reference=location or None,
                    ) if location else None,
                )
            )
    return targets


def _extract_project_tables(text: str) -> List[FacilityTarget]:
    """建设项目库表 → FacilityTarget(type=项目名, location_hint=选址).

    P8 放宽：表头名称列含"项目名称/工程名称/设施名称"任一即可（真实报告
    【建设项目库】【产业项目清单】标准格式）；位置列 = 表头位置列，无则取
    数据行中首个含地理后缀的文本列。
    """
    targets = []
    seen = set()
    for header, rows in _iter_tables(text):
        if not rows:
            continue
        # 名称列判定：表头含项目/工程/设施名称字样的列
        name_idx = next(
            (i for i, h in enumerate(header) if _PROJECT_NAME_HEADER_RE.search(h)),
            None,
        )
        if name_idx is None:
            continue
        # P8: 位置列优先（表头含 位置/选址），无则回退地理后缀文本列
        location_idx = next(
            (i for i, h in enumerate(header) if _LOCATION_HEADER_RE.search(h)),
            None,
        )
        for row in rows:
            if name_idx >= len(row):
                continue
            name = row[name_idx]
            if not name or len(name) < 4 or "名称" in name or "合计" in name or name in seen:
                continue
            location = ""
            if location_idx is not None and location_idx < len(row):
                location = row[location_idx]
            if not location:
                for cell in row[name_idx + 1:]:
                    if any(kw in cell for kw in ("村", "园", "基地", "段", "路", "区", "中心", "坑", "塘")):
                        location = cell
                        break
            seen.add(name)
            targets.append(
                FacilityTarget(
                    type=name,
                    status="planned_new",
                    location_hint=location,
                    anchor_village=location,
                    semantic=SemanticMetadata(
                        natural_language_description=f"规划项目{name}",
                        spatial_hint=location,
                    ),
                )
            )
    return targets


__all__ = ["_extract_zone_tables", "_extract_project_tables"]
