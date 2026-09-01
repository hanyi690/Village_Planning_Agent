from pathlib import Path

from docx import Document


path = Path("F:/project/Village_Planning_Agent/docs/reports-weekly/2026-08-25-to-2026-08-29.docx")
doc = Document(path)
target = "选定一个目标明确、空间范围可控的村庄样例，固定输入资料、GIS 图层和规划目标。"
removed = 0
for paragraph in list(doc.paragraphs):
    if paragraph.text.strip() == target:
        element = paragraph._element
        element.getparent().remove(element)
        removed += 1
if removed != 1:
    raise RuntimeError(f"expected one paragraph, removed {removed}")
doc.save(path)
print(f"removed={removed} path={path}")
