"""
通用文档加载器

支持 Markdown、TXT、PPTX、PDF、DOCX、DOC 等多种格式。
符合 LangChain 文档加载器接口规范，支持按类别（policies/cases）组织知识库。
所有格式都会统一转换为 Markdown，并自动清理冗余信息。
"""
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Literal, Dict, List
from pathlib import Path

from langchain_core.documents import Document
import filetype

# ==================== 支持的文件格式 ====================
# 字典格式：扩展名 -> 描述
SUPPORTED_EXTENSIONS = {
    '.txt': 'Plain text file',
    '.md': 'Markdown file',
    '.pdf': 'PDF document',
    '.doc': 'Microsoft Word 97-2003',
    '.docx': 'Microsoft Word document',
    '.ppt': 'Microsoft PowerPoint 97-2003',
    '.pptx': 'Microsoft PowerPoint presentation',
    '.xls': 'Microsoft Excel 97-2003',
    '.xlsx': 'Microsoft Excel spreadsheet',
    '.epub': 'EPUB ebook',
    '.html': 'HTML file',
    '.htm': 'HTML file',
}

# Optional imports for specific file formats
try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None


# ==================== 文件类型检测 ====================

class FileTypeDetector:
    """通过文件内容检测真实类型，不依赖扩展名"""

    MIME_TYPE_MAP = {
        'application/pdf': 'pdf',
        'application/msword': 'doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
        'application/vnd.ms-word': 'doc',
        'application/wps-office.doc': 'doc',
        'application/vnd.ms-powerpoint': 'ppt',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
        'application/vnd.ms-excel': 'xls',
        'application/wps-office.xls': 'xls',
        'text/plain': 'txt',
        'text/markdown': 'md',
        'application/x-ole-storage': 'ole',
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'image/gif': 'gif',
        'image/webp': 'webp',
        'image/bmp': 'bmp',
    }

    EXT_TYPE_MAP = {
        '.pdf': 'pdf', '.doc': 'doc', '.docx': 'docx',
        '.ppt': 'ppt', '.pptx': 'pptx', '.txt': 'txt',
        '.md': 'markdown',
    }

    @classmethod
    def detect(cls, file_path: Path) -> str:
        """检测文件真实类型"""
        ext = file_path.suffix.lower()
        kind = filetype.guess(str(file_path))

        if kind is None:
            return cls.EXT_TYPE_MAP.get(ext, 'unknown')

        mime_type = kind.mime
        doc_type = cls.MIME_TYPE_MAP.get(mime_type)

        # OLE 格式处理
        if doc_type == 'ole':
            return 'doc' if ext in ['.doc', '.docx'] else doc_type

        # .doc 扩展名保护：MIME 可能被误识别为 xls
        if ext == '.doc' and doc_type in ['xls', 'xlsx']:
            print(f"⚠️  检测到 .doc 文件被误识别为 {doc_type}，已修正为 doc")
            return 'doc'

        # .docx 文件伪装检测
        if ext == '.docx' and mime_type in [
            'application/vnd.ms-excel',
            'application/wps-office.xls',
            'application/x-ole-storage'
        ]:
            print(f"⚠️  检测到伪装成 .docx 的 .doc 文件: {file_path.name}")
            return 'doc'

        return doc_type or cls.EXT_TYPE_MAP.get(ext, 'unknown')


# ==================== .doc 文件转换器 ====================

