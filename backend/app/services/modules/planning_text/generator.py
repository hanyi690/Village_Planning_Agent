"""
Planning text generator - main orchestrator.

Orchestrates the full pipeline: fetch reports from database,
extract structured data, build articles via strategy routing,
optionally run LLM for S-GENERATE articles, append RAG appendix,
and export to markdown + JSON.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from app.services.report_store import ReportStore

from .config import PlanningTextConfig
from .content_extractor import ContentExtractor, ExtractedData, create_extracted_data
from .section_builder import SectionBuilder, BuildReport
from .llm_styler import LLMStyler
from .rag_appender import RAGAppender
from .json_exporter import JsonExporter
from .layer_exporter import LayerExporter, LayerExportConfig, LayerExportResult

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    markdown: str = ""
    json_path: Optional[str] = None
    md_path: Optional[str] = None
    build_report: Optional[BuildReport] = None
    rag_data: List[Dict[str, Any]] = field(default_factory=list)
    layer_reports: Dict[int, Dict[str, str]] = field(default_factory=dict)
    layer_export_results: Dict[int, LayerExportResult] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class PlanningTextGenerator:

    def __init__(self, config: PlanningTextConfig):
        self.config = config
        self.store = ReportStore.get_instance()

    # ---- Public API ----

    async def generate(self) -> GenerationResult:
        result = GenerationResult()

        # Phase 1: Fetch all reports from database (3 layers in parallel)
        l1, l2, l3 = await asyncio.gather(
            self.store.get_layer_reports(self.config.session_id, 1),
            self.store.get_layer_reports(self.config.session_id, 2),
            self.store.get_layer_reports(self.config.session_id, 3),
        )
        result.layer_reports = {1: l1, 2: l2, 3: l3}

        if not l1 and not l2 and not l3:
            raise ValueError(
                f"No reports found for session {self.config.session_id}"
            )

        # Phase 2: Extract structured data and inject RAG legal titles
        # Fetch dimension summaries for structured field injection
        s1, s2, s3 = await asyncio.gather(
            self.store.get_layer_summaries(self.config.session_id, 1),
            self.store.get_layer_summaries(self.config.session_id, 2),
            self.store.get_layer_summaries(self.config.session_id, 3),
        )
        all_summaries = {**s1, **s2, **s3}

        data = create_extracted_data(l1, l2, l3,
            summaries=all_summaries,
            province=self.config.province,
            city=self.config.city,
            county=self.config.county,
            township=self.config.township)
        if self.config.append_rag:
            legal_titles = await self._collect_legal_titles()
            self._inject_legal_basis(data, legal_titles)

        # Phase 3: Build articles via strategy routing
        builder = SectionBuilder(data,
                                 village_name=self.config.village_name or self.config.project_name,
                                 planning_period=self.config.planning_period,
                                 township_name=self.config.township,
                                 province_name=self.config.province,
                                 city_name=self.config.city,
                                 county_name=self.config.county)
        build_report = builder.build_all()
        result.build_report = build_report

        # Phase 4: LLM fill S-GENERATE articles
        if self.config.generate_tier3:
            styler = LLMStyler(data,
                             village_name=self.config.village_name or self.config.project_name,
                             planning_period=self.config.planning_period)
            tier3 = await styler.generate_all()
            for art in build_report.articles:
                if art.strategy == "S-GENERATE" and art.number in tier3:
                    art.content = tier3[art.number]

        # Phase 5: Render markdown
        markdown = builder.render(build_report, self.config.village_name or self.config.project_name)

        # Phase 6: RAG appendix
        rag_data = []
        if self.config.append_rag:
            appender = RAGAppender(self.config.session_id)
            markdown = await appender.append(markdown)
            rag_data = await self._collect_rag_data()

        result.markdown = markdown
        result.rag_data = rag_data

        # Phase 7: Export files
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if "md" in self.config.output_formats:
            md_path = out_dir / f"{self.config.project_name}_规划文本.md"
            md_path.write_text(markdown, encoding='utf-8')
            result.md_path = str(md_path)
            logger.info(f"[Generator] Markdown saved: {md_path}")

        if "json" in self.config.output_formats:
            s1, s2, s3 = await asyncio.gather(
                self.store.get_layer_summaries(self.config.session_id, 1),
                self.store.get_layer_summaries(self.config.session_id, 2),
                self.store.get_layer_summaries(self.config.session_id, 3),
            )
            dim_summaries = {"layer1": s1, "layer2": s2, "layer3": s3}
            exporter = JsonExporter(self.config.session_id, self.config.project_name)
            json_path = out_dir / f"{self.config.project_name}_规划文本.json"
            exporter.write(build_report, markdown, rag_data, result.layer_reports, str(json_path), dim_summaries)
            result.json_path = str(json_path)
            logger.info(f"[Generator] JSON saved: {json_path}")

        result.errors = build_report.errors

        # Phase 8: Export layer reports if configured
        if self.config.export_layers:
            layer_results = await self.export_layers()
            result.layer_export_results = layer_results

        return result

    async def export_layers(self) -> Dict[int, LayerExportResult]:
        """Export layer-specific reports (L1/L2/L3).

        Returns:
            Dict mapping layer number to LayerExportResult
        """
        export_config = LayerExportConfig(
            session_id=self.config.session_id,
            output_dir=self.config.output_dir,
            output_formats=self.config.layer_output_formats,
            include_rag_details=self.config.include_rag_details,
            include_summaries=self.config.include_summaries,
        )
        exporter = LayerExporter(export_config)
        return await exporter.export_all_layers()

    async def export_single_layer(self, layer: int) -> LayerExportResult:
        """Export a single layer report.

        Args:
            layer: Layer number (1, 2, or 3)

        Returns:
            LayerExportResult
        """
        export_config = LayerExportConfig(
            session_id=self.config.session_id,
            output_dir=self.config.output_dir,
            output_formats=self.config.layer_output_formats,
            include_rag_details=self.config.include_rag_details,
            include_summaries=self.config.include_summaries,
        )
        exporter = LayerExporter(export_config)
        return await exporter.export_layer(layer)

    async def generate_layer_report(self, layer: int) -> str:
        reports = await self.store.get_layer_reports(self.config.session_id, layer)
        if not reports:
            return f"Layer {layer} 无数据"
        lines = [f"# Layer {layer} 报告", ""]
        for dim_key, content in reports.items():
            lines.append(f"## {dim_key}")
            lines.append("")
            lines.append(content)
            lines.append("")
        return '\n'.join(lines)

    def generate_sync(self) -> GenerationResult:
        return asyncio.run(self.generate())

    # ---- Internal ----

    async def _collect_rag_data(self) -> List[Dict[str, Any]]:
        entries = []
        try:
            from app.config.loader import load_phases_config
            phases = load_phases_config()
            dim_names = {}
            for phase in phases.get("phases", []):
                for dim in phase.get("dimensions", []):
                    dim_names[dim["key"]] = dim.get("name", dim["key"])
        except Exception:
            dim_names = {}

        for layer in [1, 2, 3]:
            try:
                reports = await self.store.get_layer_reports_with_sources(
                    self.config.session_id, layer
                )
            except Exception:
                continue
            for dim_key, data in reports.items():
                ks = data.get("knowledge_sources")
                if not ks:
                    continue
                chunks = self._extract_chunks(ks)
                if not chunks:
                    continue
                seen = set()
                cleaned = []
                for c in chunks:
                    title = c.get("title", "")
                    doc_type = c.get("doc_type", "")
                    source = c.get("source", "")
                    if (not title or not doc_type) and source:
                        t, d = self._lookup_source(source)
                        if not title:
                            title = t
                        if not doc_type:
                            doc_type = d
                    if not title and source:
                        title = source.rsplit("_minerU_parsed", 1)[0]
                        title = title.removesuffix(".md").strip()
                    if title and title not in seen:
                        seen.add(title)
                        cleaned.append({
                            "source": title,
                            "doc_type": doc_type,
                            "section": "",
                        })
                if cleaned:
                    entries.append({
                        "dimension_key": dim_key,
                        "dimension_name": dim_names.get(dim_key, dim_key),
                        "layer": layer,
                        "sources": cleaned,
                    })
        return entries

    async def _collect_legal_titles(self):
        national = set()
        provincial = set()
        planning = set()
        for layer in [1, 2, 3]:
            try:
                reports = await self.store.get_layer_reports_with_sources(
                    self.config.session_id, layer
                )
            except Exception:
                continue
            for data in reports.values():
                ks = data.get("knowledge_sources")
                if not ks:
                    continue
                chunks = self._extract_chunks(ks)
                for c in chunks:
                    title = c.get("title", "")
                    doc_type = c.get("doc_type", "")
                    subcategory = c.get("subcategory", "")
                    category = c.get("category", "")
                    if not title or not doc_type:
                        source = c.get("source", "")
                        if source:
                            t, d = self._lookup_source(source)
                            if not title:
                                title = t
                            if not doc_type:
                                doc_type = d
                            if not subcategory:
                                subcategory = self._lookup_subcategory(source)
                            if not category:
                                category = self._lookup_category(source)
                    # 过滤掉教材、案例、报告等非法规类文档
                    if doc_type in ("textbook", "case", "report"):
                        continue
                    if not title:
                        continue
                    # 基于 category 和 subcategory 分类
                    # 国家层面：法律法规(法律/行政法规) + 政策文件(国家层面) + 技术规范(国家层面)
                    # 省级层面：法律法规(地方性法规) + 政策文件(地方层面/广东省) + 技术规范(地方层面/广东省)
                    # 市县层面：上位规划
                    if category == "法律法规":
                        if subcategory in ("法律", "行政法规"):
                            national.add(title)
                        elif subcategory == "地方性法规":
                            provincial.add(title)
                        else:
                            national.add(title)  # 默认归入国家层面
                    elif category == "政策文件":
                        if subcategory == "国家层面":
                            national.add(title)
                        elif subcategory in ("地方层面", "广东省"):
                            provincial.add(title)
                        else:
                            provincial.add(title)  # 默认归入省级层面
                    elif category == "技术规范":
                        if subcategory == "国家层面":
                            national.add(title)
                        elif subcategory in ("地方层面", "广东省"):
                            provincial.add(title)
                        else:
                            national.add(title)  # 默认归入国家层面
                    else:
                        # 上位规划、其他
                        planning.add(title)
        return sorted(national), sorted(provincial), sorted(planning)

    @staticmethod
    def _lookup_subcategory(source: str) -> str:
        try:
            info = PlanningTextGenerator._source_map_cache.get(source, {})
            return info.get("subcategory", "")
        except Exception:
            return ""

    @staticmethod
    def _lookup_category(source: str) -> str:
        try:
            info = PlanningTextGenerator._source_map_cache.get(source, {})
            return info.get("category", "")
        except Exception:
            return ""

    @staticmethod
    def _inject_legal_basis(data, legal_titles):
        national, provincial, planning = legal_titles
        if national:
            data.legal_basis_national = sorted(set(data.legal_basis_national) | set(national))
        if provincial:
            data.legal_basis_provincial = sorted(set(data.legal_basis_provincial) | set(provincial))
        if planning:
            data.legal_basis_planning = sorted(set(data.legal_basis_planning) | set(planning))

    @staticmethod
    def _extract_chunks(ks) -> list:
        if isinstance(ks, dict):
            chunks = ks.get("retrieved_chunks", [])
            if isinstance(chunks, list):
                return chunks
        if isinstance(ks, list):
            return [c for c in ks if isinstance(c, dict)]
        return []

    @staticmethod
    def _lookup_source(source: str) -> tuple:
        try:
            import json
            from pathlib import Path
            cache_path = Path(__file__).parent.parent.parent.parent.parent.parent / "data" / "RAG_doc" / "_cache" / "source_metadata_map.json"
            if not hasattr(PlanningTextGenerator, '_source_map_cache'):
                PlanningTextGenerator._source_map_cache = {}
                if cache_path.exists():
                    PlanningTextGenerator._source_map_cache = json.loads(cache_path.read_text("utf-8"))
            info = PlanningTextGenerator._source_map_cache.get(source, {})
            return info.get("title", ""), info.get("doc_type", "")
        except Exception:
            return "", ""
