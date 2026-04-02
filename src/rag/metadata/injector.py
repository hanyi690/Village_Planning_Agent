"""
元数据注入器

在文档入库时自动注入结构化元数据，支持维度标签、地形类型、文档类型等自动识别。
"""
from typing import List, Dict, Any, Optional
from pathlib import Path
from langchain_core.documents import Document

from .tagging_rules import (
    DimensionTagger,
    TerrainTagger,
    DocumentTypeTagger,
    extract_regions_from_text,
)


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
    """

    def __init__(self):
        self.dimension_tagger = DimensionTagger()
        self.terrain_tagger = TerrainTagger()
        self.doc_type_tagger = DocumentTypeTagger()

    def inject(
        self,
        doc: Document,
        full_content: str = "",
        idx: int = 0,
        total: int = 1,
        category: Optional[str] = None,
        # 新增：手动指定的元数据（若不指定则自动标注）
        manual_doc_type: Optional[str] = None,
        manual_dimension_tags: Optional[list[str]] = None,
        manual_terrain: Optional[str] = None,
    ) -> Document:
        """
        为文档切片注入元数据

        Args:
            doc: 文档对象（会被修改）
            full_content: 完整文档内容（用于全局元数据识别）
            idx: 当前切片索引
            total: 总切片数
            category: 文档类别（policies/cases/standards/domain/local）

        Returns:
            注入元数据后的文档对象
        """
        source = doc.metadata.get("source", "")
        content = doc.page_content

        # 使用完整内容进行全局元数据识别（只对第一个切片）
        analysis_content = full_content if idx == 0 and full_content else content

        # 1. 维度标签识别
        dimension_tags = self.dimension_tagger.detect_dimensions(analysis_content)

        # 同时检查文件名
        filename_dims = self.dimension_tagger.detect_dimensions_for_filename(source)
        for dim in filename_dims:
            if dim not in dimension_tags and dim != "general":
                dimension_tags.append(dim)

        # 2. 地形类型识别
        terrain = self.terrain_tagger.detect_terrain(analysis_content)

        # 如果内容中未检测到地形，尝试从文件名识别
        if terrain == "all":
            terrain = self.terrain_tagger.detect_terrain_from_filename(source)

        # 3. 文档类型识别
        doc_type = self.doc_type_tagger.detect_doc_type(
            content=analysis_content,
            filename=source
        )

        # 4. 地区识别（只对第一个切片）
        regions = []
        if idx == 0:
            regions = extract_regions_from_text(analysis_content)

        # 更新元数据（ChromaDB 不支持列表类型，需转换为逗号分隔的字符串）
        doc.metadata.update({
            "dimension_tags": ",".join(manual_dimension_tags) if manual_dimension_tags else (",".join(dimension_tags) if dimension_tags else "general"),
            "terrain": manual_terrain if manual_terrain else terrain,
            "document_type": manual_doc_type if manual_doc_type else doc_type,
            "source": source,
            "category": category or doc.metadata.get("category", "policies"),
            "chunk_index": idx,
            "total_chunks": total,
            "regions": ",".join(regions) if regions else "",
        })

        return doc

    def inject_batch(
        self,
        documents: List[Document],
        category: Optional[str] = None,
        # 新增：手动指定的元数据
        doc_type: Optional[str] = None,
        dimension_tags: Optional[list[str]] = None,
        terrain: Optional[str] = None,
    ) -> List[Document]:
        """
        批量注入元数据

        Args:
            documents: 文档切片列表
            category: 文档类别
            doc_type: 文档类型（手动指定，可选）
            dimension_tags: 维度标签（手动指定，可选）
            terrain: 地形类型（手动指定，可选）

        Returns:
            注入元数据后的文档列表
        """
        if not documents:
            return []

        # 合并所有内容为完整文档（用于全局元数据识别）
        full_content = "\n\n".join(doc.page_content for doc in documents)
        total = len(documents)

        for idx, doc in enumerate(documents):
            self.inject(
                doc=doc,
                full_content=full_content,
                idx=idx,
                total=total,
                category=category,
                manual_doc_type=doc_type,
                manual_dimension_tags=dimension_tags,
                manual_terrain=terrain,
            )

        return documents


class CategoryDetector:
    """
    文档类别检测器

    基于目录结构和文件路径自动识别文档类别。

    支持的类别：
    - policies: 政策导向库
    - standards: 通用规范库
    - cases: 案例参考库
    - domain: 专业领域库
    - local: 本地实地库
    """

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
        """
        从文件路径检测类别

        Args:
            file_path: 文件路径

        Returns:
            类别标识，默认返回 "policies"
        """
        path_str = str(file_path).lower()

        # 检查是否包含类别目录
        for category in KB_CATEGORIES:
            if f"/{category}/" in path_str or f"\\{category}\\" in path_str:
                return category

        # 检查文件名是否包含类别关键词
        filename = file_path.name
        for category, keywords in CategoryDetector.CATEGORY_KEYWORDS.items():
            if any(kw in filename for kw in keywords):
                return category

        # 默认返回 policies
        return "policies"

    @staticmethod
    def detect_from_directory(data_dir: Path) -> Dict[str, List[Path]]:
        """
        扫描目录，按类别分组文件

        Args:
            data_dir: 数据目录

        Returns:
            {category: [file_paths]}
        """
        result: Dict[str, List[Path]] = {
            "policies": [],
            "standards": [],
            "cases": [],
            "domain": [],
            "local": [],
        }

        if not data_dir.exists():
            return result

        # 扫描所有支持的文件
        extensions = [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".md"]

        for ext in extensions:
            for file_path in data_dir.rglob(f"*{ext}"):
                category = CategoryDetector.detect_from_path(file_path)
                result[category].append(file_path)

        # 过滤空列表
        return {k: v for k, v in result.items() if v}
