"""
层级索引上下文管理

提供文档上下文功能，基于层级树索引实现 Small-to-Big 检索。

包含：
- HierarchyTreeIndex: 层级树索引，用于 O(1) 查找父块
- OutlineIndexManager: 索引文件管理器
- LLMOutlineCorrector: LLM 大纲矫正器
- DocumentContextProvider: 文档上下文提供器（替代旧的 DocumentContextManager）

2026-05-17: 从 chunker.py 独立，整合上下文功能
"""
import logging
import re
import hashlib
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from app.core.settings import OUTLINE_INDEX_DIR

logger = logging.getLogger(__name__)


@dataclass
class HierarchyTreeIndex:
    """层级树索引：用于 O(1) 查找父块"""
    by_id: Dict[str, Dict] = field(default_factory=dict)  # chunk_id -> chunk_dict
    children: Dict[str, List[str]] = field(default_factory=dict)  # parent_id -> [child_ids]
    by_section: Dict[str, str] = field(default_factory=dict)  # section_title -> chunk_id

    def add_chunk(self, chunk_dict: Dict) -> None:
        """添加切片到索引"""
        chunk_id = chunk_dict.get("chunk_id", "")
        if chunk_id:
            self.by_id[chunk_id] = chunk_dict
        section_title = chunk_dict.get("section_title", "")
        if section_title and chunk_id:
            self.by_section[section_title] = chunk_id

    def build_parent_child_relations(self, chunks: List[Dict]) -> None:
        """构建父子关系映射"""
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "")
            parent_id = chunk.get("parent_id")
            if parent_id and parent_id in self.by_id:
                if parent_id not in self.children:
                    self.children[parent_id] = []
                self.children[parent_id].append(chunk_id)

    def get_parent(self, chunk_id: str) -> Optional[Dict]:
        """获取直接父块"""
        chunk = self.by_id.get(chunk_id)
        if chunk and chunk.get("parent_id"):
            return self.by_id.get(chunk["parent_id"])
        return None

    def get_ancestors(self, chunk_id: str) -> List[Dict]:
        """获取所有祖先块（从近到远）"""
        result = []
        chunk = self.by_id.get(chunk_id)
        while chunk and chunk.get("parent_id"):
            parent = self.by_id.get(chunk["parent_id"])
            if parent:
                result.append(parent)
                chunk = parent
            else:
                break
        return result

    def get_children(self, chunk_id: str) -> List[Dict]:
        """获取所有子块"""
        child_ids = self.children.get(chunk_id, [])
        return [self.by_id.get(cid) for cid in child_ids if cid in self.by_id]

    def find_ancestor_at_depth(self, chunk_id: str, target_depth: int) -> Optional[Dict]:
        """查找指定层级的祖先"""
        chunk = self.by_id.get(chunk_id)
        if not chunk:
            return None

        # 如果当前块就是目标层级，直接返回
        if chunk.get("depth") == target_depth:
            return chunk

        # 向上遍历找到目标层级的祖先
        while chunk:
            parent_id = chunk.get("parent_id")
            if parent_id:
                parent = self.by_id.get(parent_id)
                if parent and parent.get("depth") == target_depth:
                    return parent
                chunk = parent
            else:
                break
        return None

    def get_section_content(self, chunk_id: str) -> Optional[str]:
        """获取切片所属章节的完整内容（包含所有子块）"""
        chunk = self.by_id.get(chunk_id)
        if not chunk:
            return None

        # 收集当前块和所有子块内容
        contents = [chunk.get("content", "")]

        def collect_children(parent_id: str):
            child_ids = self.children.get(parent_id, [])
            for cid in child_ids:
                child = self.by_id.get(cid)
                if child:
                    contents.append(child.get("content", ""))
                    collect_children(cid)

        collect_children(chunk_id)
        return "\n\n".join(contents)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "by_id": self.by_id,
            "children": self.children,
            "by_section": self.by_section,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "HierarchyTreeIndex":
        """从字典创建"""
        return cls(
            by_id=data.get("by_id", {}),
            children=data.get("children", {}),
            by_section=data.get("by_section", {}),
        )


