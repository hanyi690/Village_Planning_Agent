from typing import List, Dict, Any, Optional, Union
from langchain import hub
from langchain_chroma import Chroma
from langchain_community.document_loaders import (
    WebBaseLoader,
    TextLoader,
    PyPDFLoader,
    Docx2txtLoader,
    UnstructuredMarkdownLoader,
    UnstructuredPowerPointLoader,
    UnstructuredExcelLoader,
)
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain.embeddings import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.messages import Document
import os
from pathlib import Path

from ..core.config import VECTOR_STORE_DIR, OPENAI_API_KEY, LLM_MODEL, MAX_TOKENS

# 确保环境变量
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# 全局变量
_embeddings = None
_vectorstore = None
_retriever = None
_rag_chain = None
_llm = None

# 支持的文档类型映射
SUPPORTED_EXTENSIONS = {
    '.txt': TextLoader,
    '.pdf': PyPDFLoader,
    '.docx': Docx2txtLoader,
    '.md': UnstructuredMarkdownLoader,
    '.pptx': UnstructuredPowerPointLoader,
    '.ppt': UnstructuredPowerPointLoader,
    '.xlsx': UnstructuredExcelLoader,
    '.xls': UnstructuredExcelLoader,
}

def get_embeddings():
    """获取嵌入模型实例"""
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings()
    return _embeddings

def get_llm():
    """获取LLM实例"""
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=LLM_MODEL, temperature=0.0, max_tokens=MAX_TOKENS)
    return _llm

def get_vectorstore(persist_directory: str = VECTOR_STORE_DIR):
    """获取向量数据库实例"""
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = Chroma(
            persist_directory=persist_directory, 
            embedding_function=get_embeddings()
        )
    return _vectorstore

def get_retriever(k: int = 4):
    """获取检索器"""
    global _retriever
    if _retriever is None:
        vectorstore = get_vectorstore()
        _retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": k}
        )
    return _retriever

def format_docs(docs: List[Document]) -> str:
    """格式化文档为字符串"""
    return "\n\n".join(doc.page_content for doc in docs)

def get_rag_chain():
    """获取RAG链"""
    global _rag_chain
    if _rag_chain is None:
        # 从hub获取prompt模板
        prompt = hub.pull("rlm/rag-prompt")
        
        # 构建RAG链
        _rag_chain = (
            {
                "context": get_retriever() | format_docs, 
                "question": RunnablePassthrough()
            }
            | prompt
            | get_llm()
            | StrOutputParser()
        )
    return _rag_chain

def query_knowledge(query: str) -> str:
    """
    基于已构建的向量库进行检索并返回回答
    """
    try:
        rag_chain = get_rag_chain()
        result = rag_chain.invoke(query)
        return result
    except Exception as e:
        return f"查询过程中出现错误: {str(e)}"

def load_single_document(file_path: str) -> List[Document]:
    """加载单个文档"""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的文件格式: {ext}。支持格式: {list(SUPPORTED_EXTENSIONS.keys())}")
    
    loader_class = SUPPORTED_EXTENSIONS[ext]
    loader = loader_class(str(file_path))
    return loader.load()

def load_directory_documents(directory_path: str, recursive: bool = True) -> List[Document]:
    """加载目录中的所有文档"""
    directory = Path(directory_path)
    if not directory.exists() or not directory.is_dir():
        raise ValueError(f"目录不存在或不是目录: {directory_path}")
    
    all_documents = []
    pattern = "**/*" if recursive else "*"
    
    for ext in SUPPORTED_EXTENSIONS.keys():
        for file_path in directory.glob(pattern + ext):
            try:
                documents = load_single_document(str(file_path))
                # 为每个文档添加文件路径元数据
                for doc in documents:
                    doc.metadata["source"] = str(file_path)
                all_documents.extend(documents)
                print(f"成功加载文档: {file_path}")
            except Exception as e:
                print(f"加载文档失败 {file_path}: {str(e)}")
                continue
    
    return all_documents

def split_documents(documents: List[Document], chunk_size: int = 1000, chunk_overlap: int = 200) -> List[Document]:
    """分割文档"""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    return text_splitter.split_documents(documents)

def add_documents_to_vectorstore(documents: List[Document]):
    """将文档添加到向量数据库"""
    if not documents:
        return {"status": "warning", "message": "没有文档可添加"}
    
    try:
        vectorstore = get_vectorstore()
        
        # 分割文档
        splits = split_documents(documents)
        
        # 添加到向量数据库
        vectorstore.add_documents(splits)
        vectorstore.persist()
        
        return {
            "status": "success", 
            "message": f"成功添加 {len(splits)} 个文档块",
            "original_docs": len(documents),
            "chunks": len(splits)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def add_single_document(file_path: str) -> Dict[str, Any]:
    """添加单个文档到向量数据库"""
    try:
        documents = load_single_document(file_path)
        # 添加文件路径元数据
        for doc in documents:
            if "source" not in doc.metadata:
                doc.metadata["source"] = file_path
        return add_documents_to_vectorstore(documents)
    except Exception as e:
        return {"status": "error", "message": str(e)}

def add_directory_documents(directory_path: str, recursive: bool = True) -> Dict[str, Any]:
    """添加目录中的所有文档到向量数据库"""
    try:
        documents = load_directory_documents(directory_path, recursive)
        if not documents:
            return {"status": "warning", "message": "目录中没有找到支持的文档"}
        return add_documents_to_vectorstore(documents)
    except Exception as e:
        return {"status": "error", "message": str(e)}

def add_texts(texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    将文本列表直接添加到向量数据库
    """
    try:
        documents = []
        for i, text in enumerate(texts):
            metadata = metadatas[i] if metadatas and i < len(metadatas) else {}
            documents.append(Document(page_content=text, metadata=metadata))
        
        return add_documents_to_vectorstore(documents)
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_document_count() -> int:
    """获取向量库中的文档块数量"""
    try:
        vectorstore = get_vectorstore()
        return vectorstore._collection.count()
    except:
        return 0

def search_similar_documents(query: str, k: int = 4) -> List[Document]:
    """搜索相似的文档（不经过LLM，直接返回文档）"""
    try:
        vectorstore = get_vectorstore()
        return vectorstore.similarity_search(query, k=k)
    except Exception as e:
        print(f"搜索相似文档失败: {e}")
        return []

def clear_vectorstore() -> Dict[str, Any]:
    """清空向量数据库"""
    global _vectorstore, _retriever, _rag_chain
    try:
        vectorstore = get_vectorstore()
        vectorstore.delete_collection()
        # 重置全局变量
        _vectorstore = None
        _retriever = None
        _rag_chain = None
        return {"status": "success", "message": "向量数据库已清空"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_vectorstore_info() -> Dict[str, Any]:
    """获取向量数据库信息"""
    try:
        vectorstore = get_vectorstore()
        count = vectorstore._collection.count()
        return {
            "status": "success",
            "document_count": count,
            "persist_directory": VECTOR_STORE_DIR
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 初始化函数
def initialize_rag_system() -> Dict[str, Any]:
    """初始化RAG系统"""
    try:
        # 预加载必要的组件
        get_embeddings()
        get_llm()
        get_vectorstore()
        get_retriever()
        
        # 检查向量库状态
        info = get_vectorstore_info()
        return {
            "status": "initialized", 
            "vectorstore_info": info
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

