"""
文档摘要生成器

迁移来源：src/rag/core/summarization.py

为决策智能体提供多级摘要视图，实现从宏观到微观的渐进式文档理解。
"""
import re
from dataclasses import dataclass
from typing import Any, List

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import create_llm
from app.core.settings import DEFAULT_PROVIDER


@dataclass
class ChapterSummary:
    title: str
    level: int
    summary: str
    key_points: List[str]
    start_index: int
    end_index: int


@dataclass
class DocumentSummary:
    source: str
    executive_summary: str
    chapter_summaries: List[ChapterSummary]
    key_points: List[str]


EXECUTIVE_SUMMARY_SYSTEM = """你是一个专业的文档摘要专家，擅长提炼乡村规划、政策文件的核心内容。生成一份200字左右的执行摘要，包含核心目标、定位方向、关键指标、重点措施。"""

CHAPTER_SUMMARY_SYSTEM = """你是一个专业的文档分析专家。为文档的每个章节生成300字左右的摘要，包含章节主题、主要内容、关键要点。"""

KEY_POINTS_SYSTEM = """你是一个专业的信息提取专家。从文档中提取10-15条最关键的要点，包含发展目标、重要措施、关键项目、重要指标、时间节点。"""


class DocumentSummarizer:
    """文档摘要生成器"""

    def __init__(self, provider: str = DEFAULT_PROVIDER, temperature: float = 0.3):
        self.llm = create_llm(provider=provider, temperature=temperature)
        self._init_prompts()

    def _init_prompts(self):
        self.executive_summary_prompt = ChatPromptTemplate.from_messages([
            ("system", EXECUTIVE_SUMMARY_SYSTEM),
            ("human", "请为以下文档生成执行摘要：\n\n{content}")
        ])
        self.chapter_summary_prompt = ChatPromptTemplate.from_messages([
            ("system", CHAPTER_SUMMARY_SYSTEM),
            ("human", "请为以下章节生成摘要：\n\n章节标题：{title}\n\n章节内容：\n{content}")
        ])
        self.key_points_prompt = ChatPromptTemplate.from_messages([
            ("system", KEY_POINTS_SYSTEM),
            ("human", "请从以下文档中提取关键要点：\n\n{content}")
        ])

    def _split_by_headers(self, content: str) -> List[dict]:
        chapters = []
        lines = content.split('\n')
        current_chapter = {"title": "文档开头", "level": 0, "content": [], "start_index": 0}
        title_pattern = re.compile(r'^(#{1,6})\s+(.+)$')

        for i, line in enumerate(lines):
            match = title_pattern.match(line.strip())
            if match:
                if current_chapter["content"]:
                    end_index = sum(len(l) + 1 for l in lines[:i])
                    current_chapter["end_index"] = end_index
                    current_chapter["content"] = "\n".join(current_chapter["content"])
                    chapters.append(current_chapter.copy())
                level = len(match.group(1))
                title = match.group(2).strip()
                start_index = sum(len(l) + 1 for l in lines[:i+1])
                current_chapter = {"title": title, "level": level, "content": [], "start_index": start_index}
            else:
                current_chapter["content"].append(line)

        if current_chapter["content"]:
            current_chapter["end_index"] = len(content)
            current_chapter["content"] = "\n".join(current_chapter["content"])
            chapters.append(current_chapter)

        return chapters

    def _extract_bullet_points(self, text: str) -> List[str]:
        points = []
        for line in text.split('\n'):
            stripped = line.strip()
            if re.match(r'^[\*\-\•]\s+', stripped):
                point = re.sub(r'^[\*\-\•]\s+', '', stripped).strip()
            elif re.match(r'^\d+\.\s+', stripped):
                point = re.sub(r'^\d+\.\s+', '', stripped).strip()
            elif stripped and not stripped.startswith('#'):
                point = stripped
            else:
                continue
            if point and len(point) > 5:
                points.append(point)
        return points

    def _extract_simple_points(self, text: str, max_points: int = 15) -> List[str]:
        points = []
        for sentence in re.split(r'[。；;\n]', text):
            sentence = sentence.strip()
            if 10 < len(sentence) < 100:
                points.append(sentence)
                if len(points) >= max_points:
                    break
        return points

    def generate_executive_summary(self, document: Document) -> str:
        content = document.page_content[:5000]
        try:
            chain = self.executive_summary_prompt | self.llm
            result = chain.invoke({"content": content})
            return re.sub(r'^#+\s*', '', result.content.strip())
        except Exception as e:
            return f"执行摘要生成失败: {str(e)}"

    def generate_chapter_summaries(self, document: Document, max_chapters: int = 20) -> List[ChapterSummary]:
        content = document.page_content
        chapters = self._split_by_headers(content)
        if len(chapters) > max_chapters:
            chapters = chapters[:max_chapters]

        chapter_summaries = []
        for chapter in chapters:
            if len(chapter["content"].strip()) < 50:
                continue
            try:
                chain = self.chapter_summary_prompt | self.llm
                result = chain.invoke({"title": chapter["title"], "content": chapter["content"][:3000]})
                summary_text = result.content.strip()
                key_points = self._extract_bullet_points(summary_text) or self._extract_simple_points(summary_text, 5)
                chapter_summaries.append(ChapterSummary(
                    title=chapter["title"], level=chapter["level"],
                    summary=summary_text, key_points=key_points[:5],
                    start_index=chapter["start_index"], end_index=chapter["end_index"]
                ))
            except Exception as e:
                chapter_summaries.append(ChapterSummary(
                    title=chapter["title"], level=chapter["level"],
                    summary=f"摘要生成失败: {str(e)}", key_points=[],
                    start_index=chapter["start_index"], end_index=chapter["end_index"]
                ))
        return chapter_summaries

    def generate_key_points(self, document: Document) -> List[str]:
        content = document.page_content[:8000]
        try:
            chain = self.key_points_prompt | self.llm
            result = chain.invoke({"content": content})
            return self._extract_bullet_points(result.content.strip())[:15]
        except Exception as e:
            return self._extract_simple_points(content, 15)

    def generate_summary(self, document: Document) -> DocumentSummary:
        source = document.metadata.get("source", "unknown")
        return DocumentSummary(
            source=source,
            executive_summary=self.generate_executive_summary(document),
            chapter_summaries=self.generate_chapter_summaries(document),
            key_points=self.generate_key_points(document)
        )


def summarize_document(document: Document, provider: str = DEFAULT_PROVIDER) -> DocumentSummary:
    return DocumentSummarizer(provider=provider).generate_summary(document)


__all__ = ["DocumentSummarizer", "DocumentSummary", "ChapterSummary", "summarize_document"]