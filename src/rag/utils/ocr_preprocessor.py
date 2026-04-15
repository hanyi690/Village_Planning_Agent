"""
OCR 输出预处理器

处理 MarkItDown + DashScope qwen-vl-ocr 产生的扫描版 PDF 输出格式：
- 移除 ## Page N 页面标记（避免被误判为标题）
- 移除 *[Image OCR] 和 [End OCR]* 包装标记
- 将教材章节标题转换为 Markdown 格式

使用场景：
- 扫描版教材 PDF（章节标题在扫描图像中）
- OCR 输出被错误分割成每页一个切片的问题
"""
import re
import logging

logger = logging.getLogger(__name__)


class OCRPreProcessor:
    """OCR 输出预处理"""

    # 页面标记模式（需移除，避免误判为标题）
    PAGE_MARKER_PATTERN = r'^##\s+Page\s+\d+\s*\n'

    # OCR 包装块模式：匹配 *[Image OCR]\n...内容...\n[End OCR]*
    OCR_BLOCK_PATTERN = r'\*\[Image OCR\]\n(.*?)\n\[End OCR\]\*'

    # 教材章节 → Markdown 标题转换规则
    CHAPTER_TO_HEADER = [
        # 第一章 → # 第一章（中文数字章节）
        (r'^(第[一二三四五六七八九十百]+章[^\n]*)', r'# \1'),
        # 第1章 → # 第1章（阿拉伯数字章节）
        (r'^(第\s*\d+\s*章[^\n]*)', r'# \1'),
        # 第一节 → ## 第一节（中文数字节）
        (r'^(第[一二三四五六七八九十]+节[^\n]*)', r'## \1'),
        # 1.1 概述 → ### 1.1 概述（数字编号小节）
        (r'^(\d+\.\d+[^\n]*)', r'### \1'),
    ]

    def preprocess(self, content: str) -> str:
        """
        预处理 OCR 输出内容

        Args:
            content: OCR 输出的原始内容

        Returns:
            清理后的内容，章节标题已转换为 Markdown 格式
        """
        # 记录原始状态
        header_count_before = len(re.findall(r'^#{1,3}\s', content, re.MULTILINE))
        page_markers = len(re.findall(self.PAGE_MARKER_PATTERN, content, re.MULTILINE))
        ocr_blocks = len(re.findall(self.OCR_BLOCK_PATTERN, content, re.DOTALL))

        logger.info(f"  OCR预处理: 页面标记 {page_markers} 个, OCR块 {ocr_blocks} 个")
        logger.info(f"  Markdown标题: {header_count_before} 个")

        # 1. 移除页面标记（## Page N）
        content = re.sub(self.PAGE_MARKER_PATTERN, '', content, flags=re.MULTILINE)

        # 2. 提取 OCR 内容块（移除包装标记，保持内容结构）
        ocr_blocks_content = re.findall(self.OCR_BLOCK_PATTERN, content, re.DOTALL)
        content = '\n\n'.join(ocr_blocks_content) if ocr_blocks_content else content

        # 3. 转换教材章节标题为 Markdown 格式
        for pattern, replacement in self.CHAPTER_TO_HEADER:
            matches = re.findall(pattern, content, re.MULTILINE)
            if matches:
                logger.info(f"  章节匹配: {len(matches)} 处 → {matches[:3]}...")
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

        header_count_after = len(re.findall(r'^#{1,3}\s', content, re.MULTILINE))
        logger.info(f"  转换后Markdown标题: {header_count_before} → {header_count_after}")

        # 4. 清理多余空行
        content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)

        return content.strip()

    def is_ocr_output(self, content: str) -> bool:
        """
        检测是否为 OCR 输出格式

        Args:
            content: 文档内容

        Returns:
            True 如果是 OCR 输出格式
        """
        return bool(re.search(r'## Page \d+.*\*\[Image OCR\]', content))