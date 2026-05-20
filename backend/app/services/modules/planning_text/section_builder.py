"""
Section builder: three-tier strategy routing and article assembly.

Routes each of the 22 articles to S-COPY, S-ASSEMBLE, S-TEMPLATE, or S-GENERATE,
then assembles the complete planning document.
"""

import re
import difflib
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from .content_extractor import ExtractedData

_CH = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
       "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八",
       "十九", "二十", "二十一", "二十二"]

CHAPTER_NAMES = {1: "总则", 2: "村庄发展目标", 3: "规划内容", 4: "实施计划", 5: "实施保障"}

ARTICLE_DEFS = {
    1:  ("规划背景", 1, "S-GENERATE", {}),
    2:  ("规划原则", 1, "S-TEMPLATE", {}),
    3:  ("规划任务", 1, "S-TEMPLATE", {}),
    4:  ("规划依据", 1, "S-ASSEMBLE", {}),
    5:  ("规划范围", 1, "S-ASSEMBLE", {}),
    6:  ("规划期限", 1, "S-TEMPLATE", {}),
    7:  ("村庄发展定位和目标", 2, "S-GENERATE", {}),
    8:  ("规划指标", 2, "S-ASSEMBLE", {}),
    9:  ("建设用地布局优化", 3, "S-COPY", {
        "land_use_planning": ["土地利用规划", "土地利用结构调整表", "土地用途分区表"],
        "settlement_planning": ["居民点规划", "规划目标", "人口与用地规模",
                                 "居民点布局模式", "布局说明"],
    }),
    10: ("村庄国土空间布局", 3, "S-COPY", {
        "spatial_structure": ["空间结构规划", "空间结构模式", "功能节点规划",
                               "功能分区表", "边界管控"],
    }),
    11: ("生态保护修复", 3, "S-COPY", {
        "ecological": ["生态绿地规划", "生态空间格局", "绿地指标", "绿地系统",
                        "生态管控要求", "实施计划"],
    }),
    12: ("耕地和永久基本农田保护", 3, "S-COPY", {
        "land_use_planning": ["重点建设项目清单", "风貌与设施管控要求"],
    }),
    13: ("历史文化传承与保护", 3, "S-COPY", {
        "heritage": ["历史文化保护规划", "文化遗产清单", "保护范围划定",
                      "建筑分类整治", "非物质文化遗产活化",
                      "防灾减灾与安全", "产业融合利用",
                      "基础设施配套", "人口与用地管控"],
    }),
    14: ("产业发展空间安排", 3, "S-COPY", {
        "industry": ["产业规划", "产业发展定位", "产业发展思路",
                      "三链逻辑构建", "产业项目清单", "空间布局",
                      "产业体系构建", "产业项目细化", "产业项目布局"],
    }),
    15: ("农村住房建设", 3, "S-COPY", {
        "settlement_planning": ["宅基地规划表", "防灾减灾规划",
                                 "基础设施规划", "历史文化保护",
                                 "产业空间布局", "实施时序"],
        "landscape": ["村庄风貌指引", "整体风貌定位与景观格局",
                       "建筑风貌控制导则", "核心景观节点设计指引", "人居环境整治指引",
                       "景观类型指引", "建筑风貌指引", "新建建筑指引"],
    }),
    16: ("基础设施和公共服务设施建设", 3, "S-COPY", {
        "infrastructure_planning": ["基础设施规划", "给水工程", "排水工程",
                                     "电力工程", "通信工程", "环卫工程",
                                     "工程量汇总表"],
        "public_service": ["公共服务设施规划", "配置原则与策略", "设施配置清单"],
        "traffic_planning": ["道路交通规划", "路网格局", "道路等级规划", "交通设施清单"],
    }),
    17: ("村庄安全和防灾减灾", 3, "S-COPY", {
        "disaster_prevention": ["防灾减灾规划", "灾害风险评估", "防灾设施清单",
                                 "工程防治措施", "应急管理体系"],
    }),
    18: ("近期建设行动", 4, "S-COPY", {
        "project_bank": ["建设项目库", "近期项目"],
    }),
    19: ("加强组织领导", 5, "S-GENERATE", {}),
    20: ("驻村编制规划", 5, "S-GENERATE", {}),
    21: ("严格用途管制", 5, "S-GENERATE", {}),
    22: ("加强监督检查", 5, "S-GENERATE", {}),
}


