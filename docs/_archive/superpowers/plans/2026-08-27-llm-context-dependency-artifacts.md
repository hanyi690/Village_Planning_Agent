# LLM Context, Dependency Artifacts, and Async Summary Implementation Plan

> Superseded by [ADR 008](../../adr/008-final-llm-context-evidence-boundary.md).
> The implementation follows the hard-cut contracts in ADR 008 and does not
> retain the compatibility paths described in this historical plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the complete L1/L2/L3/GROUND/SELECT provider path small, portable, and deterministic by precomputing project cognition, routing only direct dependency artifacts through the configured dependency DAG, retrieving missing evidence from the canonical KG/Bundle/Fact plane without leaking retrieval context into analysis prompts, accepting validated JSON content for providers without strict schema/tool support, and generating report summaries in a separate asynchronous task.

**Architecture:** A versioned `ProjectCognitionSnapshot` is the preflight identity for every retrieval request. `EvidenceBroker` compiles one requirement-focused retrieval context, queries the canonical Fact Registry/KG/Bundle/RAG plane, and returns a compact `EvidencePacket`/`EvidenceCoverage`; its planner context and query trace never enter an analysis prompt. The dependency configuration remains the only cross-dimension context-routing authority: a new dependency-context reader loads the latest `instruction` artifact and summary metadata for exact direct upstream dimensions (`depends_on`, `layer_depends_on`, `phase_depends_on`) without loading report bodies. L1 and L2 run a bounded evidence loop (decision/observation → deterministic gap extraction → targeted KG/Bundle/Fact retrieval → compact recompile → typed semantic artifact); L2 remains abstract. L3, GROUND, and SELECT consume only deduplicated fact projections, abstract decisions, closed-set candidate cards, and targeted evidence packets. Report persistence writes a pending display summary first, then `TaskSupervisor` runs one deduplicated summary projection call using the complete structured artifact as its source. The shared structured runner keeps strict Instructor/tool behavior as the first path and enables a stage-scoped, fail-closed JSON-content/JSON-mode fallback for L1/L2/L3 and summary calls.

**Tech Stack:** Python 3, Pydantic V2, SQLModel/SQLAlchemy async sessions, LangGraph, Instructor 1.15.x, OpenAI-compatible providers, asyncio, pytest.

## Global Constraints

- L1 remains the only semantic producer from raw session reports; L2/L3 consume only the direct upstream artifacts allowed by the dependency graph.
- Full report bodies remain in `ReportStore` and are never concatenated into L2/L3 dependency prompts by default.
- Structured artifacts are validated locally by the existing Pydantic/closed-set boundaries; a syntactically valid JSON response is not accepted unless it validates against the requested model.
- JSON-content fallback is opt-in for the L1/L2/L3/summary contracts and must not weaken unrelated grounding/materialization contracts.
- Summary generation is independent of the hot report-generation call, is deduplicated by `(session, layer, dimension, version)`, and records an explicit pending state when it cannot complete.
- Do not use report-body character truncation as the context-control mechanism. Context reduction must come from dependency routing and typed projections; existing source-page segmentation for L1 extraction remains a separate ingestion boundary.
- Preserve existing user changes, LF line endings, Python 4-space indentation, and the central `run_structured_output` provider boundary.
- Do not print API keys, full prompts, report bodies, or provider response bodies in diagnostics.
- Every retrieval request must bind to a `ProjectCognitionSnapshot`/scope and return a safe digest, coverage status, and source-family counts; retrieval plans, query traces, raw KG/Bundle rows, and duplicate source text must not be copied into analysis messages.
- KG, Bundle, L1, and eligible text/RAG records are Fact Registry source families. Deduplication may merge equivalent claims but must preserve authority, source family, locator, version, conflict, and lineage metadata.
- L1/L2 may request evidence when text or current facts are insufficient. Evidence lookup is deterministic-first and requirement-scoped; an evidence gap is a valid typed outcome and never an excuse to fabricate an observed fact.
- L2 evidence retrieval is not disabled merely because L2 stays abstract. The default behavior may avoid broad document RAG, but KG/Bundle/Fact Registry lookup for declared requirements remains available and must be visible through compact coverage metadata.
- `run_rag`/evidence adapters must expose structured coverage to the worker without forcing a second retrieval call; display-oriented `explore_audit` is derived from that result rather than initialized as an empty semantic source.