class OutlineIndexManager:
    """层级索引管理器"""

    def __init__(self, index_dir: Path = OUTLINE_INDEX_DIR):
        self.index_dir = index_dir
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def get_index_path(self, source_name: str) -> Path:
        """获取索引文件路径"""
        base_name = Path(source_name).stem
        return self.index_dir / f"{base_name}_index.json"

    def compute_file_hash(self, file_path: Path) -> str:
        """计算文件哈希"""
        content = file_path.read_bytes()
        return hashlib.md5(content).hexdigest()

    def exists(self, source_name: str) -> bool:
        """检查索引是否存在"""
        return self.get_index_path(source_name).exists()

    def load(self, source_name: str) -> Optional[Dict]:
        """加载索引（返回字典）"""
        index_path = self.get_index_path(source_name)
        if not index_path.exists():
            return None

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[OutlineIndexManager] 加载索引失败: {e}")
            return None

    def load_tree_index(self, source_name: str) -> Optional[HierarchyTreeIndex]:
        """加载树形索引"""
        data = self.load(source_name)
        if data and "tree_index" in data:
            return HierarchyTreeIndex.from_dict(data["tree_index"])
        return None

    def save(self, index: Dict) -> None:
        """保存索引"""
        source_name = index.get("source_name", "")
        index_path = self.get_index_path(source_name)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        logger.info(f"[OutlineIndexManager] 索引已保存: {index_path}")

    def is_valid(self, source_name: str, source_path: Path) -> bool:
        """检查索引是否有效（文件未变化）"""
        data = self.load(source_name)
        if not data:
            return False
        current_hash = self.compute_file_hash(source_path)
        return data.get("file_hash") == current_hash

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

    def __init__(self, batch_size: int = 100):
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
        """矫正文档大纲层级"""
        headings = self._extract_headings(content)

        if len(headings) < 2:
            logger.debug("[LLMOutlineCorrector] 标题数量不足，跳过矫正")
            return content, headings

        logger.info(f"[LLMOutlineCorrector] 提取 {len(headings)} 个候选标题")
        headings = self._infer_levels_with_llm(headings)
        corrected_content = self._rewrite_headings(content, headings)

        logger.info(f"[LLMOutlineCorrector] 矫正完成")
        return corrected_content, headings

    def _extract_headings(self, content: str) -> List[Dict]:
        """提取候选标题（增强版）"""
        lines = content.split("\n")
        headings = []

        def is_likely_heading(line: str, prev_line: str, next_line: str) -> bool:
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

            # Markdown 标题
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

            # 中文章节
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

            # 中文数字条款
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

            # 阿拉伯数字编号
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

            # 无"第"字中文编号
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

            match = re.match(r"^(\d+)[\.\、]\s*(.+)$", stripped)
            if match and is_likely_heading(stripped, prev_line, next_line):
                if not re.match(r"^\d+[\.\、]", next_line.strip()):
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

            # 罗马数字编号
            match = re.match(r"^([IVXLCDM]+)[\.\、]\s*(.+)$", stripped)
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
        """使用 LLM 推断标题层级（带重试机制）"""
        if len(headings) < 2:
            return headings

        total = len(headings)
        max_retries = 2  # 最大重试次数

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

            # 重试机制
            for retry in range(max_retries + 1):
                try:
                    response = self.llm.invoke(prompt)
                    content = response.content

                    json_match = re.search(r"\[[\s\S]*\]", content)
                    if json_match:
                        outline = json.loads(json_match.group())

                        for item in outline:
                            idx = item.get("index", 0)
                            level = item.get("level", 1)

                            try:
                                level = int(level) if level is not None else 1
                                level = max(1, min(level, 4))
                            except (ValueError, TypeError):
                                level = 1

                            if isinstance(idx, int) and 0 <= idx < len(batch):
                                global_idx = batch_start + idx
                                headings[global_idx]["inferred_level"] = level
                                headings[global_idx]["heading_type"] = item.get("type", "section")

                        logger.debug(f"[LLMOutlineCorrector] 批次 {batch_start//self.batch_size + 1} 完成")
                        break  # 成功，跳出重试循环

                except json.JSONDecodeError as e:
                    if retry < max_retries:
                        logger.warning(f"[LLMOutlineCorrector] JSON 解析失败，重试 {retry + 1}/{max_retries}: {e}")
                    else:
                        logger.warning(f"[LLMOutlineCorrector] JSON 解析失败，已达最大重试次数: {e}")
                        self._fallback_infer_batch(batch, headings, batch_start)
                except Exception as e:
                    if retry < max_retries:
                        logger.warning(f"[LLMOutlineCorrector] LLM 调用失败，重试 {retry + 1}/{max_retries}: {e}")
                    else:
                        logger.warning(f"[LLMOutlineCorrector] LLM 调用失败，已达最大重试次数: {e}")
                        self._fallback_infer_batch(batch, headings, batch_start)

        # 最终回退：为未推断的标题设置默认值
        for h in headings:
            if "inferred_level" not in h:
                h["inferred_level"] = self._smart_fallback_level(h)
                h["heading_type"] = "section"

        return headings

    def _fallback_infer_batch(self, batch: List[Dict], headings: List[Dict], batch_start: int):
        """批次失败时的回退推断"""
        for idx, h in enumerate(batch):
            global_idx = batch_start + idx
            headings[global_idx]["inferred_level"] = self._smart_fallback_level(h)
            headings[global_idx]["heading_type"] = "section"

    def _smart_fallback_level(self, heading: Dict) -> int:
        """智能回退：根据标题格式推断层级"""
        text = heading.get("clean_text", "")
        original_level = heading.get("original_level", 1) or 1

        # 根据中文编号格式推断
        if re.match(r'^第[一二三四五六七八九十]+[篇章]', text):
            return 1  # 篇/章 -> 一级
        if re.match(r'^第[一二三四五六七八九十]+[节条]', text):
            return 2  # 节/条 -> 二级
        if re.match(r'^[（(][一二三四五六七八九十]+[）)]', text):
            return 3  # （一）-> 三级
        if re.match(r'^\d+[\.、]', text):
            return 2  # 1. -> 二级

        # 回退到原始层级
        return original_level

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