class DocToDocxConverter:
    """
    将旧版 .doc 文件转换为 .docx 格式
    
    支持跨平台：
    - Windows: 优先使用 win32com (效果更好，需要安装 Microsoft Word)
    - Linux/Docker: 使用 LibreOffice 命令行 (soffice --headless)
    
    MarkItDown 不支持旧版 .doc (OLE 格式)，需要先转换为 .docx
    """

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 120

    @staticmethod
    def is_available() -> bool:
        """检查转换器是否可用（win32com 或 LibreOffice）"""
        # Windows: 检查 win32com
        try:
            import win32com.client
            return True
        except ImportError:
            pass
        
        # Linux/Docker: 检查 LibreOffice (跨平台检测)
        soffice_path = shutil.which('soffice')
        return soffice_path is not None

    @staticmethod
    def convert(
        doc_path: Path,
        output_dir: Optional[Path] = None,
        timeout: Optional[int] = None
    ) -> Optional[Path]:
        """
        将 .doc 文件转换为 .docx
        
        Args:
            doc_path: .doc 文件路径
            output_dir: 输出目录，默认为临时目录
            timeout: 超时时间（秒），默认 120
            
        Returns:
            转换后的 .docx 文件路径，失败返回 None
        """
        import tempfile
        
        timeout = timeout or DocToDocxConverter.DEFAULT_TIMEOUT

        if not doc_path.exists():
            print(f"❌ 文件不存在: {doc_path}")
            return None

        # 设置输出路径
        if output_dir is None:
            output_dir = Path(tempfile.gettempdir()) / "doc_conversions"
        output_dir.mkdir(parents=True, exist_ok=True)

        docx_path = output_dir / (doc_path.stem + ".docx")

        # 如果已存在转换后的文件，直接返回
        if docx_path.exists():
            print(f"✅ 使用已转换的文件: {docx_path}")
            return docx_path

        # 尝试 Windows 方式 (win32com)
        if DocToDocxConverter._try_win32com(doc_path, docx_path):
            return docx_path

        # 尝试 LibreOffice 方式
        if DocToDocxConverter._try_libreoffice(doc_path, output_dir, timeout):
            return docx_path

        # 所有方式都失败
        print("❌ 无法转换 .doc 文件。")
        print("   Windows: 请安装 pywin32: pip install pywin32")
        print("   Docker:  请确保 LibreOffice 已安装")
        return None

    @staticmethod
    def _try_win32com(doc_path: Path, docx_path: Path) -> bool:
        """Windows COM 方式转换"""
        try:
            import win32com.client
            
            print(f"🔄 正在转换 .doc 为 .docx (win32com): {doc_path.name} ...")
            
            word = win32com.client.Dispatch('Word.Application')
            word.Visible = False
            
            doc = word.Documents.Open(str(doc_path.absolute()))
            doc.SaveAs(str(docx_path.absolute()), FileFormat=16)  # wdFormatXMLDocument
            doc.Close()
            word.Quit()
            
            print(f"✅ 转换成功: {docx_path}")
            return True
            
        except ImportError:
            return False
        except Exception as e:
            print(f"⚠️  win32com 转换失败: {e}")
            return False

    @staticmethod
    def _try_libreoffice(doc_path: Path, output_dir: Path, timeout: int) -> bool:
        """LibreOffice 命令行方式转换"""
        try:
            print(f"🔄 正在转换 .doc 为 .docx (LibreOffice): {doc_path.name} ...")
            
            cmd = [
                'soffice',
                '--headless',
                '--convert-to', 'docx',
                '--outdir', str(output_dir),
                str(doc_path.absolute())
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            docx_path = output_dir / (doc_path.stem + ".docx")
            if docx_path.exists():
                print(f"✅ 转换成功: {docx_path}")
                return True
            else:
                print(f"⚠️  LibreOffice 转换失败: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"❌ LibreOffice 转换超时 (>{timeout}s)")
            return False
        except FileNotFoundError:
            print("⚠️  LibreOffice 未安装")
            return False
        except Exception as e:
            print(f"⚠️  LibreOffice 转换失败: {e}")
            return False


# ==================== Markdown 清理 ====================

class MarkdownCleaner:
    """清理 Markdown 内容，去除格式数据和冗余信息"""

    FOOTER_PATTERNS = [
        r'第\s*\d+\s*页', r'Page\s*\d+',
        r'保密|机密|内部资料', r'www\.\w+\.com', r'http[s]?://\S+',
    ]

    PLACEHOLDER_PATTERNS = [
        r'点击此处添加.*', r'请输入.*', r'\[.*?\]', r'{{.*?}}',
    ]

    @classmethod
    def clean_text(cls, text: str) -> str:
        """清理文本内容"""
        for pattern in cls.FOOTER_PATTERNS + cls.PLACEHOLDER_PATTERNS:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        text = re.sub(r'\n\s*\n\s*\n+', '\n\n\n', text)
        lines = [line.strip() for line in text.split('\n')]

        cleaned_lines = []
        for line in lines:
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', line))
            alnum_chars = len(re.findall(r'[a-zA-Z0-9]', line))
            total_chars = len(line)

            if (chinese_chars + alnum_chars) / max(total_chars, 1) > 0.1 or (chinese_chars + alnum_chars) >= 5:
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines).strip()

    @classmethod
    def is_meaningful_content(cls, text: str, min_length: int = 20) -> bool:
        """判断文本是否有意义"""
        if len(text.strip()) < min_length:
            return False
        if not re.search(r'[\u4e00-\u9fff\u4e00-\u9fa5a-zA-Z0-9]', text):
            return False
        if text.strip().replace('-', '').replace('/', '').replace(':', '').strip().isdigit():
            return False
        return True


# ==================== 基础加载器 ====================

class BaseDocumentLoader:
    """文档加载器基类，提供公共方法"""

    # 支持的知识库类别（与 KB_CATEGORIES 保持一致）
    SUPPORTED_CATEGORIES = Literal["policies", "cases", "standards", "domain", "local", "laws", "plans"]

    def __init__(
        self,
        file_path: str | Path,
        category: Optional[SUPPORTED_CATEGORIES] = None,
    ):
        self.file_path = Path(file_path)
        self.category = category
        self.cleaner = MarkdownCleaner()

    def _create_document(
        self,
        content: str,
        **metadata_kwargs
    ) -> Optional[Document]:
        """创建文档对象"""
        if not self.cleaner.is_meaningful_content(content):
            return None

        cleaned_content = self.cleaner.clean_text(content)
        if not self.cleaner.is_meaningful_content(cleaned_content):
            return None

        metadata = {
            "source": str(self.file_path.name),
            **metadata_kwargs
        }

        if self.category:
            metadata["category"] = self.category

        return Document(page_content=cleaned_content, metadata=metadata)

    def _validate_file(self) -> None:
        """验证文件存在"""
        if not self.file_path.exists():
            raise FileNotFoundError(f"找不到文件: {self.file_path}")


# ==================== MarkItDown 统一加载器 ====================
# 使用 Microsoft MarkItDown 统一处理多种文档格式
# 支持: doc, docx, pdf, ppt, pptx, xlsx, xls, epub, html 等

# MarkItDown 支持的格式
MARKITDOWN_EXTENSIONS = {
    '.doc', '.docx',    # Word
    '.pdf',             # PDF
    '.ppt', '.pptx',    # PowerPoint
    '.xls', '.xlsx',    # Excel
    '.epub',            # EPUB
    '.html', '.htm',    # HTML
}


class MarkItDownLoader(BaseDocumentLoader):
    """
    使用 MarkItDown 统一加载多种文档格式

    支持格式: doc, docx, pdf, ppt, pptx, xls, xlsx, epub, html

    特性:
    - 超时保护机制，防止大文件卡死
    - 旧版 .doc (OLE格式) 自动转换为 .docx 后再解析
    - 跨平台支持（Windows win32com + Linux LibreOffice）
    - OCR 输出预处理（扫描版教材 PDF）

    优势:
    - 跨平台兼容
    - 统一输出 Markdown 格式
    - 保留文档结构（标题、列表、表格）
    - 支持"伪装文件"（如 .docx 实际是 .doc）
    """

    # 默认超时配置
    DEFAULT_TIMEOUT = 60  # 秒（本地解析器）

    # ==================== 预编译正则表达式（类级别常量）====================
    # OCR 相关模式
    OCR_PAGE_MARKER_RE = re.compile(r'^#{1,6}\s+Page\s+\d+', re.MULTILINE)
    OCR_BLOCK_PATTERN_RE = re.compile(r'\*\[Image OCR\]\n(.*?)\n\[End OCR\]\*\*', re.DOTALL)
    HEADER_COUNT_RE = re.compile(r'^#{1,3}\s', re.MULTILINE)

    # 章节转换规则（预编译）
    CHAPTER_TO_HEADER_RE = [
        # 英文章节
        (re.compile(r'^(Chapter\s+\d+[^\n]*)', re.MULTILINE), r'# \1'),
        (re.compile(r'^(Section\s+\d+\.\d+[^\n]*)', re.MULTILINE), r'## \1'),
        # 中文章节
        (re.compile(r'^(第[一二三四五六七八九十百]+章[^\n]*)', re.MULTILINE), r'# \1'),
        (re.compile(r'^(第\s*\d+\s*章[^\n]*)', re.MULTILINE), r'# \1'),
        (re.compile(r'^(第[一二三四五六七八九十]+节[^\n]*)', re.MULTILINE), r'## \1'),
        (re.compile(r'^(\d+\.\d+[^\n]*)', re.MULTILINE), r'### \1'),
    ]

    def __init__(
        self,
        file_path: str | Path,
        category: Optional[BaseDocumentLoader.SUPPORTED_CATEGORIES] = None,
        timeout: Optional[int] = None,
    ):
        super().__init__(file_path, category)
        # 本地解析器默认60秒超时
        self.timeout = timeout or self.DEFAULT_TIMEOUT

    def load(self) -> list[Document]:
        """使用 MarkItDown 加载文档（带超时保护）"""
        self._validate_file()
        
        file_ext = self.file_path.suffix.lower()
        actual_file = self.file_path
        
        # 特殊处理 .doc 文件：先转换为 .docx
        if file_ext == '.doc':
            actual_file = self._convert_doc_to_docx()
            if actual_file is None:
                raise Exception(
                    "无法解析 .doc 文件。\n"
                    "Windows: 请安装 pywin32: pip install pywin32\n"
                    "Docker:  确保 LibreOffice 已安装\n"
                    "或请将文件另存为 .docx 格式后重新上传。"
                )
            file_ext = '.docx'
        
        print(f"📄 正在使用 MarkItDown 读取: {self.file_path.name} ({file_ext}) ...")

        try:
            # PDF 文件使用 Fallback 链（MarkItDown 失败时自动切换备用解析器）
            if file_ext == '.pdf':
                markdown_content = self._convert_pdf_with_fallback(actual_file)
            else:
                markdown_content = self._convert_with_markitdown(actual_file)
            return self._parse_markdown(markdown_content, file_ext)
        except ImportError:
            raise Exception(
                "markitdown 库未安装，请运行: pip install 'markitdown[docx,pdf,xlsx,pptx]'"
            )
        except TimeoutError:
            raise Exception(
                f"文档处理超时 (>{self.timeout}秒)，文件可能过大或损坏: {self.file_path.name}\n"
                "建议：将文件转换为 .docx/.pptx 格式后重新上传，或检查文件是否损坏。"
            )
        except Exception as e:
            raise Exception(f"MarkItDown 解析失败: {e}")

    def _convert_doc_to_docx(self) -> Optional[Path]:
        """将 .doc 文件转换为 .docx"""
        return DocToDocxConverter.convert(self.file_path, timeout=self.timeout)

    def _convert_with_markitdown(self, file_path: Optional[Path] = None) -> str:
        """使用 MarkItDown 转换文档为 Markdown（本地解析器，不带OCR）"""
        try:
            from markitdown import MarkItDown
        except ImportError:
            raise ImportError("markitdown 未安装")

        # 禁用 OCR 插件，仅使用本地解析器
        md = MarkItDown(enable_plugins=False)
        target_path = file_path or self.file_path

        # 使用 func_timeout 实现超时保护
        from func_timeout import func_timeout, FunctionTimedOut

        def _convert():
            return md.convert(str(target_path))

        effective_timeout = min(self.timeout, 60)  # 本地解析器最多60秒

        try:
            result = func_timeout(effective_timeout, _convert)
            return result.markdown
        except FunctionTimedOut:
            raise TimeoutError(
                f"MarkItDown 处理超时 (>{effective_timeout}s): {target_path.name}"
            )

    def _convert_pdf_with_fallback(self, file_path: Path) -> str:
        """
        PDF 文件 Fallback 解析链（本地优先）

        优先级：
        1. MarkItDown → pdfminer.six，输出 Markdown（优先，方便切片）
        2. PyMuPDF → 纯文本备用
        3. pdfplumber → 表格/结构化内容

        Args:
            file_path: PDF 文件路径

        Returns:
            解析后的 Markdown 内容

        Raises:
            Exception: 所有解析器都失败时抛出详细错误
        """
        from .pdf_fallback import convert_with_pymupdf, extract_with_pdfplumber, check_parsers

        parsers_status = check_parsers()

        # 1. 先尝试 MarkItDown（输出 Markdown 格式，方便切片）
        try:
            print("🔄 尝试 MarkItDown 解析...")
            content = self._convert_with_markitdown(file_path)
            if content and len(content.strip()) >= 100:
                print(f"✅ MarkItDown 解析成功，内容长度: {len(content)}")
                return content
        except TimeoutError:
            print("⚠️ MarkItDown 解析超时，尝试备用解析器...")
        except Exception as e:
            print(f"⚠️ MarkItDown 解析失败: {e}")

        # 2. PyMuPDF 备用（纯文本）
        if parsers_status['pymupdf']:
            print("🔄 尝试 PyMuPDF 解析...")
            try:
                content = convert_with_pymupdf(file_path)
                if content and len(content.strip()) >= 100:
                    print(f"✅ PyMuPDF 解析成功，内容长度: {len(content)}")
                    return content
            except Exception as e:
                print(f"⚠️ PyMuPDF 解析失败: {e}")

        # 3. pdfplumber 备用（表格处理）
        if parsers_status['pdfplumber']:
            print("🔄 尝试 pdfplumber 解析...")
            content, error = extract_with_pdfplumber(file_path)
            if content and len(content.strip()) >= 100:
                print(f"✅ pdfplumber 解析成功")
                return content
            if error:
                print(f"⚠️ pdfplumber: {error}")

        # 所有解析器都失败
        raise Exception(
            f"PDF 解析失败: {file_path.name}\n"
            f"解析器状态: pymupdf={parsers_status['pymupdf']}, pdfplumber={parsers_status['pdfplumber']}\n"
            "建议：检查文件是否损坏，或手动转换为 .docx 格式"
        )

    def _parse_markdown(self, content: str, file_ext: str) -> list[Document]:
        """解析 Markdown 内容为 Document 列表"""
        if not content or not content.strip():
            print(f"⚠️  文档内容为空")
            return []

        # OCR 输出预处理（扫描版教材 PDF）- 内嵌实现
        if self._is_ocr_output(content):
            content = self._preprocess_ocr_output(content)
            print(f"🔄 OCR 输出预处理完成")

        # 清理内容
        content = self.cleaner.clean_text(content)
        
        # 按标题分割（保留文档结构）
        documents = self._split_by_headers(content, file_ext)
        
        # 如果按标题分割后为空，按段落分割
        if not documents:
            documents = self._split_by_paragraphs(content, file_ext)
        
        print(f"✅ 提取完成，共获取 {len(documents)} 个文档片段")
        return documents

    def _split_by_headers(self, content: str, file_ext: str) -> list[Document]:
        """按 Markdown 标题分割文档"""
        documents = []
        lines = content.split('\n')
        
        current_section = []
        current_header = "文档开始"
        current_level = 0
        section_idx = 0
        
        for line in lines:
            header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            
            if header_match:
                # 保存当前章节
                if current_section:
                    section_content = '\n'.join(current_section).strip()
                    if self.cleaner.is_meaningful_content(section_content):
                        doc = self._create_document(
                            section_content,
                            section=section_idx + 1,
                            type=file_ext.lstrip('.'),
                            header=current_header,
                            header_level=current_level,
                        )
                        if doc:
                            documents.append(doc)
                            section_idx += 1
                
                # 开始新章节
                current_level = len(header_match.group(1))
                current_header = header_match.group(2).strip()
                current_section = [line]
            else:
                current_section.append(line)
        
        # 保存最后一个章节
        if current_section:
            section_content = '\n'.join(current_section).strip()
            if self.cleaner.is_meaningful_content(section_content):
                doc = self._create_document(
                    section_content,
                    section=section_idx + 1,
                    type=file_ext.lstrip('.'),
                    header=current_header,
                    header_level=current_level,
                )
                if doc:
                    documents.append(doc)
        
        return documents

    def _split_by_paragraphs(self, content: str, file_ext: str) -> list[Document]:
        """按段落分割文档"""
        documents = []
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        for idx, paragraph in enumerate(paragraphs, start=1):
            if self.cleaner.is_meaningful_content(paragraph):
                doc = self._create_document(
                    f"## 段落 {idx}\n\n{paragraph}",
                    paragraph=idx,
                    type=file_ext.lstrip('.'),
                )
                if doc:
                    documents.append(doc)
        
        return documents

    def _preprocess_ocr_output(self, content: str) -> str:
        """
        OCR 输出预处理（合并自 ocr_preprocessor.py）

        处理 MarkItDown + DashScope qwen-vl-ocr 产生的扫描版 PDF 输出格式：
        - 移除 ## Page N 页面标记（避免被误判为标题）
        - 移除 *[Image OCR] 和 [End OCR]* 包装标记
        - 将教材章节标题转换为 Markdown 格式

        Args:
            content: OCR 输出的原始内容

        Returns:
            清理后的内容，章节标题已转换为 Markdown 格式
        """
        import logging
        logger = logging.getLogger(__name__)

        # 记录原始状态（使用预编译模式）
        header_count_before = len(self.HEADER_COUNT_RE.findall(content))
        page_markers = len(self.OCR_PAGE_MARKER_RE.findall(content))

        # 2. 提取 OCR 内容块（移除包装标记，保持内容结构）
        ocr_blocks_content = self.OCR_BLOCK_PATTERN_RE.findall(content)
        ocr_blocks = len(ocr_blocks_content)

        logger.info(f"  OCR预处理: 页面标记 {page_markers} 个, OCR块 {ocr_blocks} 个")
        logger.info(f"  Markdown标题: {header_count_before} 个")

        # 1. 移除页面标记（## Page N）
        content = self.OCR_PAGE_MARKER_RE.sub('', content)

        content = '\n\n'.join(ocr_blocks_content) if ocr_blocks_content else content

        # 3. 转换教材章节标题为 Markdown 格式（使用预编译规则）
        for compiled_pattern, replacement in self.CHAPTER_TO_HEADER_RE:
            matches = compiled_pattern.findall(content)
            if matches:
                logger.info(f"  章节匹配: {len(matches)} 处 -> {matches[:3]}...")
            content = compiled_pattern.sub(replacement, content)

        header_count_after = len(self.HEADER_COUNT_RE.findall(content))
        logger.info(f"  转换后Markdown标题: {header_count_before} -> {header_count_after}")

        # 4. 清理多余空行
        content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)

        return content.strip()

    def _is_ocr_output(self, content: str) -> bool:
        """检测是否为 OCR 输出格式"""
        return bool(re.search(r'## Page \d+.*\*\[Image OCR\]', content))


