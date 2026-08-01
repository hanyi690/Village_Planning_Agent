"""Ingest parsed standards into the KB.

For each item in INGEST spec:
  - writes a *_minerU_parsed.md into data/RAG_doc/_doc_md/ (RAG pipeline input)
  - copy source PDF into docs/RAG 知识库/04 技术规范/ (KB human-reading PDFs only)

Per current KB policy (PDFs only), we no longer write .md/.json/.images into KB —
those belong in downloads/mineru_md/<stem>/ as the canonical parsed artifact set.
"""

import re
import shutil
from pathlib import Path

REPO = Path(r"F:\project\Village_Planning_Agent")
PARSED = REPO / "downloads" / "mineru_md"
KB = REPO / "docs" / "RAG 知识库"
NATIONAL = KB / "04 技术规范" / "01 国家层面"
GUANGDONG = KB / "04 技术规范" / "02 地方层面" / "01 广东省"
RAG = REPO / "data" / "RAG_doc" / "_doc_md"
RAG_NATIONAL = RAG / "04_技术规范" / "01_国家层面"
RAG_GUANGDONG = RAG / "04_技术规范" / "02_地方层面" / "01_广东省"

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe(name):
    return ILLEGAL.sub("-", name).rstrip(" .")


INGEST = [
    ("TD-T 1027-2010 县级土地利用总体规划数据库标准",
     "downloads\\nrsis\\TD-T 1027-2010 县级土地利用总体规划数据库标准.pdf",
     NATIONAL, RAG_NATIONAL, "07", safe("TD/T 1027-2010 县级土地利用总体规划数据库标准.md"),
     "TD/T 1027-2010 县级土地利用总体规划数据库标准",
     "TD-T 1027-2010 县级土地利用总体规划数据库标准_minerU_parsed.md"),
    ("TD-T 1057-2020 国土调查数据库标准",
     "downloads\\nrsis\\TD-T 1057-2020 国土调查数据库标准.pdf",
     NATIONAL, RAG_NATIONAL, "08", safe("TD/T 1057-2020 国土调查数据库标准.md"),
     "TD/T 1057-2020 国土调查数据库标准",
     "TD-T 1057-2020 国土调查数据库标准_minerU_parsed.md"),
    ("TD-T 1055-2019 第三次全国国土调查技术规程",
     "downloads\\nrsis\\TD-T 1055-2019 第三次全国国土调查技术规程.pdf",
     NATIONAL, RAG_NATIONAL, "09", safe("TD/T 1055-2019 第三次全国国土调查技术规程.md"),
     "TD/T 1055-2019 第三次全国国土调查技术规程",
     "TD-T 1055-2019 第三次全国国土调查技术规程_minerU_parsed.md"),
    ("TD-T 1032-2011 基本农田划定技术规程",
     "downloads\\nrsis\\TD-T 1032-2011 基本农田划定技术规程.pdf",
     NATIONAL, RAG_NATIONAL, "10", safe("TD/T 1032-2011 基本农田划定技术规程.md"),
     "TD/T 1032-2011 基本农田划定技术规程",
     "TD-T 1032-2011 基本农田划定技术规程_minerU_parsed.md"),
    ("A5_GBT21010-2017",
     "downloads\\openstd\\GB-T 21010-2017 土地利用现状分类.pdf",
     NATIONAL, RAG_NATIONAL, "04", safe("GB/T 21010-2017 土地利用现状分类.md"),
     "GB/T 21010-2017 土地利用现状分类",
     "GB-T 21010-2017 土地利用现状分类_minerU_parsed.md"),
    ("A6_GBT43214-2023",
     "downloads\\openstd\\GB-T 43214-2023 省级国土空间规划编制技术规程.pdf",
     NATIONAL, RAG_NATIONAL, "11", safe("GB/T 43214-2023 省级国土空间规划编制技术规程.md"),
     "GB/T 43214-2023 省级国土空间规划编制技术规程",
     "GB-T 43214-2023 省级国土空间规划编制技术规程_minerU_parsed.md"),
    ("A7_GBT39972-2021",
     "downloads\\openstd\\GB-T 39972-2021 国土空间规划\u201c一张图\u201d实施监督信息系统技术规范.pdf",
     NATIONAL, RAG_NATIONAL, "12", safe("GB/T 39972-2021 国土空间规划 一张图 实施监督信息系统技术规范.md"),
     "GB/T 39972-2021 国土空间规划 一张图 实施监督信息系统技术规范",
     "GB-T 39972-2021 国土空间规划 一张图 实施监督信息系统技术规范_minerU_parsed.md"),
    ("国土调查数据库标准",
     "docs\\国土调查数据库标准 .pdf",
     NATIONAL, RAG_NATIONAL, "13", "国土调查数据库标准 试行修订稿.md",
     "国土调查数据库标准（试行修订稿）",
     "国土调查数据库标准_minerU_parsed.md"),
    ("广东省县级国土空间总体规划数据库标准（试行）",
     "docs\\广东省县级国土空间总体规划数据库标准（试行）.pdf",
     GUANGDONG, RAG_GUANGDONG, "03", "广东省县级国土空间总体规划数据库标准 试行.md",
     "广东省县级国土空间总体规划数据库标准（试行）",
     "广东省县级国土空间总体规划数据库标准_minerU_parsed.md"),
]


def _copyfile(src, dst):
    with open(src, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data)
    shutil.copystat(src, dst, follow_symlinks=False)


def ingest():
    rows = []
    for parsed_stem, src_pdf, target_dir, rag_dir, prefix, md_name, display, rag_md_name in INGEST:
        parsed_dir = PARSED / parsed_stem
        if not parsed_dir.exists():
            print(f"SKIP (no parse dir): {parsed_stem}")
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        rag_dir.mkdir(parents=True, exist_ok=True)
        rag_md = rag_dir / rag_md_name
        full_md = parsed_dir / "full.md"
        if full_md.exists():
            _copyfile(full_md, rag_md)
        else:
            print(f"WARN: full.md missing for {parsed_stem}")
        src = REPO / src_pdf
        if src.exists():
            _copyfile(src, target_dir / Path(src_pdf).name)
            print(f"  KB PDF placed: {Path(src_pdf).name}")
        else:
            print(f"WARN: source pdf missing for {parsed_stem}: {src}")
        rows.append({
            "stem": parsed_stem,
            "display": display,
            "prefix": prefix,
            "rag_md": rag_md,
            "size": rag_md.stat().st_size if rag_md.exists() else 0,
        })
        print(f"ingested RAG:{rag_md.name} ({rag_md.stat().st_size}B)")
    return rows


if __name__ == "__main__":
    ingest()