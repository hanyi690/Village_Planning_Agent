"""
元数据注入器

在文档入库时自动注入结构化元数据，支持维度标签、地形类型、文档类型等自动识别。
支持关键词标注（快速）和语义标注（精准）两种模式。

来源：src/rag/metadata/injector.py
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from langchain_core.documents import Document
import asyncio

from ..config.document_types import (
    DimensionTagger,
    TerrainTagger,
    DocumentTypeTagger,
    extract_regions_from_text,
)
from ..utils.semantic_tagger import get_semantic_tagger


@dataclass
class InjectionParams:
    """元数据注入参数封装"""
    doc: Document
    full_content: str = ""
    idx: int = 0
    total: int = 1
    category: Optional[str] = None
    manual_doc_type: Optional[str] = None
    manual_dimension_tags: Optional[List[str]] = None
    manual_terrain: Optional[str] = None
    dimension_tags: List[str] = field(default_factory=list)
    terrain: str = "all"
    doc_type: str = ""
    regions: List[str] = field(default_factory=list)


class MetadataInjector:
    """元数据注入器"""

    def __init__(self, use_semantic: bool = False):
        self.dimension_tagger = DimensionTagger()
        self.terrain_tagger = TerrainTagger()
        self.doc_type_tagger = DocumentTypeTagger()
        self.semantic_tagger = get_semantic_tagger() if use_semantic else None
        self.use_semantic = use_semantic

    def _prepare_common_fields(self, params: InjectionParams) -> None:
        source = params.doc.metadata.get("source", "")
        content = params.doc.page_content
        analysis_content = params.full_content if params.idx == 0 and params.full_content else content
        params.terrain = self.terrain_tagger.detect_terrain(analysis_content)
        if params.terrain == "all":
            params.terrain = self.terrain_tagger.detect_terrain_from_filename(source)
        params.doc_type = self.doc_type_tagger.detect_doc_type(content=analysis_content, filename=source)
        if params.idx == 0:
            params.regions = extract_regions_from_text(analysis_content)

    def _inject_core(self, params: InjectionParams) -> Document:
        source = params.doc.metadata.get("source", "")
        params.doc.metadata.update({
            "dimension_tags": ",".join(params.manual_dimension_tags) if params.manual_dimension_tags
                              else (",".join(params.dimension_tags) if params.dimension_tags else "general"),
            "terrain": params.manual_terrain if params.manual_terrain else params.terrain,
            "document_type": params.manual_doc_type if params.manual_doc_type else params.doc_type,
            "source": source,
            "category": params.category or params.doc.metadata.get("category", "policies"),
            "chunk_index": params.idx,
            "total_chunks": params.total,
            "regions": ",".join(params.regions) if params.regions else "",
        })
        return params.doc

    def inject(self, params: InjectionParams) -> Document:
        source = params.doc.metadata.get("source", "")
        content = params.doc.page_content
        analysis_content = params.full_content if params.idx == 0 and params.full_content else content
        params.dimension_tags = self.dimension_tagger.detect_dimensions(analysis_content)
        filename_dims = self.dimension_tagger.detect_dimensions_for_filename(source)
        for dim in filename_dims:
            if dim not in params.dimension_tags and dim != "general":
                params.dimension_tags.append(dim)
        self._prepare_common_fields(params)
        return self._inject_core(params)

    async def inject_async(self, params: InjectionParams, use_semantic: Optional[bool] = None) -> Document:
        should_use_semantic = use_semantic if use_semantic is not None else self.use_semantic
        source = params.doc.metadata.get("source", "")
        content = params.doc.page_content
        analysis_content = params.full_content if params.idx == 0 and params.full_content else content
        if should_use_semantic and self.semantic_tagger and not params.manual_dimension_tags:
            params.dimension_tags = await self.semantic_tagger.tag_chunk_async(content)
        else:
            params.dimension_tags = self.dimension_tagger.detect_dimensions(analysis_content)
        filename_dims = self.dimension_tagger.detect_dimensions_for_filename(source)
        for dim in filename_dims:
            if dim not in params.dimension_tags and dim != "general":
                params.dimension_tags.append(dim)
        self._prepare_common_fields(params)
        return self._inject_core(params)

    async def inject_batch_async(
        self,
        documents: List[Document],
        category: Optional[str] = None,
        use_semantic: Optional[bool] = None,
        doc_type: Optional[str] = None,
        dimension_tags: Optional[list[str]] = None,
        terrain: Optional[str] = None,
    ) -> List[Document]:
        if not documents:
            return []
        full_content = "\n\n".join(doc.page_content for doc in documents)
        total = len(documents)
        tasks = [
            self.inject_async(
                InjectionParams(
                    doc=doc, full_content=full_content, idx=idx, total=total,
                    category=category,
                    manual_doc_type=doc_type,
                    manual_dimension_tags=dimension_tags,
                    manual_terrain=terrain,
                ),
                use_semantic=use_semantic,
            )
            for idx, doc in enumerate(documents)
        ]
        return await asyncio.gather(*tasks)

    def inject_batch(
        self,
        documents: List[Document],
        category: Optional[str] = None,
        doc_type: Optional[str] = None,
        dimension_tags: Optional[list[str]] = None,
        terrain: Optional[str] = None,
    ) -> List[Document]:
        if not documents:
            return []
        full_content = "\n\n".join(doc.page_content for doc in documents)
        total = len(documents)
        for idx, doc in enumerate(documents):
            params = InjectionParams(
                doc=doc, full_content=full_content, idx=idx, total=total,
                category=category,
                manual_doc_type=doc_type,
                manual_dimension_tags=dimension_tags,
                manual_terrain=terrain,
            )
            self.inject(params)
        return documents


__all__ = ["MetadataInjector", "InjectionParams"]