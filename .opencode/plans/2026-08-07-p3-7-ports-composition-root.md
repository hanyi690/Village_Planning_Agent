# P3-7: Ports from Real Call Sites + Composition Root

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define Ports from actual call sites (not guessed interfaces), establish a composition root with explicit lifecycle, and route fire-and-forget tasks through TaskSupervisor with proper categorization.

**Architecture:** (1) Audit every `app.services` import from `app.modules` and extract the actual method signatures used -> define minimal Protocol ports. (2) Create a composition root (in `app/services/composition.py`) that creates `ReportStore`, `PlanningContext`, `TaskSupervisor` and injects them. (3) Categorize each `asyncio.create_task` in `session_routes.py` as request-scoped vs fire-and-forget vs cancellable, and route accordingly.

**Tech Stack:** Python, Protocol (typing), pytest

## Global Constraints

- Backend tests from `backend/` directory
- 4-space indent, double quotes
- LF line endings
- Commit only when explicitly asked, at task boundaries

---

### Task 1: Audit real call sites to define Ports

**Files:**
- Create: `docs/audit/port-call-sites.md` (audit document)
- Create: `backend/app/modules/ports/report_reader.py`
- Create: `backend/app/modules/ports/report_writer.py`

- [ ] **Step 1: Audit every ReportStore method call from modules**

Run: `cd backend && grep -rn "ReportStore\.\|store\.\|ReportStore" app/modules/ --include="*.py"`

For each call site, record: file, line, method called, arguments, return type used.

- [ ] **Step 2: Define minimal Ports from actual usage**

Based on the audit, split into reader and writer (don't create one fat Port):

```python
# report_reader.py
class ReportReaderPort(Protocol):
    def get_layer_reports_with_sources(self, session_id: str, layer: int) -> Dict[str, Any]: ...
    def get_report(self, session_id: str, layer: int, dimension_key: str) -> Optional[Dict[str, Any]]: ...

# report_writer.py
class ReportWriterPort(Protocol):
    def save_report(self, session_id: str, layer: int, dimension_key: str, content: str, ...) -> str: ...
```

Only include methods actually called from modules. Don't guess.

- [ ] **Step 3: Audit get_cached_context call from kg enrichment**

Run: `cd backend && grep -rn "get_cached_context\|planning_context" app/modules/kg/ --include="*.py"`

Define a `ContextReaderPort` with only the methods KG enrichment actually uses.

- [ ] **Step 4: Commit**

```bash
git add docs/audit/port-call-sites.md backend/app/modules/ports/
git commit -m "docs: audit real call sites and define minimal Ports"
```

---

### Task 2: Create composition root

**Files:**
- Create: `backend/app/services/composition.py`
- Modify: `backend/app/main.py` (initialize composition root in lifespan)

- [ ] **Step 1: Create composition root**

```python
# composition.py
"""Composition root: creates and injects all service dependencies.

Called from app.main lifespan. Modules receive Ports, not concrete services.
"""
from __future__ import annotations
from typing import Optional


class CompositionRoot:
    _report_store: Optional[object] = None  # ReportStore
    _task_supervisor: Optional[object] = None
    _context_provider: Optional[object] = None

    @classmethod
    def initialize(cls):
        from app.services.report_store import ReportStore
        from app.services.task_supervisor import TaskSupervisor
        cls._report_store = ReportStore.get_instance()
        cls._task_supervisor = TaskSupervisor()

    @classmethod
    def get_report_store(cls):
        if cls._report_store is None:
            cls.initialize()
        return cls._report_store

    @classmethod
    def get_task_supervisor(cls):
        if cls._task_supervisor is None:
            cls.initialize()
        return cls._task_supervisor
```

- [ ] **Step 2: Initialize in main.py lifespan**

In `backend/app/main.py` lifespan, add:
```python
    from app.services.composition import CompositionRoot
    CompositionRoot.initialize()
```

- [ ] **Step 3: Update modules to receive Ports via injection**

In `planning_text/generator.py`, `rag_appender.py`, `layer_exporter.py`, `rag/service.py`:
- Remove `from app.services.report_store import ReportStore`
- Add `store: ReportReaderPort` parameter to functions
- Callers in services layer pass `CompositionRoot.get_report_store()`

- [ ] **Step 4: Write architecture test**

```python
def test_no_module_imports_services():
    import os
    MODULES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "app", "modules")
    violations = []
    for root, dirs, files in os.walk(os.path.abspath(MODULES_DIR)):
        for f in files:
            if not f.endswith(".py"): continue
            filepath = os.path.join(root, f)
            with open(filepath, "r", encoding="utf-8") as fh:
                source = fh.read()
            if "from app.services" in source:
                violations.append(filepath)
    assert not violations
```

- [ ] **Step 5: Run tests and commit**

```bash
cd backend && python -m pytest tests/ -v --tb=short -x
git add backend/
git commit -m "feat: composition root + Port injection, eliminate modules->services imports"
```

---

### Task 3: Categorize and route fire-and-forget tasks

**Files:**
- Modify: `backend/app/api/session_routes.py` (8 create_task calls)

- [ ] **Step 1: Categorize each of the 8 calls**

For each `asyncio.create_task` at lines 521, 548, 598, 605, 628, 636, 708, 1014:
- Is it request-scoped (should finish before response)?
- Is it fire-and-forget (can outlive request)?
- Does it need cancellation support?
- Does it need deduplication?

Record in `docs/audit/task-categorization.md`.

- [ ] **Step 2: Route through TaskSupervisor**

For fire-and-forget tasks:
```python
supervisor = CompositionRoot.get_task_supervisor()
supervisor.create_task(session_id, coro)
```

For request-scoped tasks that should be awaited: just `await` them.

- [ ] **Step 3: Write test**

```python
def test_no_bare_create_task_in_session_routes():
    import inspect
    from app.api import session_routes
    source = inspect.getsource(session_routes)
    assert "asyncio.create_task" not in source
```

- [ ] **Step 4: Run tests and commit**

```bash
cd backend && python -m pytest tests/ -v --tb=short -x
git add backend/
git commit -m "fix: route all session_routes background tasks through TaskSupervisor"
```