class DocumentContextProvider:
    """
    文档上下文提供器

    替代旧的 DocumentContextManager，基于层级树索引实现上下文功能。
    """

    def __init__(self, index_manager: Optional[OutlineIndexManager] = None):
        self._index_manager = index_manager or OutlineIndexManager()
        self._tree_indices: Dict[str, HierarchyTreeIndex] = {}

    def load_tree_index(self, source_name: str) -> Optional[HierarchyTreeIndex]:
        """加载文档的树形索引"""
        if source_name in self._tree_indices:
            return self._tree_indices[source_name]

        tree_index = self._index_manager.load_tree_index(source_name)
        if tree_index:
            self._tree_indices[source_name] = tree_index
        return tree_index

    def get_section_context(self, chunk_id: str, source_name: str) -> Optional[Dict]:
        """
        获取切片所属父块的整个子树内容

        返回直接父块及其所有后代的内容（Small-to-Big 检索）。

        Args:
            chunk_id: 切片 ID
            source_name: 源文件名

        Returns:
            包含 content、section_title、depth 的字典
        """
        tree_index = self.load_tree_index(source_name)
        if not tree_index:
            return None

        chunk = tree_index.by_id.get(chunk_id)
        if not chunk:
            return None

        # 找到直接父块
        parent = tree_index.get_parent(chunk_id)
        target = parent if parent else chunk
        target_chunk_id = target.get("chunk_id", chunk_id)

        # 获取父块的子树内容（包含所有后代）
        content = tree_index.get_section_content(target_chunk_id)

        return {
            "content": content,
            "section_title": target.get("section_title", ""),
            "depth": target.get("depth", 1),
            "chunk_id": target_chunk_id,
        }

    def get_ancestor_at_depth(self, chunk_id: str, source_name: str, target_depth: int) -> Optional[Dict]:
        """
        获取指定层级的祖先块

        Args:
            chunk_id: 切片 ID
            source_name: 源文件名
            target_depth: 目标层级

        Returns:
            祖先块信息
        """
        tree_index = self.load_tree_index(source_name)
        if not tree_index:
            return None

        ancestor = tree_index.find_ancestor_at_depth(chunk_id, target_depth)
        if not ancestor:
            return None

        return {
            "content": ancestor.get("content", ""),
            "section_title": ancestor.get("section_title", ""),
            "depth": ancestor.get("depth", 1),
            "chunk_id": ancestor.get("chunk_id", ""),
        }

    def get_full_document(self, source_name: str) -> Optional[str]:
        """
        获取完整文档内容

        从 OutlineIndex.corrected_content 读取。
        """
        data = self._index_manager.load(source_name)
        if data:
            return data.get("corrected_content", "")
        return None

    def get_document_metadata(self, source_name: str) -> Optional[Dict]:
        """获取文档元数据"""
        return self._index_manager.load(source_name)


# 全局单例
_context_provider: Optional[DocumentContextProvider] = None


def get_context_provider() -> DocumentContextProvider:
    """获取文档上下文提供器单例"""
    global _context_provider
    if _context_provider is None:
        _context_provider = DocumentContextProvider()
    return _context_provider


__all__ = [
    "HierarchyTreeIndex",
    "OutlineIndexManager",
    "LLMOutlineCorrector",
    "DocumentContextProvider",
    "get_context_provider",
]
