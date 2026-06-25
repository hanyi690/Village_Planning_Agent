"""
Content extractor for Layer 1/2/3 reports.

Extracts structured data (numbers, tables, key text) from the three-layer
planning reports for use in article assembly.
"""

import json
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ExtractedData:
    """从L1/L2/L3报告提取的结构化数据。

    数值字段由摘要注入，用于 llm_styler.py 等场景。
    表格数据只从 layer3_sections 直接复制，不进行正则组装。
    """
    # 区位字段（从 config 注入）
    province: str = ""
    city: str = ""
    county: str = ""
    town: str = ""

    # L2 内容（直接复制）
    development_goal: str = ""
    planning_positioning: str = ""
    planning_strategies: str = ""
    resource_endowment: str = ""

    # 数值字段（从摘要注入，用于 llm_styler）
    total_area_ha: float = 0.0
    population_registered: int = 0
    population_resident: int = 0
    population_household: int = 0
    village_count: int = 0
    farmland_ha: float = 0.0
    construction_land_ha: float = 0.0
    ecological_land_ha: float = 0.0
    forest_coverage_pct: float = 0.0

    # 来源追踪（记录每个数值字段的来源维度，避免静默覆盖）
    _field_sources: Dict[str, str] = field(default_factory=dict, repr=False)
    # 限定键名存储（保留所有来源的值，key 格式: "dimension.field"）
    _qualified_metrics: Dict[str, float] = field(default_factory=dict, repr=False)

    # L3 结构化数据（表格只从这里复制）
    layer3_sections: Dict[str, Dict[str, str]] = field(default_factory=dict)
    layer3_tables: Dict[str, List[Dict]] = field(default_factory=dict)
    _raw_reports: Dict[str, str] = field(default_factory=dict, repr=False)

    # 法律依据（从 superior_planning 提取）
    legal_basis_national: List[str] = field(default_factory=list)
    legal_basis_provincial: List[str] = field(default_factory=list)
    legal_basis_planning: List[str] = field(default_factory=list)

    # 村名列表（从 socio_economic 提取）
    village_names: List[str] = field(default_factory=list)

    def get_full(self, dim: str) -> str:
        return self._raw_reports.get(dim, "")


