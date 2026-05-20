"""
Content extractor for Layer 1/2/3 reports.

Extracts structured data (numbers, tables, key text) from the three-layer
planning reports for use in article assembly.
"""

import json
import re
from typing import Any, Dict, List
from dataclasses import dataclass, field


@dataclass
class ExtractedData:
    total_area_ha: float = 0.0
    population_household: int = 0
    population_registered: int = 0
    population_resident: int = 0
    farmland_ha: float = 0.0
    paddy_ha: float = 0.0
    construction_land_ha: float = 0.0
    ecological_land_ha: float = 0.0
    forest_coverage_pct: float = 0.0
    commercial_forest_ha: float = 0.0
    ecological_forest_ha: float = 0.0
    water_ha: float = 0.0
    village_count: int = 0
    village_names: List[str] = field(default_factory=list)
    building_count: int = 0
    collapse_points: int = 0
    landslide_points: int = 0
    development_goal: str = ""
    planning_positioning: str = ""
    planning_strategies: str = ""
    resource_endowment: str = ""
    province: str = ""
    city: str = ""
    county: str = ""
    town: str = ""
    legal_basis_national: List[str] = field(default_factory=list)
    legal_basis_provincial: List[str] = field(default_factory=list)
    legal_basis_planning: List[str] = field(default_factory=list)
    layer3_sections: Dict[str, Dict[str, str]] = field(default_factory=dict)
    layer3_tables: Dict[str, List[Dict]] = field(default_factory=dict)
    raw_numbers: Dict[str, float] = field(default_factory=dict)
    _raw_reports: Dict[str, str] = field(default_factory=dict, repr=False)

    def get_full(self, dim: str) -> str:
        return self._raw_reports.get(dim, "")


class ContentExtractor:

    LAYER3_DIMS = [
        'industry', 'traffic_planning', 'public_service',
        'infrastructure_planning', 'ecological', 'disaster_prevention',
        'heritage', 'landscape', 'project_bank',
        'spatial_structure', 'land_use_planning', 'settlement_planning',
    ]

    NUM_PATTERNS = [
        (r'土地总[用]?面积[约]*\s*([\d.]+)\s*公顷', 'total_area_ha', 1.0),
        (r'户籍人口\s*(\d+)\s*人', 'population_registered', 1),
        (r'常住人口[约]?\s*(\d+)\s*人', 'population_resident', 1),
        (r'(\d+)\s*户', 'population_household', 1),
        (r'耕地面积[约]*\s*([\d.]+)\s*公顷', 'farmland_ha', 1.0),
        (r'水田面积[达]?\s*([\d.]+)\s*公顷', 'paddy_ha', 1.0),
        (r'建设用地[总面积]?\s*([\d.]+)\s*公顷', 'construction_land_ha', 1.0),
        (r'生态用地[总面积]?\s*([\d.]+)\s*公顷', 'ecological_land_ha', 1.0),
        (r'林地[面积]*[在占比达]?\s*(\d+)\s*%', 'forest_coverage_pct', 1.0),
        (r'商业林[面积约]*\s*([\d.]+)\s*公顷', 'commercial_forest_ha', 1.0),
        (r'生态林[面积约]*\s*([\d.]+)\s*公顷', 'ecological_forest_ha', 1.0),
        (r'水域面积\s*([\d.]+)\s*公顷', 'water_ha', 1.0),
        (r'(\d+)\s*个自然村', 'village_count', 1),
        (r'建筑\s*(\d+)\s*处', 'building_count', 1),
        (r'(\d+)\s*处崩塌', 'collapse_points', 1),
        (r'(\d+)\s*处滑坡', 'landslide_points', 1),
    ]

    def __init__(self, reports: Dict[str, str]):
        self.reports = reports
        self.data = ExtractedData()

    def extract_all(self) -> ExtractedData:
        land_use = self.reports.get('land_use', '')
        m = re.search(r'土地总用地面积[约]*\s*([\d.]+)\s*公顷', land_use)
        if m:
            self.data.total_area_ha = float(m.group(1))
            self.data.raw_numbers['total_area_ha'] = self.data.total_area_ha

        all_text = '\n'.join(self.reports.values())
        for pattern, field, mult in self.NUM_PATTERNS:
            if field == 'total_area_ha' and self.data.total_area_ha > 0:
                continue
            match = re.search(pattern, all_text)
            if match:
                try:
                    val = float(match.group(1)) * mult
                    setattr(self.data, field, val)
                    self.data.raw_numbers[field] = val
                except (ValueError, AttributeError):
                    pass

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
        pattern = re.compile(r'【(.+?)】\s*\n?')
        parts = list(pattern.finditer(text))
        for i, match in enumerate(parts):
            title = match.group(1).strip()
            start = match.end()
            end = parts[i + 1].start() if i + 1 < len(parts) else len(text)
            content = text[start:end].strip()
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
        loc = self.reports.get('location', '')
        socio = self.reports.get('socio_economic', '')
        combined = loc + '\n' + socio

        for pat in [
            r'完整名单[：:]\s*(.+?)(?:\n|$)',
            r'下辖(.+?)(?:共|等)?\d+\s*个自然村',
            r'包括(.+?)等\d+个自然村',
            r'分别为(.+?)，其中',
        ]:
            match = re.search(pat, combined)
            if match:
                names_str = match.group(1)
                names = re.split(r'[、，,]', names_str)
                names = [n.strip() for n in names if n.strip() and len(n.strip()) <= 6]
                if names:
                    names[-1] = re.sub(r'[共等\s\d]+.*$', '', names[-1]).strip()
                if names:
                    self.data.village_names = names
                    self.data.village_count = len(names)
                    return

    def _extract_location_info(self):
        loc = self.reports.get('location', '')
        if not loc:
            return
        patterns = [
            (r'([^\s，,]+省)', 'province'),
            (r'([^\s，,]+市)', 'city'),
            (r'([^\s，,]+县)', 'county'),
            (r'([^\s，,]+镇)', 'town'),
        ]
        for pat, field in patterns:
            match = re.search(pat, loc)
            if match:
                setattr(self.data, field, match.group(1))

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
    all_reports = {**layer1_reports, **layer2_reports, **layer3_reports}
    data = ContentExtractor(all_reports).extract_all()

    # 从 config 注入区位（优先级最高，替代 _extract_location_info 正则）
    if province:
        data.province = province
    if city:
        data.city = city
    if county:
        data.county = county
    if township:
        data.town = township

    # 从维度摘要注入数值字段（优先于正则提取的结果）
    if summaries:
        _inject_from_summaries(data, summaries)

    return data


