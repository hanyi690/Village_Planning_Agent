"""
元数据注入器

在文档入库时自动注入结构化元数据，支持维度标签、地形类型、文档类型等自动识别。
支持关键词标注（快速）和语义标注（精准）两种模式。
"""
from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field
from langchain_core.documents import Document
import asyncio

from .tagging_rules import (
    DimensionTagger,
    TerrainTagger,
    DocumentTypeTagger,
    extract_regions_from_text,
)
from .semantic_tagger import get_semantic_tagger


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
    # 计算结果（处理过程中填充）
    dimension_tags: List[str] = field(default_factory=list)
    terrain: str = "all"
    doc_type: str = ""
    regions: List[str] = field(default_factory=list)


class MetadataInjector:
    """
    元数据注入器

    在文档切片入库时，自动为每个切片注入结构化元数据。

    元数据字段：
    - dimension_tags: 适用的分析维度列表
    - terrain: 地形类型（mountain/plain/hill/coastal/riverside/all）
    - document_type: 文档类型（policy/standard/case/guide/report）
    - source: 来源文件路径
    - category: 知识类别（policies/cases/standards/domain/local）
    - chunk_index: 切片在文档中的索引
    - total_chunks: 文档总切片数
    - regions: 涉及的地区列表

    支持两种标注模式：
    - use_semantic=False: 关键词匹配（快速，适合批量处理）
    - use_semantic=True: Flash模型语义标注（精准，适合重要文档）
    """

    def __init__(self, use_semantic: bool = False):
        self.dimension_tagger = DimensionTagger()
        self.terrain_tagger = TerrainTagger()
        self.doc_type_tagger = DocumentTypeTagger()
        self.semantic_tagger = get_semantic_tagger() if use_semantic else None
        self.use_semantic = use_semantic

    def _prepare_common_fields(self, params: InjectionParams) -> None:
        """填充共享字段：terrain, doc_type, regions"""
        source = params.doc.metadata.get("source", "")
        content = params.doc.page_content
        analysis_content = params.full_content if params.idx == 0 and params.full_content else content

        # 地形检测
        params.terrain = self.terrain_tagger.detect_terrain(analysis_content)
        if params.terrain == "all":
            params.terrain = self.terrain_tagger.detect_terrain_from_filename(source)

        # 文档类型检测
        params.doc_type = self.doc_type_tagger.detect_doc_type(content=analysis_content, filename=source)

        # 地区识别
        if params.idx == 0:
            params.regions = extract_regions_from_text(analysis_content)

    def _inject_core(self, params: InjectionParams) -> Document:
        """核心注入逻辑 - 共享于 sync/async 方法"""
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
        """同步注入（关键词标注）"""
        source = params.doc.metadata.get("source", "")
        content = params.doc.page_content
        analysis_content = params.full_content if params.idx == 0 and params.full_content else content

        # 维度标注（关键词）
        params.dimension_tags = self.dimension_tagger.detect_dimensions(analysis_content)

        # 添加文件名检测的维度
        filename_dims = self.dimension_tagger.detect_dimensions_for_filename(source)
        for dim in filename_dims:
            if dim not in params.dimension_tags and dim != "general":
                params.dimension_tags.append(dim)

        self._prepare_common_fields(params)
        return self._inject_core(params)

    async def inject_async(self, params: InjectionParams, use_semantic: Optional[bool] = None) -> Document:
        """异步注入（可选语义标注）"""
        should_use_semantic = use_semantic if use_semantic is not None else self.use_semantic
        source = params.doc.metadata.get("source", "")
        content = params.doc.page_content
        analysis_content = params.full_content if params.idx == 0 and params.full_content else content

        # 维度标注（语义或关键词）
        if should_use_semantic and self.semantic_tagger and not params.manual_dimension_tags:
            params.dimension_tags = await self.semantic_tagger.tag_chunk_async(content)
        else:
            params.dimension_tags = self.dimension_tagger.detect_dimensions(analysis_content)

        # 添加文件名检测的维度
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
        """批量异步注入元数据（支持语义标注）"""
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
        """批量注入元数据"""
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


class CategoryDetector:
    """文档类别检测器"""

    from src.core.config import KB_CATEGORIES

    CATEGORY_KEYWORDS: Dict[str, List[str]] = {
        "policies": ["政策", "policy", "十四五", "乡村", "振兴", "战略", "规划"],
        "standards": ["标准", "standard", "规范", "规程", "GB", "DB", "技术"],
        "cases": ["案例", "case", "示范", "典型", "经验", "模式"],
        "domain": ["领域", "domain", "专业", "专项", "交通", "生态", "水利"],
        "local": ["本地", "local", "实地", "调研", "访谈", "问卷"],
    }

    @staticmethod
    def detect_from_path(file_path: Path) -> str:
        """从文件路径检测类别"""
        path_str = str(file_path).lower()

        for category in KB_CATEGORIES:
            if f"/{category}/" in path_str or f"\\{category}\\" in path_str:
                return category

        filename = file_path.name
        for category, keywords in CategoryDetector.CATEGORY_KEYWORDS.items():
            if any(kw in filename for kw in keywords):
                return category

        return "policies"

    @staticmethod
    def detect_from_directory(data_dir: Path) -> Dict[str, List[Path]]:
        """扫描目录，按类别分组文件"""
        result: Dict[str, List[Path]] = {
            "policies": [],
            "standards": [],
            "cases": [],
            "domain": [],
            "local": [],
        }

        if not data_dir.exists():
            return result

        extensions = [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".md"]

        for ext in extensions:
            for file_path in data_dir.rglob(f"*{ext}"):
                category = CategoryDetector.detect_from_path(file_path)
                result[category].append(file_path)

        return {k: v for k, v in result.items() if v}