class ContentExtractor:

    LAYER3_DIMS = [
        'industry', 'traffic_planning', 'public_service',
        'infrastructure_planning', 'ecological', 'disaster_prevention',
        'heritage', 'landscape', 'project_bank',
        'spatial_structure', 'land_use_planning', 'settlement_planning',
    ]

    def __init__(self, reports: Dict[str, str]):
        self.reports = reports
        self.data = ExtractedData()

    def extract_all(self) -> ExtractedData:
        # 只提取结构化内容，不进行数值正则提取
        self._extract_layer2()
        self._extract_layer3_sections()
        self._extract_layer3_tables()
        self._extract_village_names()
        self.data._raw_reports = dict(self.reports)
        self._extract_legal_basis()
        self._extract_superior_planning_citations()
        return self.data

    def _extract_layer2(self):
        for key, attr in [
            ('development_goals', 'development_goal'),
            ('planning_positioning', 'planning_positioning'),
            ('planning_strategies', 'planning_strategies'),
            ('resource_endowment', 'resource_endowment'),
        ]:
            if key in self.reports:
                content = self.reports[key]
                if isinstance(content, str) and content.strip().startswith('{'):
                    try:
                        parsed = json.loads(content)
                        content = parsed.get('summary', content)
                    except Exception:
                        content = content.strip()
                setattr(self.data, attr, content.strip() if isinstance(content, str) else str(content))

    def _extract_layer3_sections(self):
        for dim in self.LAYER3_DIMS:
            content = self.reports.get(dim, '')
            if not content:
                continue
            self.data.layer3_sections[dim] = self._parse_bracket_sections(content)

    def _parse_bracket_sections(self, text: str) -> Dict[str, str]:
        sections: Dict[str, str] = {}

        # Pattern 1: 【标题】格式
        bracket_pattern = re.compile(r'【(.+?)】\s*\n?')
        bracket_parts = list(bracket_pattern.finditer(text))

        # Pattern 2: Markdown标题格式 (## 标题 或 ### 标题)
        md_pattern = re.compile(r'^(#{1,3})\s+(.+?)\s*$', re.MULTILINE)
        md_parts = list(md_pattern.finditer(text))

        # 合并两种格式的匹配结果
        all_parts = []

        for match in bracket_parts:
            title = match.group(1).strip()
            all_parts.append((match.start(), match.end(), title))

        for match in md_parts:
            title = match.group(2).strip()
            # 过滤掉可能是列表项的短标题
            if len(title) >= 2 and not title.startswith(('-', '*', '•')):
                all_parts.append((match.start(), match.end(), title))

        # 按位置排序
        all_parts.sort(key=lambda x: x[0])

        for i, (start, end, title) in enumerate(all_parts):
            content_start = end
            content_end = all_parts[i + 1][0] if i + 1 < len(all_parts) else len(text)
            content = text[content_start:content_end].strip()
            content = re.sub(r'\n{3,}', '\n\n', content)

            lines = content.split('\n')
            if lines and re.match(r'^[：:，,。；;、！!？?）\)】】]+$', lines[0].strip()):
                punct = lines[0].strip()
                for j in range(1, len(lines)):
                    if lines[j].strip() and not re.match(r'^[：:，,。；;、！!？?）\)】】]+$', lines[j].strip()):
                        lines[j] = punct + lines[j]
                        lines[0] = ''
                        break
                content = '\n'.join(lines).strip()

            sections[title] = content
        return sections

    def _extract_layer3_tables(self):
        for dim in self.LAYER3_DIMS:
            content = self.reports.get(dim, '')
            if not content:
                continue
            tables = self._parse_markdown_tables(content)
            if tables:
                self.data.layer3_tables[dim] = tables

    def _parse_markdown_tables(self, text: str) -> List[Dict]:
        tables = []
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('|') and not line.startswith('|---'):
                table_name = ""
                j = i - 1
                while j >= 0:
                    prev = lines[j].strip()
                    if prev and not prev.startswith('|') and not prev.startswith('-'):
                        table_name = prev[:60]
                        break
                    j -= 1
                headers = [c.strip() for c in line.split('|') if c.strip()]
                i += 1
                if i < len(lines) and re.match(r'^\|[\s\-:]+\|', lines[i].strip()):
                    i += 1
                rows = []
                while i < len(lines):
                    row_line = lines[i].strip()
                    if not row_line.startswith('|'):
                        break
                    cells = [c.strip() for c in row_line.split('|') if c.strip()]
                    if cells:
                        rows.append(cells)
                    i += 1
                if headers and rows:
                    tables.append({'name': table_name, 'headers': headers, 'rows': rows})
            else:
                i += 1
        return tables

    def _extract_village_names(self):
        socio = self.reports.get('socio_economic', '')
        # 优先从 socio_economic 提取，避免 location 边界描述干扰
        match = re.search(r'完整名单[：:]\s*([^。\n]+)', socio)
        if not match:
            match = re.search(r'下辖\s*\d+\s*个自然村[，,：:\s]*(.+?)(?:\n|$)', socio)
        if not match:
            loc = self.reports.get('location', '')
            match = re.search(r'包括(.+?)等\s*\d+\s*个自然村', loc + '\n' + socio)

        if match:
            names_str = match.group(1)
            # 在句号处截断，避免匹配到后续描述
            if '。' in names_str:
                names_str = names_str.split('。')[0]
            names = re.split(r'[、，,]', names_str)
            # 过滤：长度2-6，不含方位词（至/接/靠/连），不含数字计数
            names = [
                n.strip() for n in names
                if n.strip() and 2 <= len(n.strip()) <= 6
                and not re.search(r'[至接靠连]|^\d+$', n.strip())
            ]
            if names:
                self.data.village_names = names

    def _extract_superior_planning_citations(self):
        sp_text = self.reports.get('superior_planning', '')
        if not sp_text:
            return
        sp_sections = {}
        chapter_pat = re.compile(r'第[一二三四五六七八九十]+章\s+(.+?)(?=\n)')
        parts = list(chapter_pat.finditer(sp_text))
        for i, match in enumerate(parts):
            title = match.group(1).strip()
            start = match.end()
            end = parts[i + 1].start() if i + 1 < len(parts) else len(sp_text)
            content = sp_text[start:end].strip()
            sp_sections[title] = content
        if sp_sections:
            self.data.layer3_sections['superior_planning'] = sp_sections
        specific_docs = set()
        for law_name in re.findall(r'《([^》]+)》', sp_text):
            full = f'《{law_name}》'
            if len(full) < 80:
                specific_docs.add(full)
        for doc in specific_docs:
            if '中华人民共和国' in doc:
                if doc not in self.data.legal_basis_national:
                    self.data.legal_basis_national.append(doc)
            elif '省' in doc and ('条例' in doc or '规划' in doc or '意见' in doc or '批复' in doc):
                if doc not in self.data.legal_basis_provincial:
                    self.data.legal_basis_provincial.append(doc)
            elif '市' in doc or '县' in doc or '镇' in doc:
                if doc not in self.data.legal_basis_planning:
                    self.data.legal_basis_planning.append(doc)
            elif '规划' in doc or '国土空间' in doc:
                if doc not in self.data.legal_basis_planning:
                    self.data.legal_basis_planning.append(doc)
        self.data.legal_basis_national = sorted(set(self.data.legal_basis_national))
        self.data.legal_basis_provincial = sorted(set(self.data.legal_basis_provincial))
        self.data.legal_basis_planning = sorted(set(self.data.legal_basis_planning))

    def _extract_legal_basis(self):
        national = set()
        provincial = set()
        planning = set()
        raw_reports = self.reports
        all_sources = raw_reports.get('knowledge_sources', [])
        if not all_sources:
            reports_dict = raw_reports.get('reports', raw_reports)
            meta = reports_dict.get('_meta', {})
            all_sources = meta.get('knowledge_sources', [])
        if all_sources:
            for src in all_sources:
                source_name = src.get('source', '') if isinstance(src, dict) else str(src)
                name = re.sub(r'_minerU_parsed\.md$', '', source_name)
                name = re.sub(r'\.md$', '', name)
                name = re.sub(r'^\d+\s*', '', name)
                if not name.strip():
                    continue
                if '《中华人民共和国' in name or '国务院' in name or '中共中央' in name:
                    national.add(name)
                elif '省' in name and ('条例' in name or '规划' in name or '意见' in name):
                    provincial.add(name)
                elif '市' in name or '县' in name or '镇' in name:
                    if '规划' in name or '批复' in name or '方案' in name:
                        planning.add(name)
                elif '规划' in name or '国土空间' in name:
                    planning.add(name)
        combined_text = '\n'.join(self.reports.values()) if isinstance(self.reports, dict) else ''
        for law_name in re.findall(r'《中华人民共和国([^》]+)》', combined_text):
            full = f'《中华人民共和国{law_name}》'
            if len(full) < 80:
                national.add(full)
        for law_name in re.findall(r'《([^》]*(?:省|市|县|镇)[^》]*(?:条例|规划|意见|通知|批复|方案|导则)[^》]*)》', combined_text):
            if len(law_name) < 60:
                if '省' in law_name:
                    provincial.add(f'《{law_name}》')
                else:
                    planning.add(f'《{law_name}》')
        sup_text = self.reports.get('superior_planning', '')
        for law_name in re.findall(r'《([^》]+)》', sup_text):
            full = f'《{law_name}》'
            if len(full) < 80:
                if '中华人民共和国' in full or '国务院' in full:
                    national.add(full)
                elif '省' in law_name:
                    provincial.add(full)
                elif '市' in law_name or '县' in law_name or '镇' in law_name:
                    planning.add(full)
        self.data.legal_basis_national = sorted(national)
        self.data.legal_basis_provincial = sorted(provincial)
        self.data.legal_basis_planning = sorted(planning)

    def get_section(self, dim: str, title: str) -> str:
        sections = self.data.layer3_sections.get(dim, {})
        for t, c in sections.items():
            if title in t or t in title:
                return c
        return ""

    def get_full(self, dim: str) -> str:
        return self.reports.get(dim, "")


