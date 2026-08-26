"""
Metadata Extractor - Extract metadata from file path, filename, and content

Features:
- Extract category/subcategory from directory path
- Extract sequence number and title from filename
- Extract parser info from Markdown content
- Use LLM Flash to infer doc_type from title

2026-05-16: Created for RAG processing flow optimization
"""

import re
import logging
from typing import Literal
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Category mapping: directory path -> (category, subcategory, level)
CATEGORY_MAPPING = {
    "01_专业教材": ("专业教材", "", ""),
    "02_法律法规/01_法律": ("法律法规", "法律", "国家"),
    "02_法律法规/02_地方性法规": ("法律法规", "地方性法规", "地方"),
    "02_法律法规/03_行政法规": ("法律法规", "行政法规", "国家"),
    "03_政策文件/01_国家层面": ("政策文件", "国家政策", "国家"),
    "03_政策文件/02_地方层面/01_广东省": ("政策文件", "地方政策", "广东省"),
    "04_技术规范/01_国家层面": ("技术规范", "国家标准", "国家"),
    "04_技术规范/02_地方层面/01_广东省": ("技术规范", "地方标准", "广东省"),
    "05_上位规划/01_广东省": ("上位规划", "", "广东省"),
    "06_相关案例": ("相关案例", "", ""),
}


class DocumentTypeProposal(BaseModel):
    """Strict semantic proposal returned by the document classifier."""

    model_config = ConfigDict(extra="forbid")

    doc_type: Literal["textbook", "guide", "policy", "standard", "case", "report"]
    keywords: list[str] = Field(default_factory=list, max_length=24)


def _pending_doc_type_result(reason: str) -> Dict[str, Any]:
    """Return an explicit unresolved result; never invent a document type."""

    return {
        "status": "pending",
        "reason": str(reason).strip() or "document_type_inference_pending",
        "doc_type": "",
        "keywords": [],
    }


@dataclass
class ExtractedMetadata:
    """Extracted metadata structure"""
    # Category info (from path)
    category: str = ""
    subcategory: str = ""
    level: str = ""

    # Document info (from filename)
    seq: str = ""
    title: str = ""
    standard_no: str = ""

    # Parser info (from content)
    parser: str = ""
    parse_time: str = ""

    # LLM inferred
    doc_type: str = ""
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = {}
        if self.category:
            result["category"] = self.category
        if self.subcategory:
            result["subcategory"] = self.subcategory
        if self.level:
            result["level"] = self.level
        if self.seq:
            result["seq"] = self.seq
        if self.title:
            result["title"] = self.title
        if self.standard_no:
            result["standard_no"] = self.standard_no
        if self.parser:
            result["parser"] = self.parser
        if self.parse_time:
            result["parse_time"] = self.parse_time
        if self.doc_type:
            result["doc_type"] = self.doc_type
        if self.keywords:
            result["keywords"] = self.keywords
        return result


