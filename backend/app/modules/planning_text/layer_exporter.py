"""
Layer report exporter.

Exports layer-specific reports (L1/现状分析, L2/规划思路, L3/详细规划)
in MD/JSON/DOCX formats with optional RAG dimension-level details.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT

from app.modules.ports.report_reader import ReportReaderPort
from app.modules.ports.registry import get_report_store_default
from app.modules.schema.layers import LAYER_NAMES_BY_NUMBER
from .docx_styles import (
    setup_document_styles,
    setup_page_margins,
    fix_heading_fonts,
    set_run_font,
    set_cell_font,
    CN_FONT,
    EN_FONT,
)

logger = logging.getLogger(__name__)

# Layer names (reuses LAYER_NAMES_BY_NUMBER from state)
LAYER_NAMES = LAYER_NAMES_BY_NUMBER

_TYPE_LABELS = {
    "policy": "法规",
    "standard": "标准",
    "textbook": "教材",
    "case": "案例",
    "planning": "上位规划",
    "guide": "指南",
}


@dataclass
class LayerExportConfig:
    """Configuration for layer report export."""
    session_id: str
    output_dir: str = "output/export"  # 统一到项目根目录
    output_formats: Tuple[str, ...] = ("md", "json", "docx")  # 默认包含 DOCX
    include_rag_details: bool = False
    include_summaries: bool = True


@dataclass
class DimensionReport:
    """Single dimension report with metadata."""
    dimension_key: str
    dimension_name: str
    layer: int
    content: str
    summary: Optional[Dict[str, Any]] = None
    rag_sources: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class LayerExportResult:
    """Result of layer export operation."""
    layer: int
    layer_name: str
    dimensions: List[DimensionReport]
    md_path: Optional[str] = None
    json_path: Optional[str] = None
    docx_path: Optional[str] = None
    errors: List[str] = field(default_factory=list)


class LayerExporter:
    """Exports layer-specific reports in multiple formats."""

    def __init__(self, config: LayerExportConfig, store: ReportReaderPort = None):
        self.config = config
        if store is None:
            store = get_report_store_default()
        self.store = store

    async def export_layer(self, layer: int) -> LayerExportResult:
        """Export a single layer report.

        Args:
            layer: Layer number (1, 2, or 3)

        Returns:
            LayerExportResult with paths to exported files
        """
        result = LayerExportResult(
            layer=layer,
            layer_name=LAYER_NAMES.get(layer, f"Layer {layer}"),
            dimensions=[],
        )

        # Fetch reports
        reports = await self.store.get_layer_reports(
            self.config.session_id, layer
        )
        if not reports:
            result.errors.append(f"Layer {layer} 无数据")
            return result

        # Fetch summaries if needed
        summaries = {}
        if self.config.include_summaries:
            try:
                summaries = await self.store.get_layer_summaries(
                    self.config.session_id, layer
                )
            except Exception as e:
                logger.warning(f"[LayerExporter] Failed to fetch summaries: {e}")

        # Fetch RAG sources if needed
        rag_sources = {}
        if self.config.include_rag_details:
            rag_sources = await self._fetch_rag_sources(layer)

        # Build dimension reports with proper ordering
        dim_names, dim_order = self._get_dimension_names_and_order()

        # Sort dimensions by configuration order
        sorted_dim_keys = sorted(
            reports.keys(),
            key=lambda k: dim_order.get(k, (layer, 999))
        )

        for dim_key in sorted_dim_keys:
            content = reports[dim_key]
            dim_report = DimensionReport(
                dimension_key=dim_key,
                dimension_name=dim_names.get(dim_key, dim_key),
                layer=layer,
                content=content,
                summary=summaries.get(dim_key),
                rag_sources=rag_sources.get(dim_key, []),
            )
            result.dimensions.append(dim_report)

        # Export files
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if "md" in self.config.output_formats:
            result.md_path = self._export_md(result, out_dir)

        if "json" in self.config.output_formats:
            result.json_path = self._export_json(result, out_dir)

        if "docx" in self.config.output_formats:
            result.docx_path = self._export_docx(result, out_dir)

        return result

    async def _fetch_layer_data(self, layer: int) -> LayerExportResult:
        """Fetch layer report data from database without writing files to disk."""
        result = LayerExportResult(
            layer=layer,
            layer_name=LAYER_NAMES.get(layer, f"Layer {layer}"),
            dimensions=[],
        )

        reports = await self.store.get_layer_reports(
            self.config.session_id, layer
        )
        if not reports:
            result.errors.append(f"Layer {layer} 无数据")
            return result

        summaries = {}
        if self.config.include_summaries:
            try:
                summaries = await self.store.get_layer_summaries(
                    self.config.session_id, layer
                )
            except Exception as e:
                logger.warning(f"[LayerExporter] Failed to fetch summaries: {e}")

        rag_sources = {}
        if self.config.include_rag_details:
            rag_sources = await self._fetch_rag_sources(layer)

        dim_names, dim_order = self._get_dimension_names_and_order()
        sorted_dim_keys = sorted(
            reports.keys(),
            key=lambda k: dim_order.get(k, (layer, 999))
        )

        for dim_key in sorted_dim_keys:
            content = reports[dim_key]
            dim_report = DimensionReport(
                dimension_key=dim_key,
                dimension_name=dim_names.get(dim_key, dim_key),
                layer=layer,
                content=content,
                summary=summaries.get(dim_key),
                rag_sources=rag_sources.get(dim_key, []),
            )
            result.dimensions.append(dim_report)

        return result

    async def export_all_layers(self) -> Dict[int, LayerExportResult]:
        """Export all three layer reports.

        Returns:
            Dict mapping layer number to LayerExportResult
        """
        import asyncio
        results = {}
        for layer in [1, 2, 3]:
            results[layer] = await self.export_layer(layer)
        return results

    # ---- Private methods ----

    async def _fetch_rag_sources(self, layer: int) -> Dict[str, List[Dict]]:
        """Fetch RAG knowledge sources for a layer."""
        rag_map = {}
        try:
            reports = await self.store.get_layer_reports_with_sources(
                self.config.session_id, layer
            )
            for dim_key, data in reports.items():
                ks = data.get("knowledge_sources")
                if not ks:
                    continue
                chunks = self._extract_chunks(ks)
                if chunks:
                    rag_map[dim_key] = self._process_rag_chunks(chunks)
        except Exception as e:
            logger.warning(f"[LayerExporter] Failed to fetch RAG sources: {e}")
        return rag_map

    def _process_rag_chunks(self, chunks: List[Dict]) -> List[Dict[str, Any]]:
        """Process RAG chunks into structured format."""
        seen = set()
        result = []
        for c in chunks:
            title = c.get("title", "")
            doc_type = c.get("doc_type", "")
            source = c.get("source", "")
            if not title and source:
                title, doc_type = self._lookup_source(source)
            if not title and source:
                title = source.rsplit("_minerU_parsed", 1)[0].removesuffix(".md").strip()
            if title and title not in seen:
                seen.add(title)
                result.append({
                    "title": title,
                    "doc_type": doc_type,
                    "label": _TYPE_LABELS.get(doc_type, doc_type),
                    "score": c.get("score", 0),
                    "content_preview": c.get("content", "")[:200] if c.get("content") else "",
                })
        return result

    def _export_md(self, result: LayerExportResult, out_dir: Path) -> str:
        """Export layer report as markdown."""
        lines = [
            f"# {result.layer_name}报告",
            "",
            f"**项目**: {self.config.session_id}",
            f"**层级**: Layer {result.layer} - {result.layer_name}",
            f"**维度数**: {len(result.dimensions)}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
        ]

        for dim in result.dimensions:
            lines.append(f"## {dim.dimension_name}")
            lines.append("")
            # Fix table formatting for consistent output
            content = self._fix_table_format(dim.content)
            lines.append(content)
            lines.append("")

            # Add RAG details if enabled
            if self.config.include_rag_details and dim.rag_sources:
                lines.append("### 参考知识来源")
                lines.append("")
                for src in dim.rag_sources:
                    lines.append(f"- [{src['label']}] {src['title']}")
                lines.append("")

            # Add summary if available
            if self.config.include_summaries and dim.summary:
                lines.append("### 结构化摘要")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(dim.summary, ensure_ascii=False, indent=2))
                lines.append("```")
                lines.append("")

            lines.append("---")
            lines.append("")

        md_content = "\n".join(lines)
        md_path = out_dir / f"L{result.layer}_{result.layer_name}.md"
        md_path.write_text(md_content, encoding='utf-8')
        logger.info(f"[LayerExporter] MD saved: {md_path}")
        return str(md_path)

    def _export_json(self, result: LayerExportResult, out_dir: Path) -> str:
        """Export layer report as JSON."""
        data = {
            "meta": {
                "session_id": self.config.session_id,
                "layer": result.layer,
                "layer_name": result.layer_name,
                "dimension_count": len(result.dimensions),
                "generated_at": datetime.now().isoformat(),
                "include_rag_details": self.config.include_rag_details,
                "include_summaries": self.config.include_summaries,
            },
            "dimensions": [],
        }

        for dim in result.dimensions:
            dim_data = {
                "key": dim.dimension_key,
                "name": dim.dimension_name,
                "layer": dim.layer,
                "content": dim.content,
                "word_count": len(dim.content) if dim.content else 0,
            }
            if self.config.include_summaries and dim.summary:
                dim_data["summary"] = dim.summary
            if self.config.include_rag_details and dim.rag_sources:
                dim_data["rag_sources"] = dim.rag_sources
            data["dimensions"].append(dim_data)

        json_path = out_dir / f"L{result.layer}_{result.layer_name}.json"
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        logger.info(f"[LayerExporter] JSON saved: {json_path}")
        return str(json_path)

    def _export_docx(self, result: LayerExportResult, out_dir: Path) -> Optional[str]:
        """Export layer report as DOCX using python-docx with table support."""
        # 直接使用 python-docx fallback 方法，因为 Pandoc 在 Windows 上不可靠
        return self._export_docx_fallback(result, out_dir)

    async def export_layer_to_bytes(self, layer: int) -> Optional[bytes]:
        """Export a single layer report as DOCX bytes (no file saved).

        Args:
            layer: Layer number (1, 2, or 3)

        Returns:
            DOCX file as bytes, or None if export failed
        """
        result = await self._fetch_layer_data(layer)
        if result.errors or not result.dimensions:
            return None

        try:
            from docx import Document
            from io import BytesIO

            doc = Document()
            setup_page_margins(doc)
            setup_document_styles(doc)

            title = doc.add_heading(f"{result.layer_name}报告", level=1)
            fix_heading_fonts(title)
            for run in title.runs:
                run.bold = True

            doc.add_paragraph(f"项目: {self.config.session_id}")
            doc.add_paragraph(f"层级: Layer {result.layer} - {result.layer_name}")
            doc.add_paragraph(f"维度数: {len(result.dimensions)}")
            doc.add_paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            doc.add_paragraph("")

            for dim in result.dimensions:
                h2 = doc.add_heading(dim.dimension_name, level=2)
                fix_heading_fonts(h2)
                for run in h2.runs:
                    run.bold = False
                if dim.content:
                    self._add_content_with_tables(doc, dim.content)

            # 保存到内存
            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            return buffer.getvalue()

        except Exception as e:
            logger.warning(f"[LayerExporter] Failed to export to bytes: {e}")
            return None

    async def export_layer_to_json_bytes(self, layer: int) -> Optional[bytes]:
        """Export a single layer report as JSON bytes (no file saved).

        Reuses export_layer to fetch and build data, then serializes
        the same JSON structure that _export_json produces.
        """
        result = await self._fetch_layer_data(layer)
        if result.errors or not result.dimensions:
            return None

        data = {
            "meta": {
                "session_id": self.config.session_id,
                "layer": result.layer,
                "layer_name": result.layer_name,
                "dimension_count": len(result.dimensions),
                "generated_at": datetime.now().isoformat(),
            },
            "dimensions": [],
        }

        for dim in result.dimensions:
            dim_data = {
                "key": dim.dimension_key,
                "name": dim.dimension_name,
                "layer": dim.layer,
                "content": dim.content,
            }
            if dim.summary:
                dim_data["summary"] = dim.summary
            data["dimensions"].append(dim_data)

        return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')

    async def export_layer_to_md_bytes(self, layer: int) -> Optional[bytes]:
        """Export a single layer report as Markdown bytes (no file saved).

        Reuses export_layer to fetch and build data, then renders
        the same Markdown content that _export_md produces.
        """
        result = await self._fetch_layer_data(layer)
        if result.errors or not result.dimensions:
            return None

        lines = [
            f"# {result.layer_name}报告",
            "",
            f"**项目**: {self.config.session_id}",
            f"**层级**: Layer {result.layer} - {result.layer_name}",
            f"**维度数**: {len(result.dimensions)}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
        ]

        for dim in result.dimensions:
            lines.append(f"## {dim.dimension_name}")
            lines.append("")
            lines.append(self._fix_table_format(dim.content))
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines).encode('utf-8')

    async def export_planning_text_to_bytes(
        self,
        project_name: str = "村庄规划",
        village_name: str = "",
    ) -> Optional[bytes]:
        """Export complete planning text as DOCX bytes (no file saved).

        Uses PlanningTextGenerator to generate Markdown, then converts
        to DOCX via md_to_docx.
        """
        import sys
        import tempfile

        from .generator import PlanningTextGenerator
        from .config import PlanningTextConfig

        config = PlanningTextConfig(
            session_id=self.config.session_id,
            project_name=project_name,
            village_name=village_name,
            output_dir=str(Path(self.config.output_dir) / "planning_text"),
            output_formats=(),
            append_rag=True,
            generate_tier3=True,
        )

        generator = PlanningTextGenerator(config)
        result = await generator.generate()

        md_content = getattr(result, 'markdown', None)
        if not md_content and getattr(result, 'md_path', None):
            md_path = Path(result.md_path)
            if md_path.exists():
                md_content = md_path.read_text(encoding='utf-8')

        if not md_content:
            logger.warning("[LayerExporter] No markdown content from PlanningTextGenerator")
            return None

        # Write MD to temp file, convert to DOCX via md_to_docx
        script_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "scripts"
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))

        from md_to_docx import create_docx_from_md

        with tempfile.TemporaryDirectory() as tmp_dir:
            md_tmp = Path(tmp_dir) / "planning_text.md"
            docx_tmp = Path(tmp_dir) / "planning_text.docx"
            md_tmp.write_text(md_content, encoding='utf-8')

            try:
                create_docx_from_md(md_tmp, docx_tmp)
                return docx_tmp.read_bytes()
            except Exception as e:
                logger.warning(f"[LayerExporter] MD->DOCX conversion failed: {e}")
                return None

    def _build_docx_markdown(self, result: LayerExportResult) -> str:
        """Build Markdown content for Pandoc conversion."""
        lines = [
            f"# {result.layer_name}报告",
            "",
            f"**项目**: {self.config.session_id}",
            f"**层级**: Layer {result.layer} - {result.layer_name}",
            f"**维度数**: {len(result.dimensions)}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
        ]

        for dim in result.dimensions:
            lines.append(f"## {dim.dimension_name}")
            lines.append("")
            # Fix table formatting: replace Chinese dashes with standard hyphens
            content = self._fix_table_format(dim.content)
            lines.append(content)
            lines.append("")

            if self.config.include_rag_details and dim.rag_sources:
                lines.append("### 参考知识来源")
                lines.append("")
                for src in dim.rag_sources:
                    lines.append(f"- [{src['label']}] {src['title']}")
                lines.append("")

            if self.config.include_summaries and dim.summary:
                lines.append("### 结构化摘要")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(dim.summary, ensure_ascii=False, indent=2))
                lines.append("```")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _fix_table_format(self, content: str) -> str:
        """Fix Markdown table formatting for Pandoc compatibility.

        Pandoc requires standard hyphens (-) in table separators,
        but LLM may generate Chinese dashes (—) which break rendering.
        """
        import re

        def fix_table_separator(line: str) -> str:
            # Match table separator lines like | :— | :— | or | ——— | ——— |
            # Replace Chinese dashes with standard hyphens
            if '|' in line and re.match(r'^\s*\|[:\s—―\-]+\|', line):
                # Replace Chinese dashes (— U+2014, ― U+2015) with hyphens
                return line.replace('—', '-').replace('―', '-')
            return line

        lines = content.split('\n')
        fixed_lines = [fix_table_separator(line) for line in lines]
        return '\n'.join(fixed_lines)

    def _export_docx_fallback(self, result: LayerExportResult, out_dir: Path) -> Optional[str]:
        """Fallback DOCX export using python-docx with table support."""
        try:
            from docx import Document

            doc = Document()
            setup_page_margins(doc)
            setup_document_styles(doc)

            title = doc.add_heading(f"{result.layer_name}报告", level=1)
            fix_heading_fonts(title)
            for run in title.runs:
                run.bold = True

            doc.add_paragraph(f"项目: {self.config.session_id}")
            doc.add_paragraph(f"层级: Layer {result.layer} - {result.layer_name}")
            doc.add_paragraph(f"维度数: {len(result.dimensions)}")
            doc.add_paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            doc.add_paragraph("")

            for dim in result.dimensions:
                h2 = doc.add_heading(dim.dimension_name, level=2)
                fix_heading_fonts(h2)
                for run in h2.runs:
                    run.bold = False

                if dim.content:
                    self._add_content_with_tables(doc, dim.content)

                if self.config.include_rag_details and dim.rag_sources:
                    h3 = doc.add_heading("参考知识来源", level=3)
                    fix_heading_fonts(h3)
                    for run in h3.runs:
                        run.bold = True
                    for src in dim.rag_sources:
                        p = doc.add_paragraph(f"[{src['label']}] {src['title']}")
                        set_run_font(p.runs[0]) if p.runs else None

                if self.config.include_summaries and dim.summary:
                    h3 = doc.add_heading("结构化摘要", level=3)
                    fix_heading_fonts(h3)
                    for run in h3.runs:
                        run.bold = True
                    p = doc.add_paragraph(
                        json.dumps(dim.summary, ensure_ascii=False, indent=2)
                    )
                    if p.runs:
                        set_run_font(p.runs[0], font_size=10.5)

            docx_path = out_dir / f"L{result.layer}_{result.layer_name}.docx"
            doc.save(str(docx_path))
            logger.info(f"[LayerExporter] DOCX saved (fallback with tables): {docx_path}")
            return str(docx_path)

        except ImportError:
            logger.warning("[LayerExporter] python-docx not installed, skipping DOCX export")
            return None
        except Exception as e:
            logger.warning(f"[LayerExporter] DOCX fallback export failed: {e}")
            return None

    def _add_content_with_tables(self, doc, content: str) -> None:
        """Add content to document, parsing and rendering Markdown tables."""
        import re

        # 分割内容为表格和非表格部分
        lines = content.split('\n')
        current_para_lines = []
        table_lines = []
        in_table = False

        for line in lines:
            # 检测表格开始（包含 | 的行）
            if '|' in line and not line.strip().startswith('#'):
                if not in_table:
                    # 先添加之前累积的段落
                    if current_para_lines:
                        para_text = '\n'.join(current_para_lines).strip()
                        if para_text:
                            self._add_formatted_paragraph(doc, para_text)
                        current_para_lines = []
                    in_table = True
                    table_lines = [line]
                else:
                    table_lines.append(line)
            else:
                if in_table:
                    # 表格结束，渲染表格
                    if table_lines:
                        self._add_markdown_table(doc, table_lines)
                    table_lines = []
                    in_table = False
                # 添加到当前段落
                current_para_lines.append(line)

        # 处理剩余内容
        if in_table and table_lines:
            self._add_markdown_table(doc, table_lines)
        elif current_para_lines:
            para_text = '\n'.join(current_para_lines).strip()
            if para_text:
                self._add_formatted_paragraph(doc, para_text)

    def _add_markdown_table(self, doc, table_lines: List[str]) -> None:
        """Parse Markdown table and add to document."""
        # 过滤空行
        table_lines = [l for l in table_lines if l.strip()]

        if len(table_lines) < 2:
            # 不是有效表格，作为普通文本添加
            doc.add_paragraph('\n'.join(table_lines))
            return

        # 解析表格
        rows_data = []
        for line in table_lines:
            # 跳过分隔行
            stripped = line.strip()
            if '|' in stripped and re.search(r':-+|:—+', stripped):
                continue
            cells = [c.strip() for c in line.split('|')]
            if cells and cells[0] == '':
                cells = cells[1:]
            if cells and cells[-1] == '':
                cells = cells[:-1]
            if cells:
                rows_data.append(cells)

        if not rows_data:
            return

        # 创建表格
        num_cols = max(len(row) for row in rows_data)
        num_rows = len(rows_data)

        table = doc.add_table(rows=num_rows, cols=num_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = 'Table Grid'

        # 填充数据
        for i, row_data in enumerate(rows_data):
            row = table.rows[i]
            for j, cell_text in enumerate(row_data):
                if j < num_cols:
                    cell = row.cells[j]
                    cell.text = ''
                    p = cell.paragraphs[0]
                    run = p.add_run(cell_text)
                    # 首行为表头：仿宋 11pt 加粗居中
                    if i == 0:
                        set_run_font(run, font_size=11, bold=True)
                    else:
                        set_run_font(run, font_size=10.5)

        # 添加空行分隔
        doc.add_paragraph("")

    def _add_formatted_paragraph(self, doc, text: str) -> None:
        """Add paragraph with basic formatting (bold, headers)."""
        # 检查是否是标题行
        if text.startswith('【') and text.endswith('】'):
            # 小标题：仿宋 12pt 加粗
            para = doc.add_paragraph()
            run = para.add_run(text)
            set_run_font(run, bold=True)
            para.paragraph_format.space_before = Pt(6)
            para.paragraph_format.space_after = Pt(3)
            para.paragraph_format.first_line_indent = Pt(0)
        elif re.match(r'^#+\s+', text):
            # Markdown 标题，提取内容
            level_match = re.match(r'^#+', text)
            level = len(level_match.group()) if level_match else 2
            content = re.sub(r'^#+\s+', '', text)
            heading = doc.add_heading(content, level=min(level, 3))
            fix_heading_fonts(heading)
            # Heading 2 不加粗，Heading 1/3 加粗
            for run in heading.runs:
                run.bold = (level != 2)
        else:
            # 普通段落，处理加粗
            para = doc.add_paragraph()
            # Font/alignment/line spacing inherited from Normal style

            # 处理 **bold** 格式
            parts = re.split(r'\*\*(.+?)\*\*', text)
            for i, part in enumerate(parts):
                if i % 2 == 1:  # 奇数索引是加粗内容
                    run = para.add_run(part)
                    set_run_font(run, bold=True)
                elif part:  # 非空普通文本
                    run = para.add_run(part)
                    set_run_font(run)

    def _get_dimension_names_and_order(self) -> Tuple[Dict[str, str], Dict[str, Tuple[int, int]]]:
        """Get dimension names and order from config."""
        try:
            from app.config.loader import load_config
            config = load_config()
            dim_names = {}
            dim_order = {}

            for phase in config.phases:
                # Extract layer number from phase id (e.g., "layer1" -> 1)
                layer = 1
                if phase.id.startswith("layer"):
                    try:
                        layer = int(phase.id.replace("layer", ""))
                    except ValueError:
                        pass

                for i, dim in enumerate(phase.dimensions):
                    dim_names[dim.key] = dim.name
                    dim_order[dim.key] = (layer, i)

            return dim_names, dim_order
        except Exception:
            return {}, {}

    @staticmethod
    def _extract_chunks(ks: Any) -> List[Dict]:
        """Extract chunks from knowledge sources."""
        if isinstance(ks, dict):
            chunks = ks.get("retrieved_chunks", [])
            if isinstance(chunks, list):
                return chunks
        if isinstance(ks, list):
            return [c for c in ks if isinstance(c, dict)]
        return []

    @staticmethod
    def _lookup_source(source: str) -> Tuple[str, str]:
        """Lookup source metadata from cache."""
        try:
            cache_path = (
                Path(__file__).parent.parent.parent.parent.parent.parent
                / "data" / "RAG_doc" / "_cache" / "source_metadata_map.json"
            )
            if not hasattr(LayerExporter, '_source_map'):
                LayerExporter._source_map = {}
                if cache_path.exists():
                    LayerExporter._source_map = json.loads(
                        cache_path.read_text("utf-8")
                    )
            info = LayerExporter._source_map.get(source, {})
            return info.get("title", ""), info.get("doc_type", "")
        except Exception:
            return "", ""


__all__ = [
    "LayerExportConfig",
    "LayerExporter",
    "LayerExportResult",
    "DimensionReport",
    "LAYER_NAMES",
]