def create_extracted_data(
    layer1_reports: Dict[str, str],
    layer2_reports: Dict[str, str],
    layer3_reports: Dict[str, str],
    *,
    summaries: Dict[str, Dict[str, Any]] = None,
    province: str = "",
    city: str = "",
    county: str = "",
    township: str = "",
) -> ExtractedData:
    """从L1/L2/L3报告提取结构化内容。

    表格只从L3报告直接复制，数值字段从摘要注入（用于llm_styler）。
    """
    all_reports = {**layer1_reports, **layer2_reports, **layer3_reports}
    data = ContentExtractor(all_reports).extract_all()

    # 从摘要注入数值字段（用于 llm_styler）
    if summaries:
        _inject_from_summaries(data, summaries)

    # 从 config 注入位置
    if province:
        data.province = province
    if city:
        data.city = city
    if county:
        data.county = county
    if township:
        data.town = township

    return data


def _get_metrics(summaries: Dict[str, Dict[str, Any]], dimension: str) -> Dict[str, Any]:
    """Extract metrics dict from summaries — supports both flat and nested formats.

    Nested: {dk: {"summary": {"metrics": ...}}} (PlanningKG format)
    Flat:   {dk: {"metrics": ...}} (legacy format)
    """
    dim = summaries.get(dimension, {})
    summary_obj = dim.get("summary", {})
    if summary_obj and "metrics" in summary_obj:
        return summary_obj["metrics"]
    return dim.get("metrics", {})


