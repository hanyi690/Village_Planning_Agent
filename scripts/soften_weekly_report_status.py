from pathlib import Path

from docx import Document


path = Path("F:/project/Village_Planning_Agent/docs/reports-weekly/2026-08-25-to-2026-08-29.docx")
doc = Document(path)
risk = "风险：结构化模块已经较多，但如果没有一张新的、可重复生成的规划产出图，系统价值仍不够直观。"
old_status = "当前不是“全流程已经完成”，而是“结构化分析系统已基本搭起，下一阶段必须用一个可控样例重新打通并产出可信规划图”。"
new_status = "阶段判断：目前已完成结构化分析系统的主要架构整理，下一阶段将继续通过可控样例完善端到端验证，并形成更稳定的规划图输出。"
removed = 0
replaced = 0
for paragraph in list(doc.paragraphs):
    if paragraph.text.strip() == risk:
        element = paragraph._element
        element.getparent().remove(element)
        removed += 1
    elif old_status in paragraph.text:
        for run in paragraph.runs:
            if old_status in run.text:
                run.text = run.text.replace(old_status, new_status)
                replaced += 1
if removed != 1 or replaced != 1:
    raise RuntimeError(f"expected removed=1/replaced=1, got {removed}/{replaced}")
doc.save(path)
print(f"removed={removed} replaced={replaced} path={path}")