---

### Task 1: Add the dependency-artifact context boundary

**Files:**
- Create: `backend/app/infrastructure/llm/dependency_context.py`
- Modify: `backend/app/infrastructure/reports/report_store.py:390-500`
- Test: `backend/tests/core/test_dependency_context.py`

**Interfaces:**
- Produces `DependencyArtifact` and `DependencyContext` immutable dataclasses.
- Produces `direct_dependency_keys(dimension_config) -> tuple[str, ...]`, preserving configured order and removing duplicates.
- Produces `load_dependency_context(session_id, dimension_key, config, layer) -> DependencyContext`.
- Produces `DependencyContext.render_for_prompt() -> str`, containing only dependency metadata, parsed structured `instruction` artifacts, and summary status; it never contains `DimensionReport.content`.
- `ReportStore` adds `get_latest_dependency_records(session_id, dependency_keys) -> dict[str, dict[str, Any]]`, selecting only `dimension_key`, `layer`, `version`, `report_id`, `summary`, and `instruction`.

- [ ] **Step 1: Write the failing routing tests**

```python
@pytest.mark.asyncio
async def test_dependency_context_reads_only_direct_configured_artifacts(monkeypatch):
    from types import SimpleNamespace
    from app.infrastructure.llm.dependency_context import load_dependency_context

    cfg = SimpleNamespace(
        depends_on=["resource_endowment"],
        layer_depends_on=["natural_environment", "land_use"],
        phase_depends_on=["planning_strategies"],
    )
    calls = []

    class Store:
        async def get_latest_dependency_records(self, session_id, dependency_keys):
            calls.append((session_id, tuple(dependency_keys)))
            return {
                "resource_endowment": {
                    "layer": 2,
                    "version": 3,
                    "report_id": "r-resource",
                    "summary": '{"summary_status":"resolved"}',
                    "instruction": '{"objectives":[{"objective_id":"o1"}]}',
                    "content": "THIS FULL BODY MUST NEVER BE RENDERED",
                },
                "natural_environment": {
                    "layer": 1,
                    "version": 2,
                    "report_id": "r-natural",
                    "summary": "pending",
                    "instruction": '{"observations":[{"fact_type":"risk"}]}',
                },
            }

    monkeypatch.setattr(
        "app.infrastructure.llm.dependency_context.ReportStore.get_instance",
        lambda: Store(),
    )
    context = await load_dependency_context("s1", "spatial_structure", cfg, 3)

    assert context.keys == (
        "resource_endowment",
        "natural_environment",
        "land_use",
        "planning_strategies",
    )
    assert "THIS FULL BODY" not in context.render_for_prompt()
    assert '"objective_id":"o1"' in context.render_for_prompt()
    assert calls == [("s1", context.keys)]


def test_direct_dependency_keys_deduplicates_all_three_edges_in_config_order():
    from types import SimpleNamespace
    from app.infrastructure.llm.dependency_context import direct_dependency_keys

    cfg = SimpleNamespace(
        depends_on=["a", "b"],
        layer_depends_on=["b", "c"],
        phase_depends_on=["a", "d"],
    )
    assert direct_dependency_keys(cfg) == ("a", "b", "c", "d")
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run from `F:\project\Village_Planning_Agent\backend`:

```powershell
python -m pytest tests/core/test_dependency_context.py -q -o addopts=''
```

Expected: FAIL because the dependency-context module and metadata query do not exist.

- [ ] **Step 3: Implement the metadata query and renderer**

Implement one SQL query in `ReportStore.get_latest_dependency_records()` ordered by the requested keys and descending version, then keep the first row for each dimension. `DependencyArtifact` must carry `dimension_key`, `layer`, `version`, `report_id`, `summary`, and a JSON-compatible `instruction`. Decode valid JSON containers for rendering; preserve an opaque instruction only as an explicit `instruction_status="unparseable"` diagnostic and never load or include `content`.

```python
@dataclass(frozen=True)
class DependencyArtifact:
    dimension_key: str
    layer: int
    version: int
    report_id: str
    summary: str
    instruction: Any
    instruction_status: str = "resolved"