# ==================== 保留旧加载器作为别名（向后兼容）====================

# DOCLoader 和 DOCXLoader 统一使用 MarkItDownLoader
DOCLoader = MarkItDownLoader
DOCXLoader = MarkItDownLoader
PDFLoader = MarkItDownLoader
PPTXLoader = MarkItDownLoader


# ==================== Markdown 加载器 ====================

class MarkdownLoader(BaseDocumentLoader):
    """Markdown 文档加载器"""

    def __init__(
        self,
        file_path: str | Path,
        encoding: str = "utf-8",
        category: Optional[BaseDocumentLoader.SUPPORTED_CATEGORIES] = None,
    ):
        super().__init__(file_path, category)
        self.encoding = encoding

    def load(self) -> list[Document]:
        """加载 Markdown 文件"""
        self._validate_file()
        print(f"📄 正在读取 Markdown: {self.file_path} ...")

        with open(self.file_path, "r", encoding=self.encoding, errors="ignore") as f:
            content = f.read()

        content = self.cleaner.clean_text(content)
        documents = self._split_by_headers(content)

        print(f"✅ 提取完成，共获取 {len(documents)} 个文档片段")
        return documents

    def _split_by_headers(self, content: str) -> list[Document]:
        """按 Markdown 标题分割文档"""
        documents = []
        lines = content.split("\n")

        current_section = []
        current_header = "文档开始"
        current_level = 0
        section_idx = 0

        for line in lines:
            header_match = re.match(r'^(#{1,6})\s+(.+)$', line)

            if header_match:
                if current_section:
                    section_content = "\n".join(current_section).strip()
                    doc = self._create_document(
                        section_content,
                        section=section_idx + 1,
                        type="markdown",
                        header=current_header,
                        header_level=current_level,
                    )
                    if doc:
                        documents.append(doc)
                        section_idx += 1

                current_level = len(header_match.group(1))
                current_header = header_match.group(2).strip()
                current_section = [line]
            else:
                current_section.append(line)

        if current_section:
            section_content = "\n".join(current_section).strip()
            doc = self._create_document(
                section_content,
                section=section_idx + 1,
                type="markdown",
                header=current_header,
                header_level=current_level,
            )
            if doc:
                documents.append(doc)

        return documents