def _inject_from_summaries(data: ExtractedData, summaries: Dict[str, Dict[str, Any]]) -> None:
    """从维度摘要注入数值字段，仅覆盖正则提取为零值的字段。"""
    # 区位（如果 config 未提供，从摘要补充）
    loc_s = summaries.get("location", {})
    if not data.province and loc_s.get("province"):
        data.province = loc_s["province"]
    if not data.city and loc_s.get("city"):
        data.city = loc_s["city"]
    if not data.county and loc_s.get("county"):
        data.county = loc_s["county"]
    if not data.town and loc_s.get("town"):
        data.town = loc_s["town"]

    # 社会经济
    socio_s = summaries.get("socio_economic", {})
    if socio_s.get("registered_population") and not data.population_registered:
        data.population_registered = int(socio_s["registered_population"])
    if socio_s.get("resident_population") and not data.population_resident:
        data.population_resident = int(socio_s["resident_population"])
    if socio_s.get("households") and not data.population_household:
        data.population_household = int(socio_s["households"])

    # 土地利用
    land_s = summaries.get("land_use", {})
    if land_s.get("total_area_ha") and not data.total_area_ha:
        data.total_area_ha = float(land_s["total_area_ha"])
    if land_s.get("farmland_area_ha") and not data.farmland_ha:
        data.farmland_ha = float(land_s["farmland_area_ha"])
    if land_s.get("construction_area_ha") and not data.construction_land_ha:
        data.construction_land_ha = float(land_s["construction_area_ha"])
    if land_s.get("ecological_area_ha") and not data.ecological_land_ha:
        data.ecological_land_ha = float(land_s["ecological_area_ha"])
    if land_s.get("water_area_ha") and not data.water_ha:
        data.water_ha = float(land_s["water_area_ha"])
    if land_s.get("forest_coverage_rate") and not data.forest_coverage_pct:
        data.forest_coverage_pct = float(land_s["forest_coverage_rate"])

    # 自然环境（补充森林覆盖率）
    nat_s = summaries.get("natural_environment", {})
    if nat_s.get("forest_coverage_rate") and not data.forest_coverage_pct:
        data.forest_coverage_pct = float(nat_s["forest_coverage_rate"])

    # 建筑
    arch_s = summaries.get("architecture", {})
    if arch_s.get("total_buildings") and not data.building_count:
        data.building_count = int(arch_s["total_buildings"])
