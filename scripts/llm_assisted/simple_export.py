"""
Simple Export - 简化版规划文本导出

直接从 Layer3 Markdown 提取内容，按条文编号组织输出。
不使用 LLM，保留原始表格和列表结构。

核心功能：
1. 解析 Layer3 Markdown 结构
2. 按条文编号映射章节
3. Markdown 格式转换
4. 输出法定规划文本
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# ==========================================
# 章节映射规则
# ==========================================

ARTICLE_MAPPING = {
    # 第三章 规划内容
    "第九条_建设用地布局优化": [],  # 使用固定内容
    "第十条_村庄国土空间布局": ["空间结构规划"],
    "第十一条_生态保护修复": ["生态绿地规划"],
    "第十二条_耕地和永久基本农田保护": [],  # 使用固定内容
    "第十三条_历史文化传承与保护": ["历史文保规划", "历史文化保护规划"],
    "第十四条_产业发展空间安排": ["产业规划"],
    "第十五条_农村住房建设": ["居民点规划"],
    "第十六条_基础设施和公共服务设施建设": ["基础设施规划", "公共服务设施规划"],
    "第十七条_村庄安全和防灾减灾": ["防灾减灾规划", "防震减灾规划"],
    # 第四章 实施计划
    "第十八条_近期建设行动": ["建设项目库"],
}

# 中文数字映射
CHINESE_NUMBERS = [
    "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "二十一", "二十二"
]

# 条文标题映射（与参考文档一致）
ARTICLE_TITLES = {
    1: "规划背景",
    2: "规划原则",
    3: "规划任务",
    4: "规划依据",
    5: "规划范围",
    6: "规划期限",
    7: "村庄发展定位和目标",
    8: "规划指标",
    9: "建设用地布局优化",
    10: "村庄国土空间布局",
    11: "生态保护修复",
    12: "耕地和永久基本农田保护",
    13: "历史文化传承与保护",
    14: "产业发展空间安排",
    15: "农村住房建设",
    16: "基础设施和公共服务设施建设",
    17: "村庄安全和防灾减灾",
    18: "近期建设行动",
    19: "加强组织领导",
    20: "驻村编制规划",
    21: "严格用途管制",
    22: "加强监督检查",
}


@dataclass
class ExportResult:
    """导出结果"""
    success: bool
    markdown_path: str
    word_path: str = ""
    article_count: int = 0
    errors: List[str] = field(default_factory=list)


class Layer3Parser:
    """Layer3 Markdown 解析器"""

    def __init__(self, content: str):
        self.content = content
        self.chapters: Dict[str, str] = {}
        self._parse()

    def _parse(self):
        """解析 Markdown，按二级标题分割"""
        lines = self.content.split("\n")
        current_title = ""
        current_content: List[str] = []

        for line in lines:
            header_match = re.match(r"^##\s+(.+)$", line)
            if header_match:
                if current_title:
                    self.chapters[current_title] = "\n".join(current_content).strip()
                current_title = header_match.group(1).strip()
                current_content = []
            else:
                current_content.append(line)

        if current_title:
            self.chapters[current_title] = "\n".join(current_content).strip()

    def get_chapter(self, name: str) -> Optional[str]:
        """获取指定章节内容"""
        if name in self.chapters:
            return self.chapters[name]
        for title, content in self.chapters.items():
            if name in title or title in name:
                return content
        return None


class MarkdownTransformer:
    """Markdown 格式转换器"""

    def transform(self, content: str) -> str:
        """
        转换 Markdown 格式为法定条文格式

        转换规则：
        1. 删除元数据标题（### 规划内容、### 参考依据）
        2. 【xxx】转为 **xxx**
        3. 删除维度标识行
        4. 删除分隔线
        5. 删除引用块
        6. 保留表格
        """
        lines = content.split("\n")
        result_lines: List[str] = []
        skip_until_next_section = False
        in_table = False

        for line in lines:
            stripped = line.strip()

            # 检测表格
            if stripped.startswith("|"):
                in_table = True
            elif in_table and not stripped.startswith("|"):
                in_table = False

            # 跳过参考依据章节
            if stripped == "### 参考依据":
                skip_until_next_section = True
                continue

            if skip_until_next_section:
                if stripped.startswith("## ") or (stripped.startswith("### ") and stripped != "### 参考依据"):
                    skip_until_next_section = False
                else:
                    continue

            # 删除元数据标题
            if stripped == "### 规划内容":
                continue

            # 删除维度标识行
            if stripped.startswith("**维度标识**"):
                continue

            # 删除分隔线
            if stripped == "---":
                continue

            # 删除引用块（非表格区域）
            if not in_table and stripped.startswith(">"):
                continue

            # 处理 **xxx** 格式：删除加粗标记，保留文本
            line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)

            # 【xxx】转为普通文本
            line = re.sub(r"【(.+?)】", r"\1", line)

            result_lines.append(line)

        result = "\n".join(result_lines)
        result = re.sub(r"\n{3,}", "\n\n", result)

        return result.strip()


class PlanningDocumentBuilder:
    """法定规划文档构建器"""

    def __init__(self):
        self.transformer = MarkdownTransformer()

    def build(self, layer3_content: str, project_name: str = "金田村") -> str:
        """构建法定规划文档"""
        parser = Layer3Parser(layer3_content)
        sections: List[str] = []

        sections.append(f"# {project_name}规划文本")
        sections.append("")

        # 第一章 总则
        sections.extend(self._build_chapter_1())

        # 第二章 村庄发展目标
        sections.extend(self._build_chapter_2())

        # 第三章 规划内容（第9条到第17条）
        sections.append("## 第三章 规划内容")
        sections.append("")

        for article_num in range(9, 18):
            article_content = self._build_article(parser, article_num, chapter_num=3)
            sections.append(article_content)
            sections.append("")

        # 第四章 实施计划（第18条）
        sections.append("## 第四章 实施计划")
        sections.append("")

        article_content = self._build_article(parser, 18, chapter_num=4)
        sections.append(article_content)
        sections.append("")

        # 第五章 实施保障
        sections.extend(self._build_chapter_5())

        # 附件
        sections.extend(self._build_attachments())

        return "\n".join(sections)

    def _build_article(self, parser: Layer3Parser, article_num: int, chapter_num: int = 3) -> str:
        """构建单条条文

        Args:
            parser: Layer3解析器
            article_num: 条款编号
            chapter_num: 章节编号（用于表格编号）
        """
        article_title = f"第{CHINESE_NUMBERS[article_num-1]}条 {ARTICLE_TITLES[article_num]}"
        article_key = f"第{CHINESE_NUMBERS[article_num-1]}条_{ARTICLE_TITLES[article_num]}"

        source_chapters = ARTICLE_MAPPING.get(article_key, [])

        # 如果没有映射，返回固定内容或待补充
        if not source_chapters:
            fixed_content = self._get_fixed_article_content(article_num)
            if fixed_content:
                return f"{article_title}\n\n{fixed_content}"
            return f"{article_title}\n\n【待补充】"

        contents: List[str] = []
        for chapter_name in source_chapters:
            chapter_content = parser.get_chapter(chapter_name)
            if chapter_content:
                transformed = self.transformer.transform(chapter_content)
                if transformed:
                    contents.append(transformed)

        if not contents:
            fixed_content = self._get_fixed_article_content(article_num)
            if fixed_content:
                return f"{article_title}\n\n{fixed_content}"
            return f"{article_title}\n\n【待补充】"

        merged_content = "\n\n".join(contents)

        # 添加表格编号
        merged_content = self._add_table_numbering(merged_content, chapter_num)

        # 特殊处理：第18条只提取近期项目
        if article_num == 18:
            merged_content = self._extract_recent_projects(merged_content)

        return f"{article_title}\n\n{merged_content}"

    def _get_fixed_article_content(self, article_num: int) -> Optional[str]:
        """获取固定条款内容"""
        fixed_contents = {
            9: """根据《国土资源部办公厅关于印发村土地利用规划编制技术导则的通知》和《广东省村庄规划编制基本技术指南（试行）》的要求，结合金田村实际情况，对建设用地布局进行优化调整。

