"""
Export Service - Unified export orchestration.

Orchestrates export of planning documents in multiple formats:
- JSON: Structured planning document
- MD: Markdown reports
- DOCX: Word documents
- Planning Text: Complete planning document

Supports layer-specific export (L1/L2/L3) and full document export.
"""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, validator

from app.services.report_store import ReportStore
from app.database.operations import get_planning_session_async
from .layer_exporter import LayerExporter, LayerExportConfig, LAYER_NAMES
from .generator import PlanningTextGenerator
from .config import PlanningTextConfig

logger = logging.getLogger(__name__)


class ExportFormat(str, Enum):
    """Export format options."""
    JSON = "json"
    MD = "md"
    DOCX = "docx"
    PLANNING_TEXT = "planning_text"


class ExportLayer(str, Enum):
    """Layer selection options."""
    L1 = "1"
    L2 = "2"
    L3 = "3"
    ALL = "all"


class SessionExportRequest(BaseModel):
    """Export request model."""
    formats: List[ExportFormat] = Field(default=[ExportFormat.JSON])
    layers: List[ExportLayer] = Field(default=[ExportLayer.ALL])
    include_rag_details: bool = Field(default=False)
    include_summaries: bool = Field(default=True)

    @validator('formats')
    def formats_not_empty(cls, v):
        if not v:
            raise ValueError('At least one format must be selected')
        return v


class ExportFile(BaseModel):
    """Single export file info."""
    format: ExportFormat
    layer: Optional[int] = None
    filename: str
    download_url: str
    size_bytes: Optional[int] = None


class SessionExportResponse(BaseModel):
    """Export response model."""
    session_id: str
    project_name: str
    files: List[ExportFile] = []
    generated_at: str
    errors: List[str] = []


