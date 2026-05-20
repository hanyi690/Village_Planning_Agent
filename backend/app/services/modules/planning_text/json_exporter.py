"""
JSON exporter for planning document.

Exports the complete structured planning document as a single JSON file,
including all articles, RAG appendix, layer reports, and metadata.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .section_builder import BuildReport, ARTICLE_DEFS, CHAPTER_NAMES, _CH


class JsonExporter:

    def __init__(self, session_id: str, project_name: str):
        self.session_id = session_id
        self.project_name = project_name

    def export(
        self,
        report: BuildReport,
        markdown: str,
        rag_data: List[Dict[str, Any]],
        layer_reports: Dict[int, Dict[str, str]],
        dimension_summaries: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        chapters = self._build_chapters(report)
        articles = self._build_articles(report)

        return {
            "meta": {
                "project_name": self.project_name,
                "session_id": self.session_id,
                "generated_at": datetime.now().isoformat(),
                "strategy_counts": report.strategy_counts,
                "total_articles": len(report.articles),
                "completed_articles": sum(
                    1 for a in report.articles
                    if a.content and "【待" not in a.content
                ),
                "errors": report.errors,
            },
            "dimension_summaries": dimension_summaries or {},
            "chapters": chapters,
            "articles": articles,
            "rag_appendix": rag_data,
            "layer_reports": {
                f"layer{l}": reports for l, reports in layer_reports.items()
            },
            "markdown": markdown,
        }

    def write(
        self,
        report: BuildReport,
        markdown: str,
        rag_data: List[Dict[str, Any]],
        layer_reports: Dict[int, Dict[str, str]],
        output_path: str,
        dimension_summaries: Dict[str, Any] | None = None,
    ) -> str:
        data = self.export(report, markdown, rag_data, layer_reports, dimension_summaries)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return str(path)

    def _build_chapters(self, report: BuildReport) -> List[Dict[str, Any]]:
        chapters = []
        cur_ch = 0
        cur_articles = []
        for art in report.articles:
            ch = ARTICLE_DEFS[art.number][1]
            if ch != cur_ch:
                if cur_articles:
                    chapters.append({
                        "number": cur_ch,
                        "name": CHAPTER_NAMES.get(cur_ch, ""),
                        "articles": cur_articles,
                    })
                cur_ch = ch
                cur_articles = []
            cur_articles.append(self._article_to_dict(art))
        if cur_articles:
            chapters.append({
                "number": cur_ch,
                "name": CHAPTER_NAMES.get(cur_ch, ""),
                "articles": cur_articles,
            })
        return chapters

    def _build_articles(self, report: BuildReport) -> List[Dict[str, Any]]:
        return [self._article_to_dict(a) for a in report.articles]

    def _article_to_dict(self, art) -> Dict[str, Any]:
        return {
            "number": art.number,
            "title": art.title,
            "strategy": art.strategy,
            "content": art.content,
            "word_count": len(art.content) if art.content else 0,
        }
