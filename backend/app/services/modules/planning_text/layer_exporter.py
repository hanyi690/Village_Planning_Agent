"""
Layer report exporter.

Exports layer-specific reports (L1/现状分析, L2/规划思路, L3/详细规划)
in MD/JSON/DOCX formats with optional RAG dimension-level details.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from app.services.report_store import ReportStore

logger = logging.getLogger(__name__)

# Layer names
LAYER_NAMES = {
    1: "现状分析",
    2: "规划思路",
    3: "详细规划",
}

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

    def __init__(self, config: LayerExportConfig):
        self.config = config
        self.store = ReportStore.get_instance()

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
        result = await self.export_layer(layer)
        if result.errors or not result.dimensions:
            return None

        try:
            from docx import Document
            from docx.shared import Pt, Cm
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.enum.table import WD_TABLE_ALIGNMENT
            from io import BytesIO

            doc = Document()

            # 设置页边距
            for section in doc.sections:
                section.top_margin = Cm(2.54)
                section.bottom_margin = Cm(2.54)
                section.left_margin = Cm(2.54)
                section.right_margin = Cm(2.54)

            title = doc.add_heading(f"{result.layer_name}报告", level=1)
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER

            doc.add_paragraph(f"项目: {self.config.session_id}")
            doc.add_paragraph(f"层级: Layer {result.layer} - {result.layer_name}")
            doc.add_paragraph(f"维度数: {len(result.dimensions)}")
            doc.add_paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            doc.add_paragraph("")

            for dim in result.dimensions:
                doc.add_heading(dim.dimension_name, level=2)
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

    def _apply_docx_styles(self, docx_path: Path) -> None:
        """Apply page margins and paragraph styles to DOCX."""
        try:
            from docx import Document
            from docx.shared import Cm, Pt
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement

            doc = Document(str(docx_path))

            # 设置页边距：上下左右各 2.54 cm (1 英寸)
            for section in doc.sections:
                section.top_margin = Cm(2.54)
                section.bottom_margin = Cm(2.54)
                section.left_margin = Cm(2.54)
                section.right_margin = Cm(2.54)

            # 设置段落格式
            for para in doc.paragraphs:
                # 正文段落：首行缩进 2 字符
                if para.style.name.startswith('Normal') or para.style.name == '':
                    para.paragraph_format.first_line_indent = Cm(0.74)  # 约 2 字符
                    para.paragraph_format.line_spacing = 1.5
                # 标题不缩进
                elif 'Heading' in para.style.name:
                    para.paragraph_format.first_line_indent = Cm(0)
                    para.paragraph_format.space_before = Pt(12)
                    para.paragraph_format.space_after = Pt(6)

            # 设置表格单元格内边距
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        cell.paragraphs[0].paragraph_format.space_before = Pt(2)
                        cell.paragraphs[0].paragraph_format.space_after = Pt(2)

            doc.save(str(docx_path))
            logger.debug(f"[LayerExporter] Applied styles to {docx_path}")

        except ImportError:
            logger.warning("[LayerExporter] python-docx not installed, skipping style application")
        except Exception as e:
            logger.warning(f"[LayerExporter] Failed to apply styles: {e}")

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
            from docx.shared import Pt, Cm, Inches
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.enum.table import WD_TABLE_ALIGNMENT
            from docx.oxml.ns import nsdecls
            from docx.oxml import parse_xml

            doc = Document()

            # 设置页边距
            for section in doc.sections:
                section.top_margin = Cm(2.54)
                section.bottom_margin = Cm(2.54)
                section.left_margin = Cm(2.54)
                section.right_margin = Cm(2.54)

            title = doc.add_heading(f"{result.layer_name}报告", level=1)
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER

            doc.add_paragraph(f"项目: {self.config.session_id}")
            doc.add_paragraph(f"层级: Layer {result.layer} - {result.layer_name}")
            doc.add_paragraph(f"维度数: {len(result.dimensions)}")
            doc.add_paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            doc.add_paragraph("")

            for dim in result.dimensions:
                doc.add_heading(dim.dimension_name, level=2)

                if dim.content:
                    self._add_content_with_tables(doc, dim.content)

                if self.config.include_rag_details and dim.rag_sources:
                    doc.add_heading("参考知识来源", level=3)
                    for src in dim.rag_sources:
                        doc.add_paragraph(
                            f"[{src['label']}] {src['title']}",
                            style='List Bullet',
                        )

                if self.config.include_summaries and dim.summary:
                    doc.add_heading("结构化摘要", level=3)
                    doc.add_paragraph(
                        json.dumps(dim.summary, ensure_ascii=False, indent=2)
                    )

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
        import re
        from docx.shared import Pt
        from docx.enum.table import WD_TABLE_ALIGNMENT

        # 过滤空行
        table_lines = [l for l in table_lines if l.strip()]

        if len(table_lines) < 2:
            # 不是有效表格，作为普通文本添加
            doc.add_paragraph('\n'.join(table_lines))
            return

        # 解析表格
        rows_data = []
        for line in table_lines:
            # 跳过分隔行（如 | :--- | :--- | 或 | :— | :— |）
            # 分隔行特征：包含 | 且只有 : - — 空格字符
            stripped = line.strip()
            # 检查是否是分隔行：包含 :- 或 :— 模式
            if '|' in stripped and re.search(r':-+|:—+', stripped):
                continue
            # 解析单元格
            cells = [c.strip() for c in line.split('|')]
            # 移除首尾空单元格（由边缘 | 产生）
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

        # 设置表格样式
        table.style = 'Table Grid'

        # 填充数据
        for i, row_data in enumerate(rows_data):
            row = table.rows[i]
            for j, cell_text in enumerate(row_data):
                if j < num_cols:
                    cell = row.cells[j]
                    cell.text = cell_text
                    # 设置单元格字体
                    for paragraph in cell.paragraphs:
                        paragraph.paragraph_format.space_before = Pt(2)
                        paragraph.paragraph_format.space_after = Pt(2)
                        for run in paragraph.runs:
                            run.font.size = Pt(10)

        # 添加空行分隔
        doc.add_paragraph("")

    def _add_formatted_paragraph(self, doc, text: str) -> None:
        """Add paragraph with basic formatting (bold, headers)."""
        import re
        from docx.shared import Pt, Cm

        # 检查是否是标题行
        if text.startswith('【') and text.endswith('】'):
            # 小标题
            para = doc.add_paragraph()
            run = para.add_run(text)
            run.bold = True
            run.font.size = Pt(11)
            para.paragraph_format.space_before = Pt(6)
            para.paragraph_format.space_after = Pt(3)
        elif re.match(r'^#+\s+', text):
            # Markdown 标题，提取内容
            level_match = re.match(r'^#+', text)
            level = len(level_match.group()) if level_match else 2
            content = re.sub(r'^#+\s+', '', text)
            heading = doc.add_heading(content, level=min(level, 3))
        else:
            # 普通段落，处理加粗
            para = doc.add_paragraph()
            para.paragraph_format.first_line_indent = Cm(0.74)
            para.paragraph_format.line_spacing = 1.5

            # 处理 **bold** 格式
            parts = re.split(r'\*\*(.+?)\*\*', text)
            for i, part in enumerate(parts):
                if i % 2 == 1:  # 奇数索引是加粗内容
                    run = para.add_run(part)
                    run.bold = True
                elif part:  # 非空普通文本
                    para.add_run(part)

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