class ExportService:
    """Unified export service for planning documents."""

    def __init__(self, session_id: str, output_dir: str = "output/export"):
        self.session_id = session_id
        self.output_dir = Path(output_dir) / session_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.store = ReportStore.get_instance()
        self._session_metadata: Optional[Tuple[str, str]] = None

    async def export(
        self,
        formats: List[ExportFormat],
        layers: List[ExportLayer],
        include_rag_details: bool = False,
        include_summaries: bool = True,
    ) -> SessionExportResponse:
        """
        Export planning documents in specified formats and layers.

        Args:
            formats: List of export formats (json, md, docx, planning_text)
            layers: List of layers to export (1, 2, 3, or all)
            include_rag_details: Include RAG knowledge sources in export
            include_summaries: Include dimension summaries in export

        Returns:
            SessionExportResponse with list of exported files
        """
        files: List[ExportFile] = []
        errors: List[str] = []

        # Resolve layers to export
        layer_nums = self._resolve_layers(layers)

        # Export layer-specific reports in parallel
        export_tasks = []
        for fmt in formats:
            if fmt == ExportFormat.PLANNING_TEXT:
                continue
            for layer in layer_nums:
                export_tasks.append(self._export_layer(
                    layer=layer,
                    fmt=fmt,
                    include_rag_details=include_rag_details,
                    include_summaries=include_summaries,
                ))

        if export_tasks:
            results = await asyncio.gather(*export_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    errors.append(f"Export task {i} failed: {result}")
                elif result:
                    files.append(result)

        # Export complete planning text if requested
        if ExportFormat.PLANNING_TEXT in formats:
            try:
                planning_files = await self._export_planning_text(
                    include_rag_details=include_rag_details,
                    include_summaries=include_summaries,
                )
                files.extend(planning_files)
            except Exception as e:
                errors.append(f"Planning text export failed: {e}")
                logger.error(f"[ExportService] {e}")

        # Get project name from session
        project_name, _ = await self._get_session_metadata()

        return SessionExportResponse(
            session_id=self.session_id,
            project_name=project_name,
            files=files,
            generated_at=datetime.now().isoformat(),
            errors=errors,
        )

    def _resolve_layers(self, layers: List[ExportLayer]) -> List[int]:
        """Resolve layer selection to actual layer numbers."""
        if ExportLayer.ALL in layers:
            return [1, 2, 3]
        return [int(l.value) for l in layers if l != ExportLayer.ALL]

    async def _export_layer(
        self,
        layer: int,
        fmt: ExportFormat,
        include_rag_details: bool,
        include_summaries: bool,
    ) -> Optional[ExportFile]:
        """Export a single layer in specified format."""
        config = LayerExportConfig(
            session_id=self.session_id,
            output_dir=str(self.output_dir),
            output_formats=(fmt.value,),
            include_rag_details=include_rag_details,
            include_summaries=include_summaries,
        )

        exporter = LayerExporter(config)
        result = await exporter.export_layer(layer)

        if result.errors:
            logger.warning(f"[ExportService] Layer {layer} export errors: {result.errors}")

        # Get the exported file path based on format
        file_path = None
        if fmt == ExportFormat.MD:
            file_path = result.md_path
        elif fmt == ExportFormat.JSON:
            file_path = result.json_path
        elif fmt == ExportFormat.DOCX:
            file_path = result.docx_path

        if not file_path:
            return None

        path = Path(file_path)
        layer_name = LAYER_NAMES.get(layer, f"Layer{layer}")
        filename = path.name
        download_url = f"/api/sessions/{self.session_id}/export/{filename}"

        return ExportFile(
            format=fmt,
            layer=layer,
            filename=filename,
            download_url=download_url,
            size_bytes=self._get_file_size(path),
        )

    async def _export_planning_text(
        self,
        include_rag_details: bool,
        include_summaries: bool,
    ) -> List[ExportFile]:
        """Export complete planning document."""
        files = []

        # Get project info from session (cached)
        project_name, village_name = await self._get_session_metadata()

        config = PlanningTextConfig(
            session_id=self.session_id,
            project_name=project_name,
            village_name=village_name,
            output_dir=str(self.output_dir),
            output_formats=("md", "json", "docx"),
            append_rag=include_rag_details,
            generate_tier3=True,  # Enable LLM generation for complete planning text
        )

        generator = PlanningTextGenerator(config)

        try:
            result = await generator.generate()

            if result.md_path:
                files.append(self._create_export_file(result.md_path, ExportFormat.PLANNING_TEXT))
            if result.json_path:
                files.append(self._create_export_file(result.json_path, ExportFormat.JSON))

            # Generate DOCX from MD
            if result.md_path:
                try:
                    import sys
                    from pathlib import Path
                    script_dir = Path(__file__).parent.parent.parent.parent.parent / "scripts"
                    if str(script_dir) not in sys.path:
                        sys.path.insert(0, str(script_dir))
                    from md_to_docx import create_docx_from_md
                    md_path = Path(result.md_path)
                    docx_path = md_path.with_suffix('.docx')
                    create_docx_from_md(md_path, docx_path)
                    files.append(self._create_export_file(str(docx_path), ExportFormat.DOCX))
                except Exception as e:
                    logger.warning(f"[ExportService] DOCX generation failed: {e}")

        except Exception as e:
            logger.error(f"[ExportService] Planning text generation failed: {e}")
            raise

        return files

    def _create_export_file(self, file_path: str, fmt: ExportFormat) -> ExportFile:
        """Create ExportFile from file path."""
        path = Path(file_path)
        return ExportFile(
            format=fmt,
            filename=path.name,
            download_url=f"/api/sessions/{self.session_id}/export/{path.name}",
            size_bytes=self._get_file_size(path),
        )

    def _get_file_size(self, path: Path) -> Optional[int]:
        """Get file size, return None if file doesn't exist."""
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return None

    async def _get_session_metadata(self) -> Tuple[str, str]:
        """Get session metadata (project_name, village_name) with caching."""
        if self._session_metadata is not None:
            return self._session_metadata

        try:
            session = await get_planning_session_async(self.session_id)
            if session:
                # project_name: 项目名称（如"金田村规划"）
                # village_name: 村名（如"金田村"）
                # township: 镇名（如"金田镇"）
                # 如果 village_name 为空，尝试用 township 作为后备
                village = session.get("village_name") or session.get("township", "")
                self._session_metadata = (
                    session.get("project_name", "村庄规划"),
                    village,
                )
                return self._session_metadata
        except Exception as e:
            logger.debug(f"[ExportService] Could not fetch session metadata: {e}")

        self._session_metadata = ("村庄规划", "")
        return self._session_metadata

    def get_file_path(self, filename: str) -> Optional[Path]:
        """Get full path for a exported file."""
        file_path = self.output_dir / filename
        if file_path.exists():
            return file_path
        return None


__all__ = [
    "ExportFormat",
    "ExportLayer",
    "SessionExportRequest",
    "ExportFile",
    "SessionExportResponse",
    "ExportService",
]