@dataclass(frozen=True)
class DependencyContext:
    dimension_key: str
    layer: int
    keys: tuple[str, ...]
    artifacts: tuple[DependencyArtifact, ...]
    missing_keys: tuple[str, ...] = ()

    def render_for_prompt(self) -> str:
        payload = {
            "consumer_dimension": self.dimension_key,
            "consumer_layer": self.layer,
            "allowed_direct_dependencies": [
                {
                    "dimension_key": item.dimension_key,
                    "layer": item.layer,
                    "version": item.version,
                    "report_id": item.report_id,
                    "summary": item.summary,
                    "instruction": item.instruction,
                    "instruction_status": item.instruction_status,
                }
                for item in self.artifacts
            ],
            "missing_direct_dependencies": list(self.missing_keys),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

The renderer must not slice strings or append a “truncated” marker. A missing row is represented as a missing dependency, allowing the worker to fail closed with a useful diagnostic rather than silently using an unrelated report.

- [ ] **Step 4: Run the routing tests and existing report-store tests**

Run:

```powershell
python -m pytest tests/core/test_dependency_context.py tests/core/test_report_store.py -q -o addopts=''
```

Expected: PASS for the new routing behavior and no regression in report persistence.

### Task 2: Decouple report persistence from summary generation

**Files:**
- Modify: `backend/app/infrastructure/reports/report_store.py:83-260`
- Modify: `backend/app/infrastructure/tasks/task_supervisor.py:1-80`
- Modify: `backend/app/infrastructure/llm/dimension_runtime.py:1076-1126`
- Modify: `backend/app/data/ingestion/summary_generator.py:112-211`
- Test: `backend/tests/core/test_async_report_summary.py`

**Interfaces:**
- `ReportStore.schedule_summary(session_id, dim_key, layer, version, report_id, source_artifact) -> asyncio.Task | None` persists no report body into task state and uses `build_summary_task_key`.
- `ReportStore.bulk_save()` and `save()` write the caller-provided summary projection immediately, but never await an LLM summary call.
- `ReportStore.schedule_summary()` invokes `dimension_runtime.generate_summary(..., source_artifact=...)` after the report row exists, then calls `update_summary()` only if the row still has the same `report_id` and `version`.
- `generate_summary()` and `generate_summary_model()` accept a complete structured artifact as the preferred source; `content` remains a compatibility fallback for direct callers, not a prompt truncation mechanism.

- [ ] **Step 1: Write async lifecycle tests**

```python
@pytest.mark.asyncio
async def test_bulk_save_does_not_wait_for_summary_llm(monkeypatch):
    from app.infrastructure.reports.report_store import ReportStore

    started = asyncio.Event()
    release = asyncio.Event()

    async def generate_summary(*_args, **_kwargs):
        started.set()
        await release.wait()
        return '{"summary_status":"resolved"}'

    monkeypatch.setattr(
        "app.infrastructure.llm.dimension_runtime.generate_summary",
        generate_summary,
    )
    store = FakeReportStoreDatabaseBackedStore()
    report_id = await store.save_with_test_database(
        session_id="s1",
        dim_key="traffic",
        version=1,
        content="full report",
        layer=1,
        instruction='{"observations":[]}',
    )

    assert report_id
    assert not started.is_set()
```

```python
@pytest.mark.asyncio
async def test_summary_task_is_deduplicated_and_updates_only_matching_version(monkeypatch):
    from app.infrastructure.tasks.task_supervisor import TaskSupervisor, build_summary_task_key

    supervisor = TaskSupervisor()
    first = supervisor.create_task(build_summary_task_key("s1", 1, "traffic", 1), asyncio.sleep(0))
    second = supervisor.create_task(build_summary_task_key("s1", 1, "traffic", 1), asyncio.sleep(0))
    assert first.cancelled() or first.done()
    assert second is not first
```

- [ ] **Step 2: Run the tests to verify the current synchronous behavior fails the lifecycle assertion**

Run:

```powershell
python -m pytest tests/core/test_async_report_summary.py -q -o addopts=''
```

Expected: FAIL because `ReportStore.save()` currently awaits `_generate_summary()` before inserting the row.

- [ ] **Step 3: Implement pending-first persistence and supervised summary tasks**

Remove the `await self._generate_summary(...)` from the hot save path. After `save()` or `bulk_save()` successfully commits, schedule one task per report whose summary is pending or whose caller requests enrichment. Keep the existing deterministic typed projection as the initial event/UI-safe value, but mark it with `summary_status="pending"` when the asynchronous LLM projection is outstanding. Add a conditional `report_id`/`version` guard to `update_summary()` so an old task cannot overwrite a newer revision.

The summary prompt must consume the complete structured artifact (`instruction`) rather than `content[:3000]`. If a legacy report has no instruction artifact, use the complete report body only through an explicit compatibility path and record `summary_source="legacy_report_body"`; do not create a fake excerpt by slicing the body.

- [ ] **Step 4: Run summary lifecycle and existing projection tests**

Run:

```powershell
python -m pytest tests/core/test_async_report_summary.py tests/core/test_dimension_runtime_structured_projection.py tests/core/test_summary_report_projection.py -q -o addopts=''
```

Expected: PASS, with the existing direct `generate_summary()` contract preserved for compatibility and report writes no longer blocked by an LLM call.

### Task 3: Route L2/L3 inputs through direct dependency artifacts

**Files:**
- Modify: `backend/app/infrastructure/llm/dimension_runtime.py:834-957`
- Modify: `backend/app/domain/objectives/worker.py:106-142,514-557,845-860`
- Modify: `backend/app/domain/program/worker.py:1094-1127,1226-1237,1563-1679`
- Modify: `backend/app/domain/program/claim_projection.py:13-78`
- Test: `backend/tests/core/test_dependency_prompt_routing.py`

**Interfaces:**
- `load_dependency_reports()` and `load_layered_dependency_reports()` return `DependencyContext` renderings (or a typed context object) built from exact direct dependency keys, never full report bodies.
- `_build_prompt()` for L2 and L3 receives the dependency-context rendering and no longer invokes `_compact_prompt_background()` for upstream reports.
- L2 continues to use the authoritative `L1Snapshot`/`L1FactCatalog` for closed-set fact IDs; the dependency context carries dimension-level typed artifacts and report references, not a second copy of the full fact snapshot.
- L3 claims consumes only the configured direct L1/L2/same-layer artifacts plus the existing EvidenceGraph candidate context; `project_bank` uses claim artifacts directly instead of parsing report prose.

- [ ] **Step 1: Write prompt-routing tests**

```python
@pytest.mark.asyncio
async def test_l3_dependency_loader_never_calls_layer_report_body_loader(monkeypatch):
    from types import SimpleNamespace
    from app.infrastructure.llm.dimension_runtime import load_layered_dependency_reports

    cfg = SimpleNamespace(
        depends_on=["industry"],
        layer_depends_on=["socio_economic"],
        phase_depends_on=["planning_strategies"],
    )
    called = []

    class Store:
        async def get_latest_dependency_records(self, session_id, keys):
            called.append(tuple(keys))
            return {
                "industry": {
                    "layer": 3, "version": 1, "report_id": "r1",
                    "summary": '{"summary_status":"resolved"}',
                    "instruction": '{"claims":[{"claim_id":"c1","statement":"产业项目"}]}',
                },
                "socio_economic": {
                    "layer": 1, "version": 1, "report_id": "r2",
                    "summary": '{"summary_status":"resolved"}',
                    "instruction": '{"observations":[{"fact_type":"scoped_metric"}]}',
                },
                "planning_strategies": {
                    "layer": 2, "version": 1, "report_id": "r3",
                    "summary": '{"summary_status":"resolved"}',
                    "instruction": '{"strategies":[{"strategy_id":"s1"}]}',
                },
            }
        async def get_layer_reports(self, *_args, **_kwargs):
            raise AssertionError("full layer report loading is forbidden for L3 prompt routing")
        async def get_latest(self, *_args, **_kwargs):
            raise AssertionError("full report loading is forbidden for dependency prompt routing")

    monkeypatch.setattr(
        "app.infrastructure.llm.dimension_runtime.ReportStore.get_instance",
        lambda: Store(),
    )
    l1, l2, same = await load_layered_dependency_reports(
        "spatial_structure", cfg, 3, "s1", False,
    )
    assert '"claim_id":"c1"' in same
    assert '"fact_type":"scoped_metric"' in l1
    assert '"strategy_id":"s1"' in l2
    assert called == [("industry", "socio_economic", "planning_strategies")]
```

```python
def test_l3_report_synthesis_prompt_contains_validated_claims_but_not_original_full_prompt():
    from app.domain.program.worker import _build_l3_report_synthesis_prompt
    prompt = _build_l3_report_synthesis_prompt(
        "industry",
        "raw evidence and full planning context",
        validated_claim_set_fixture(),
        [],
    )
    assert "raw evidence and full planning context" not in prompt
    assert "validated" in prompt
```

- [ ] **Step 2: Run the routing tests and capture the current failures**

Run:

```powershell
python -m pytest tests/core/test_dependency_prompt_routing.py -q -o addopts=''
```

Expected: FAIL because current loaders call `get_latest()`/`get_layer_reports()` and L3 report synthesis appends the original full prompt.

- [ ] **Step 3: Implement direct-artifact routing**

Replace the duplicated `load_dependency_reports()` and `load_layered_dependency_reports()` body loaders with the shared dependency-context loader. For each dimension, use exactly:

```python
depends_on + layer_depends_on + phase_depends_on
```

in configured order, deduplicated once. Missing direct dependencies must produce a `DependencyError` that names the consumer and missing keys. Do not fall back to every report in a layer.

Change L3 report synthesis so it receives only the validated `PlanningClaimSet`, validation feedback, and a short report-writing instruction. Do not append the original `prompt`, raw EvidenceGraph context, or the full dependency prose again. Remove the `compact_claim_context()` report-parser path from `project_bank`; if compatibility is needed, parse the stored `instruction` artifact with the shared safe JSON decoder and emit claim fields directly.

Keep the L1 fact catalog path separate and authoritative. Do not duplicate its entire selectable-fact JSON into every dependency block; the L2/L3 closed-set helpers remain the sole source of runtime fact ID options.

- [ ] **Step 4: Run L2/L3 worker and dependency tests**

Run:

```powershell
python -m pytest tests/core/test_dependency_prompt_routing.py tests/core/test_l2* tests/core/test_planning_claim_provider_adapter.py tests/core/test_l3* -q -o addopts=''
```

Expected: PASS for direct dependency routing, no full-report loader calls, and no re-injection of the original L3 prompt into report synthesis.

### Task 4: Add an opt-in portable JSON-content fallback to the shared runner

**Files:**
- Modify: `backend/app/infrastructure/llm/structured.py:300-372,429-602,604-681`
- Modify: `backend/app/infrastructure/llm/instructor_client.py:18-116`
- Modify: `backend/app/domain/assessment/l1_extraction_loop.py:360-462`
- Modify: `backend/app/domain/objectives/worker.py:201-223,311-338`
- Modify: `backend/app/infrastructure/llm/planning_claims.py:84-106`
- Modify: `backend/app/data/ingestion/summary_generator.py:151-211`
- Test: `backend/tests/core/test_structured_output_runner.py`
- Test: `backend/tests/core/test_portable_structured_output.py`

**Interfaces:**
- `run_structured_output(..., allow_content_json: bool = False) -> ModelT` keeps the current strict default.
- When `allow_content_json=True`, the runner accepts a provider assistant content value only after `decode_json_container()` and `response_model.model_validate()` both succeed.
- On a tool/schema protocol failure, the runner may retry the same compact request once through an Instructor `Mode.JSON` client, identified in diagnostics as `structured_mode="json_fallback"`; it must not retry on ordinary provider quota/auth failures.
- `get_async_instructor_client(mode_override: str | None = None)` and its cache key support provider/mode-specific clients while preserving no-argument compatibility for existing test doubles.

- [ ] **Step 1: Write portable-output tests**

```python
@pytest.mark.asyncio
async def test_opt_in_runner_accepts_valid_json_content_after_missing_tool(monkeypatch):
    from app.infrastructure.llm import structured

    class CompletionClient:
        class Chat:
            class Completions:
                async def create(self, **_kwargs):
                    raise _retry_exception_with_content('{"value": 7}')
            completions = Completions()
        chat = Chat()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda *args, **kwargs: CompletionClient())
    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        contract_key="l2.decision",
        allow_content_json=True,
        max_retries=0,
        timeout=2,
    )
    assert result == _Result(value=7)
```

```python
@pytest.mark.asyncio
async def test_opt_in_runner_still_rejects_valid_json_that_fails_model_validation(monkeypatch):
    from app.infrastructure.llm import structured
    # Return {"other": 7}; assert the runner raises and never promotes it.
```

- [ ] **Step 2: Run the tests and verify strict behavior is unchanged**

Run:

```powershell
python -m pytest tests/core/test_portable_structured_output.py tests/core/test_structured_output_runner.py -q -o addopts=''
```

Expected: the new opt-in test fails before implementation, while the existing tests that omit `allow_content_json` continue to expect rejection.

- [ ] **Step 3: Implement content decoding and JSON-mode fallback**

Add a small helper that extracts the assistant message content from `InstructorRetryException.last_completion`, decodes it through `app.contracts.json_container.decode_json_container`, and validates the resulting object locally. Never accept prose, a JSON array when the response model expects an object, wrapper markers, or a model-invalid object.

For provider protocol failures that indicate unsupported tools/schema, call `get_async_instructor_client(mode_override="json")` once with the same prepared messages and response model. The protocol instruction for that retry must explicitly say “JSON content” so the model is not asked to emit a tool call. Do not increase input context or attach the previous full completion to the retry. Record only safe request/response shapes.

Pass `allow_content_json=True` only for `l1.observe`, `l1.report`, `l2.decision`, `l2.report`, `l3.claims`, `l3.report`, and `display.summary`. Leave grounding and execution contracts strict until separately audited.

- [ ] **Step 4: Run the full structured-output and contract-registry tests**

Run:

```powershell
python -m pytest tests/core/test_portable_structured_output.py tests/core/test_structured_output_runner.py tests/core/test_contract_registry.py tests/core/test_l1_typed_output_recovery.py tests/core/test_planning_claim_provider_adapter.py -q -o addopts=''
```

Expected: PASS, including old strict-default rejection tests and new opt-in portable-model tests.

### Task 5: Make stage calls small and observable without adding duplicate context

**Files:**
- Modify: `backend/app/domain/assessment/l1_extraction_loop.py:323-462`
- Modify: `backend/app/domain/objectives/worker.py:165-338`
- Modify: `backend/app/domain/program/worker.py:1167-1238`
- Modify: `backend/app/infrastructure/llm/stats_collector.py`
- Modify: `backend/app/infrastructure/llm/structured.py:429-448`
- Test: `backend/tests/core/test_llm_context_metrics.py`

**Interfaces:**
- Each structured request records safe `input_chars`, `input_message_count`, `output_chars` when available, `contract_key`, `dependency_keys`, and `summary_statuses` in the existing stats/step-report channels.
- L1 observe requests contain the current source page and compact task boundary only; report synthesis contains validated observations only.
- L2 decision/report requests remain separate; closed-set reasks include only validator feedback plus the same dependency artifact references, not a second full catalog/report body.
- L3 claims/report requests remain separate; report synthesis contains validated claims only.

- [ ] **Step 1: Write metric tests**

```python
def test_request_shape_reports_input_size_without_exposing_content():
    from app.infrastructure.llm.structured import _request_shape
    shape = _request_shape(
        {
            "model": "test",
            "messages": [
                {"role": "system", "content": "secret prompt"},
                {"role": "user", "content": "secret evidence"},
            ],
        },
        contract_key="l3.claims",
    )
    assert shape["input_chars"] > 0
    assert "secret evidence" not in str(shape)
```

- [ ] **Step 2: Implement safe input/output metrics and remove duplicate retry material**

Use the already prepared messages for metrics so system protocol text and user content are counted once. Keep only digests/lengths in logs. Change semantic retry builders to include validator paths and IDs/digests, not the original raw prompt. Do not introduce a generic “trim to N characters” helper.

- [ ] **Step 3: Run targeted worker and metrics tests**

Run:

```powershell
python -m pytest tests/core/test_llm_context_metrics.py tests/core/test_dimension_runtime_structured_projection.py tests/core/test_l1_typed_output_recovery.py tests/core/test_planning_claim_provider_adapter.py -q -o addopts=''
```

Expected: PASS with request sizes visible in safe diagnostics and no raw context leakage.

### Task 6: End-to-end verification and migration notes

**Files:**
- Modify: `docs/architecture/CURRENT_RUNTIME.md` or the closest current runtime document
- Modify: `backend/app/infrastructure/README.md` if the async summary/dependency artifact boundary needs a module entry
- Test: `backend/tests/core/test_dependency_context.py`
- Test: `backend/tests/core/test_async_report_summary.py`
- Test: `backend/tests/core/test_portable_structured_output.py`

- [ ] **Step 1: Run the complete targeted regression set**

Run from `F:\project\Village_Planning_Agent\backend`:

```powershell
python -m pytest tests/core/test_dependency_context.py tests/core/test_async_report_summary.py tests/core/test_portable_structured_output.py tests/core/test_structured_output_runner.py tests/core/test_contract_registry.py tests/core/test_llm_config.py tests/core/test_l1_typed_output_recovery.py tests/core/test_planning_claim_provider_adapter.py -q -o addopts=''
```

- [ ] **Step 2: Run static checks for direct provider calls and duplicate body loading**

Run:

```powershell
rg -n "chat\.completions\.create" backend/app
rg -n "get_layer_reports\(|get_latest\(" backend/app/infrastructure/llm backend/app/domain/objectives backend/app/domain/program
rg -n "\[:[0-9]+\].*(report|content|prompt)|_compact_prompt_background|compact_claim_context" backend/app/domain/objectives backend/app/domain/program backend/app/infrastructure/llm
```

Expected: direct provider calls remain centralized in `structured.py`; L2/L3 dependency loaders use metadata/artifact queries; no upstream report truncation helper remains in the planning prompt path. Any remaining slice must be an explicit field-level safety bound or L1 source-page segmentation, documented as such.

- [ ] **Step 3: Review the diff against the global constraints**

Check that:

- dependency routing uses all three configured edge lists exactly once;
- missing dependencies fail closed instead of falling back to all layer reports;
- report persistence returns before summary LLM completion;
- summary tasks cannot overwrite a newer report version;
- JSON fallback is opt-in and locally validated;
- no full report body, API key, or provider response is added to logs;
- old strict-output tests still pass.

- [ ] **Step 4: Document rollout configuration**

Document that deployments with models lacking tool/native schema support should set `LLM_STRUCTURED_MODE=json` or rely on the stage-scoped fallback, and that `BACKGROUND_SUMMARY_ENRICHMENT` controls whether the independent summary projection is attempted. Document the observable `pending` summary state and the fact that L1/L2/L3 semantic execution does not wait on display-summary completion.

### Task 7: Add project cognition and a cross-source evidence projection boundary

**Files:**
- Create or modify: `backend/app/contracts/evidence/*`, `backend/app/infrastructure/context/*`, `backend/app/evidence/retrieval/*`
- Modify: `backend/app/infrastructure/llm/dimension_runtime.py`
- Test: `backend/tests/core/test_project_cognition.py`
- Test: `backend/tests/core/test_evidence_context_isolation.py`

**Interfaces:**
- `ProjectCognitionSnapshot` is a versioned, JSON-safe artifact containing only project identity, source snapshot/version/digest refs, CRS/spatial scope, schema/entity counts, known anchors, and Fact Registry coverage statistics.
- `ProjectCognitionView` is a per-request projection containing the minimum scope and anchors required to compile a query. It must not contain report bodies, full KG/Bundle dumps, raw retrieval responses, or previous prompts.
- `FactProjection` is the normalized cross-source claim shape. Its identity/dedup key must preserve source family, authority, locator, snapshot/version, confidence, conflict status, and lineage.
- `build_project_cognition(context, scope) -> ProjectCognitionSnapshot` is deterministic and cacheable by project/session/source revisions.
- `render_analysis_evidence(packet, coverage, budget) -> str` renders facts, source refs, conflicts, and unresolved requirements only; it never renders the retrieval plan, query trace, raw candidates, or full-source content.

- [ ] **Step 1: Add failing contract tests**

Cover: stable cognition digest; KG and Bundle facts entering the same registry; equivalent claims deduplicating without losing source-family lineage; scope filtering; and retrieval/analysis packet separation.

- [ ] **Step 2: Implement deterministic cognition and projection adapters**

Reuse existing `PlanningContext`, `VillageBundle`, `KGFactRecord`, `EvidenceFact`, `EvidencePacket`, and `EvidenceCoverage` contracts. Do not introduce a second retriever or copy the entire `EvidenceBundle` into a prompt. Keep source records in the artifact/evidence plane and expose only bounded typed projections.

- [ ] **Step 3: Make `run_rag` return the shared evidence result safely**

Preserve existing call compatibility where possible, but attach `EvidenceCoverage`, packet digest, source-family counts, and skip/insufficiency status to the retrieval log/result. Workers must be able to build display audit data from this result without calling `retrieve_evidence` a second time.

### Task 8: Wire L1/L2 evidence loops and preserve compact downstream boundaries

**Files:**
- Modify: `backend/app/domain/assessment/analysis_node.py`
- Modify: `backend/app/domain/assessment/l1_extraction_loop.py`
- Modify: `backend/app/domain/objectives/worker.py`
- Modify: `backend/app/domain/program/worker.py`
- Modify: `backend/app/workflow/stages/ground.py`
- Modify: `backend/app/workflow/stages/select.py` if present
- Test: `backend/tests/core/test_l1_l2_evidence_loop.py`
- Test: `backend/tests/core/test_ground_select_context_boundary.py`

**Interfaces and invariants:**
- L1 preflight includes source index plus `ProjectCognitionView`; L1 observation analysis may request only missing fields/claims. A targeted KG/Bundle/Fact lookup is compiled into a compact `EvidencePacket`, then the observation artifact is revalidated before L1 report synthesis.
- L2 decision receives deduplicated L1 facts, direct dependency artifacts, abstract task constraints, and declared requirement coverage. If evidence is insufficient it emits a typed `needs_evidence`/gap state; after retrieval it is recompiled, but L2 remains abstract and never receives a full report body.
- Runtime `EvidenceCoverage.unresolved_requirements`, unavailable source families, and conflicts are deterministically merged into L1/L2 gap metadata. Model-authored gaps remain distinguishable from runtime gaps.
- L2-B → L3-A carries only direct dependency projections, L2 abstract decisions, canonical fact refs, and L3-targeted evidence. It does not carry L2 report prose, retrieval planner context, original L1 source text, or prior completion history.
- GROUND and SELECT continue to call the LLM reasoning boundary. They receive compact closed-set candidate/scenario cards and only request missing fields through the same EvidenceBroker; IDs, geometry, and hard constraints remain system validated.

- [ ] **Step 1: Add failing evidence-loop and boundary tests**

Cover L1 text insufficiency with KG/Bundle supplementation, L2 snapshot/coverage gaps, L2 abstract output, direct dependency routing, closed-set GROUND/SELECT JSON, and no duplicate raw context.

- [ ] **Step 2: Implement one bounded loop per stage**

Use a small maximum number of evidence rounds from the existing stage budget. Each round changes the requirement fingerprint and packet digest; it does not append another copy of the prior prompt. Prefer deterministic lookup first; use a retrieval LLM only for unresolved semantic query compilation.

- [ ] **Step 3: Update report/display projections**

L1/L2 report synthesis consumes validated semantic artifacts and exact source-span references only. `explore_audit` becomes a UI projection of coverage and counts. No report-body slice may be used as a substitute for evidence routing.

### Task 9: Verify real MiniMax execution through rendering and close the migration loop

**Files:**
- Modify: `docs/architecture/CURRENT_RUNTIME.md` or the closest current runtime document
- Test/verify: `backend/tests/acceptance/test_real_graph_resume_delivery.py`
- Test/verify: `frontend/e2e/v1-contract.spec.ts`
- Test/verify: `frontend/scripts/gis-e2e-playwright.ts`

- [ ] **Step 1: Run targeted regression without implicit e2e marker filtering**

Use `-o addopts='' -p no:cacheprovider -m 'not slow'` and record structured-output, evidence-context, summary, L1/L2 boundary, delivery, and render results.

- [ ] **Step 2: Run a fresh MiniMax graph/resume/delivery execution**

Use `LLM_PROVIDER=minimax`, `RUN_REAL_GRAPH_RESUME=true`, and a fresh non-persistent run root. Confirm real provider calls, L1/L2/L3 completion, GROUND/SELECT/EXECUTE/DELIVER, non-diagnostic delivery, non-empty `/map-layers`, and completed static/interactive render artifacts. Never print credentials, full prompts, or provider completions.

- [ ] **Step 3: Run frontend contract and GIS rendering verification against that service**

Confirm the browser reads the delivered layer manifest and renders at least one non-empty planning layer. Keep backend acceptance, API contract, and browser rendering evidence separate in the report.

- [ ] **Step 4: Record residual limitations**

Document any provider-specific retry/latency limitation, the exact stage where a run can abstain with `needs_evidence`, and which existing legacy callers still require migration. Do not call the goal complete until the fresh MiniMax path reaches rendering or a repeated external blocker has been formally recorded.
