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

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from app.modules.schema.contracts.parse_contracts import (
    AxisTarget,
    FacilityTarget,
    ProjectTarget,
    RoadTarget,
    SpatialPreference,
    ZoneTarget,
)
from app.modules.schema.contracts.provenance import SemanticMetadata

from app.modules.parsing.spatial_language import direction_from_location

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
        table_targets = []
        seen = set()
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
            table_targets.append(
                ZoneTarget(
                    land_use=name,
                    area_ratio=area_ratio,
                    area_ha=area_ha,
                    semantic=SemanticMetadata(
                        natural_language_description=f"功能分区{name}"
                        + (f"占比{area_ratio*100:.0f}%" if area_ratio > 0.0 else "")
                        + (f"，面积{area_ha}公顷" if area_ha is not None else ""),
                        spatial_hint=f"AREA:{area_ha}" if area_ha is not None else "",
                    ),
                    spatial_preference=SpatialPreference(
                        direction=direction_from_location(location),
                        reference=location or None,
                    ) if location else None,
                )
            )
        if table_targets:
            return table_targets
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


def _extract_road_tables(text: str) -> List[RoadTarget]:
    """Road hierarchy tables -> typed road targets."""
    targets = []
    seen = set()
    for header, rows in _iter_tables(text):
        name_idx = next(
            (i for i, cell in enumerate(header) if "道路名称" in cell),
            None,
        )
        width_idx = next(
            (i for i, cell in enumerate(header) if "宽度" in cell),
            None,
        )
        if name_idx is None or width_idx is None:
            continue
        type_idx = next(
            (i for i, cell in enumerate(header) if "道路类型" in cell),
            None,
        )
        connects_idx = next(
            (i for i, cell in enumerate(header) if "连接" in cell),
            None,
        )
        for row in rows:
            if name_idx >= len(row) or width_idx >= len(row):
                continue
            name = row[name_idx].strip()
            width_match = _NUMBER_RE.search(row[width_idx])
            if not name or not width_match or name in seen:
                continue
            road_type = (
                row[type_idx].strip()
                if type_idx is not None and type_idx < len(row)
                else ""
            )
            connects = (
                [row[connects_idx].strip()]
                if connects_idx is not None
                and connects_idx < len(row)
                and row[connects_idx].strip()
                else []
            )
            seen.add(name)
            targets.append(
                RoadTarget(
                    road_level=name,
                    width_m=float(width_match.group()),
                    connects=connects,
                    semantic=SemanticMetadata(
                        natural_language_description=(
                            f"{road_type}{name}，规划宽度{width_match.group()}米"
                        ),
                    ),
                )
            )
    return targets


# ── P8: INSTRUCTION 段结构化提取 (migrated from parse_agent.py Wave M2) ──

_INSTRUCTION_MARKER = "【INSTRUCTION】"

_INSTRUCTION_TYPE_MAP = {
    "项目": "project",
    "功能分区": "zone",
    "分区": "zone",
    "设施": "facility",
    "道路": "road",
    "轴线": "axis",
    "现状设施": "facility",
    "现状项目": "project",
    "现状分区": "zone",
}

_INSTRUCTION_LOCATION_HEADER_RE = re.compile(r"(位置|选址|所在位置|方位|位于)")
_INSTRUCTION_NAME_HEADER_RE = re.compile(r"(名称|项目|工程)")


def _extract_instruction_section(text: str) -> str:
    """取【INSTRUCTION】标记起的结构化段（含标记行）。无标记返回空。"""
    if not text:
        return ""
    idx = text.find(_INSTRUCTION_MARKER)
    if idx < 0:
        return ""
    return text[idx:]


def _classify_project_category(name: str, description: str = "") -> str:
    text = f"{name} {description}"
    if any(word in text for word in ("道路", "村道", "公路", "桥", "路网")):
        return "road"
    if any(word in text for word in ("服务中心", "卫生", "学校", "广场", "停车", "公园", "设施")):
        return "facility"
    if any(word in text for word in ("污水", "供水", "排水", "电力", "通信", "环卫")):
        return "infrastructure"
    if any(word in text for word in ("整治", "修复", "复垦")):
        return "land_consolidation"
    if any(word in text for word in ("产业", "基地", "园区", "旅游", "民宿")):
        return "industry"
    return "other"


