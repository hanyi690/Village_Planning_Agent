"""
将规划文本 MD 转换为 DOCX

格式规范参照: 平远县泗水镇金田村村庄规划（2022-2035年）文本.docx
"""
import sys
import re
from pathlib import Path

from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

# Import shared style definitions
_project_root = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from backend.app.services.modules.planning_text.docx_styles import (
    setup_document_styles,
    setup_page_margins,
    fix_heading_fonts,
    set_run_font,
    set_cell_font,
    CN_FONT,
    EN_FONT,
    CN_FONT_TABLE_TITLE,
)


def create_docx_from_md(md_path: Path, docx_path: Path):
    """从 Markdown 创建 DOCX"""
    content = md_path.read_text(encoding='utf-8')

    doc = Document()

    # 设置页边距和文档样式
    setup_page_margins(doc)
    setup_document_styles(doc)

    # 解析并添加内容
    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 跳过主标题（# 村庄规划...）
        if line.startswith('# ') and not line.startswith('## '):
            text = line[2:].strip()
            h = doc.add_heading(text, level=0)
            fix_heading_fonts(h)
            i += 1
            continue

        # 章标题 (## 第一章 ...)
        if line.startswith('## '):
            text = line[3:].strip()
            h = doc.add_heading(text, level=1)
            fix_heading_fonts(h)
            # Heading 2 may inherit bold from theme, force run.bold = True
            for run in h.runs:
                run.bold = True
            i += 1
            continue

        # 条标题 (### 第一条 ...)
        if line.startswith('### '):
            text = line[4:].strip()
            h = doc.add_heading(text, level=2)
            fix_heading_fonts(h)
            # Heading 2 should NOT be bold per reference report
            for run in h.runs:
                run.bold = False
            i += 1
            continue

        # 小标题 (#### ...)
        if line.startswith('#### '):
            text = line[5:].strip()
            h = doc.add_heading(text, level=3)
            fix_heading_fonts(h)
            for run in h.runs:
                run.bold = True
            i += 1
            continue

        # 表格编号行（如 "表 3-1 土地利用结构调整表"）
        if re.match(r'^表\s*\d+-\d+', line):
            p = doc.add_paragraph()
            run = p.add_run(line)
            set_run_font(run, cn_font=CN_FONT_TABLE_TITLE, font_size=10.5)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(0)
            i += 1
            continue

        # 图编号行（如 "图 1-1 规划范围"）
        if re.match(r'^图\s*\d+-\d+', line):
            p = doc.add_paragraph()
            run = p.add_run(line)
            set_run_font(run, cn_font=CN_FONT_TABLE_TITLE, font_size=10.5)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            i += 1
            continue

        # 单位行（如 "单位：公顷"）
        if line.startswith('单位') and ('：' in line or ':' in line):
            p = doc.add_paragraph()
            run = p.add_run(line)
            set_run_font(run, cn_font=CN_FONT, font_size=12)
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p.paragraph_format.first_line_indent = Pt(0)
            i += 1
            continue

        # 表格处理
        if line.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1

            if len(table_lines) >= 2:
                headers = [c.strip() for c in table_lines[0].split('|') if c.strip()]

                data_start = 1
                if len(table_lines) > 1 and re.match(r'^\|[\s\-:]+\|', table_lines[1]):
                    data_start = 2

                rows = []
                for tl in table_lines[data_start:]:
                    cells = [c.strip() for c in tl.split('|') if c.strip()]
                    if cells:
                        rows.append(cells)

                if headers and rows:
                    table = doc.add_table(rows=len(rows) + 1, cols=len(headers))
                    table.style = 'Table Grid'
                    table.alignment = WD_TABLE_ALIGNMENT.CENTER

                    # 表头：仿宋 ~11pt Bold Center
                    for j, header in enumerate(headers):
                        cell = table.rows[0].cells[j]
                        cell.text = ''
                        p = cell.paragraphs[0]
                        run = p.add_run(header)
                        set_run_font(run, cn_font=CN_FONT, font_size=11, bold=True)

                    # 数据行：仿宋 10.5pt Center
                    for row_idx, row_data in enumerate(rows):
                        for col_idx, cell_data in enumerate(row_data):
                            if col_idx < len(headers):
                                cell = table.rows[row_idx + 1].cells[col_idx]
                                cell.text = ''
                                p = cell.paragraphs[0]
                                run = p.add_run(cell_data)
                                set_run_font(run, cn_font=CN_FONT, font_size=10.5)

            continue

        # 普通段落
        if line:
            p = doc.add_paragraph()
            # 处理 **bold** 内联格式
            parts = re.split(r'\*\*(.+?)\*\*', line)
            for idx, part in enumerate(parts):
                if idx % 2 == 1:  # 加粗内容
                    run = p.add_run(part)
                    run.bold = True
                    set_run_font(run, bold=True)
                elif part:  # 普通文本
                    run = p.add_run(part)
                    # Font inherits from Normal style via setup_document_styles

        i += 1

    # 保存
    doc.save(str(docx_path))
    print(f'DOCX 已保存: {docx_path}')
    return docx_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        md_path = Path('output/experiments/baseline/baseline_570463be/村庄规划_规划文本.md')
        docx_path = md_path.with_suffix('.docx')
    else:
        md_path = Path(sys.argv[1])
        docx_path = Path(sys.argv[2]) if len(sys.argv) > 2 else md_path.with_suffix('.docx')

    create_docx_from_md(md_path, docx_path)