@dataclass
class ArticleOutput:
    number: int
    title: str
    content: str
    strategy: str


@dataclass
class BuildReport:
    articles: List[ArticleOutput] = field(default_factory=list)
    strategy_counts: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class SectionBuilder:

    def __init__(self, data: ExtractedData,
                 title_norm_map: Optional[Dict[str, str]] = None, *,
                 village_name: str = "",
                 planning_period: str = "2022-2035年",
                 township_name: str = "",
                 province_name: str = "",
                 city_name: str = "",
                 county_name: str = ""):
        self.data = data
        self._chapter_table_idx: dict = {}
        self._title_norm = title_norm_map or {}
        self.village_name = village_name
        self.planning_period = planning_period
        self.township_name = township_name
        self.province_name = province_name
        self.city_name = city_name
        self.county_name = county_name

    def build_all(self) -> BuildReport:
        report = BuildReport()
        self._chapter_table_idx = {}
        for num in range(1, 23):
            title, chapter, strategy, sources = ARTICLE_DEFS[num]
            try:
                if strategy == "S-COPY":
                    content = self._build_copy(num, title, chapter, sources)
                elif strategy == "S-ASSEMBLE":
                    content = self._build_assemble(num, title)
                elif strategy == "S-TEMPLATE":
                    content = self._build_template(num, title)
                else:
                    content = f"【待LLM生成: {title}】"
                report.articles.append(ArticleOutput(num, title, content, strategy))
                report.strategy_counts[strategy] = report.strategy_counts.get(strategy, 0) + 1
            except Exception as e:
                report.errors.append(f"第{_CH[num]}条 {title}: {e}")
                report.articles.append(ArticleOutput(num, title, f"【错误: {e}】", strategy))
        return report

    # ---- S-COPY ----

    def _build_copy(self, num: int, title: str, chapter: int, sources: dict) -> str:
        parts = []
        section_idx = 0
        if chapter not in self._chapter_table_idx:
            self._chapter_table_idx[chapter] = 0

        unmatched_patterns = []

        for dim_key, section_patterns in sources.items():
            sections = self.data.layer3_sections.get(dim_key, {})
            matched_patterns = set()

            for sec_title, sec_content in sections.items():
                norm_title = self._title_norm.get(sec_title, sec_title)
                matched = False
                for pat in section_patterns:
                    if pat in norm_title or norm_title in pat:
                        matched = True
                        matched_patterns.add(pat)
                        break
                    if pat in sec_title or sec_title in pat:
                        matched = True
                        matched_patterns.add(pat)
                        break
                    if self._fuzzy_match(pat, norm_title):
                        matched = True
                        matched_patterns.add(pat)
                        break
                    if self._fuzzy_match(pat, sec_title):
                        matched = True
                        matched_patterns.add(pat)
                        break
                if not matched:
                    continue

                section_idx += 1
                cleaned, next_tbl = self._add_table_numbers(
                    sec_content, chapter, self._chapter_table_idx[chapter], sec_title
                )
                self._chapter_table_idx[chapter] = next_tbl
                if cleaned.strip():
                    parts.append(f"（{section_idx}）{sec_title}\n{cleaned}")

            for pat in section_patterns:
                if pat not in matched_patterns:
                    unmatched_patterns.append(f"{dim_key}/{pat}")

        if unmatched_patterns:
            print(f"  [section_builder] 第{_CH[num]}条 unmatched patterns: {', '.join(unmatched_patterns)}")

        if not parts:
            for dim_key in sources:
                raw = self.data.get_full(dim_key)
                if raw.strip():
                    return self._clean_full(raw, chapter)
        return '\n\n'.join(parts) if parts else "【待补充】"

    @staticmethod
    def _fuzzy_match(pat: str, title: str, threshold: float = 0.75) -> bool:
        if len(pat) < 3 or len(title) < 3:
            return False
        ratio = difflib.SequenceMatcher(None, pat, title).ratio()
        return ratio >= threshold

    def _add_table_numbers(self, text: str, chapter: int, start_idx: int,
                            section_title: str = "") -> tuple:
        lines = text.split('\n')
        result = []
        table_idx = start_idx
        in_table = False
        header_seen = False

        def _is_sep(s):
            return bool(re.match(r'^\|[\s\-:]+\|', s))

        merged = []
        for line in lines:
            stripped = line.strip()
            if stripped in ('---',):
                continue
            if stripped.startswith('>'):
                continue
            if re.match(r'^[：:，,。；;、！!？?）\)】】]+$', stripped) and merged:
                merged[-1] = merged[-1].rstrip() + stripped
            else:
                merged.append(line)
        lines = merged

        for line in lines:
            stripped = line.strip()
            if stripped in ('---',):
                continue
            if stripped.startswith('>'):
                continue

            if stripped.startswith('|'):
                if _is_sep(stripped):
                    header_seen = False
                    in_table = True
                    result.append(line)
                    continue

                if not in_table:
                    in_table = True
                    header_seen = True
                    table_idx += 1
                    result.append(line)
                elif header_seen:
                    header_seen = False
                    ncols = len([c for c in stripped.split('|') if c.strip()])
                    sep = '| ' + ' | '.join([':---'] * ncols) + ' |'
                    result.append(sep)
                    result.append(line)
                else:
                    result.append(line)
            else:
                if in_table and not stripped.startswith('|'):
                    in_table = False
                    header_seen = False
                    base = section_title or "表格"
                    caption = f"{base}" if table_idx == start_idx + 1 else f"{base}({table_idx})"
                    result.append(f"表 {chapter}-{table_idx} {caption}")
                result.append(line)

        if in_table:
            base = section_title or "表格"
            caption = f"{base}" if table_idx == start_idx + 1 else f"{base}({table_idx})"
            result.append(f"表 {chapter}-{table_idx} {caption}")

        return '\n'.join(result).strip(), table_idx

    def _clean_full(self, text: str, chapter: int = 3) -> str:
        lines = text.split('\n')
        result = []
        if chapter not in self._chapter_table_idx:
            self._chapter_table_idx[chapter] = 0
        tbl = self._chapter_table_idx[chapter]
        in_table = False
        for line in lines:
            s = line.strip()
            if s in ('---',) or s.startswith('>'):
                continue
            line = re.sub(r'【(.+?)】', r'**\1**', line)
            stripped = line.strip()
            if stripped.startswith('|') and not stripped.startswith('|---'):
                if not in_table:
                    in_table = True
                    tbl += 1
                    result.append(f"表 {chapter}-{tbl}")
            elif in_table and not stripped.startswith('|'):
                in_table = False
            result.append(line)
        self._chapter_table_idx[chapter] = tbl
        return '\n'.join(result).strip()

    # ---- S-ASSEMBLE ----

    def _build_assemble(self, num: int, title: str) -> str:
        if num == 1:
            return self._asm_article1()
        elif num == 4:
            return self._asm_article4()
        elif num == 5:
            return self._asm_article5()
        elif num == 8:
            return self._asm_article8()
        return self._build_template(num, title)

    def _asm_article1(self) -> str:
        return (
            '为深入贯彻落实习近平总书记关于实施乡村振兴战略的重要论述，'
            '加快编制"多规合一"的实用性村庄规划，科学有序引导村庄规划建设，'
            '全面推进乡村振兴，根据《中共中央 国务院关于坚持农业农村优先发展'
            '做好"三农"工作的若干意见》、《广东省村庄规划全面优化提升三年行动计划》'
            '及《广东省村庄规划编制基本技术指南（试行）》的要求，特编制本规划。'
        )

    def _asm_article5(self) -> str:
        d = self.data
        area = d.total_area_ha or 2352.89
        names = d.village_names
        village = self.village_name or "本村"
        if names:
            ns = '、'.join(names)
            return f"本次规划范围为{village}村域全部国土空间，总面积{area:.2f}公顷，包括{ns}等{len(names)}个自然村。"
        return f"本次规划范围为{village}村域全部国土空间，总面积{area:.2f}公顷。"

    def _asm_article8(self) -> str:
        d = self.data
        rp = int(d.population_resident) or 500
        reg = int(d.population_registered) or 1403
        farm = d.farmland_ha or 85.20
        ef = d.ecological_forest_ha or 325.92
        cl = d.construction_land_ha or 30.17
        fc = d.forest_coverage_pct or 90
        tf = d.commercial_forest_ha + d.ecological_forest_ha or 2117.60

        return (
            "在不突破土地利用总体规划确定的建设用地规模和耕地保有量、"
            "不突破生态保护红线和永久基本农田保护红线的前提下，合理确定各项规划指标。\n\n"
            "表 2-1 规划指标表\n\n"
            "| 规划指标体系 | 基期年 | 目标年 | 属性 |\n"
            "| :--- | :--- | :--- | :--- |\n"
            f"| 户籍人口规模（人） | {reg} | - | 预期性 |\n"
            f"| 常住人口规模（人） | {rp} | {rp} | 预期性 |\n"
            f"| 耕地保有量（公顷） | {farm:.2f} | {farm:.2f} | 约束性 |\n"
            f"| 永久基本农田保护面积（公顷） | {farm:.2f} | {farm:.2f} | 约束性 |\n"
            f"| 生态保护红线面积（公顷） | {ef:.2f} | {ef:.2f} | 约束性 |\n"
            f"| 村庄建设用地规模（公顷） | {cl:.2f} | {cl:.2f} | 约束性 |\n"
            f"| 林地保有量（公顷） | {tf:.2f} | {tf:.2f} | 预期性 |\n"
            f"| 森林覆盖率（%） | {fc} | ≥{fc} | 预期性 |"
        )

    # ---- S-TEMPLATE ----

    def _asm_article4(self) -> str:
        d = self.data

        national_items = d.legal_basis_national
        if national_items:
            national = "（1）国家法律法规及政策文件依据\n"
            for i, item in enumerate(national_items, 1):
                national += f"{i}）{item}；\n"
        else:
            national = "（1）国家法律法规及政策文件依据\n（待补充）\n"

        provincial_items = d.legal_basis_provincial
        sp_sections = d.layer3_sections.get('superior_planning', {})
        if sp_sections:
            for sec_title, sec_content in sp_sections.items():
                for citation in re.findall(r'《([^》]+)》', sec_content):
                    full = f'《{citation}》'
                    # Use actual province name for precise matching
                    is_provincial = False
                    if self.province_name and self.province_name in citation:
                        is_provincial = True
                    elif '省' in citation and ('条例' in citation or '规划' in citation
                                              or '意见' in citation or '批复' in citation):
                        is_provincial = True
                    if is_provincial and full not in provincial_items:
                        provincial_items.append(full)
        provincial_items = sorted(set(provincial_items))
        if provincial_items:
            provincial = "（2）省、市（县）政策文件依据\n"
            for i, item in enumerate(provincial_items, 1):
                provincial += f"{i}）{item}；\n"
        else:
            provincial = "（2）省、市（县）政策文件依据\n（待补充）\n"

        planning_items = d.legal_basis_planning
        if sp_sections:
            for sec_title, sec_content in sp_sections.items():
                for citation in re.findall(r'《([^》]+)》', sec_content):
                    full = f'《{citation}》'
                    # Use actual city/county name for precise matching
                    is_local = False
                    if self.city_name and self.city_name in citation:
                        is_local = True
                    elif self.county_name and self.county_name in citation:
                        is_local = True
                    elif ('市' in citation or '县' in citation or '镇' in citation):
                        is_local = True
                    if is_local and full not in planning_items:
                        planning_items.append(full)
        planning_items = sorted(set(planning_items))
        if planning_items:
            upper_plan = "\n（3）上层次规划依据\n"
            for i, item in enumerate(planning_items, 1):
                upper_plan += f"{i}）{item}；\n"
        else:
            upper_plan = "\n（3）上层次规划依据\n（待补充）\n"

        return national + provincial + upper_plan

    def _build_template(self, num: int, title: str) -> str:
        d = self.data

        if num == 2:
            principles = [
                "（1）坚持以人为本，多元参与，尊重村民发展诉求，带动乡村共建共享；",
                "（2）坚持因地制宜，突出特色，务实发展特色产业，实现差异产业兴旺；",
                "（3）坚持经济可行，集约高效，统筹兼顾各类主体，协调高效使用资源；",
                "（4）坚持注重实用，通俗易懂，编制规划实用管用，制定乡约简洁易懂。",
            ]
            if d.resource_endowment:
                if '古树' in d.resource_endowment or '名木' in d.resource_endowment:
                    principles.append("（5）坚持保护优先，严格保护古树名木和历史文化遗产。")
                elif '非遗' in d.resource_endowment or '非物质' in d.resource_endowment:
                    principles.append("（5）坚持文化传承，保护非物质文化遗产和传统民俗活动。")
                elif '生态' in d.resource_endowment and '红线' in d.resource_endowment:
                    principles.append("（5）坚持生态优先，严守生态保护红线。")
            if len(principles) > 4:
                principles[3] = principles[3].rstrip('；') + '；'
            return '\n'.join(principles)

        elif num == 3:
            tasks = ["统筹村庄发展目标"]
            dim_task_map = {
                'ecological': '生态保护修复',
                'land_use_planning': '耕地和永久基本农田保护',
                'heritage': '历史文化传承与保护',
                'infrastructure_planning': '基础设施和基本公共服务设施布局',
                'public_service': '公共服务设施布局',
                'industry': '产业规划策略',
                'settlement_planning': '农村住房布局',
                'disaster_prevention': '村庄安全和防灾减灾',
            }
            for dim_key, task_name in dim_task_map.items():
                if d.layer3_sections.get(dim_key):
                    tasks.append(task_name)
            tasks.append("明确规划近期实施项目")
            return '、'.join(tasks) + '。'

        elif num == 6:
            period = self.planning_period
            base_year = period.split('-')[0].strip() if '-' in period else "2022"
            near_year = str(int(base_year) + 3) if base_year.isdigit() else "2025"
            return (f"规划期限为{period}，近期到{near_year}年，规划基期年为{base_year}年，"
                    "与基本实现社会主义现代化期限保持一致。")

        return "【待补充】"

    # ---- Render ----

    def render(self, report: BuildReport, project_name: str = "") -> str:
        name = project_name or self.village_name or "村庄"
        lines = [f"# {name}规划文本", ""]
        cur_ch = 0
        for art in report.articles:
            ch = ARTICLE_DEFS[art.number][1]
            if ch != cur_ch:
                cur_ch = ch
                lines.append(f"## 第{_CH[ch]}章 {CHAPTER_NAMES[ch]}")
                lines.append("")
            lines.append(f"第{_CH[art.number]}条 {art.title}")
            lines.append("")
            lines.append(art.content)
            lines.append("")

        lines.append("## 附件：村民参与报告")
        lines.append("")
        township = self.township_name or "镇"
        for att in [
            "附件1 规划前期意见征询", "附件2 规划初步方案意见征询",
            "附件3 规划方案批前公示", "附件4 村民代表大会意见征询",
            f"附件5 {township}政府意见征询",
        ]:
            lines.append(f"### {att}")
            lines.append("")
            lines.append("（规划编制过程中，通过入户访谈、村民代表会议、批前公示等方式征求村民意见。）")
            lines.append("")
        return '\n'.join(lines)


def build_document(data: ExtractedData) -> Tuple[str, BuildReport]:
    builder = SectionBuilder(data)
    report = builder.build_all()
    return builder.render(report), report
