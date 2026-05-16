"""
层级切片器

利用 LLM 推断文档大纲层级，使用 LangChain MarkdownHeaderTextSplitter 切片。
实现 Small-to-Big 检索架构。

缓存架构:
- MD 文档: data/RAG_doc/_doc_md/
- 层级索引: data/RAG_doc/_cache/outline_index/ (JSON 格式，作为索引)
- 向量缓存: data/RAG_doc/_cache/vector_cache/

2026-05-16: 重写，集成 LLM 大纲矫正，实现完整缓存流程
"""
import logging
import re
import hashlib
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger(__name__)

from app.core.settings import OUTLINE_INDEX_DIR


@dataclass
class HierarchyChunk:
    """层级切片数据结构"""
    content: str
    chunk_id: str
    depth: int  # 标题层级 (0=文档, 1=章, 2=节, 3=条)
    parent_id: Optional[str]
    ancestors: List[str]  # 祖先标题路径
    section_title: str
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class OutlineIndex:
    """层级索引数据结构"""
    source_name: str
    source_path: str
    file_hash: str
    created_at: str
    heading_count: int
    chunk_count: int
    level_distribution: Dict[int, int]
    headings: List[Dict[str, Any]]  # 提取的标题列表
    corrected_content: str  # 矫正后的 Markdown 内容
    chunks: List[Dict[str, Any]]  # 切片列表

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class OutlineIndexManager:
    """层级索引管理器"""

    def __init__(self, index_dir: Path = OUTLINE_INDEX_DIR):
        self.index_dir = index_dir
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def get_index_path(self, source_name: str) -> Path:
        """获取索引文件路径"""
        # 使用源文件名（去掉扩展名）作为索引文件名
        base_name = Path(source_name).stem
        return self.index_dir / f"{base_name}_index.json"

    def compute_file_hash(self, file_path: Path) -> str:
        """计算文件哈希"""
        content = file_path.read_bytes()
        return hashlib.md5(content).hexdigest()

    def exists(self, source_name: str) -> bool:
        """检查索引是否存在"""
        return self.get_index_path(source_name).exists()

    def load(self, source_name: str) -> Optional[OutlineIndex]:
        """加载索引"""
        index_path = self.get_index_path(source_name)
        if not index_path.exists():
            return None

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return OutlineIndex(**data)
        except Exception as e:
            logger.warning(f"[OutlineIndexManager] 加载索引失败: {e}")
            return None

    def save(self, index: OutlineIndex) -> None:
        """保存索引"""
        index_path = self.get_index_path(index.source_name)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"[OutlineIndexManager] 索引已保存: {index_path}")

    def is_valid(self, source_name: str, source_path: Path) -> bool:
        """
        检查索引是否有效（文件未变化）
        
        Args:
            source_name: 源文件名
            source_path: 源文件路径
        
        Returns:
            True 如果索引有效且文件未变化
        """
        index = self.load(source_name)
        if index is None:
            return False

        current_hash = self.compute_file_hash(source_path)
        return index.file_hash == current_hash

    def delete(self, source_name: str) -> bool:
        """删除索引"""
        index_path = self.get_index_path(source_name)
        if index_path.exists():
            index_path.unlink()
            logger.info(f"[OutlineIndexManager] 索引已删除: {index_path}")
            return True
        return False

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有索引"""
        indices = []
        for index_file in self.index_dir.glob("*_index.json"):
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                indices.append({
                    "source_name": data.get("source_name", ""),
                    "created_at": data.get("created_at", ""),
                    "heading_count": data.get("heading_count", 0),
                    "chunk_count": data.get("chunk_count", 0),
                    "level_distribution": data.get("level_distribution", {}),
                })
            except Exception:
                continue
        return indices


class LLMOutlineCorrector:
    """LLM 大纲矫正器"""

    def __init__(self, batch_size: int = 80):
        self._llm = None
        self.batch_size = batch_size

    @property
    def llm(self):
        """延迟加载 LLM"""
        if self._llm is None:
            try:
                from app.core.llm import create_flash_llm
                self._llm = create_flash_llm()
            except Exception as e:
                logger.warning(f"加载 Flash LLM 失败: {e}")
                raise
        return self._llm

    def correct(self, content: str, source_name: str = "") -> tuple:
        """
        矫正文档大纲层级

        Args:
            content: Markdown 文档内容
            source_name: 文档名称（用于日志）

        Returns:
            (corrected_content, headings) 矫正后的内容和标题列表
        """
        # 1. 提取候选标题
        headings = self._extract_headings(content)

        if len(headings) < 2:
            logger.debug("[LLMOutlineCorrector] 标题数量不足，跳过矫正")
            return content, headings

        logger.info(f"[LLMOutlineCorrector] 提取 {len(headings)} 个候选标题")

        # 2. LLM 推断层级
        headings = self._infer_levels_with_llm(headings)

        # 3. 重写 Markdown 标题
        corrected_content = self._rewrite_headings(content, headings)

        logger.info(f"[LLMOutlineCorrector] 矫正完成")
        return corrected_content, headings

    def _extract_headings(self, content: str) -> List[Dict]:
        """
        提取候选标题（增强版）

        覆盖：
        1. Markdown 标题（# ## ###）
        2. 中文章节（第一章、第二节、第一编）
        3. 中文数字条款（第一条、第二款）
        4. 阿拉伯数字编号（1.1、2.3.4、1.0.1条）
        5. 无"第"字中文编号（一、（一）、1.、1））
        6. 罗马数字编号（I.、II.、i)、ii)）

        误判过滤：
        1. 正文中的"第一，...；第二，..."
        2. 表格/列表中的编号
        3. 利用上下文（前一行是否为空行）
        """
        lines = content.split("\n")
        headings = []

        # 中文数字映射
        cn_num_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                      "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
                      "百": 100, "零": 0}

        def is_likely_heading(line: str, prev_line: str, next_line: str) -> bool:
            """判断是否像标题（利用上下文）"""
            prev_empty = not prev_line.strip() or prev_line.strip().startswith("#")
            next_has_content = next_line.strip() and not self._looks_like_numbered_line(next_line.strip())
            short_enough = len(line) < 100
            return (prev_empty or next_has_content) and short_enough

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            prev_line = lines[i - 1] if i > 0 else ""
            next_line = lines[i + 1] if i < len(lines) - 1 else ""

            # 1. Markdown 标题
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                text = stripped.lstrip("# ").strip()
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": text,
                    "original_level": level,
                    "heading_type": "markdown",
                })
                continue

            # 2. 中文章节（第一章、第二节、第一编、第一目）
            match = re.match(r"^第([一二三四五六七八九十百零]+)([章节部分编目])\s*(.*)$", stripped)
            if match:
                type_map = {"编": "chapter", "章": "chapter", "节": "section",
                           "部": "chapter", "分": "chapter", "目": "item"}
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": stripped,
                    "original_level": 0,
                    "heading_type": type_map.get(match.group(2), "section"),
                })
                continue

            # 3. 中文数字条款（第一条、第二款）
            match = re.match(r"^第([一二三四五六七八九十百零]+)([条款目])\s*(.*)$", stripped)
            if match:
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": stripped,
                    "original_level": 0,
                    "heading_type": "article",
                })
                continue

            # 4. 阿拉伯数字编号（1.1、2.3.4、第1.0.1条）
            match = re.match(r"^第?(\d+(?:\.\d+)+)[条款]?\s*(.*)$", stripped)
            if match:
                dots = match.group(1).count(".")
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": stripped,
                    "original_level": dots + 1,
                    "heading_type": "article",
                })
                continue

            # 5. 无"第"字中文编号（一、（一）、1.、1））
            match = re.match(r"^([一二三四五六七八九十]+)[、\.]\s*(.+)$", stripped)
            if match and is_likely_heading(stripped, prev_line, next_line):
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": stripped,
                    "original_level": 2,
                    "heading_type": "section",
                })
                continue

            match = re.match(r"^[（\(]([一二三四五六七八九十]+)[）\)]\s*(.*)$", stripped)
            if match and is_likely_heading(stripped, prev_line, next_line):
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": stripped,
                    "original_level": 3,
                    "heading_type": "item",
                })
                continue

            match = re.match(r"^(\d+)[\.、]\s*(.+)$", stripped)
            if match and is_likely_heading(stripped, prev_line, next_line):
                if not re.match(r"^\d+[\.、]", next_line.strip()):
                    headings.append({
                        "line_no": i,
                        "text": stripped,
                        "clean_text": stripped,
                        "original_level": 2,
                        "heading_type": "section",
                    })
                    continue

            match = re.match(r"^[（\(]?(\d+)[）\)]\s*(.+)$", stripped)
            if match and is_likely_heading(stripped, prev_line, next_line):
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": stripped,
                    "original_level": 3,
                    "heading_type": "item",
                })
                continue

            # 6. 罗马数字编号
            match = re.match(r"^([IVXLCDM]+)[\.、]\s*(.+)$", stripped)
            if match and is_likely_heading(stripped, prev_line, next_line):
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": stripped,
                    "original_level": 2,
                    "heading_type": "section",
                })
                continue

            match = re.match(r"^([ivxlcdm]+)[\)）]\s*(.+)$", stripped)
            if match and is_likely_heading(stripped, prev_line, next_line):
                headings.append({
                    "line_no": i,
                    "text": stripped,
                    "clean_text": stripped,
                    "original_level": 3,
                    "heading_type": "item",
                })
                continue

        return headings

    def _looks_like_numbered_line(self, line: str) -> bool:
        """判断是否像编号行"""
        patterns = [
            r"^\d+[\.\)、]",
            r"^[（\(]\d+[）\)]",
            r"^[一二三四五六七八九十]+[、\.\)]",
            r"^[（\(][一二三四五六七八九十]+[）\)]",
        ]
        for pattern in patterns:
            if re.match(pattern, line):
                return True
        return False

    def _infer_levels_with_llm(self, headings: List[Dict]) -> List[Dict]:
        """使用 LLM 推断标题层级"""
        if len(headings) < 2:
            return headings

        total = len(headings)

        for batch_start in range(0, total, self.batch_size):
            batch_end = min(batch_start + self.batch_size, total)
            batch = headings[batch_start:batch_end]

            heading_list = "\n".join([
                f"[{idx}] {h['clean_text'][:80]}"
                for idx, h in enumerate(batch)
            ])

            prompt = f"""你是文档结构分析专家。推断以下标题的层级关系。