# ==================== 文本文件加载器 ====================

class TextFileLoader(BaseDocumentLoader):
    """TXT 文档加载器"""

    def __init__(
        self,
        file_path: str | Path,
        encoding: str = "utf-8",
        category: Optional[BaseDocumentLoader.SUPPORTED_CATEGORIES] = None,
    ):
        super().__init__(file_path, category)
        self.encoding = encoding

    def load(self) -> list[Document]:
        """加载文本文件"""
        self._validate_file()
        print(f"📂 正在读取文本文件: {self.file_path} ...")

        with open(self.file_path, "r", encoding=self.encoding, errors="ignore") as f:
            content = f.read()

        content = self.cleaner.clean_text(content)
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

        documents = []
        for idx, paragraph in enumerate(paragraphs, start=1):
            doc = self._create_document(
                f"## 段落 {idx}\n\n{paragraph}",
                paragraph=idx,
                type="text",
            )
            if doc:
                documents.append(doc)

        print(f"✅ 提取完成，共获取 {len(documents)} 个段落")
        return documents


# ==================== 批量加载函数 ====================

def load_documents_from_directory(
    directory: str | Path,
    file_extensions: Optional[list[str]] = None,
    category: Optional[BaseDocumentLoader.SUPPORTED_CATEGORIES] = None,
) -> list[Document]:
    """从目录批量加载文档，自动检测真实文件类型
    
    支持格式（通过 MarkItDown）:
    - Word: .doc, .docx
    - PDF: .pdf
    - PowerPoint: .ppt, .pptx
    - Excel: .xls, .xlsx
    - 其他: .epub, .html
    
    纯文本格式:
    - Markdown: .md
    - 文本: .txt
    """
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"目录不存在: {directory}")

    if file_extensions is None:
        # 默认支持的所有格式
        file_extensions = [
            # MarkItDown 支持的格式
            ".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx",
            ".epub", ".html", ".htm",
            # 纯文本格式
            ".md", ".txt",
        ]

    all_documents = []

    for file_path in directory.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in file_extensions:
            continue

        try:
            real_type = FileTypeDetector.detect(file_path)
            print(f"🔍 检测文件类型: {file_path.name} -> {real_type}")

            loader = _create_loader(file_path, real_type, category)
            if loader is None:
                continue

            documents = loader.load()
            all_documents.extend(documents)
        except Exception as e:
            print(f"⚠️  加载文件 {file_path} 时出错: {e}")
            continue

    print(f"📚 总共加载了 {len(all_documents)} 个文档片段")
    return all_documents


