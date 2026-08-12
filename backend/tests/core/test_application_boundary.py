from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.commands.create_session import (
    CreateSessionCommand,
    CreateSessionService,
)
from app.application.commands.submit_human_review import (
    SubmitHumanDecisionCommand,
    SubmitHumanDecisionService,
)


ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_v1_transport_has_no_runtime_store_or_sse_dependencies() -> None:
    forbidden_names = {
        "PlanningRuntimeService",
        "ReportStore",
        "ArtifactStore",
        "load_artifact",
        "SSEPublisher",
        "event_hub",
        "resolve_human_review",
        "CompositionRoot",
    }
    forbidden_imports = {
        "app.services.runtime",
        "app.infrastructure.artifacts.runtime",
        "app.infrastructure.reports.report_store",
        "app.infrastructure.events.sse_publisher",
    }
    transport_root = ROOT / "app" / "api" / "v1" / "routes"
    transport_files = sorted(transport_root.glob("*.py")) + [
        ROOT / "app" / "api" / "v1" / "session_create.py"
    ]
    for path in transport_files:
        source = path.read_text(encoding="utf-8")
        assert not forbidden_names.intersection(source), path
        assert not _imports(path).intersection(forbidden_imports), path


class _Upload:
    def __init__(self, filename: str, content: bytes = b"content") -> None:
        self.filename = filename
        self.content_type = "text/plain"
        self._content = content

    async def read(self) -> bytes:
        return self._content


class _Sessions:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []
        self.deleted: list[str] = []

    async def create(self, values: dict[str, object]) -> str:
        self.created.append(values)
        return str(values["session_id"])

    async def update(self, session_id: str, values: dict[str, object]) -> None:
        self.updated.append((session_id, values))

    async def delete(self, session_id: str) -> None:
        self.deleted.append(session_id)


class _Ingestion:
    async def process(self, file: object, session_id: str, category: str) -> dict[str, object]:
        upload = file
        return {
            "filename": getattr(upload, "filename", "unknown"),
            "file_category": category,
            "parsed_text": "parsed village data",
            "checksum": "checksum",
        }


class _Starter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def start(self, session_id: str, initial_state: dict[str, object]) -> None:
        self.calls.append((session_id, initial_state))


@pytest.mark.asyncio
async def test_create_session_command_coordinates_typed_ports() -> None:
    sessions = _Sessions()
    starter = _Starter()
    service = CreateSessionService(
        sessions=sessions,
        ingestion=_Ingestion(),
        starter=starter,
    )

    result = await service.execute(
        CreateSessionCommand(
            session_id="session-1",
            project_name="Village plan",
            village_name="Village",
            village_data="initial village data",
            village_data_files=(_Upload("landuse.geojson"),),
        )
    )

    assert result.session_id == "session-1"
    assert sessions.created[0]["session_id"] == "session-1"
    assert sessions.updated[0][0] == "session-1"
    assert starter.calls[0][0] == "session-1"
    assert sessions.deleted == []


@pytest.mark.asyncio
async def test_human_decision_command_enforces_event_compare_and_set() -> None:
    class _Runtime:
        def __init__(self) -> None:
            self.values = {
                "human_interrupt": {"event_id": "event-1"},
                "human_review_resume_consumed": False,
            }
            self.calls: list[tuple[str, dict[str, object], str]] = []

        async def current_values(self, session_id: str) -> dict[str, object]:
            return self.values

        async def resume_interrupt(
            self,
            session_id: str,
            resume_data: dict[str, object],
            *,
            expected_event_id: str,
        ) -> None:
            self.calls.append((session_id, resume_data, expected_event_id))

    runtime = _Runtime()
    service = SubmitHumanDecisionService(runtime)

    result = await service.execute(
        SubmitHumanDecisionCommand(
            session_id="session-1",
            event_id="event-1",
            action="approve",
            decisions={"target": "approved"},
        )
    )

    assert result.resolved is True
    assert runtime.calls == [
        (
            "session-1",
            {"target": "approved", "action": "approve"},
            "event-1",
        )
    ]


def test_application_projections_are_the_only_v1_projection_builders() -> None:
    transport_root = ROOT / "app" / "api" / "v1" / "routes"
    sources = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(transport_root.glob("*.py"))
    )
    assert "application.projections" in sources
    assert "def _artifact_payload" not in sources
    assert "def _delivery_projection" not in sources
    assert "def _render_layer_projection" not in sources
    assert "def _public_event" not in sources