class MetadataExtractor:
    """Extract metadata from file path, filename, and content"""

    # Filename patterns
    SEQ_TITLE_PATTERN = re.compile(r'^(\d{2})[\s　]+(.+)$')
    STANDARD_NO_PATTERN = re.compile(r'([A-Z]{2,4}[/\-]?\d{4,}(?:\-\d+)?)', re.IGNORECASE)
    BOOK_TITLE_PATTERN = re.compile(r'^[《<](.+)[》>]$')

    # Parser patterns in Markdown
    PARSER_PATTERN = re.compile(r'<!--\s*解析器:\s*(\w+)\s*-->')
    PARSE_TIME_PATTERN = re.compile(r'<!--\s*解析耗时:\s*([\d.]+)s\s*-->')

    @classmethod
    def extract(cls, file_path: Path, content: Optional[str] = None) -> ExtractedMetadata:
        """
        Extract all metadata from file

        Args:
            file_path: File path
            content: Optional file content for parser info extraction

        Returns:
            ExtractedMetadata object
        """
        metadata = ExtractedMetadata()

        # Extract from path
        cls._extract_from_path(file_path, metadata)

        # Extract from filename
        cls._extract_from_filename(file_path, metadata)

        # Extract from content
        if content:
            cls._extract_from_content(content, metadata)

        return metadata

    @classmethod
    def _extract_from_path(cls, file_path: Path, metadata: ExtractedMetadata) -> None:
        """Extract category info from directory path"""
        # Find the _doc_md directory as base
        parts = file_path.parts
        try:
            doc_md_idx = parts.index("_doc_md")
            rel_parts = parts[doc_md_idx + 1:-1]  # Exclude filename
        except ValueError:
            # No _doc_md in path, use all parts
            rel_parts = parts[:-1]

        if not rel_parts:
            return

        # Build path string for mapping
        path_str = "/".join(rel_parts)

        # Try exact match first
        for pattern, (category, subcategory, level) in CATEGORY_MAPPING.items():
            if path_str == pattern or path_str.startswith(pattern + "/"):
                metadata.category = category
                metadata.subcategory = subcategory
                metadata.level = level
                return

        # Try partial match (first directory)
        first_dir = rel_parts[0] if rel_parts else ""
        for pattern, (category, subcategory, level) in CATEGORY_MAPPING.items():
            if pattern.startswith(first_dir):
                metadata.category = category
                metadata.subcategory = subcategory
                metadata.level = level
                return

    @classmethod
    def _extract_from_filename(cls, file_path: Path, metadata: ExtractedMetadata) -> None:
        """Extract sequence number and title from filename"""
        stem = file_path.stem

        # Remove common suffixes
        for suffix in ["_minerU_parsed", "_parsed", "_converted", "_md"]:
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break

        # Try to match "XX Title" pattern
        match = cls.SEQ_TITLE_PATTERN.match(stem)
        if match:
            metadata.seq = match.group(1)
            title = match.group(2).strip()
        else:
            title = stem.strip()

        # Extract standard number if present
        std_match = cls.STANDARD_NO_PATTERN.search(title)
        if std_match:
            metadata.standard_no = std_match.group(1)

        # Clean up title
        title = cls.BOOK_TITLE_PATTERN.sub(r'\1', title)
        title = re.sub(r'\s+', ' ', title).strip()

        metadata.title = title

    @classmethod
    def _extract_from_content(cls, content: str, metadata: ExtractedMetadata) -> None:
        """Extract parser info from Markdown content"""
        # Extract parser name
        parser_match = cls.PARSER_PATTERN.search(content)
        if parser_match:
            metadata.parser = parser_match.group(1)

        # Extract parse time
        time_match = cls.PARSE_TIME_PATTERN.search(content)
        if time_match:
            metadata.parse_time = time_match.group(1)

    @classmethod
    async def infer_doc_type_with_llm(cls, title: str, content: str = "") -> Dict[str, Any]:
        """
        Use LLM Flash to infer doc_type from title

        Args:
            title: Document title
            content: Optional content sample

        Returns:
            Dict with doc_type and keywords
        """
        from app.infrastructure.llm.factory import create_flash_llm

        llm = create_flash_llm(max_tokens=100, temperature=0.1)

        content_sample = content[:500] if content else ""

        prompt = f"""Analyze the following document title and infer its type.

Title: {title}

Content sample: {content_sample}

Output the typed JSON object with exactly these fields:
{{"doc_type": "textbook|guide|policy|standard|case|report", "keywords": ["keyword1", "keyword2"]}}

Doc type rules:
- textbook: Educational materials, textbooks, tutorials
- guide: Guidelines, manuals, operation guides
- policy: Laws, regulations, policies, notices
- standard: Technical standards, specifications (GB, CJJ, etc.)
- case: Planning cases, design examples, project reports
- report: General reports, analysis documents

Output the object only, no explanation."""

        try:
            from app.infrastructure.llm.structured import run_structured_output

            proposal = await run_structured_output(
                DocumentTypeProposal,
                [{"role": "user", "content": prompt}],
                llm=llm,
                max_retries=1,
            )
            keywords = list(dict.fromkeys(
                str(keyword).strip()[:80]
                for keyword in proposal.keywords
                if str(keyword).strip()
            ))
            return {
                "status": "accepted",
                "doc_type": proposal.doc_type,
                "keywords": keywords,
            }
        except Exception as e:
            logger.warning(f"[MetadataExtractor] LLM inference failed: {e}")
        return _pending_doc_type_result("structured_document_type_unavailable")


__all__ = [
    "MetadataExtractor",
    "ExtractedMetadata",
    "DocumentTypeProposal",
    "CATEGORY_MAPPING",
]