要求：
1. 输出JSON数组，每个元素包含: index, level (1=最高层级), type
2. type 可以是: chapter(章), section(节), article(条), item(项)
3. 层级必须连续，不能跳跃

候选标题：
{heading_list}

JSON:"""

            try:
                response = self.llm.invoke(prompt)
                content = response.content

                json_match = re.search(r"\[[\s\S]*\]", content)
                if json_match:
                    outline = json.loads(json_match.group())

                    for item in outline:
                        idx = item.get("index", 0)
                        if 0 <= idx < len(batch):
                            global_idx = batch_start + idx
                            headings[global_idx]["inferred_level"] = item.get("level", 1)
                            headings[global_idx]["heading_type"] = item.get("type", "section")

                logger.debug(f"[LLMOutlineCorrector] 批次 {batch_start//self.batch_size + 1} 完成")

            except Exception as e:
                logger.warning(f"[LLMOutlineCorrector] LLM 调用失败: {e}")

        # 填充未推断的标题
        for h in headings:
            if "inferred_level" not in h:
                h["inferred_level"] = h.get("original_level", 1) or 1
                h["heading_type"] = "section"

        return headings

    def _rewrite_headings(self, content: str, headings: List[Dict]) -> str:
        """重写 Markdown 标题"""
        lines = content.split("\n")

        for h in headings:
            line_no = h["line_no"]
            level = h.get("inferred_level", 1)
            clean_text = h["clean_text"]

            level = min(level, 4)
            new_heading = "#" * level + " " + clean_text
            lines[line_no] = new_heading

        return "\n".join(lines)


class HierarchySlicer:
    """层级切片器：LLM 大纲矫正 + LangChain 切片 + 完整缓存"""

    def __init__(self, use_llm_outline: bool = True):
        """
        Args:
            use_llm_outline: 是否使用 LLM 矫正大纲（默认开启）
        """
        self.use_llm_outline = use_llm_outline
        self._corrector = None
        self._index_manager = OutlineIndexManager()

    @property
    def corrector(self):
        """延迟加载矫正器"""
        if self._corrector is None:
            self._corrector = LLMOutlineCorrector()
        return self._corrector

    @property
    def index_manager(self):
        """索引管理器"""
        return self._index_manager

    def slice(self, content: str, source_name: str = "") -> List[HierarchyChunk]:
        """
        切分文档，构建层级树

        Args:
            content: Markdown 文档内容
            source_name: 文档名称

        Returns:
            层级切片列表
        """
        # 1. 简单预处理：清理垃圾
        content = self._clean_content(content)

        # 2. LLM 大纲矫正
        if self.use_llm_outline:
            try:
                content, headings = self.corrector.correct(content, source_name)
            except Exception as e:
                logger.warning(f"[HierarchySlicer] LLM 矫正失败: {e}")
                headings = []

        # 3. LangChain 切片
        try:
            chunks = self._slice_with_langchain(content, source_name)
        except ImportError:
            logger.warning("[HierarchySlicer] LangChain 未安装，使用简单切分")
            chunks = self._fallback_simple(content, source_name)

        return chunks

    def slice_with_cache(
        self,
        file_path: str,
        source_name: Optional[str] = None,
        force_refresh: bool = False
    ) -> tuple:
        """
        带缓存的切片处理

        Args:
            file_path: MD 文件路径
            source_name: 源文件名（可选，默认从路径提取）
            force_refresh: 是否强制刷新缓存

        Returns:
            (chunks, index) 切片列表和索引对象
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        source_name = source_name or path.name
        file_hash = self._index_manager.compute_file_hash(path)

        # 检查缓存是否有效
        if not force_refresh and self._index_manager.is_valid(source_name, path):
            logger.info(f"[HierarchySlicer] 使用缓存索引: {source_name}")
            index = self._index_manager.load(source_name)
            if index:
                chunks = [HierarchyChunk(**c) for c in index.chunks]
                return chunks, index

        # 缓存失效或强制刷新，重新处理
        logger.info(f"[HierarchySlicer] 重新处理文档: {source_name}")

        content = path.read_text(encoding="utf-8")
        chunks = self.slice(content, source_name)

        # 计算层级分布
        level_distribution = {}
        for c in chunks:
            level_distribution[c.depth] = level_distribution.get(c.depth, 0) + 1

        # 创建索引
        index = OutlineIndex(
            source_name=source_name,
            source_path=str(path),
            file_hash=file_hash,
            created_at=datetime.now().isoformat(),
            heading_count=len(chunks),
            chunk_count=len(chunks),
            level_distribution=level_distribution,
            headings=[],  # 可选：存储标题列表
            corrected_content=content,
            chunks=[c.to_dict() for c in chunks],
        )

        # 保存索引
        self._index_manager.save(index)

        return chunks, index

    def _clean_content(self, content: str) -> str:
        """简单清理：移除垃圾行"""
        lines = content.split("\n")
        cleaned = []

        filter_patterns = [
            r"^<!--\s*解析",
            r"^\*\s*\d+\s*[-—]\s*$",
            r"^!\[image\]",
            r"^(?:索引号|分类|发布机构|成文日期|名称|文号|发布日期|主题词)[：:]",
        ]

        in_toc = False
        toc_level = 0

        for line in lines:
            stripped = line.strip()

            if re.match(r"^#+\s*目\s*录", stripped, re.IGNORECASE):
                in_toc = True
                match = re.match(r"^(#+)", stripped)
                toc_level = len(match.group(1)) if match else 1
                continue

            if in_toc:
                match = re.match(r"^(#+)\s+", stripped)
                if match and len(match.group(1)) <= toc_level:
                    in_toc = False
                else:
                    continue

            skip = False
            for pattern in filter_patterns:
                if re.match(pattern, stripped):
                    skip = True
                    break

            if not skip:
                cleaned.append(line)

        return "\n".join(cleaned)

    def _slice_with_langchain(self, content: str, source_name: str) -> List[HierarchyChunk]:
        """使用 LangChain MarkdownHeaderTextSplitter 切片"""
        from langchain_text_splitters import MarkdownHeaderTextSplitter

        headers_to_split_on = [
            ("#", "Header1"),
            ("##", "Header2"),
            ("###", "Header3"),
            ("####", "Header4"),
        ]

        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False,
        )

        documents = splitter.split_text(content)

        results = []
        for i, doc in enumerate(documents):
            metadata = doc.metadata
            ancestors = []

            for level in ["Header1", "Header2", "Header3", "Header4"]:
                if level in metadata:
                    ancestors.append(metadata[level])

            depth = len(ancestors)
            section_title = ancestors[-1] if ancestors else ""
            chunk_id = self._generate_chunk_id(source_name, i, doc.page_content)
            has_table = "<table>" in doc.page_content or ("|" in doc.page_content and "---" in doc.page_content)

            results.append(HierarchyChunk(
                content=doc.page_content,
                chunk_id=chunk_id,
                depth=depth,
                parent_id=None,
                ancestors=ancestors,
                section_title=section_title,
                metadata={
                    "source": source_name,
                    "chunk_index": i,
                    "has_table": has_table,
                    "char_count": len(doc.page_content),
                    "method": "langchain_llm",
                },
            ))

        logger.info(f"[HierarchySlicer] 切片完成: {len(results)} 切片")
        return results

    def _generate_chunk_id(self, source_name: str, index: int, text: str) -> str:
        """生成唯一的 chunk_id"""
        hash_part = hashlib.md5(text.encode()).hexdigest()[:8]
        if source_name:
            return f"{source_name}_{index}_{hash_part}"
        return f"chunk_{index}_{hash_part}"

    def _fallback_simple(self, content: str, source_name: str) -> List[HierarchyChunk]:
        """降级策略：按段落切分"""
        paragraphs = content.split("\n\n")

        results = []
        for i, para in enumerate(paragraphs):
            if not para.strip():
                continue

            chunk_id = self._generate_chunk_id(source_name, i, para)

            results.append(HierarchyChunk(
                content=para.strip(),
                chunk_id=chunk_id,
                depth=0,
                parent_id=None,
                ancestors=[],
                section_title="",
                metadata={
                    "source": source_name,
                    "chunk_index": i,
                    "has_table": "|" in para and "---" in para,
                    "method": "simple",
                },
            ))

        logger.info(f"[HierarchySlicer] 简单切片完成: {len(results)} 切片")
        return results


# 兼容别名
Chunk = HierarchyChunk


__all__ = [
    "HierarchyChunk",
    "HierarchySlicer",
    "LLMOutlineCorrector",
    "OutlineIndex",
    "OutlineIndexManager",
    "Chunk",
    "OUTLINE_INDEX_DIR",
]
