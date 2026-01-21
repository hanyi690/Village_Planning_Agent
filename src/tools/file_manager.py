"""
村庄数据管理器 - 统一文件和数据处理入口

提供智能数据加载接口，支持多种文件格式和数据源：
- 本地文件（txt, pdf, docx, md, pptx, xlsx等）
- 纯文本（直接传入）
- RAG知识库集成
"""

from typing import Dict, Any, List, Union, Optional
from pathlib import Path
from ..utils.logger import get_logger

logger = get_logger(__name__)

# 延迟导入RAG模块，避免导入错误影响基础功能
_rag_loaders = None

def _get_rag_loaders():
    """延迟导入RAG加载器"""
    global _rag_loaders
    if _rag_loaders is None:
        try:
            from ..knowledge.rag import load_single_document, SUPPORTED_EXTENSIONS
            _rag_loaders = {
                "load_single_document": load_single_document,
                "SUPPORTED_EXTENSIONS": SUPPORTED_EXTENSIONS
            }
        except ImportError as e:
            logger.warning(f"[FileManager] RAG模块导入失败，部分功能不可用: {e}")
            _rag_loaders = {"error": str(e)}
    return _rag_loaders


class VillageDataManager:
    """
    村庄数据管理器

    统一的数据加载和处理接口，支持多种数据源和文件格式。
    """

    def __init__(self):
        """初始化数据管理器"""
        self.logger = logger

    def load_data(
        self,
        source: Union[str, Path],
        source_type: Optional[str] = None,
        validate: bool = True,
        extract_metadata: bool = True
    ) -> Dict[str, Any]:
        """
        统一数据加载接口

        支持的数据源：
        - 本地文件（txt, pdf, docx, md, pptx, xlsx等）- 自动检测格式
        - 纯文本（直接传入）
        - RAG知识库（集成现有rag.py）

        Args:
            source: 数据源，可以是文件路径或纯文本内容
            source_type: 数据源类型（可选），如果不提供则自动检测
            validate: 是否验证数据有效性
            extract_metadata: 是否提取元数据

        Returns:
            Dict 包含：
            - success (bool): 是否成功
            - content (str): 提取的文本内容
            - metadata (dict): 来源、类型、长度等
            - error (str): 失败时的错误信息

        Example:
            >>> manager = VillageDataManager()
            >>>
            >>> # 从文件加载
            >>> result = manager.load_data("data/village.pdf")
            >>> if result["success"]:
            >>>     print(result["content"])
            >>>
            >>> # 从文本加载
            >>> result = manager.load_data("人口：1200人\\n面积：5.2平方公里")
            >>> print(result["content"])
        """
        # 自动检测数据源类型
        detected_type = self._detect_source_type(source) if source_type is None else source_type

        if detected_type == "file":
            return self._load_from_file(source, extract_metadata=extract_metadata)
        elif detected_type == "text":
            return self._load_from_text(source, extract_metadata=extract_metadata)
        else:
            return {
                "success": False,
                "content": "",
                "metadata": {},
                "error": f"无法识别的数据源类型: {detected_type}"
            }

    def _detect_source_type(self, source: Union[str, Path]) -> str:
        """
        智能检测数据源类型

        检测逻辑：
        1. 如果看起来像文件路径且文件存在 -> file
        2. 如果内容较短且包含换行符 -> 可能是文本
        3. 否则 -> text
        """
        source_str = str(source).strip()

        # 检查是否为文件路径
        if len(source_str) < 200:  # 文件路径通常不会太长
            # 检查是否为路径格式
            if ("\\" in source_str or "/" in source_str) and "." in source_str:
                # 尝试作为路径解析
                try:
                    path = Path(source_str)
                    if path.exists() and path.is_file():
                        return "file"
                except:
                    pass

        # 默认当作文本处理
        return "text"

    def _load_from_file(
        self,
        file_path: Union[str, Path],
        extract_metadata: bool = True
    ) -> Dict[str, Any]:
        """
        从文件加载数据

        Args:
            file_path: 文件路径
            extract_metadata: 是否提取元数据

        Returns:
            加载结果字典
        """
        try:
            # 获取RAG加载器
            rag_loaders = _get_rag_loaders()
            if "error" in rag_loaders:
                return {
                    "success": False,
                    "content": "",
                    "metadata": {},
                    "error": f"文档加载器不可用，请检查依赖: {rag_loaders['error']}"
                }

            load_single_document = rag_loaders["load_single_document"]
            SUPPORTED_EXTENSIONS = rag_loaders["SUPPORTED_EXTENSIONS"]

            path = Path(file_path)

            # 检查文件是否存在
            if not path.exists():
                return {
                    "success": False,
                    "content": "",
                    "metadata": {},
                    "error": f"文件不存在: {file_path}"
                }

            # 检查文件格式是否支持
            ext = path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                return {
                    "success": False,
                    "content": "",
                    "metadata": {},
                    "error": f"不支持的文件格式: {ext}。支持格式: {list(SUPPORTED_EXTENSIONS.keys())}"
                }

            self.logger.info(f"[FileManager] 正在加载文件: {file_path}")

            # 使用RAG系统的文档加载器
            documents = load_single_document(str(path))

            if not documents:
                return {
                    "success": False,
                    "content": "",
                    "metadata": {},
                    "error": f"无法从文件提取内容: {file_path}"
                }

            # 提取文本内容
            content = "\n\n".join(doc.page_content for doc in documents)

            # 构建元数据
            metadata = {}
            if extract_metadata:
                metadata = {
                    "filename": path.name,
                    "filepath": str(path.absolute()),
                    "extension": ext,
                    "size": len(content),
                    "file_size": path.stat().st_size if path.exists() else 0,
                    "type": "file"
                }

            self.logger.info(f"[FileManager] 文件加载成功: {metadata.get('filename', 'unknown')}, {len(content)} 字符")

            return {
                "success": True,
                "content": content,
                "metadata": metadata,
                "error": ""
            }

        except Exception as e:
            self.logger.error(f"[FileManager] 文件加载失败: {str(e)}")
            return {
                "success": False,
                "content": "",
                "metadata": {},
                "error": f"文件加载失败: {str(e)}"
            }

    def _load_from_text(
        self,
        text: str,
        extract_metadata: bool = True
    ) -> Dict[str, Any]:
        """
        从纯文本加载数据

        Args:
            text: 文本内容
            extract_metadata: 是否提取元数据

        Returns:
            加载结果字典
        """
        try:
            if not text or not text.strip():
                return {
                    "success": False,
                    "content": "",
                    "metadata": {},
                    "error": "文本内容为空"
                }

            content = text.strip()

            # 构建元数据
            metadata = {}
            if extract_metadata:
                metadata = {
                    "size": len(content),
                    "line_count": len(content.split("\n")),
                    "type": "text"
                }

            self.logger.info(f"[FileManager] 文本加载成功: {len(content)} 字符")

            return {
                "success": True,
                "content": content,
                "metadata": metadata,
                "error": ""
            }

        except Exception as e:
            self.logger.error(f"[FileManager] 文本加载失败: {str(e)}")
            return {
                "success": False,
                "content": "",
                "metadata": {},
                "error": f"文本加载失败: {str(e)}"
            }

    def batch_load_files(
        self,
        file_paths: List[Union[str, Path]],
        merge: bool = False
    ) -> Dict[str, Any]:
        """
        批量加载文件

        Args:
            file_paths: 文件路径列表
            merge: 是否合并所有文件内容

        Returns:
            批量加载结果字典
        """
        results = []
        all_content = []
        errors = []

        for file_path in file_paths:
            result = self.load_data(file_path)
            results.append(result)

            if result["success"]:
                all_content.append(f"# 文件: {result['metadata'].get('filename', 'unknown')}\n\n{result['content']}")
            else:
                errors.append(f"{file_path}: {result['error']}")

        if merge:
            merged_content = "\n\n" + "="*80 + "\n\n".join(all_content) if all_content else ""
            return {
                "success": len(all_content) > 0,
                "content": merged_content,
                "metadata": {
                    "file_count": len(all_content),
                    "total_size": len(merged_content),
                    "type": "batch",
                    "errors": errors
                },
                "error": "" if len(all_content) > 0 else "所有文件加载失败"
            }
        else:
            return {
                "success": len(all_content) > 0,
                "results": results,
                "metadata": {
                    "total_files": len(file_paths),
                    "success_count": len(all_content),
                    "error_count": len(errors)
                },
                "error": "" if len(all_content) > 0 else "所有文件加载失败"
            }

    def add_to_rag(
        self,
        source: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        添加数据到RAG知识库

        Args:
            source: 数据源（文件路径或文本）
            metadata: 额外的元数据

        Returns:
            添加结果字典
        """
        try:
            # 延迟导入RAG函数
            from ..knowledge.rag import add_single_document, add_texts

            detected_type = self._detect_source_type(source)

            if detected_type == "file":
                self.logger.info(f"[FileManager] 添加文件到RAG: {source}")
                result = add_single_document(str(source))
                return result
            elif detected_type == "text":
                self.logger.info(f"[FileManager] 添加文本到RAG: {len(str(source))} 字符")
                result = add_texts([str(source)], metadatas=[metadata or {}])
                return result
            else:
                return {
                    "status": "error",
                    "message": f"无法识别的数据源类型: {detected_type}"
                }

        except Exception as e:
            self.logger.error(f"[FileManager] 添加到RAG失败: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }


# ==========================================
# 便捷函数
# ==========================================

def read_village_data(source: Union[str, Path], source_type: Optional[str] = None) -> str:
    """
    便捷接口：读取村庄数据（向后兼容）

    Args:
        source: 数据源（文件路径或文本内容）
        source_type: 数据源类型（可选）

    Returns:
        str: 提取的文本内容，失败时返回空字符串

    Example:
        >>> # 从文件读取
        >>> data = read_village_data("data/village.txt")
        >>>
        >>> # 直接传入文本
        >>> data = read_village_data("人口：1200人")
    """
    manager = VillageDataManager()
    result = manager.load_data(source, source_type=source_type)

    if result["success"]:
        return result["content"]
    else:
        logger.error(f"[FileManager] 读取村庄数据失败: {result['error']}")
        return ""


def load_data_with_metadata(source: Union[str, Path]) -> Dict[str, Any]:
    """
    新版接口：读取数据并返回完整元数据

    Args:
        source: 数据源（文件路径或文本内容）

    Returns:
        Dict: 包含success, content, metadata, error的完整信息

    Example:
        >>> data = load_data_with_metadata("data/village.pdf")
        >>> if data["success"]:
        >>>     print(f"加载了 {data['metadata']['size']} 字符")
        >>>     content = data["content"]
    """
    manager = VillageDataManager()
    return manager.load_data(source)


__all__ = [
    "VillageDataManager",
    "read_village_data",
    "load_data_with_metadata",
]
