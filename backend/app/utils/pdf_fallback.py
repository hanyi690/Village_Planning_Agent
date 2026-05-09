"""
PDF Fallback Parser - PDF 备用解析链

When MarkItDown cannot parse a PDF, falls back through PyPDF2 then pdfplumber.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PyPDF2Extractor:
    """PyPDF2 text extractor"""

    @staticmethod
    def extract(file_path: Path) -> Optional[str]:
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(file_path))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text and text.strip():
                    pages.append(text.strip())
            if pages:
                return '\n\n'.join(pages)
        except ImportError:
            logger.debug("[PyPDF2Extractor] PyPDF2 not installed")
        except Exception as e:
            logger.warning(f"[PyPDF2Extractor] Extraction failed: {e}")
        return None


class pdfplumberExtractor:
    """pdfplumber text extractor (layout-aware)"""

    @staticmethod
    def extract(file_path: Path) -> Optional[str]:
        try:
            import pdfplumber
            pages = []
            with pdfplumber.open(str(file_path)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text and text.strip():
                        pages.append(text.strip())
            if pages:
                return '\n\n'.join(pages)
        except ImportError:
            logger.debug("[pdfplumberExtractor] pdfplumber not installed")
        except Exception as e:
            logger.warning(f"[pdfplumberExtractor] Extraction failed: {e}")
        return None


class PDFFallbackParser:
    """PDF fallback chain: try each parser in sequence"""

    _chain = [
        ('PyPDF2', PyPDF2Extractor.extract),
        ('pdfplumber', pdfplumberExtractor.extract),
    ]

    @classmethod
    def parse(cls, file_path: Path) -> Optional[str]:
        for name, extractor in cls._chain:
            logger.info(f"[PDFFallbackParser] Trying {name} for: {file_path.name}")
            content = extractor(file_path)
            if content and len(content.strip()) >= 50:
                logger.info(f"[PDFFallbackParser] {name} succeeded ({len(content)} chars)")
                return content
            elif content:
                logger.warning(f"[PDFFallbackParser] {name} content too short ({len(content)} chars)")

        logger.warning(f"[PDFFallbackParser] All parsers failed for: {file_path.name}")
        return None


def parse_pdf_with_fallback(file_path: Path) -> Optional[str]:
    """Convenience function for PDF fallback parsing"""
    return PDFFallbackParser.parse(file_path)


__all__ = [
    "PDFFallbackParser",
    "PyPDF2Extractor",
    "pdfplumberExtractor",
    "parse_pdf_with_fallback",
]