本次金田村拟调整地块4个，主要是为了落实金田村文化广场、公共服务设施及基础设施的建设。其中，调入地块3个，拟调整为景观与绿化用地、公共服务设施用地及基础设施用地；调出地块1个，位于田坑自然村北部，面积为0.0763公顷。""",
            12: """根据《梅州市平远县土地利用总体规划（2010-2020年）调整完善方案》，落实永久基本农田面积为81.43公顷，占村域总面积的3.46%。主要分布在村庄北部，分布在田坑、园寨等自然村。

永久基本农田一经划定，任何单位和个人不得改变或者占用。国家能源、交通、水利、军事设施等重点建设项目选址确实无法避开基本农田保护区，需要占用基本农田，涉及农用地转用的，必须报国务院批准。

规划至2035年，金田村范围内暂无永久基本农田整备区。规划对基本农田内的河道进行清淤梳理、砌筑生态河道；对金田村内13000多平方米基本农田进行整改平整。""",
        }
        return fixed_contents.get(article_num)

    def _add_table_numbering(self, content: str, chapter_num: int) -> str:
        """为表格添加编号"""
        lines = content.split('\n')
        result: List[str] = []
        table_count = 0
        in_table = False
        table_header = ""

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 检测表格开始
            if stripped.startswith('|') and '---' not in stripped:
                if not in_table:
                    in_table = True
                    table_count += 1
                    # 提取表头作为表名
                    table_header = stripped.replace('|', ' ').strip()
                    # 生成表格编号
                    result.append(f"表 {chapter_num}-{table_count} {table_header[:30]}...")
                    result.append("")
            elif in_table and not stripped.startswith('|'):
                in_table = False

            result.append(line)

        return '\n'.join(result)

    def _extract_recent_projects(self, content: str) -> str:
        """提取近期项目部分"""
        # 处理两种格式：带 ** 和不带 **
        recent_match = re.search(
            r"(?:\*\*)?近期项目(?:\*\*)?.*?(?=(?:\*\*)?中期项目(?:\*\*)?|(?:\*\*)?远期项目(?:\*\*)?|$)",
            content,
            re.DOTALL
        )
        if recent_match:
            return recent_match.group(0).strip()
        return content

    def _build_chapter_1(self) -> List[str]:
        """构建第一章 总则"""
        return [
            "## 第一章 总则",
            "",
            "第一条 规划背景",
            '为深入贯彻落实习近平总书记关于实施乡村振兴战略的重要论述，加快编制"多规合一"的实用性村庄规划，科学有序引导村庄规划建设，全面推进乡村振兴，根据《中共中央 国务院关于坚持农业农村优先发展做好"三农"工作的若干意见》、《广东省村庄规划全面优化提升三年行动计划》及《广东省村庄规划编制基本技术指南（试行）》的要求，特编制本规划，主要作为开展国土空间开发保护活动、实施国土空间用途管制、核发乡村建设项目规划许可、进行各项建设等的法定依据。',
            "",
            "第二条 规划原则",
            "（1）坚持以人为本，多元参与，尊重村民发展诉求，带动乡村共建共享；",
            "（2）坚持因地制宜，突出特色，务实发展特色产业，实现差异产业兴旺；",
            "（3）坚持经济可行，集约高效，统筹兼顾各类主体，协调高效使用资源；",
            "（4）坚持注重实用，通俗易懂，编制规划实用管用，制定乡约简洁易懂。",
            "",
            "第三条 规划任务",
            "统筹村庄发展目标、生态保护修复、耕地和永久基本农田保护、历史文化传承与保护、基础设施和基本公共服务设施布局、产业规划策略、农村住房布局、村庄安全和防灾减灾，明确规划近期实施项目。",
            "",
            "第四条 规划依据",
            "（1）国家政策文件依据",
            "1）《中华人民共和国土地管理法》（2019年修订）；",
            "2）《中华人民共和国城乡规划法》（2019年修订）；",
            "3）《中华人民共和国文物保护法》（2017年修订）；",
            "4）《中华人民共和国乡村振兴促进法》（2021）；",
            "5）《基本农田保护条例》（国务院令第257号）；",
            "6）《中共中央 国务院关于建立国土空间规划体系并监督实施的若干意见》（中发〔2019〕18号）；",
            "7）《中央农办 农业农村部 自然资源部 国家发展改革委 财政部关于统筹推进村庄规划工作的意见》（农规发〔2019〕1号）；",
            "8）《自然资源部办公厅关于加强村庄规划促进乡村振兴的通知》（自然资办发〔2019〕35号）；",
            "9）《国土资源部办公厅关于印发村土地利用规划编制技术导则的通知》（国土资厅发〔2017〕26号）；",
            "10）《关于印发<生态保护红线划定指南>的通知》（环办生态〔2017〕48号）。",
            "",
            "（2）省、市（县）政策文件依据",
            "1）《广东省土地利用总体规划条例》（2009年）；",
            '2）《广东省推进农业农村现代化"十四五"规划》；',
            "3）《广东省人民政府办公厅关于改善农村人居环境的意见》；",
            "4）《农村人居环境整治提升五年行动方案（2021-2025年）》；",
            "5）《中共广东省委、广东省人民政府关于推进小城镇健康发展的意见》；",
            "6）《梅州市乡村振兴示范带建设实施方案》；",
            "7）《平远县全面推进农房管控和乡村风貌提升实施方案》。",
            "",
            "（3）上层次规划依据",
            "1）《梅州市城市总体规划（2015-2030年）》；",
            "2）《梅江·韩江绿色健康文化产业带发展规划（2016-2030）》；",
            "3）《梅州市平远县城市总体规划（2012-2020）》；",
            "4）《平远县域乡村建设规划（2017-2035年）》；",
            "5）《平远县生态控制线划定专项规划》；",
            "6）《平远县域城镇体系规划》（2001-2020年）；",
            "7）《平远县全面推进农房管控和乡村风貌提升实施方案》；",
            "8）《平远县泗水镇总体规划（2011-2030）》。",
            "",
            "第五条 规划范围",
            "本次规划范围为金田村村域全部国土空间，总面积2352.89公顷，包括园寨、田坑、社前、分水、清明、塘笃、长塘、炉池、肩丰、营仔、新山、和黄竹12个自然村。",
            "",
            "第六条 规划期限",
            "规划期限为2022-2035年，近期到2025年，规划基期年为2022年，与基本实现社会主义现代化期限保持一致。",
            "",
        ]

    def _build_chapter_2(self) -> List[str]:
        """构建第二章 村庄发展目标"""
        return [
            "## 第二章 村庄发展目标",
            "",
            "第七条 村庄发展定位和目标",
            "根据上位规划以及村庄未来发展需求，确定金田村为集聚提升类村庄，应立足现有农田、生态、村落等乡村资源，依托现有特色种植业和良好的生态环境，按照上位规划要求，保持金田村的生态空间保持总量不减，耕地质量有所提升，永久基本农田总量不变。村庄以生态保护为基底，南药产业为抓手，林下经济为推手，乡村风貌改善为补充，将金田村建设成以特色南药为核心，集林下经济、乡村农旅等功能于一体的特色南药综合开发示范村。",
            "",
            "第八条 规划指标",
            "在不突破土地利用总体规划确定的2020年建设用地规模和耕地保有量、不突破生态保护红线和永久基本农田保护红线、不突破土地利用总体规划和城镇规划确定的禁止建设区和强制管制区等前提下，合理确定各项规划指标。",
            "",
            "表 2-1 规划指标表",
            "",
            "| 规划指标体系 | 2022年 | 2035年 | 属性 |",
            "| :--- | :--- | :--- | :--- |",
            "| 户籍人口规模（人） | 1403 | - | 预期性 |",
            "| 常住人口规模（人） | 500 | 500 | 预期性 |",
            "| 耕地保有量（公顷） | 85.42 | 127.18 | 约束性 |",
            "| 永久基本农田保护面积（公顷） | 81.43 | 81.43 | 约束性 |",
            "| 生态保护红线面积（公顷） | 367.68 | 367.68 | 约束性 |",
            "| 村庄建设用地规模（公顷） | 30.17 | 35.29 | 约束性 |",
            "| 林地保有量（公顷） | 2117.6 | 2117.6 | 预期性 |",
            "| 森林覆盖率（%） | 90 | ≥90 | 预期性 |",
            "",
        ]

    def _build_chapter_5(self) -> List[str]:
        """构建第五章 实施保障"""
        return [
            "## 第五章 实施保障",
            "",
            "第十九条 加强组织领导",
            "建立健全规划实施组织领导机制，成立村庄规划实施领导小组，统筹协调规划实施各项工作。明确各部门职责分工，形成工作合力。",
            "",
            "第二十条 驻村编制规划",
            "坚持驻村编制，深入调查研究，充分听取村民意见，确保规划符合村庄实际、体现村民意愿。",
            "",
            "第二十一条 严格用途管制",
            "严格执行国土空间用途管制制度，按照规划确定的用地性质和管控要求，规范各类建设活动。",
            "",
            "第二十二条 加强监督检查",
            "建立规划实施监督检查机制，定期开展规划执行情况检查。接受上级主管部门和村民的监督，确保规划有效实施。",
            "",
        ]

    def _build_attachments(self) -> List[str]:
        """构建附件"""
        return [
            "## 附件：村民参与报告",
            "",
            "### 附件1 规划前期意见征询",
            "规划编制前期，通过入户访谈、问卷调查等方式，广泛征求村民对村庄发展的意见建议。",
            "",
            "### 附件2 规划初步方案意见征询",
            "规划初步方案形成后，组织村民代表会议，对方案内容进行讨论和修改。",
            "",
            "### 附件3 规划方案批前公示",
            "规划方案在批前进行公示，接受村民和社会公众的监督。",
            "",
            "### 附件4 村民代表大会意见征询",
            "规划方案提交村民代表大会审议，充分听取村民代表的意见。",
            "",
            "### 附件5 泗水镇政府意见征询",
            "规划方案报送泗水镇政府审核，征求镇政府意见。",
            "",
        ]


def export_planning_document(
    layer3_path: str,
    output_dir: str = "output/planning_docs",
    project_name: str = "金田村"
) -> ExportResult:
    """导出法定规划文档"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        with open(layer3_path, "r", encoding="utf-8") as f:
            layer3_content = f.read()
    except Exception as e:
        return ExportResult(
            success=False,
            markdown_path="",
            errors=[f"读取 Layer3 文件失败: {e}"]
        )

    builder = PlanningDocumentBuilder()
    markdown_content = builder.build(layer3_content, project_name)

    markdown_path = output_path / f"{project_name}_规划文本.md"
    with open(markdown_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    article_count = len(re.findall(r"第[一二三四五六七八九十]+条", markdown_content))

    return ExportResult(
        success=True,
        markdown_path=str(markdown_path),
        article_count=article_count
    )


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="导出法定规划文档")
    parser.add_argument("--layer3", default="docs/planning_export/layer3_详细规划.md", help="Layer3 文件路径")
    parser.add_argument("--output", default="docs/planning_export/output", help="输出目录")
    parser.add_argument("--project", default="金田村", help="项目名称")

    args = parser.parse_args()

    print(f"[SimpleExport] 开始导出规划文档...")
    print(f"  Layer3: {args.layer3}")
    print(f"  输出目录: {args.output}")

    result = export_planning_document(
        layer3_path=args.layer3,
        output_dir=args.output,
        project_name=args.project
    )

    if result.success:
        print(f"[SimpleExport] 导出成功!")
        print(f"  Markdown: {result.markdown_path}")
        print(f"  条文数量: {result.article_count}")
    else:
        print(f"[SimpleExport] 导出失败:")
        for error in result.errors:
            print(f"  - {error}")


if __name__ == "__main__":
    main()


__all__ = [
    "export_planning_document",
    "PlanningDocumentBuilder",
    "Layer3Parser",
    "MarkdownTransformer",
    "ExportResult",
]