"""
村庄数据管理器 - 统一文件和数据处理入口

提供智能数据加载接口，支持多种文件格式和数据源：
- 本地文件（txt, pdf, docx, md, pptx, xlsx等）
- 纯文本（直接传入）
"""

from typing import Dict, Any, List, Union, Optional
from pathlib import Path
from ..utils.logger import get_logger

logger = get_logger(__name__)

# 支持的文件扩展名（从新 RAG 模块导入）
SUPPORTED_EXTENSIONS = {
    '.txt': 'text',
    '.md': 'markdown',
    '.pdf': 'pdf',
    '.docx': 'docx',
    '.doc': 'doc',
    '.pptx': 'pptx',
    '.ppt': 'ppt',
}


def _load_document_from_file(file_path: str) -> List[Any]:
    """
    使用新 RAG 模块的加载器加载文档
    
    Args:
        file_path: 文件路径
        
    Returns:
        Document 列表
    """
    from ..rag.utils.loaders import load_documents_from_directory, _create_loader
    from ..rag.utils.loaders import FileTypeDetector
    from pathlib import Path
    
    path = Path(file_path)
    real_type = FileTypeDetector.detect(path)
    
    loader = _create_loader(path, real_type, category=None)
    if loader is None:
        return []
    
    return loader.load()


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
        """智能检测数据源类型"""
        source_str = str(source).strip()

        # 检查是否为文件路径
        if len(source_str) < 200:
            if ("\\" in source_str or "/" in source_str) and "." in source_str:
                try:
                    path = Path(source_str)
                    if path.exists() and path.is_file():
                        return "file"
                except:
                    pass

        return "text"

    def _load_from_file(
        self,
        file_path: Union[str, Path],
        extract_metadata: bool = True
    ) -> Dict[str, Any]:
        """从文件加载数据"""
        try:
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

            # 使用新 RAG 模块的文档加载器
            documents = _load_document_from_file(str(path))

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
        """从纯文本加载数据"""
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
        """批量加载文件"""
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
    """
    manager = VillageDataManager()
    return manager.load_data(source)


__all__ = [
    "VillageDataManager",
    "read_village_data",
    "load_data_with_metadata",
    "SUPPORTED_EXTENSIONS",
]