def _create_loader(
    file_path: Path,
    file_type: str,
    category: Optional[BaseDocumentLoader.SUPPORTED_CATEGORIES],
) -> Optional[BaseDocumentLoader]:
    """根据文件类型创建对应的加载器
    
    MarkItDown 支持的格式统一使用 MarkItDownLoader:
    - doc, docx (Word)
    - pdf
    - ppt, pptx (PowerPoint)
    - xls, xlsx (Excel)
    - epub, html
    """
    # MarkItDown 支持的格式（统一处理）
    markitdown_types = {'pdf', 'doc', 'docx', 'pptx', 'ppt', 'xls', 'xlsx', 'epub', 'html'}
    
    if file_type in markitdown_types:
        return MarkItDownLoader(file_path, category=category)
    
    # 其他格式使用专用加载器
    loader_map = {
        'markdown': MarkdownLoader,
        'txt': TextFileLoader,
    }

    loader_class = loader_map.get(file_type)
    if loader_class is None:
        print(f"⚠️  不支持的文件类型: {file_type}，跳过: {file_path.name}")
        return None

    return loader_class(file_path, category=category)


def load_knowledge_base(
    data_dir: str | Path,
    categories: Optional[list[str]] = None,
    source_type: Literal["data", "docs"] = "data",
    skip_scanned: bool = True,
) -> list[Document]:
    """加载知识库（支持分类和多种数据源）

    Args:
        data_dir: 数据目录路径
        categories: 要加载的类别列表，默认自动检测
        source_type: 数据源类型
            - "data": data/ 目录（英文分类名，单层结构）
            - "docs": docs/RAG 知识库 目录（中文分类名，多层结构）
        skip_scanned: 是否排除扫描版PDF（非文字PDF），仅对 source_type="docs" 生效

    支持格式:
    - Word: .doc, .docx
    - PDF: .pdf
    - PowerPoint: .ppt, .pptx
    - Excel: .xls, .xlsx
    - 其他: .epub, .html, .md, .txt
    """
    from src.core.config import KB_CATEGORIES, KB_CATEGORY_MAPPING

    data_dir = Path(data_dir)

    if source_type == "docs":
        # 使用多层扫描函数处理 docs/RAG 知识库
        return _load_multi_level_kb(data_dir, categories, skip_scanned=skip_scanned)

    # source_type == "data" 时，使用原有逻辑
    if categories is None:
        categories = [
            item.name
            for item in data_dir.iterdir()
            if item.is_dir() and item.name in KB_CATEGORIES
        ]

    if not categories:
        raise FileNotFoundError(
            f"未找到任何类别目录。请在 {data_dir} 下创建有效的分类目录。"
        )

    all_documents = []

    # 支持的所有格式
    supported_extensions = [
        ".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx",
        ".epub", ".html", ".htm", ".md", ".txt",
    ]

    for category in categories:
        category_dir = data_dir / category
        if not category_dir.exists():
            print(f"⚠️  目录不存在，跳过: {category_dir}")
            continue

        print(f"\n{'='*60}")
        print(f"正在加载类别: {category}")
        print(f"{'='*60}")

        documents = load_documents_from_directory(
            category_dir,
            file_extensions=supported_extensions,
            category=category,
        )
        all_documents.extend(documents)

    print(f"\n{'='*60}")
    print(f"✅ 知识库加载完成！")
    print(f"   - 总文档数: {len(all_documents)}")
    print(f"   - 类别: {', '.join(categories)}")
    print(f"{'='*60}\n")

    return all_documents


