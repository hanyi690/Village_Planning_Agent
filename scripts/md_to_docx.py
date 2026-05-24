"""
将规划文本 MD 转换为 DOCX
"""
from docx import Document
from docx.shared import Pt, Inches, Cm, Twips
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import re
from pathlib import Path


def set_run_font(run, font_name='宋体', font_size=12):
    """设置运行字体"""
    run.font.name = font_name
    run.font.size = Pt(font_size)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)


def set_cell_font(cell, font_name='宋体', font_size=10.5):
    """设置单元格字体"""
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.font.name = font_name
            run.font.size = Pt(font_size)
            run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)


def create_docx_from_md(md_path: Path, docx_path: Path):
    """从 Markdown 创建 DOCX"""
    content = md_path.read_text(encoding='utf-8')

    doc = Document()

    # 设置页面边距
    sections = doc.sections
    for section in sections:
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)

    # 添加标题
    title = doc.add_heading('村庄规划规划文本', level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 解析并添加内容
    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 跳过主标题
        if line.startswith('# 村庄规划'):
            i += 1
            continue

        # 章标题 (## 第一章 ...)
        if line.startswith('## '):
            text = line[3:].strip()
            h = doc.add_heading(text, level=1)
            i += 1
            continue

        # 节标题（条）(### 第一条 ...)
        if line.startswith('### '):
            text = line[4:].strip()
            h = doc.add_heading(text, level=2)
            i += 1
            continue

        # 表格处理
        if line.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1

            # 解析表格
            if len(table_lines) >= 2:
                # 解析表头
                headers = [c.strip() for c in table_lines[0].split('|') if c.strip()]

                # 跳过分隔行
                data_start = 1
                if len(table_lines) > 1 and re.match(r'^\|[\s\-:]+\|', table_lines[1]):
                    data_start = 2

                # 解析数据行
                rows = []
                for tl in table_lines[data_start:]:
                    cells = [c.strip() for c in tl.split('|') if c.strip()]
                    if cells:
                        rows.append(cells)

                # 创建表格
                if headers and rows:
                    table = doc.add_table(rows=len(rows) + 1, cols=len(headers))
                    table.style = 'Table Grid'
                    table.alignment = WD_TABLE_ALIGNMENT.CENTER

                    # 添加表头
                    for j, header in enumerate(headers):
                        cell = table.rows[0].cells[j]
                        cell.text = header
                        for paragraph in cell.paragraphs:
                            for run in paragraph.runs:
                                run.bold = True
                                run.font.size = Pt(10.5)

                    # 添加数据行
                    for row_idx, row_data in enumerate(rows):
                        for col_idx, cell_data in enumerate(row_data):
                            if col_idx < len(headers):
                                table.rows[row_idx + 1].cells[col_idx].text = cell_data

                    doc.add_paragraph('')  # 表格后空行
            continue

        # 表格编号行（如 "表 3-1 土地利用结构调整表"）
        if re.match(r'^表\s*\d+-\d+', line):
            p = doc.add_paragraph()
            run = p.add_run(line)
            run.font.size = Pt(10)
            run.italic = True
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            continue

        # 普通段落
        if line:
            p = doc.add_paragraph()
            # 处理段落缩进
            p.paragraph_format.first_line_indent = Cm(0.74)  # 两个字符缩进
            run = p.add_run(line)
            set_run_font(run, '宋体', 12)

        i += 1

    # 保存
    doc.save(str(docx_path))
    print(f'DOCX 已保存: {docx_path}')
    return docx_path


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        # 默认路径
        md_path = Path('output/experiments/baseline/baseline_570463be/村庄规划_规划文本.md')
        docx_path = md_path.with_suffix('.docx')
    else:
        md_path = Path(sys.argv[1])
        docx_path = Path(sys.argv[2]) if len(sys.argv) > 2 else md_path.with_suffix('.docx')

    create_docx_from_md(md_path, docx_path)
