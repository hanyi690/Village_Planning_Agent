"""
层级切片器

利用 LLM 推断文档大纲层级，使用 LangChain MarkdownHeaderTextSplitter 切片。
实现 Small-to-Big 检索架构。

缓存架构:
- MD 文档: data/RAG_doc/_doc_md/
- 层级索引: data/RAG_doc/_cache/outline_index/ (JSON 格式，作为索引)
- 向量缓存: data/RAG_doc/_cache/vector_cache/

2026-05-17: 重构，将索引管理逻辑独立到 context.py
"""
import logging
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger(__name__)

from app.core.settings import OUTLINE_INDEX_DIR
from .context import (
    HierarchyTreeIndex,
    OutlineIndexManager,
    LLMOutlineCorrector,
)


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

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)


class HierarchySlicer:
    """层级切片器：LLM 大纲矫正 + LangChain 切片 + 完整缓存"""

    # 元数据字段配置（可扩展）
    METADATA_FIELDS = [
        '索引号', '分类', '发布机构', '成文日期',
        '名称', '文号', '发布日期', '主题词',
        '索 引 号', '发文机关', '标 题',  # 变体
    ]

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

    def slice(self, content: str, source_name: str = "", skip_clean: bool = False) -> List[HierarchyChunk]:
        """
        切分文档，构建层级树

        Args:
            content: Markdown 文档内容（已清理或未清理）
            source_name: 文档名称
            skip_clean: 是否跳过清理步骤（如果内容已清理则设为 True）

        Returns:
            层级切片列表
        """
        # 1. 清理噪声（如果未清理）
        if not skip_clean:
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

        # 4. 修复空标题节点
        chunks = self._fix_orphan_headings(chunks)

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
            index_data = self._index_manager.load(source_name)
            if index_data:
                chunks = [HierarchyChunk(**c) for c in index_data.get("chunks", [])]
                return chunks, index_data

        # 缓存失效或强制刷新，重新处理
        logger.info(f"[HierarchySlicer] 重新处理文档: {source_name}")

        content = path.read_text(encoding="utf-8")
        # 先清理噪声，再切片
        cleaned_content = self._clean_content(content)
        chunks = self.slice(cleaned_content, source_name, skip_clean=True)

        # 计算层级分布
        level_distribution = {}
        for c in chunks:
            level_distribution[c.depth] = level_distribution.get(c.depth, 0) + 1

        # 构建树形索引
        tree_index = HierarchyTreeIndex()
        chunk_dicts = [c.to_dict() for c in chunks]
        for chunk_dict in chunk_dicts:
            tree_index.add_chunk(chunk_dict)
        tree_index.build_parent_child_relations(chunk_dicts)

        # 创建索引（存储清理后的内容）
        index_data = {
            "source_name": source_name,
            "source_path": str(path),
            "file_hash": file_hash,
            "created_at": datetime.now().isoformat(),
            "heading_count": len(chunks),
            "chunk_count": len(chunks),
            "level_distribution": level_distribution,
            "headings": [],  # 可选：存储标题列表
            "corrected_content": cleaned_content,
            "chunks": chunk_dicts,
            "tree_index": tree_index.to_dict(),
        }

        # 保存索引
        self._index_manager.save(index_data)

        return chunks, index_data

    def _clean_content(self, content: str) -> str:
        """清理噪声内容（增强版）

        优化要点：
        1. 多行注释处理：清除所有 HTML 注释
        2. 目录跳过安全上限：防止跳过过多内容
        3. 元数据字段可配置化
        4. 代码块保护：避免删除 Markdown 代码块内的内容
        """
        # 1. 先清除所有 HTML 注释（单行和多行）
        content = re.sub(r'<!--[\s\S]*?-->', '', content)

        lines = content.split("\n")
        cleaned = []

        # 2. 增强的过滤模式
        filter_patterns = [
            r"^\*\s*\d+\s*[-—]\s*$",   # 页码标记 * 1 -
            r"^!\[image\]",            # 图片占位符
        ]

        # 3. 元数据字段正则（可配置，仅在前 20 行应用）
        metadata_pattern = re.compile(
            r'^(?:' + '|'.join(re.escape(f) for f in self.METADATA_FIELDS) + r')[：:].*$'
        )
        METADATA_FILTER_LINES = 20  # 仅在前 20 行应用元数据过滤

        in_toc = False
        toc_level = 0
        toc_line_count = 0
        MAX_TOC_LINES = 50  # 目录安全上限

        in_code_block = False
        line_index = 0  # 行号计数器

        for line in lines:
            stripped = line.strip()
            line_index += 1

            # 4. 代码块保护
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                cleaned.append(line)
                continue
            if in_code_block:
                cleaned.append(line)
                continue

            # 跳过目录
            if re.match(r"^#+\s*目\s*[录次]", stripped, re.IGNORECASE):
                in_toc = True
                match = re.match(r"^(#+)", stripped)
                toc_level = len(match.group(1)) if match else 1
                toc_line_count = 0
                continue

            if in_toc:
                toc_line_count += 1
                if toc_line_count > MAX_TOC_LINES:
                    in_toc = False
                else:
                    # 检测是否为目录行：有点线或为标题格式
                    is_toc_line = re.match(r'^\s*#+\s', stripped) or '...' in stripped or '..' in stripped
                    if not is_toc_line:
                        # 当前行不是目录格式，退出目录模式并保留该行
                        in_toc = False
                        cleaned.append(line)
                        continue
                    # 检测是否遇到同级或更高级标题（退出目录）
                    match = re.match(r"^(#+)\s+", stripped)
                    if match and len(match.group(1)) <= toc_level:
                        in_toc = False
                        cleaned.append(line)  # 保留该标题行
                        continue
                    # 继续跳过目录行
                    continue

            skip = False
            for pattern in filter_patterns:
                if re.match(pattern, stripped):
                    skip = True
                    break

            # 元数据过滤仅在前 20 行应用，避免误删正文中的表格头
            if not skip:
                if line_index <= METADATA_FILTER_LINES and metadata_pattern.match(stripped):
                    skip = True

            if not skip:
                cleaned.append(line)

        # 5. 清除连续空白行（只保留一个）
        content = "\n".join(cleaned)
        content = re.sub(r'\n{3,}', '\n\n', content)

        # 6. 合并连续短标题（如 "# 第1篇" + "# 城市与城市规划"）
        # 先去除所有空白行，再检测连续标题
        lines = content.split("\n")
        non_empty_lines = [l for l in lines if l.strip()]

        # 中文数字映射
        chinese_num_map = {
            '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
            '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
            '十一': '11', '十二': '12', '十三': '13', '十四': '14', '十五': '15',
        }

        def is_chapter_numbering(title: str) -> bool:
            """检查是否为章节编号格式（支持中文和阿拉伯数字）"""
            # 阿拉伯数字格式：第1篇、第2章、第3节、第4条
            if re.match(r'^第\d+[篇章节条]$', title):
                return True
            # 中文数字格式：第一篇、第十二章、第三节
            for cn, _ in chinese_num_map.items():
                if re.match(rf'^第{cn}[篇章节条]$', title):
                    return True
            return False

        def has_numbering_prefix(title: str) -> bool:
            """检查标题是否以编号开头"""
            # 阿拉伯数字
            if re.match(r'^第\d+[篇章节条]', title):
                return True
            # 中文数字
            for cn in chinese_num_map:
                if re.match(rf'^第{cn}[篇章节条]', title):
                    return True
            return False

        merged_lines = []
        i = 0
        while i < len(non_empty_lines):
            line = non_empty_lines[i]
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)

            if heading_match and i + 1 < len(non_empty_lines):
                next_line = non_empty_lines[i + 1]
                next_heading_match = re.match(r'^(#{1,6})\s+(.+)$', next_line)

                if next_heading_match:
                    cur_level = len(heading_match.group(1))
                    next_level = len(next_heading_match.group(1))
                    cur_title = heading_match.group(2).strip()
                    next_title = next_heading_match.group(2).strip()

                    # 扩展合并条件：
                    # 1. 同级别 + 当前标题是纯编号 + 下一个不是编号开头
                    # 2. 同级别 + 当前标题是纯编号 + 下一个也是编号（如"第一章" + "总则"）
                    is_numbering_only = is_chapter_numbering(cur_title)
                    next_has_numbering = has_numbering_prefix(next_title)

                    # 条件1：当前是纯编号，下一个不是编号开头
                    cond1 = (cur_level == next_level and is_numbering_only and not next_has_numbering)
                    # 条件2：当前是纯编号，下一个也是编号（如"第一章"后跟"总则"）
                    cond2 = (cur_level == next_level and is_numbering_only and next_has_numbering)

                    if cond1 or cond2:
                        merged_title = f"{'#' * cur_level} {cur_title} {next_title}"
                        merged_lines.append(merged_title)
                        i += 2
                        continue

            merged_lines.append(line)
            i += 1

        # 7. 恢复段落间的空行（保持 Markdown 格式）
        result_lines = []
        for j, line in enumerate(merged_lines):
            result_lines.append(line)
            # 如果当前行是标题且下一行不是标题，添加空行
            if j + 1 < len(merged_lines):
                cur_is_heading = re.match(r'^#{1,6}', line)
                next_is_heading = re.match(r'^#{1,6}', merged_lines[j + 1])
                if cur_is_heading and not next_is_heading:
                    result_lines.append("")  # 标题后加空行

        return "\n".join(result_lines)

    def _slice_with_langchain(self, content: str, source_name: str) -> List[HierarchyChunk]:
        """
        层级切片：利用 LLM 矫正后的标题层级

        切片策略：
        - 按 Markdown 标题切分（# ## ### ####）
        - 为每个层级创建占位切片（确保 Small-to-Big 检索能找到所有层级）
        - ancestors 字段记录完整层级路径（由 LLM 矫正）
        - parent_id 正确设置直接父块的 chunk_id

        Small-to-Big 在检索阶段实现，而非切片阶段。
        """
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

        # 第一遍：创建所有切片，收集所有层级的标题
        section_to_chunk_id: Dict[str, str] = {}
        temp_chunks = []
        all_headers: Dict[int, Dict[str, str]] = {}  # depth -> {section_title: chunk_id}

        for i, doc in enumerate(documents):
            metadata = doc.metadata
            ancestors = []

            for level in ["Header1", "Header2", "Header3", "Header4"]:
                if level in metadata:
                    ancestors.append(metadata[level])

            depth = len(ancestors)
            section_title = ancestors[-1] if ancestors else ""
            chunk_id = self._generate_chunk_id(source_name, i, doc.page_content)

            temp_chunks.append({
                "doc": doc,
                "chunk_id": chunk_id,
                "depth": depth,
                "ancestors": ancestors,
                "section_title": section_title,
            })

            # 记录 section_title -> chunk_id 映射
            if section_title:
                section_to_chunk_id[section_title] = chunk_id

            # 收集所有层级的标题
            for d in range(1, depth):
                if d not in all_headers:
                    all_headers[d] = {}
                header_title = ancestors[d - 1]
                if header_title and header_title not in all_headers[d]:
                    all_headers[d][header_title] = ""

        # 第二遍：为缺失的层级创建占位切片
        placeholder_index = len(temp_chunks)
        root_chunk_id = None  # 文档根节点 ID

        for d in sorted(all_headers.keys()):
            for header_title in all_headers[d]:
                if header_title not in section_to_chunk_id:
                    # 创建占位切片
                    placeholder_id = self._generate_chunk_id(source_name, placeholder_index, header_title)
                    placeholder_content = "#" * d + " " + header_title

                    # 计算占位切片的 ancestors
                    placeholder_ancestors = []
                    for existing_chunk in temp_chunks:
                        if existing_chunk["depth"] >= d:
                            existing_anc = existing_chunk["ancestors"]
                            if len(existing_anc) >= d and existing_anc[d - 1] == header_title:
                                placeholder_ancestors = existing_anc[:d]
                                break

                    # 使用 Document 创建占位切片（替代动态类型）
                    from langchain_core.documents import Document
                    placeholder_doc = Document(page_content=placeholder_content)

                    temp_chunks.append({
                        "doc": placeholder_doc,
                        "chunk_id": placeholder_id,
                        "depth": d,
                        "ancestors": placeholder_ancestors,
                        "section_title": header_title,
                        "is_placeholder": True,
                    })
                    section_to_chunk_id[header_title] = placeholder_id
                    placeholder_index += 1

                    # 记录第一个切片作为根节点
                    if root_chunk_id is None and d == 1:
                        root_chunk_id = placeholder_id

        # 第三遍：设置 parent_id
        results = []
        for item in temp_chunks:
            ancestors = item.get("ancestors", [])
            depth = item.get("depth", 1)

            # 计算父块 ID：向上遍历 ancestors 直到找到存在的切片
            parent_id = None
            if depth > 1:
                # 从 ancestors[-2] 开始向上查找
                for i in range(len(ancestors) - 2, -1, -1):
                    parent_section = ancestors[i]
                    if parent_section in section_to_chunk_id:
                        parent_id = section_to_chunk_id[parent_section]
                        break

            page_content = item["doc"].page_content
            has_table = "<table>" in page_content or \
                        ("|" in page_content and "---" in page_content)

            results.append(HierarchyChunk(
                content=page_content,
                chunk_id=item["chunk_id"],
                depth=depth,
                parent_id=parent_id,  # 正确设置父块 ID
                ancestors=ancestors,
                section_title=item.get("section_title", ""),
                metadata={
                    "source": source_name,
                    "chunk_index": len(results),
                    "has_table": has_table,
                    "char_count": len(page_content),
                    "method": "langchain_llm",
                    "is_placeholder": item.get("is_placeholder", False),
                },
            ))

        # 对超长切片进行智能二次切分
        results = self._split_long_chunks(results, source_name, max_chars=5000)

        logger.info(f"[HierarchySlicer] 切片完成: {len(results)} 切片")
        return results

    def _split_long_chunks(
        self,
        chunks: List[HierarchyChunk],
        source_name: str,
        max_chars: int = 5000
    ) -> List[HierarchyChunk]:
        """对超长切片进行智能二次切分

        策略：
        - 普通文本：按段落、句子边界切分
        - HTML 表格：按行切分，保留表头
        - 代码块/Mermaid：提取摘要

        Args:
            chunks: 原始切片列表
            source_name: 文档名称
            max_chars: 最大字符数限制

        Returns:
            处理后的切片列表
        """
        results = []

        for chunk in chunks:
            if len(chunk.content) <= max_chars:
                results.append(chunk)
                continue

            # 超长切片需要二次切分
            logger.info(f"[HierarchySlicer] 二次切分: {chunk.section_title} ({len(chunk.content)} 字符)")

            # 判断内容类型并选择切分策略
            if "<table>" in chunk.content:
                sub_chunks = self._split_table_chunk(chunk, source_name, max_chars)
            elif "```" in chunk.content and len(re.findall(r'```[\s\S]*?```', chunk.content)) > 0:
                sub_chunks = self._split_code_chunk(chunk, source_name, max_chars)
            else:
                sub_chunks = self._split_text_chunk(chunk, source_name, max_chars)

            results.extend(sub_chunks)

        return results

    def _split_table_chunk(
        self,
        chunk: HierarchyChunk,
        source_name: str,
        max_chars: int
    ) -> List[HierarchyChunk]:
        """切分包含 HTML 表格的超长切片

        策略：按表格行切分，保留表头

        Args:
            chunk: 原始切片
            source_name: 文档名称
            max_chars: 最大字符数

        Returns:
            切分后的子切片列表
        """
        content = chunk.content
        results = []

        # 提取表格前后的文本
        table_start = content.find("<table>")
        table_end = content.rfind("</table>") + len("</table>") if "</table>" in content else len(content)

        prefix_text = content[:table_start].strip() if table_start > 0 else ""
        suffix_text = content[table_end:].strip() if table_end < len(content) else ""
        table_content = content[table_start:table_end] if table_start >= 0 else content

        # 提取表头（第一行）
        header_match = re.search(r'<tr>(.*?)</tr>', table_content, re.DOTALL)
        header = header_match.group(0) if header_match else ""

        # 提取所有数据行
        rows = re.findall(r'<tr>.*?</tr>', table_content, re.DOTALL)
        data_rows = rows[1:] if len(rows) > 1 else rows

        if not data_rows:
            # 无法切分，保留原内容但截断
            return [self._create_sub_chunk(chunk, content[:max_chars], source_name, 0)]

        # 按行组合切分
        current_content = prefix_text + ("\n<table>" + header if header else "<table>")
        sub_index = 0

        for row in data_rows:
            test_content = current_content + "\n" + row
            if len(test_content) > max_chars and len(current_content) > len(prefix_text) + 10:
                # 当前内容已超限，保存并开始新切片
                results.append(self._create_sub_chunk(
                    chunk, current_content + "\n</table>", source_name, sub_index
                ))
                sub_index += 1
                current_content = "<table>" + header + "\n" + row
            else:
                current_content = test_content

        # 添加最后一个表格切片
        current_content += "\n</table>"
        if current_content.strip() and len(current_content) <= max_chars:
            results.append(self._create_sub_chunk(chunk, current_content, source_name, sub_index))
        elif current_content.strip():
            # 如果最后一个表格切片超限，需要进一步切分
            # 先保存当前内容（不含后缀）
            results.append(self._create_sub_chunk(
                chunk, current_content[:max_chars], source_name, sub_index
            ))

        # 处理表格后的内容（suffix_text）
        if suffix_text:
            if len(suffix_text) > max_chars:
                # suffix_text 也需要切分
                if "```" in suffix_text:
                    suffix_chunks = self._split_code_chunk(
                        HierarchyChunk(
                            content=suffix_text,
                            chunk_id=chunk.chunk_id,
                            depth=chunk.depth,
                            parent_id=chunk.parent_id,
                            ancestors=chunk.ancestors,
                            section_title=f"{chunk.section_title} (后缀)",
                            metadata=chunk.metadata,
                        ), source_name, max_chars
                    )
                else:
                    suffix_chunks = self._split_text_chunk(
                        HierarchyChunk(
                            content=suffix_text,
                            chunk_id=chunk.chunk_id,
                            depth=chunk.depth,
                            parent_id=chunk.parent_id,
                            ancestors=chunk.ancestors,
                            section_title=f"{chunk.section_title} (后缀)",
                            metadata=chunk.metadata,
                        ), source_name, max_chars
                    )
                results.extend(suffix_chunks)
            else:
                results.append(self._create_sub_chunk(chunk, suffix_text, source_name, sub_index + 1))

        return results if results else [chunk]

    def _split_code_chunk(
        self,
        chunk: HierarchyChunk,
        source_name: str,
        max_chars: int
    ) -> List[HierarchyChunk]:
        """切分包含代码块的超长切片

        策略：代码块保持完整，超出则提取摘要

        Args:
            chunk: 原始切片
            source_name: 文档名称
            max_chars: 最大字符数

        Returns:
            切分后的子切片列表
        """
        content = chunk.content

        # 统计代码块占比
        code_blocks = re.findall(r'```[\s\S]*?```', content)
        total_code_len = sum(len(b) for b in code_blocks)

        if total_code_len > max_chars * 0.7:
            # 代码块占比大，提取摘要
            summary = f"[代码块摘要: {len(code_blocks)} 个代码块, 共 {total_code_len} 字符]"
            # 保留代码块前后的文本
            non_code = re.sub(r'```[\s\S]*?```', '', content).strip()
            if non_code:
                summary = non_code[:max_chars - len(summary) - 100] + "\n\n" + summary

            return [self._create_sub_chunk(chunk, summary[:max_chars], source_name, 0)]

        # 否则按普通文本处理
        return self._split_text_chunk(chunk, source_name, max_chars)

    def _split_text_chunk(
        self,
        chunk: HierarchyChunk,
        source_name: str,
        max_chars: int
    ) -> List[HierarchyChunk]:
        """切分普通文本超长切片

        策略：按段落边界切分，保持句子完整

        Args:
            chunk: 原始切片
            source_name: 文档名称
            max_chars: 最大字符数

        Returns:
            切分后的子切片列表
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        # 使用递归字符切分器，优先按段落、句子边界切分
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chars,
            chunk_overlap=200,  # 重叠部分保持上下文
            separators=["\n\n", "\n", "。", "；", "，", " ", ""],
            length_function=len,
        )

        texts = splitter.split_text(chunk.content)
        results = []

        for i, text in enumerate(texts):
            results.append(self._create_sub_chunk(chunk, text, source_name, i))

        return results

    def _create_sub_chunk(
        self,
        parent: HierarchyChunk,
        content: str,
        source_name: str,
        sub_index: int
    ) -> HierarchyChunk:
        """创建子切片

        Args:
            parent: 父切片
            content: 子切片内容
            source_name: 文档名称
            sub_index: 子切片索引

        Returns:
            新的子切片
        """
        return HierarchyChunk(
            content=content,
            chunk_id=f"{parent.chunk_id}_{sub_index}",
            depth=parent.depth,
            parent_id=parent.parent_id,
            ancestors=parent.ancestors,
            section_title=f"{parent.section_title} (部分{sub_index + 1})" if sub_index > 0 else parent.section_title,
            metadata={
                **parent.metadata,
                "char_count": len(content),
                "is_sub_chunk": True,
                "parent_chunk_id": parent.chunk_id,
            },
        )

    def _fix_orphan_headings(self, chunks: List[HierarchyChunk]) -> List[HierarchyChunk]:
        """
        标记短切片为占位切片，并处理孤立切片

        核心原则：
        - 允许短切片（仅有标题）存在
        - 通过构建完整树保证无孤立节点
        - 在检索时根据占位标记合并子块内容
        - 孤立切片（顶层短切片且无子节点）强制合并到文档根节点

        Args:
            chunks: 切片列表

        Returns:
            处理后的切片列表
        """
        if len(chunks) < 2:
            return chunks

        # 构建父子关系映射
        children_map: Dict[str, List[str]] = {}
        chunk_by_id = {c.chunk_id: c for c in chunks}
        for chunk in chunks:
            if chunk.parent_id:
                children_map.setdefault(chunk.parent_id, []).append(chunk.chunk_id)

        # 找到文档根节点（depth=1 的第一个切片）
        root_chunk = None
        for chunk in chunks:
            if chunk.depth == 1:
                root_chunk = chunk
                break

        placeholder_count = 0
        orphan_fixed = 0

        for chunk in chunks:
            has_children = len(children_map.get(chunk.chunk_id, [])) > 0
            is_short = chunk.metadata.get("char_count", 0) < 50

            # 短切片且无子节点 → 标记为占位切片
            if is_short and not has_children and chunk.section_title:
                chunk.metadata["is_placeholder"] = True
                placeholder_count += 1
                logger.debug(f"[HierarchySlicer] 标记占位切片: {chunk.section_title}")

                # 孤立切片保护：顶层短切片且无子节点
                if chunk.depth == 1 and root_chunk and chunk.chunk_id != root_chunk.chunk_id:
                    # 将孤立切片的 parent_id 设为根节点
                    chunk.parent_id = root_chunk.chunk_id
                    # 更新 children_map
                    children_map.setdefault(root_chunk.chunk_id, []).append(chunk.chunk_id)
                    orphan_fixed += 1
                    logger.debug(f"[HierarchySlicer] 孤立切片已修复: {chunk.section_title} -> {root_chunk.section_title}")

            chunk.metadata["has_children"] = has_children

        if placeholder_count > 0:
            logger.info(f"[HierarchySlicer] 标记了 {placeholder_count} 个占位切片")
        if orphan_fixed > 0:
            logger.info(f"[HierarchySlicer] 修复了 {orphan_fixed} 个孤立切片")

        return chunks

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
    "Chunk",
    "OUTLINE_INDEX_DIR",
    # 从 context.py 重新导出
    "HierarchyTreeIndex",
    "OutlineIndexManager",
    "LLMOutlineCorrector",
]
