"""
OCR 和切片效果测试脚本

测试扫描版 PDF 的 OCR 和切片效果（仅前3页）
"""
from pathlib import Path
import json
import re
import sys
import fitz
from openai import OpenAI
import base64

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import DASHSCOPE_API_KEY, DASHSCOPE_API_BASE, OCR_MODEL_NAME
from src.rag.slicing.slicer import UnifiedMarkdownSlicer

PDF_PATH = Path("docs/references/城市规划原理 第4版【国家级规划教材】 (吴志强, 李德华) (z-library.sk, 1lib.sk, z-lib.sk).pdf")
TEST_PAGES = 3


def test_ocr():
    """测试 OCR（前3页）"""
    print("="*60)
    print(f"测试 1: OCR (前{TEST_PAGES}页)")
    print("="*60)

    if not PDF_PATH.exists():
        print(f"文件不存在: {PDF_PATH}")
        return None

    doc = fitz.open(str(PDF_PATH))
    print(f"PDF 总页数: {len(doc)}, OCR 模型: {OCR_MODEL_NAME}")

    client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_API_BASE)
    contents = []

    for i in range(min(TEST_PAGES, len(doc))):
        print(f"  第{i+1}页...", end=" ")
        page = doc[i]
        pix = page.get_pixmap()
        img_base64 = base64.b64encode(pix.tobytes('png')).decode()

        response = client.chat.completions.create(
            model=OCR_MODEL_NAME,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{img_base64}'}},
                    {'type': 'text', 'text': '识别图片所有文字，直接输出原文内容，不要加任何解释。如果是标题用#标记，小标题用##，保持原有排版。'}
                ]
            }],
            max_tokens=2000
        )
        text = response.choices[0].message.content
        contents.append(f"## Page {i+1}\n\n{text}")
        print(f"{len(text)}字符")

    return "\n\n".join(contents)


def test_slicing(content: str):
    """测试切片"""
    print("\n" + "="*60)
    print("测试 2: 切片")
    print("="*60)

    if not content:
        return []

    slicer = UnifiedMarkdownSlicer()
    chunks = slicer.slice(content, "textbook", {"source": PDF_PATH.name})
    print(f"切片数: {len(chunks)}")
    if chunks:
        print(f"首切片: {chunks[0].content[:80]}...")
    return chunks


def save_chunks(chunks):
    """保存切片"""
    if not chunks:
        return
    output = [{"index": i, "length": len(c.content), "preview": c.content[:60]+"..."} for i, c in enumerate(chunks[:3])]
    path = Path(__file__).parent / "test_chunks_output.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"保存到: {path}")


def main():
    print("OCR 测试")
    content = test_ocr()
    chunks = test_slicing(content)
    save_chunks(chunks)
    print("完成")


if __name__ == "__main__":
    main()