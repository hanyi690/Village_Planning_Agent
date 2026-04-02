"""
知识库增量管理器

支持单个文档的增量增删，无需每次全量重建向量库。

核心功能：
1. add_document() - 增量添加单个文档
2. delete_document() - 删除指定文档
3. list_documents() - 列出知识库中的文档
4. rebuild_index() - 仅重建文档索引

使用 ChromaDB 原生 API：
- collection.add() 增量插入
- collection.delete(where={"source": name}) 删除
"""

import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.rag.config import (
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    DATA_DIR,
)
from src.rag.core.cache import get_vector_cache
from src.rag.core.context_manager import DocumentContextManager
from src.rag.utils.loaders import load_documents_from_directory, _create_loader, FileTypeDetector
from src.rag.metadata.injector import MetadataInjector
from src.rag.slicing.strategies import SlicingStrategyFactory
from src.utils.logger import get_logger

logger = get_logger(__name__)


class KnowledgeBaseManager:
    """
    知识库增量管理器
    
    支持单个文档的增删操作，避免全量重建。
    """
    
    def __init__(self):
        """初始化管理器"""
        self.cache = get_vector_cache()
        self.context_manager = DocumentContextManager()
        self._text_splitter = None
    
    @property
    def vectorstore(self):
        """获取向量数据库"""
        return self.cache.get_vectorstore()
    
    @property
    def embedding_model(self):
        """获取 Embedding 模型"""
        return self.cache.get_embedding_model()
    
    @property
    def text_splitter(self):
        """获取文本分割器（延迟初始化）"""
        if self._text_splitter is None:
            self._text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                length_function=len,
                add_start_index=True,
            )
        return self._text_splitter
    
    def list_documents(self) -> List[Dict[str, Any]]:
        """
        列出知识库中的所有文档
        
        Returns:
            文档信息列表，包含 source, chunk_count, doc_type 等
        """
        try:
            # 从 ChromaDB 获取所有文档的元数据
            collection = self.vectorstore._collection
            
            # 获取所有文档
            results = collection.get(include=["metadatas"])
            
            if not results or not results.get("ids"):
                return []
            
            # 按来源分组统计
            doc_stats: Dict[str, Dict] = {}
            
            for idx, doc_id in enumerate(results["ids"]):
                metadata = results["metadatas"][idx] if results.get("metadatas") else {}
                source = metadata.get("source", "unknown")
                
                if source not in doc_stats:
                    doc_stats[source] = {
                        "source": source,
                        "chunk_count": 0,
                        "doc_type": metadata.get("document_type", metadata.get("type", "unknown")),
                        # 元数据字段（新增）
                        # ChromaDB 存储为逗号分隔的字符串，需解析回列表
                        "dimension_tags": metadata.get("dimension_tags", "").split(",") if metadata.get("dimension_tags") else [],
                        "terrain": metadata.get("terrain"),  # None if not set
                        "regions": metadata.get("regions", "").split(",") if metadata.get("regions") else [],
                        "category": metadata.get("category", "policies"),
                    }
                doc_stats[source]["chunk_count"] += 1
            
            return list(doc_stats.values())
            
        except Exception as e:
            logger.error(f"列出文档失败: {e}")
            return []
    
    def add_document(
        self,
        file_path: str,
        category: Optional[str] = None,
        skip_summary: bool = True,
        # 新增：手动指定的元数据（若不指定则自动标注）
        doc_type: Optional[str] = None,
        dimension_tags: Optional[list[str]] = None,
        terrain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        增量添加单个文档到知识库
        
        Args:
            file_path: 文档路径
            category: 文档类别 (policies/cases)，用于分类管理
            skip_summary: 是否跳过摘要生成（默认跳过以加速）
            
        Returns:
            添加结果，包含 status, chunks_added, message 等
        """
        path = Path(file_path)
        
        if not path.exists():
            return {
                "status": "error",
                "message": f"文件不存在: {file_path}"
            }
        
        source_name = path.name
        
        # 检查是否已存在
        existing = self._check_document_exists(source_name)
        if existing:
            logger.warning(f"  文档已存在，将先删除旧版本: {source_name}")
            self.delete_document(source_name)
        
        try:
            logger.info(f"处理文档: {source_name}")
            
            # 1. 检测文件类型
            real_type = FileTypeDetector.detect(path)
            logger.info(f"类型: {real_type}")
            
            # 2. 加载文档
            loader = _create_loader(path, real_type, category=category)
            if loader is None:
                return {
                    "status": "error",
                    "message": f"不支持的文件类型: {real_type}"
                }
            
            documents = loader.load()
            if not documents:
                return {
                    "status": "error",
                    "message": "文档内容为空或无法解析"
                }
            
            logger.info(f"加载了 {len(documents)} 个文档片段")
            
            # 3. 合并文档内容
            full_content = "\n\n".join(doc.page_content for doc in documents)
            
            # 4. 切分文档
            splits = self.text_splitter.split_text(full_content)
            logger.info(f"切分为 {len(splits)} 个片段")
            
            # 5. 创建 Document 对象并添加元数据
            split_docs = []
            for idx, split in enumerate(splits):
                # 计算起始位置
                start_index = full_content.find(split) if idx == 0 else 0
                
                doc = Document(
                    page_content=split,
                    metadata={
                        "source": source_name,
                        "type": real_type,
                        "chunk_index": idx,
                        "total_chunks": len(splits),
                        "category": category or "policies",
                        "start_index": start_index,
                        "file_hash": self._compute_file_hash(path),
                    }
                )
                split_docs.append(doc)
            
            # 6. 注入元数据（新增：维度标签、地形类型等）
            # 若用户手动指定了元数据则使用手动指定的，否则自动标注
            logger.info("   注入元数据...")
            injector = MetadataInjector()
            injector.inject_batch(
                split_docs,
                category=category,
                doc_type=doc_type,
                dimension_tags=dimension_tags,
                terrain=terrain,
            )

            # 打印元数据信息
            injected_dimension_tags = set()
            injected_terrains = set()
            for doc in split_docs:
                # ChromaDB 存储为逗号分隔的字符串，需解析回列表
                dim_tags = doc.metadata.get("dimension_tags", "")
                if isinstance(dim_tags, str):
                    dim_tags = dim_tags.split(",") if dim_tags else []
                injected_dimension_tags.update(dim_tags)
                injected_terrains.add(doc.metadata.get("terrain", "all"))

            logger.info(f"维度标签：{list(injected_dimension_tags)}")
            logger.info(f"地形类型：{list(injected_terrains)}")

            # 7. 增量添加到 ChromaDB
            self.vectorstore.add_documents(split_docs)
            logger.info(f"已添加 {len(split_docs)} 个向量")
            
            # 7. 更新文档索引
            self._update_document_index(source_name, documents, split_docs)
            
            # 8. 清除查询缓存
            self.cache.clear_cache()
            
            return {
                "status": "success",
                "message": f"成功添加文档: {source_name}",
                "source": source_name,
                "chunks_added": len(split_docs),
                "doc_type": real_type,
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "message": f"添加文档失败: {str(e)}"
            }
    
    def delete_document(self, source_name: str) -> Dict[str, Any]:
        """
        从知识库删除指定文档
        
        Args:
            source_name: 文档名称（文件名）
            
        Returns:
            删除结果
        """
        try:
            # 检查文档是否存在
            if not self._check_document_exists(source_name):
                return {
                    "status": "warning",
                    "message": f"文档不存在: {source_name}"
                }
            
            logger.info(f"删除文档: {source_name}")
            
            # 1. 从 ChromaDB 删除
            collection = self.vectorstore._collection
            
            # 根据元数据过滤删除
            collection.delete(
                where={"source": source_name}
            )
            
            logger.info(f"已从向量库删除")
            
            # 2. 从文档索引删除
            self._remove_from_index(source_name)
            
            # 3. 清除查询缓存
            self.cache.clear_cache()
            
            return {
                "status": "success",
                "message": f"成功删除文档: {source_name}",
                "source": source_name,
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "message": f"删除文档失败: {str(e)}"
            }
    
    def rebuild_index(self) -> Dict[str, Any]:
        """
        重建文档索引（不重建向量）
        
        当 document_index.json 丢失或损坏时使用。
        
        Returns:
            重建结果
        """
        try:
            logger.info("重建文档索引...")
            
            # 从 DATA_DIR 重新加载所有文档
            documents = load_documents_from_directory(DATA_DIR)
            
            if not documents:
                return {
                    "status": "warning",
                    "message": "没有找到文档"
                }
            
            # 获取向量库中的切片
            collection = self.vectorstore._collection
            results = collection.get(include=["documents", "metadatas"])
            
            # 重建索引
            splits = []
            if results and results.get("ids"):
                for idx, doc_id in enumerate(results["ids"]):
                    content = results["documents"][idx] if results.get("documents") else ""
                    metadata = results["metadatas"][idx] if results.get("metadatas") else {}
                    
                    splits.append(Document(
                        page_content=content,
                        metadata=metadata
                    ))
            
            # 使用 context_manager 重建索引
            self.context_manager.build_index(documents, splits)
            self.context_manager.save()
            
            logger.info(f"索引重建完成")
            
            return {
                "status": "success",
                "message": "文档索引重建完成",
                "documents": len(documents),
                "splits": len(splits),
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "message": f"重建索引失败: {str(e)}"
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取知识库统计信息
        
        Returns:
            统计信息
        """
        try:
            docs = self.list_documents()
            cache_stats = self.cache.get_cache_stats()
            
            total_chunks = sum(d["chunk_count"] for d in docs)
            
            return {
                "total_documents": len(docs),
                "total_chunks": total_chunks,
                "documents": docs,
                "cache": cache_stats,
                "vector_db_path": str(CHROMA_PERSIST_DIR),
                "source_dir": str(DATA_DIR),
            }
            
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _check_document_exists(self, source_name: str) -> bool:
        """检查文档是否已存在于知识库"""
        docs = self.list_documents()
        return any(d["source"] == source_name for d in docs)
    
    def _compute_file_hash(self, file_path: Path) -> str:
        """计算文件 MD5 哈希"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()[:8]
    
    def _update_document_index(
        self,
        source_name: str,
        original_docs: List[Document],
        split_docs: List[Document]
    ) -> None:
        """更新文档索引"""
        try:
            # 确保 context_manager 已加载
            self.context_manager._ensure_loaded()
            
            # 添加新文档索引
            from src.rag.core.context_manager import DocumentIndex, ChunkInfo
            
            chunks_info = []
            for idx, split in enumerate(split_docs):
                chunks_info.append(ChunkInfo(
                    chunk_index=idx,
                    start_index=split.metadata.get("start_index", 0),
                    content_preview=split.page_content[:100] + "..." if len(split.page_content) > 100 else split.page_content,
                ))
            
            # 确定 doc_type
            doc_type = split_docs[0].metadata.get("type", "unknown") if split_docs else "unknown"
            
            self.context_manager.doc_index[source_name] = DocumentIndex(
                source=source_name,
                doc_type=doc_type,
                total_chunks=len(split_docs),
                chunks_info=chunks_info,
            )
            
            self.context_manager.save()
            logger.info(f"文档索引已更新")
            
        except Exception as e:
            logger.warning(f"  更新索引失败: {e}")
    
    def _remove_from_index(self, source_name: str) -> None:
        """从文档索引中删除"""
        try:
            if source_name in self.context_manager.doc_index:
                del self.context_manager.doc_index[source_name]
                self.context_manager.save()
                logger.info(f"已从索引删除")
        except Exception as e:
            logger.warning(f"  从索引删除失败: {e}")


# 全局实例
_kb_manager = None


def get_kb_manager() -> KnowledgeBaseManager:
    """获取知识库管理器单例"""
    global _kb_manager
    if _kb_manager is None:
        _kb_manager = KnowledgeBaseManager()
    return _kb_manager


if __name__ == "__main__":
    # 测试
    manager = KnowledgeBaseManager()

    logger.info("知识库统计:")
    stats = manager.get_stats()
    logger.info(f"文档数: {stats.get('total_documents', 0)}")
    logger.info(f"切片数: {stats.get('total_chunks', 0)}")

    logger.info("文档列表:")
    for doc in stats.get("documents", []):
        logger.info(f"- {doc['source']}: {doc['chunk_count']} 切片")
