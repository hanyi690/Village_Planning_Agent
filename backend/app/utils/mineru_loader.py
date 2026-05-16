"""
MinerU Loader - MinerU API 文档解析器

使用 MinerU Agent 轻量 API（免登录）或精准 API（需 Token）

特性：
- 高质量 Markdown 输出（标题层级清晰）
- 支持表格、公式识别
- 异步轮询机制
- 自动降级到 Docling/MarkItDown

使用方法：
    from app.utils.mineru_loader import MinerULoader
    loader = MinerULoader(file_path, category="policies")
    documents = loader.load()
"""

import logging
import time
import requests
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document

from app.utils.document_loader import FileTypeDetector, MarkdownCleaner

logger = logging.getLogger(__name__)

# MinerU API 基础 URL
MINERU_BASE_URL = "https://mineru.net/api/v1/agent"
MINERU_PRECISE_URL = "https://mineru.net/api/v4"


class MinerULoader:
    """MinerU API 文档解析器"""

    def __init__(
        self,
        file_path: Path,
        category: Optional[str] = None,
        use_agent_api: Optional[bool] = None,
        token: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        """初始化 MinerU 加载器

        Args:
            file_path: 文件路径
            category: 文档类别
            use_agent_api: 是否使用 Agent 轻量 API（None 时使用全局配置）
            token: MinerU Token（精准 API 需要）
            timeout: 轮询超时时间（秒）
        """
        self.file_path = Path(file_path)
        self.file_type = FileTypeDetector.detect(self.file_path)
        self.category = category

        # 加载全局配置
        try:
            from app.core.settings import (
                MINERU_USE_AGENT_API,
                MINERU_TOKEN,
                MINERU_TIMEOUT,
            )
            self.use_agent_api = use_agent_api if use_agent_api is not None else MINERU_USE_AGENT_API
            self.token = token if token is not None else MINERU_TOKEN
            self.timeout = timeout if timeout is not None else MINERU_TIMEOUT
        except ImportError:
            self.use_agent_api = use_agent_api or True
            self.token = token or ""
            self.timeout = timeout or 300

    def load(self) -> List[Document]:
        """加载文档，返回 LangChain Document 列表"""
        content = self._extract_content()

        if not content or len(content.strip()) < 10:
            logger.warning(f"[MinerULoader] Content empty or too short: {self.file_path}")
            return []

        content = MarkdownCleaner.clean(content)

        doc = Document(
            page_content=content,
            metadata={
                "source": self.file_path.name,
                "type": self.file_type,
                "file_path": str(self.file_path),
                "category": self.category or "unknown",
                "parser": "mineru",
            }
        )
        return [doc]

    def _extract_content(self) -> str:
        """使用 MinerU API 提取内容"""
        try:
            # 检查文件大小和页数，决定使用哪个 API
            if self.use_agent_api and self._check_agent_api_eligible():
                logger.info(f"[MinerULoader] Using Agent API for: {self.file_path.name}")
                return self._parse_with_agent_api()
            else:
                logger.info(f"[MinerULoader] Using Precise API for: {self.file_path.name}")
                return self._parse_with_precise_api()

        except Exception as e:
            logger.error(f"[MinerULoader] MinerU API failed: {e}")
            import traceback
            traceback.print_exc()
            return self._fallback_to_docling()

    def _check_agent_api_eligible(self) -> bool:
        """检查是否可以使用 Agent 轻量 API（≤10MB，≤20页）"""
        # 检查文件大小
        file_size = self.file_path.stat().st_size
        if file_size > 10 * 1024 * 1024:  # 10MB
            logger.info(f"[MinerULoader] File too large for Agent API: {file_size / 1024 / 1024:.2f}MB")
            return False

        # 检查页数（仅 PDF）
        if self.file_type == "pdf":
            try:
                import fitz
                pdf_doc = fitz.open(str(self.file_path))
                page_count = pdf_doc.page_count
                pdf_doc.close()
                if page_count > 20:
                    logger.info(f"[MinerULoader] PDF too many pages for Agent API: {page_count}")
                    return False
            except ImportError:
                pass

        return True

    def _parse_with_agent_api(self) -> str:
        """使用 Agent 轻量 API 解析（免登录）"""
        file_name = self.file_path.name

        # 1. 获取签名上传 URL
        logger.info("[MinerULoader] Step 1: Getting upload URL...")
        data = {
            "file_name": file_name,
            "language": "ch",
            "enable_table": True,
            "is_ocr": False,
            "enable_formula": True,
        }

        resp = requests.post(
            f"{MINERU_BASE_URL}/parse/file",
            json=data,
            timeout=30,
        )
        result = resp.json()

        if result.get("code") != 0:
            raise Exception(f"Failed to get upload URL: {result.get('msg')}")

        task_id = result["data"]["task_id"]
        file_url = result["data"]["file_url"]
        logger.info(f"[MinerULoader] Task created: {task_id}")

        # 2. 上传文件
        logger.info("[MinerULoader] Step 2: Uploading file...")
        with open(self.file_path, "rb") as f:
            put_resp = requests.put(file_url, data=f, timeout=60)
            if put_resp.status_code not in (200, 201):
                raise Exception(f"Upload failed: HTTP {put_resp.status_code}")

        logger.info("[MinerULoader] File uploaded, waiting for result...")

        # 3. 轮询等待结果
        return self._poll_agent_result(task_id)

    def _poll_agent_result(self, task_id: str) -> str:
        """轮询 Agent API 结果"""
        state_labels = {
            "pending": "排队中",
            "running": "解析中",
            "waiting-file": "等待文件上传",
            "uploading": "文件下载中",
        }

        start = time.time()
        while time.time() - start < self.timeout:
            resp = requests.get(
                f"{MINERU_BASE_URL}/parse/{task_id}",
                timeout=30,
            )
            result = resp.json()
            state = result["data"]["state"]
            elapsed = int(time.time() - start)

            if state == "done":
                markdown_url = result["data"]["markdown_url"]
                logger.info(f"[MinerULoader] [{elapsed}s] Done! Downloading: {markdown_url}")
                md_resp = requests.get(markdown_url, timeout=60)
                return md_resp.text

            if state == "failed":
                err_msg = result["data"].get("err_msg", "Unknown error")
                raise Exception(f"Parse failed: {err_msg}")

            logger.info(f"[MinerULoader] [{elapsed}s] {state_labels.get(state, state)}...")
            time.sleep(3)

        raise Exception(f"Poll timeout ({self.timeout}s)")

    def _parse_with_precise_api(self) -> str:
        """使用精准 API 解析（需 Token）"""
        if not self.token:
            logger.warning("[MinerULoader] No token for Precise API, falling back to Docling")
            return self._fallback_to_docling()

        file_name = self.file_path.name

        # 1. 获取批量上传 URL
        logger.info("[MinerULoader] Step 1: Getting batch upload URL...")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        data = {
            "files": [{"name": file_name}],
            "model_version": "vlm",  # 使用 VLM 模型
        }

        resp = requests.post(
            f"{MINERU_PRECISE_URL}/file-urls/batch",
            headers=headers,
            json=data,
            timeout=30,
        )
        result = resp.json()

        if result.get("code") != 0:
            raise Exception(f"Failed to get batch URL: {result.get('msg')}")

        batch_id = result["data"]["batch_id"]
        file_urls = result["data"]["file_urls"]
        logger.info(f"[MinerULoader] Batch created: {batch_id}")

        # 2. 上传文件
        logger.info("[MinerULoader] Step 2: Uploading file...")
        with open(self.file_path, "rb") as f:
            put_resp = requests.put(file_urls[0], data=f, timeout=120)
            if put_resp.status_code not in (200, 201):
                raise Exception(f"Upload failed: HTTP {put_resp.status_code}")

        logger.info("[MinerULoader] File uploaded, waiting for result...")

        # 3. 轮询等待结果
        return self._poll_precise_result(batch_id)

    def _poll_precise_result(self, batch_id: str) -> str:
        """轮询精准 API 结果"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

        start = time.time()
        while time.time() - start < self.timeout:
            resp = requests.get(
                f"{MINERU_PRECISE_URL}/extract-results/batch/{batch_id}",
                headers=headers,
                timeout=30,
            )
            result = resp.json()

            if result.get("code") != 0:
                raise Exception(f"Query failed: {result.get('msg')}")

            extract_results = result["data"]["extract_result"]
            elapsed = int(time.time() - start)

            for res in extract_results:
                state = res["state"]

                if state == "done":
                    zip_url = res["full_zip_url"]
                    logger.info(f"[MinerULoader] [{elapsed}s] Done! Downloading ZIP: {zip_url}")
                    return self._download_and_extract_markdown(zip_url)

                if state == "failed":
                    err_msg = res.get("err_msg", "Unknown error")
                    raise Exception(f"Parse failed: {err_msg}")

            # 其他状态：waiting-file, pending, running, converting
            logger.info(f"[MinerULoader] [{elapsed}s] Processing...")
            time.sleep(5)

        raise Exception(f"Poll timeout ({self.timeout}s)")

    def _download_and_extract_markdown(self, zip_url: str) -> str:
        """下载 ZIP 并提取 Markdown"""
        import zipfile
        import tempfile

        # 下载 ZIP
        zip_resp = requests.get(zip_url, timeout=120)
        if zip_resp.status_code != 200:
            raise Exception(f"Download ZIP failed: HTTP {zip_resp.status_code}")

        # 保存到临时文件
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_resp.content)
            tmp_path = tmp.name

        try:
            # 解压并提取 full.md
            with zipfile.ZipFile(tmp_path, "r") as zf:
                # 查找 full.md
                for name in zf.namelist():
                    if name.endswith("full.md"):
                        return zf.read(name).decode("utf-8")

                # 如果没有 full.md，尝试其他 Markdown 文件
                for name in zf.namelist():
                    if name.endswith(".md"):
                        return zf.read(name).decode("utf-8")

            raise Exception("No Markdown file found in ZIP")

        finally:
            # 清理临时文件
            Path(tmp_path).unlink(missing_ok=True)

    def _fallback_to_docling(self) -> str:
        """降级到 Docling"""
        logger.info(f"[MinerULoader] Falling back to Docling for: {self.file_path.name}")
        try:
            from app.utils.docling_loader import DoclingLoader
            loader = DoclingLoader(self.file_path, category=self.category)
            docs = loader.load()
            return docs[0].page_content if docs else ""
        except ImportError:
            return self._fallback_to_markitdown()

    def _fallback_to_markitdown(self) -> str:
        """最终降级到 MarkItDown"""
        logger.info(f"[MinerULoader] Falling back to MarkItDown for: {self.file_path.name}")
        from app.utils.document_loader import MarkItDownLoader
        loader = MarkItDownLoader(self.file_path, category=self.category)
        docs = loader.load()
        return docs[0].page_content if docs else ""


__all__ = ["MinerULoader"]