def _inject_from_summaries(data: ExtractedData, summaries: Dict[str, Dict[str, Any]]) -> None:
    """从维度摘要注入数值字段（用于 llm_styler）。

    注意：表格数据不从摘要注入，只从 L3 报告直接复制。

    使用限定键名存储所有来源的值，避免静默覆盖。
    同时记录 _field_sources 追踪简单字段的来源维度。
    """
    # 社会经济
    socio_m = _get_metrics(summaries, "socio_economic")
    if socio_m.get("registered_population"):
        data.population_registered = int(socio_m["registered_population"])
        data._field_sources["population_registered"] = "socio_economic"
    if socio_m.get("resident_population"):
        data.population_resident = int(socio_m["resident_population"])
        data._field_sources["population_resident"] = "socio_economic"
    if socio_m.get("households"):
        data.population_household = int(socio_m["households"])
        data._field_sources["population_household"] = "socio_economic"

    # 土地利用（使用语义限定字段名 current_）
    land_m = _get_metrics(summaries, "land_use")
    if land_m.get("total_area_ha"):
        data.total_area_ha = float(land_m["total_area_ha"])
        data._field_sources["total_area_ha"] = "land_use"
        data._qualified_metrics["land_use.total_area_ha"] = float(land_m["total_area_ha"])

    # 兼容旧字段名 farmland_area_ha 和新字段名 current_farmland_ha
    farmland_val = land_m.get("current_farmland_ha") or land_m.get("farmland_area_ha")
    if farmland_val:
        data.farmland_ha = float(farmland_val)
        data._field_sources["farmland_ha"] = "land_use"
        data._qualified_metrics["land_use.current_farmland_ha"] = float(farmland_val)

    # 兼容旧字段名 construction_area_ha 和新字段名 current_construction_ha
    construction_val = land_m.get("current_construction_ha") or land_m.get("construction_area_ha")
    if construction_val:
        data.construction_land_ha = float(construction_val)
        data._field_sources["construction_land_ha"] = "land_use"
        data._qualified_metrics["land_use.current_construction_ha"] = float(construction_val)

    if land_m.get("ecological_area_ha"):
        data.ecological_land_ha = float(land_m["ecological_area_ha"])
        data._field_sources["ecological_land_ha"] = "land_use"
        data._qualified_metrics["land_use.ecological_area_ha"] = float(land_m["ecological_area_ha"])

    if land_m.get("forest_coverage_rate"):
        rate = float(land_m["forest_coverage_rate"])
        data._qualified_metrics["land_use.forest_coverage_rate"] = rate
        # 只在未被其他来源设置时写入简单字段
        if "forest_coverage_pct" not in data._field_sources:
            data.forest_coverage_pct = rate
            data._field_sources["forest_coverage_pct"] = "land_use"

    # 自然环境（不再静默覆盖，保留所有来源）
    nat_m = _get_metrics(summaries, "natural_environment")
    if nat_m.get("forest_coverage_rate"):
        rate = float(nat_m["forest_coverage_rate"])
        data._qualified_metrics["natural_environment.forest_coverage_rate"] = rate
        # 如果 land_use 已设置且值不同，保留 land_use 作为主来源
        # 自然环境的值仅存在限定键名中，冲突检测器会比较
        if "forest_coverage_pct" not in data._field_sources:
            data.forest_coverage_pct = rate
            data._field_sources["forest_coverage_pct"] = "natural_environment"

    # 村庄数量
    if data.village_names:
        data.village_count = len(data.village_names)

    # ---- L3 维度指标注入（用于冲突检测） ----

    # 上位规划（约束值）
    sup_m = _get_metrics(summaries, "superior_planning")
    _inject_qualified(data, sup_m, "superior_planning", "min_ecological_redline_ha")
    _inject_qualified(data, sup_m, "superior_planning", "min_farmland_protection_ha")
    _inject_qualified(data, sup_m, "superior_planning", "max_construction_ha")

    # 土地利用规划（规划目标值 + 现状值）
    lup_m = _get_metrics(summaries, "land_use_planning")
    _inject_qualified(data, lup_m, "land_use_planning", "current_construction_ha")
    _inject_qualified(data, lup_m, "land_use_planning", "planned_construction_ha")
    _inject_qualified(data, lup_m, "land_use_planning", "planned_farmland_ha")
    _inject_qualified(data, lup_m, "land_use_planning", "planned_ecological_ha")
    _inject_qualified(data, lup_m, "land_use_planning", "planned_residential_ha")
    _inject_qualified(data, lup_m, "land_use_planning", "planned_industry_ha")

    # 村庄建设规划（规划目标值 + 现状值）
    sp_m = _get_metrics(summaries, "settlement_planning")
    _inject_qualified(data, sp_m, "settlement_planning", "current_construction_ha")
    _inject_qualified(data, sp_m, "settlement_planning", "planned_construction_ha")
    _inject_qualified(data, sp_m, "settlement_planning", "planned_population")

    # 产业
    ind_m = _get_metrics(summaries, "industry")
    _inject_qualified(data, ind_m, "industry", "planned_industry_area_ha")

    # 生态（约束值）
    eco_m = _get_metrics(summaries, "ecological")
    _inject_qualified(data, eco_m, "ecological", "min_ecological_redline_ha")


def _inject_qualified(
    data: ExtractedData,
    metrics: Dict[str, Any],
    dimension: str,
    field_name: str,
) -> None:
    """Inject a metric value into _qualified_metrics if present.

    Uses qualified key format "dimension.field_name" so all sources
    are preserved without silent overwrites.
    """
    val = metrics.get(field_name)
    if val is not None:
        try:
            data._qualified_metrics[f"{dimension}.{field_name}"] = float(val)
        except (TypeError, ValueError):
            pass