def extract_instruction_tables(text: str) -> Dict[str, List[Any]]:
    """从【INSTRUCTION】段解析固定列 markdown 表格 -> 空间目标列表。

    行级容错：坏行 / 未知类型 / 空名称 丢弃，不影响其余行。
    返回 {projects, zones, facilities, axes, roads}。
    Migrated from app.agent.select.parse_agent._extract_instruction_tables (Wave M2).
    """
    section = _extract_instruction_section(text)
    if not section:
        return {"projects": [], "zones": [], "facilities": [], "axes": [], "roads": []}

    projects: List[ProjectTarget] = []
    zones: List[ZoneTarget] = []
    facilities: List[FacilityTarget] = []
    axes: List[AxisTarget] = []
    roads: List[RoadTarget] = []
    seen = {"projects": set(), "zones": set(), "facilities": set(), "axes": set(), "roads": set()}
    kind_to_seen = {
        "project": "projects",
        "zone": "zones",
        "facility": "facilities",
        "axis": "axes",
        "road": "roads",
    }
    bad_rows = 0
    no_location = 0

    for header, rows in _iter_tables(section):
        type_idx = 0 if any("类型" in h for h in header) else None
        name_idx = next(
            (i for i, h in enumerate(header) if _INSTRUCTION_NAME_HEADER_RE.search(h)),
            None,
        )
        loc_idx = next(
            (i for i, h in enumerate(header) if _INSTRUCTION_LOCATION_HEADER_RE.search(h)),
            None,
        )
        desc_idx = next(
            (i for i, h in enumerate(header) if "描述" in h or "内容" in h),
            None,
        )
        scale_idx = next(
            (i for i, h in enumerate(header) if "规模" in h),
            None,
        )
        if type_idx is None or name_idx is None:
            continue

        for row in rows:
            if type_idx >= len(row) or name_idx >= len(row):
                bad_rows += 1
                continue
            kind = _INSTRUCTION_TYPE_MAP.get(str(row[type_idx]).strip())
            name = row[name_idx].strip()
            seen_key = kind_to_seen.get(kind) if kind else None
            if seen_key is None or not name or len(name) < 2 or name in seen[seen_key]:
                bad_rows += 1
                continue
            location = (row[loc_idx].strip() if loc_idx is not None and loc_idx < len(row) else "") or ""
            if not location:
                no_location += 1
            description = (row[desc_idx].strip() if desc_idx is not None and desc_idx < len(row) else "") or ""
            scale = (row[scale_idx].strip() if scale_idx is not None and scale_idx < len(row) else "") or ""

            semantic = SemanticMetadata(
                natural_language_description=f"{name}：{description}" if description else name,
                spatial_hint=location or "",
                raw_text=" | ".join(str(cell) for cell in row),
            )
            instruction_seed = f"{name}|{location}|{description}|{scale}"
            instruction_id = "INS-" + hashlib.sha1(
                instruction_seed.encode("utf-8")
            ).hexdigest()[:12]
            if kind == "project":
                seen["projects"].add(name)
                project_id = "PRJ-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
                category = _classify_project_category(name, description)
                project = ProjectTarget(
                    project_id=project_id,
                    name=name,
                    category=category,
                    scale_text=scale,
                    location_hint=location,
                    source_instruction_id=instruction_id,
                    source_row=len(projects) + 1,
                    semantic=semantic,
                )
                projects.append(project)
                if category == "road":
                    roads.append(RoadTarget(
                        road_level=name,
                        connects=[location] if location else [],
                        source_project_id=project_id,
                        source_instruction_id=instruction_id,
                        semantic=semantic,
                    ))
                elif category in {"facility", "infrastructure"}:
                    facilities.append(FacilityTarget(
                        type=name,
                        status="planned_new",
                        location_hint=location,
                        anchor_village=location,
                        source_project_id=project_id,
                        source_instruction_id=instruction_id,
                        semantic=semantic,
                    ))
            elif kind == "zone":
                seen["zones"].add(name)
                zones.append(ZoneTarget(
                    land_use=name,
                    source_instruction_id=instruction_id,
                    semantic=semantic,
                    spatial_preference=SpatialPreference(
                        direction=direction_from_location(location),
                        reference=location or None,
                    ) if location else None,
                ))
            elif kind == "facility":
                seen["facilities"].add(name)
                facilities.append(FacilityTarget(
                    type=name,
                    status="planned_new",
                    location_hint=location,
                    anchor_village=location,
                    source_instruction_id=instruction_id,
                    semantic=semantic,
                ))
            elif kind == "axis":
                seen["axes"].add(name)
                axes.append(AxisTarget(
                    label=name,
                    reference_feature=location or "",
                    source_instruction_id=instruction_id,
                    semantic=semantic,
                ))
            elif kind == "road":
                seen["roads"].add(name)
                roads.append(RoadTarget(
                    road_level=name,
                    connects=[location] if location else [],
                    source_instruction_id=instruction_id,
                    semantic=semantic,
                ))

    return {
        "projects": projects,
        "zones": zones,
        "facilities": facilities,
        "axes": axes,
        "roads": roads,
    }


__all__ = [
    "_extract_zone_tables",
    "_extract_project_tables",
    "_extract_road_tables",
    "extract_instruction_tables",
]