def is_scanned_pdf(file_path: Path, sample_pages: int = 3, min_chars_per_page: int = 50) -> bool:
    """
    检测PDF是否是扫描版（非文字PDF）

    Args:
        file_path: PDF文件路径
        sample_pages: 检测的样本页数（前几页）
        min_chars_per_page: 每页最小字符数阈值，低于此值视为扫描版

    Returns:
        True 如果是扫描版PDF（非文字），False 如果是文字PDF

    检测方法：
    使用 PyMuPDF 提取前几页文本，如果平均每页字符数低于阈值，则认为是扫描版。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        # PyMuPDF 未安装，无法检测，默认返回 False（不排除）
        print(f"⚠️  PyMuPDF 未安装，无法检测扫描版PDF: {file_path.name}")
        return False

    try:
        doc = fitz.open(str(file_path))
        total_pages = len(doc)

        if total_pages == 0:
            return True  # 空PDF视为扫描版

        # 检测前几页
        pages_to_check = min(sample_pages, total_pages)
        total_chars = 0

        for page_num in range(pages_to_check):
            page = doc[page_num]
            text = page.get_text()
            total_chars += len(text.strip())

        doc.close()

        # 平均每页字符数
        avg_chars = total_chars / pages_to_check

        # 低于阈值则视为扫描版
        is_scanned = avg_chars < min_chars_per_page

        if is_scanned:
            print(f"  🔍 检测为扫描版PDF（平均{avg_chars:.1f}字符/页）：{file_path.name}")

        return is_scanned

    except Exception as e:
        print(f"⚠️  PDF检测失败: {file_path.name} - {e}")
        return False  # 检测失败时不排除


def scan_multi_level_kb(
    docs_dir: str | Path,
    skip_scanned: bool = True,
    scanned_threshold: int = 50,
) -> Dict[str, List[Path]]:
    """
    扫描多层目录结构的知识库（docs/RAG 知识库）

    Args:
        docs_dir: docs/RAG 知识库 目录路径
        skip_scanned: 是否排除扫描版PDF（非文字PDF）
        scanned_threshold: 扫描版PDF检测阈值（每页最小字符数）

    Returns:
        按英文 category 分组的文件路径字典
    """
    from src.core.config import KB_CATEGORY_MAPPING

    docs_dir = Path(docs_dir)
    if not docs_dir.exists():
        return {}

    result: Dict[str, List[Path]] = {}
    scanned_files: List[str] = []  # 记录被排除的扫描版PDF

    # 支持的文件格式
    supported_extensions = {".pdf", ".doc", ".docx", ".md", ".txt", ".ppt", ".pptx"}

    for chinese_dir, mapping in KB_CATEGORY_MAPPING.items():
        category = mapping["category"]
        result[category] = []

        category_dir = docs_dir / chinese_dir
        if not category_dir.exists():
            continue

        # 递归搜索所有文件
        for file_path in category_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                # 检测扫描版PDF
                if skip_scanned and file_path.suffix.lower() == ".pdf":
                    if is_scanned_pdf(file_path, min_chars_per_page=scanned_threshold):
                        scanned_files.append(str(file_path))
                        continue  # 排除扫描版PDF

                result[category].append(file_path)

    # 输出扫描版PDF排除汇总
    if skip_scanned and scanned_files:
        print(f"\n📋 排除 {len(scanned_files)} 个扫描版PDF（非文字PDF）：")
        for f in scanned_files[:5]:  # 只显示前5个
            print(f"   - {Path(f).name}")
        if len(scanned_files) > 5:
            print(f"   ... 及其他 {len(scanned_files) - 5} 个文件")

    # 过滤空类别
    return {k: v for k, v in result.items() if v}


def _load_multi_level_kb(
    docs_dir: Path,
    categories: Optional[list[str]] = None,
    skip_scanned: bool = True,
) -> list[Document]:
    """
    加载多层目录结构的知识库（内部函数）

    Args:
        docs_dir: docs/RAG 知识库 目录路径
        categories: 要加载的类别列表，默认加载所有
        skip_scanned: 是否排除扫描版PDF

    Returns:
        文档列表
    """
    from src.core.config import KB_CATEGORY_MAPPING

    # 扫描获取文件分组
    files_by_category = scan_multi_level_kb(docs_dir, skip_scanned=skip_scanned)

    if categories is None:
        categories = list(files_by_category.keys())

    if not categories:
        print(f"⚠️  docs/RAG 知识库 目录下未找到任何文档")
        return []

    all_documents = []

    for category in categories:
        if category not in files_by_category:
            print(f"⚠️  类别 {category} 无文件，跳过")
            continue

        file_paths = files_by_category[category]
        print(f"\n{'='*60}")
        print(f"正在加载类别: {category} ({len(file_paths)} 个文件)")
        print(f"{'='*60}")

        for file_path in file_paths:
            try:
                real_type = FileTypeDetector.detect(file_path)
                loader = _create_loader(file_path, real_type, category)
                if loader is None:
                    continue

                documents = loader.load()
                all_documents.extend(documents)
            except Exception as e:
                print(f"⚠️  加载文件 {file_path.name} 时出错: {e}")
                continue

    print(f"\n{'='*60}")
    print(f"✅ 知识库加载完成！")
    print(f"   - 总文档数: {len(all_documents)}")
    print(f"   - 类别: {', '.join(categories)}")
    print(f"{'='*60}\n")

    return all_documents
