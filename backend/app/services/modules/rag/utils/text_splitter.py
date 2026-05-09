"""
Text Splitter - 文本切片策略工厂

Provides adaptive slicing strategies for different document types.
"""

import logging
from typing import Dict, List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class SlicingStrategyFactory:
    """Factory for document slicing strategies based on document type"""

    # Default chunk sizes by document type
    _STRATEGIES = {
        'textbook': {'chunk_size': 1500, 'chunk_overlap': 200},
        'guide': {'chunk_size': 1200, 'chunk_overlap': 150},
        'policy': {'chunk_size': 1000, 'chunk_overlap': 100},
        'standard': {'chunk_size': 800, 'chunk_overlap': 100},
        'case': {'chunk_size': 1500, 'chunk_overlap': 200},
        'report': {'chunk_size': 1200, 'chunk_overlap': 150},
        'default': {'chunk_size': 1000, 'chunk_overlap': 100},
    }

    @classmethod
    def slice_document(
        cls,
        content: str,
        doc_type: str,
        metadata: Optional[Dict] = None,
    ) -> List[str]:
        """Slice document content into chunks

        Args:
            content: Full document text
            doc_type: Document type (textbook/guide/policy/standard/case/report)
            metadata: Optional metadata dict

        Returns:
            List of text chunks
        """
        strategy = cls._STRATEGIES.get(doc_type, cls._STRATEGIES['default'])

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=strategy['chunk_size'],
            chunk_overlap=strategy['chunk_overlap'],
            length_function=len,
            add_start_index=True,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )

        chunks = splitter.split_text(content)
        logger.info(f"[SlicingStrategyFactory] Split into {len(chunks)} chunks (type={doc_type})")
        return chunks


__all__ = ["SlicingStrategyFactory"]
