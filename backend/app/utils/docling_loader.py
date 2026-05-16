"""
Docling Loader - 高级文档解析器

特性：
- CUDA 加速（可选）
- RapidOCR 支持（中英文 OCR）
- 分批处理大文档
- 表格结构提取
- Markdown 输出（保留标题结构）

使用方法：
    from app.utils.docling_loader import DoclingLoader
    loader = DoclingLoader(file_path, category="policies")
    documents = loader.load()
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.utils.document_loader import FileTypeDetector, MarkdownCleaner

logger = logging.getLogger(__name__)


class DoclingLoader:
    """高级文档加载器，使用 Docling 引擎"""

    def __init__(
        self,
        file_path: Path,
        category: Optional[str] = None,
        use_cuda: Optional[bool] = None,
        batch_size: Optional[int] = None,
        force_ocr: Optional[bool] = None,
    ):
        """初始化 Docling 加载器

        Args:
            file_path: 文件路径
            category: 文档类别
            use_cuda: 是否使用 CUDA 加速（None 时使用全局配置）
            batch_size: 分批处理每批页数（None 时使用全局配置）
            force_ocr: 是否强制全页 OCR（用于扫描件）
        """
        self.file_path = Path(file_path)
        self.file_type = FileTypeDetector.detect(self.file_path)
        self.category = category

        # 加载全局配置
        try:
            from app.core.settings import (
                DOCLING_USE_CUDA,
                DOCLING_BATCH_SIZE,
                DOCLING_FORCE_OCR,
            )
            self.use_cuda = use_cuda if use_cuda is not None else DOCLING_USE_CUDA
            self.batch_size = batch_size if batch_size is not None else DOCLING_BATCH_SIZE
            self.force_ocr = force_ocr if force_ocr is not None else DOCLING_FORCE_OCR
        except ImportError:
            self.use_cuda = use_cuda or False
            self.batch_size = batch_size or 50
            self.force_ocr = force_ocr or False

    def load(self) -> List[Document]:
        """加载文档，返回 LangChain Document 列表"""
        content = self._extract_content()

        if not content or len(content.strip()) < 10:
            logger.warning(f"[DoclingLoader] Content empty or too short: {self.file_path}")
            return []

        content = MarkdownCleaner.clean(content)

        doc = Document(
            page_content=content,
            metadata={
                "source": self.file_path.name,
                "type": self.file_type,
                "file_path": str(self.file_path),
                "category": self.category or "unknown",
                "parser": "docling",
            }
        )
        return [doc]

    def _extract_content(self) -> str:
        """使用 Docling 提取内容"""
        try:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                PdfPipelineOptions,
                TableStructureOptions,
                TableFormerMode,
                RapidOcrOptions,
            )
            from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
        except ImportError:
            logger.warning("[DoclingLoader] docling not installed, falling back to MarkItDown")
            return self._fallback_to_markitdown()

        try:
            # 配置加速选项
            accelerator_options = self._configure_accelerator()

            # 配置 PDF 管道
            pipeline_options = PdfPipelineOptions(accelerator_options=accelerator_options)
            pipeline_options.allow_external_plugins = True
            pipeline_options.force_backend_text = True  # 避免阅读顺序错误
            pipeline_options.document_timeout = 300.0  # 5 分钟超时

            # 配置 OCR
            pipeline_options.do_ocr = True
            pipeline_options.ocr_options = RapidOcrOptions(
                lang=["chinese", "english"],
                backend="torch" if self.use_cuda else "onnxruntime",
                text_score=0.5,
            )
            if self.force_ocr:
                pipeline_options.ocr_options.force_full_page_ocr = True
                logger.info("[DoclingLoader] Force full page OCR enabled")

            # 配置表格提取
            pipeline_options.do_table_structure = True
            pipeline_options.table_structure_options = TableStructureOptions(
                do_cell_matching=True,
                mode=TableFormerMode.ACCURATE,
            )

            # 创建转换器
            converter = DocumentConverter(
                allowed_formats=[
                    InputFormat.PDF,
                    InputFormat.IMAGE,
                    InputFormat.DOCX,
                    InputFormat.PPTX,
                ],
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                }
            )

            # 检查是否需要分批处理
            if self.batch_size > 0 and self.file_type == "pdf":
                total_pages = self._get_pdf_page_count()
                if total_pages > self.batch_size:
                    logger.info(f"[DoclingLoader] Large document: {total_pages} pages, batch processing")
                    return self._parse_with_batch(converter, total_pages)

            # 直接解析
            logger.info(f"[DoclingLoader] Parsing: {self.file_path.name}")
            start_time = time.time()
            conv_result = converter.convert(str(self.file_path))
            doc = conv_result.document

            markdown = doc.export_to_markdown()
            parse_time = time.time() - start_time
            logger.info(f"[DoclingLoader] Parsed in {parse_time:.2f}s, {len(markdown)} chars")

            return markdown

        except Exception as e:
            logger.error(f"[DoclingLoader] Parse failed: {e}")
            import traceback
            traceback.print_exc()
            return self._fallback_to_markitdown()

    def _configure_accelerator(self) -> "AcceleratorOptions":
        """配置加速器"""
        from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice

        if self.use_cuda:
            try:
                import torch
                if torch.cuda.is_available():
                    logger.info(f"[DoclingLoader] Using CUDA: {torch.cuda.get_device_name(0)}")
                    return AcceleratorOptions(
                        device=AcceleratorDevice.CUDA,
                        num_threads=4,
                    )
                else:
                    logger.warning("[DoclingLoader] CUDA not available, using CPU")
            except Exception as e:
                logger.warning(f"[DoclingLoader] CUDA config failed: {e}")

        return AcceleratorOptions(
            device=AcceleratorDevice.CPU,
            num_threads=4,
        )

    def _get_pdf_page_count(self) -> int:
        """获取 PDF 页数"""
        try:
            import fitz  # PyMuPDF
            pdf_doc = fitz.open(str(self.file_path))
            count = pdf_doc.page_count
            pdf_doc.close()
            return count
        except ImportError:
            try:
                import pdfplumber
                with pdfplumber.open(str(self.file_path)) as pdf:
                    return len(pdf.pages)
            except ImportError:
                logger.warning("[DoclingLoader] PyMuPDF/pdfplumber not installed, cannot check page count")
                return 0

    def _parse_with_batch(self, converter, total_pages: int) -> str:
        """分批处理大文档"""
        all_content = []
        num_batches = (total_pages + self.batch_size - 1) // self.batch_size

        logger.info(f"[DoclingLoader] Batch processing: {num_batches} batches ({self.batch_size} pages/batch)")

        for batch_idx in range(num_batches):
            # page_range 页码从 1 开始
            start_page = batch_idx * self.batch_size + 1
            end_page = min((batch_idx + 1) * self.batch_size, total_pages)

            logger.info(f"[DoclingLoader] Batch {batch_idx + 1}/{num_batches}: pages {start_page}-{end_page}")

            try:
                conv_result = converter.convert(
                    str(self.file_path),
                    page_range=(start_page, end_page)
                )
                all_content.append(conv_result.document.export_to_markdown())

                # 清理内存
                del conv_result

            except Exception as e:
                logger.error(f"[DoclingLoader] Batch {batch_idx + 1} failed: {e}")

            finally:
                if self.use_cuda:
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass

        combined = "\n\n".join(all_content)
        logger.info(f"[DoclingLoader] Batch processing complete: {len(combined)} chars")
        return combined

    def _fallback_to_markitdown(self) -> str:
        """降级到 MarkItDown"""
        logger.info(f"[DoclingLoader] Falling back to MarkItDown for: {self.file_path.name}")
        from app.utils.document_loader import MarkItDownLoader
        loader = MarkItDownLoader(self.file_path, category=self.category)
        docs = loader.load()
        return docs[0].page_content if docs else ""


__all__ = ["DoclingLoader"]
