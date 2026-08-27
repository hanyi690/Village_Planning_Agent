# Evidence Retrieval Core Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current one-pass multi-retriever service into a bounded, requirement-driven evidence controller with clean storage boundaries, explicit coverage, iterative gap closure, and embedding-independent degraded operation.

**Architecture:** A neutral bundle query module removes the evidence-to-LLM dependency inversion. `EvidenceRequirement` and `EvidenceCoverage` become the unit of retrieval and sufficiency; a controller executes bounded rounds, while lexical, structured, graph, spatial, and optional dense results are fused without allowing any provider to own planning decisions.

**Tech Stack:** Python 3.12, FastAPI, Pydantic V2, asyncio, PostgreSQL-compatible retrieval contracts, pgvector-compatible rank fusion, pytest.

## Global Constraints

- Preserve `bundle://feature/<BSM>` as the only geometry-bearing reference exposed by evidence retrieval.
- Do not copy WKT or raw coordinates into evidence packets or LLM prompts.
- Dense embeddings are optional; lexical, Bundle, KG, report, and spatial retrieval must remain usable when the embedding provider is unavailable.
- External search remains opt-in and cannot satisfy a hard planning requirement without an authority and applicability decision.
- Retrieval may report bounded completeness only against declared requirements, source families, snapshots, and budgets.
- Keep all retrieval rounds deterministic for the same request and source-version fingerprints.
- Do not add a second evidence API; preserve `POST /api/v1/sessions/{session_id}/evidence/query`.
- Keep Python indentation at 4 spaces and line endings LF.
- Do not commit unrelated worktree changes.

---

## Target File Structure

```text
backend/app/contracts/evidence/
├── evidence_contracts.py
├── evidence_packet_contracts.py
└── requirement_contracts.py

backend/app/evidence/retrieval/
├── controller.py
├── query_planner.py
├── sufficiency.py
├── rank_fusion.py
├── evidence_service.py
└── retrievers/

backend/app/infrastructure/storage/
└── bundle_query.py
```

### Task 1: Remove the evidence-to-LLM import dependency

**Files:**
- Create: `backend/app/infrastructure/storage/bundle_query.py`
- Modify: `backend/app/infrastructure/llm/tools/access/shared.py`
- Modify: `backend/app/evidence/retrieval/retrievers/bundle_retriever.py`
- Modify: `backend/app/evidence/retrieval/retrievers/report_retriever.py`
- Modify: `backend/app/workflow/plan_state/completion_node.py`
- Create: `backend/tests/core/test_evidence_import_boundaries.py`

**Interfaces:**
- Consumes: `session_id: str`, cached/persisted/live VillageBundle sources.
- Produces: `resolve_bundle(session_id: str) -> VillageBundle` and `group_stats(bundle: VillageBundle) -> dict[str, Any]` without importing LangChain, LangGraph, Transformers, or LLM tool modules.

- [ ] **Step 1: Write the failing import-boundary test**

```python
import subprocess
import sys


def test_bundle_retriever_import_does_not_load_agent_frameworks() -> None:
    code = """
import sys
import app.evidence.retrieval.retrievers.bundle_retriever
blocked = sorted(name for name in sys.modules if name.startswith(('langgraph', 'langchain', 'transformers')))
print(blocked)
raise SystemExit(1 if blocked else 0)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run the test and verify the current reverse dependency fails**

```powershell
cd backend
pytest -q -o addopts='' tests/core/test_evidence_import_boundaries.py
```

Expected: FAIL and output includes at least one of `langgraph`, `langchain`, or `transformers`.

- [ ] **Step 3: Create the neutral bundle query module**

Move `resolve_bundle`, `_label_of`, and `group_stats` from `infrastructure/llm/tools/access/shared.py` into `infrastructure/storage/bundle_query.py`. The public surface must be:

```python
from typing import Any

from app.data.model.canonical import VillageBundle
from app.infrastructure.logging import get_logger


logger = get_logger(__name__)


async def resolve_bundle(session_id: str) -> VillageBundle:
    if not session_id:
        return VillageBundle(village_name="")

    from app.application.sessions.session_bundle import build_session_bundle, get_cached_bundle

    cached = get_cached_bundle(session_id)
    if cached is not None:
        return cached
    try:
        from app.infrastructure.storage.bundle_store import BundleStore

        stored = await BundleStore.get_instance().load_bundle(session_id)
        if stored is not None:
            return stored
    except Exception as exc:
        logger.warning("[BundleQuery] snapshot load failed for %s: %s", session_id, exc)
    try:
        return await build_session_bundle(session_id)
    except Exception as exc:
        logger.error("[BundleQuery] live build failed for %s: %s", session_id, exc)
        return VillageBundle(village_name="")


def group_stats(bundle: VillageBundle) -> dict[str, Any]:
    def label_of(feature: Any) -> str:
        for attribute in ("dlbm", "zone_type", "name", "layer_type"):
            value = getattr(feature, attribute, None)
            if value:
                return str(value)
        return "unknown"

    def entries(group: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in group.keys():
            features = group.get(key) or []
            labels: dict[str, int] = {}
            for feature in features:
                label = label_of(feature)
                labels[label] = labels.get(label, 0) + 1
            result[key] = {
                "count": len(features),
                "labels": dict(sorted(labels.items(), key=lambda item: -item[1])[:8]),
            }
        return result

    return {
        "points": entries(bundle.points),
        "lines": entries(bundle.lines),
        "polygons": entries(bundle.polygons),
    }


__all__ = ["group_stats", "resolve_bundle"]
```

Copy the existing snapshot-first behavior exactly: cache, persisted BundleStore, live build, then empty VillageBundle on failure.

- [ ] **Step 4: Keep a compatibility re-export for LLM access tools**

Replace the moved functions in `shared.py` with:

```python
from app.infrastructure.storage.bundle_query import group_stats, resolve_bundle
```

Do not change `session_kg`, `budget_check`, `tool_reply`, or `simplify_geometry` in this task.

- [ ] **Step 5: Point non-LLM consumers directly at the neutral module**

Use:

```python
from app.infrastructure.storage.bundle_query import group_stats, resolve_bundle
```

in Bundle/report retrievers and completion code. No file outside `infrastructure/llm/tools/access/` may import `infrastructure.llm.tools.access.shared` after this step.

- [ ] **Step 6: Run import and focused retrieval tests**

```powershell
pytest -q -o addopts='' tests/core/test_evidence_import_boundaries.py tests/core/test_explore_query_plan_and_sufficiency.py tests/core/test_evidence_graph_boundary.py
```

Expected: PASS.

- [ ] **Step 7: Commit the dependency-boundary repair**

```powershell
git add backend/app/infrastructure/storage/bundle_query.py backend/app/infrastructure/llm/tools/access/shared.py backend/app/evidence/retrieval/retrievers/bundle_retriever.py backend/app/evidence/retrieval/retrievers/report_retriever.py backend/app/workflow/plan_state/completion_node.py backend/tests/core/test_evidence_import_boundaries.py
git commit -m "refactor: decouple evidence retrieval from llm tools"
```

### Task 2: Introduce structured evidence requirements and coverage

**Files:**
- Create: `backend/app/contracts/evidence/requirement_contracts.py`
- Modify: `backend/app/contracts/evidence/__init__.py`
- Modify: `backend/app/contracts/evidence/evidence_contracts.py`
- Create: `backend/tests/contracts/test_evidence_requirement_contracts.py`

**Interfaces:**
- Consumes: natural-language request fields, source metadata, EvidenceFact identifiers.
- Produces: `EvidenceRequirement`, `EvidenceCoverage`, and `EvidenceCoverageReport` contracts.

- [ ] **Step 1: Write failing contract tests**

```python
import pytest
from pydantic import ValidationError

from app.contracts.evidence.requirement_contracts import (
    EvidenceCoverage,
    EvidenceCoverageReport,
    EvidenceRequirement,
)


def test_hard_requirement_needs_declared_source_families() -> None:
    with pytest.raises(ValidationError):
        EvidenceRequirement(
            requirement_id="req:farmland",
            statement="候选不得占用永久基本农田",
            claim_type="constraint",
            hardness="hard",
        )


def test_coverage_keeps_support_and_contradiction_separate() -> None:
    coverage = EvidenceCoverage(
        requirement_id="req:hazard",
        status="contradicted",
        supporting_fact_ids=["fact:1"],
        contradicting_fact_ids=["fact:2"],
        reason="authoritative sources disagree",
    )
    assert coverage.supporting_fact_ids == ["fact:1"]
    assert coverage.contradicting_fact_ids == ["fact:2"]


def test_report_is_not_sufficient_with_unresolved_hard_requirement() -> None:
    report = EvidenceCoverageReport(
        request_fingerprint="f" * 64,
        coverages=[EvidenceCoverage(
            requirement_id="req:hard",
            status="unavailable",
            reason="source exhausted",
        )],
        hard_requirement_ids=["req:hard"],
    )
    assert report.sufficient is False
```

- [ ] **Step 2: Run the contract tests and verify the module is missing**

```powershell
cd backend
pytest -q -o addopts='' tests/contracts/test_evidence_requirement_contracts.py
```

Expected: collection FAIL because `requirement_contracts` does not exist.

- [ ] **Step 3: Implement the requirement contracts**

Use these exact enums and fields:

```python
from typing import Literal
from pydantic import BaseModel, Field, model_validator


RequirementHardness = Literal["hard", "soft", "context"]
CoverageStatus = Literal["supported", "contradicted", "ambiguous", "unavailable"]


class EvidenceRequirement(BaseModel):
    requirement_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    claim_type: Literal["fact", "constraint", "identity", "geometry", "metric", "rule"]
    hardness: RequirementHardness = "context"
    entity_scope: list[str] = Field(default_factory=list)
    spatial_scope: str = ""
    temporal_scope: str = ""
    accepted_source_families: list[str] = Field(default_factory=list)
    minimum_independent_sources: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def validate_hard_requirement(self) -> "EvidenceRequirement":
        if self.hardness == "hard" and not self.accepted_source_families:
            raise ValueError("hard requirements must declare accepted_source_families")
        return self


class EvidenceCoverage(BaseModel):
    requirement_id: str = Field(min_length=1)
    status: CoverageStatus
    supporting_fact_ids: list[str] = Field(default_factory=list)
    contradicting_fact_ids: list[str] = Field(default_factory=list)
    source_family_coverage: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class EvidenceCoverageReport(BaseModel):
    request_fingerprint: str = Field(min_length=64, max_length=64)
    coverages: list[EvidenceCoverage] = Field(default_factory=list)
    hard_requirement_ids: list[str] = Field(default_factory=list)

    @property
    def sufficient(self) -> bool:
        by_id = {item.requirement_id: item for item in self.coverages}
        return all(
            requirement_id in by_id and by_id[requirement_id].status == "supported"
            for requirement_id in self.hard_requirement_ids
        )


StopReason = Literal["sufficient", "source_exhausted", "human_required", "budget_exhausted"]


class EvidenceRoundTrace(BaseModel):
    round_index: int = Field(ge=0)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    requirement_ids: list[str] = Field(default_factory=list)
    added_fact_ids: list[str] = Field(default_factory=list)
    remaining_requirement_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add `requirements` and `coverage_report` to the exploration result boundary**

Extend the existing request/result contracts with defaulted fields so existing API clients remain compatible:

```python
requirements: list[EvidenceRequirement] = Field(default_factory=list)
coverage_report: EvidenceCoverageReport | None = None
retrieval_rounds: list[EvidenceRoundTrace] = Field(default_factory=list)
stop_reason: StopReason | None = None
```

Extend `EvidenceFact` with stable identity and explicit requirement binding:

```python
fact_id: str = ""
requirement_ids: list[str] = Field(default_factory=list)

@model_validator(mode="after")
def derive_fact_id(self) -> "EvidenceFact":
    self.requirement_ids = sorted(set(item for item in self.requirement_ids if item))
    if not self.fact_id:
        payload = {
            "statement": " ".join(self.statement.split()).casefold(),
            "source_refs": sorted(set(self.source_refs)),
            "fact_type": self.fact_type,
            "source_locator": self.source_locator,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.fact_id = "fact:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return self
```

Add `hashlib`, `json`, and `model_validator` imports to `evidence_contracts.py`. Retrievers bind returned facts to the query's `requirement_ids`; the coverage evaluator never infers this association from list position.

Do not remove `required_facts` during this task; adapt each non-empty string to a context requirement at the application boundary.

- [ ] **Step 5: Run contract and API schema tests**

```powershell
pytest -q -o addopts='' tests/contracts/test_evidence_requirement_contracts.py tests/core/test_api_v1_contracts.py tests/core/test_evidence_query_api.py
```

Expected: PASS.

- [ ] **Step 6: Commit the requirement contracts**

```powershell
git add backend/app/contracts/evidence backend/tests/contracts/test_evidence_requirement_contracts.py
git commit -m "feat: add structured evidence requirements and coverage"
```

### Task 3: Plan queries per requirement and source family

**Files:**
- Modify: `backend/app/evidence/retrieval/query_planner.py`
- Modify: `backend/app/evidence/retrieval/router.py`
- Modify: `backend/tests/core/test_explore_query_plan_and_sufficiency.py`

**Interfaces:**
- Consumes: `ExplorationRequest.requirements` or the legacy `required_facts` adapter.
- Produces: bounded `EvidenceQuery` objects tied to requirement IDs and appropriate retrievers.

- [ ] **Step 1: Add failing tests for requirement-specific plans**

```python
def test_query_plan_does_not_send_identical_combined_query_to_every_retriever() -> None:
    request = ExplorationRequest(
        run_id="run:test",
        query="为养老设施选址",
        request_type="evidence_gap",
        requirements=[
            EvidenceRequirement(
                requirement_id="req:hazard",
                statement="候选不得落入地灾危险范围",
                claim_type="constraint",
                hardness="hard",
                accepted_source_families=["gis_layer"],
            ),
            EvidenceRequirement(
                requirement_id="req:policy",
                statement="养老设施适用的建设要求",
                claim_type="rule",
                hardness="hard",
                accepted_source_families=["planning_document"],
            ),
        ],
    )
    plan = build_query_plan(request)
    by_requirement = {query.requirement_ids[0]: query for query in plan.queries}
    assert by_requirement["req:hazard"].query != by_requirement["req:policy"].query
    assert by_requirement["req:hazard"].retriever in {RetrieverKind.BUNDLE, RetrieverKind.KG}
    assert by_requirement["req:policy"].retriever in {RetrieverKind.LOCAL_TEXT, RetrieverKind.REPORT, RetrieverKind.RAG}
```

- [ ] **Step 2: Run the test and verify the current combined-query behavior fails**

```powershell
cd backend
pytest -q -o addopts='' tests/core/test_explore_query_plan_and_sufficiency.py
```

Expected: FAIL because `EvidenceQuery` has no `requirement_ids` and the current planner duplicates one combined query.

- [ ] **Step 3: Extend `EvidenceQuery`**

Use:

```python
@dataclass(frozen=True)
class EvidenceQuery:
    query_id: str
    retriever: RetrieverKind
    query: str
    requirement_ids: tuple[str, ...] = ()
    entity_scope: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
```

Generate `query_id` from the request fingerprint, requirement ID, retriever name, and normalized query text.

- [ ] **Step 4: Add deterministic routing by claim type and source family**

Use this minimum routing policy:

```text
identity/geometry + gis_layer -> BUNDLE and KG
metric + gis_layer -> BUNDLE
fact/rule + planning_document -> LOCAL_TEXT, REPORT, and optional RAG
explicit context_refs -> the retriever that owns each reference
project-wide context -> LOCAL_TEXT, REPORT, KG, and BUNDLE
```

Keep the total number of queries at or below 24 and preserve deterministic ordering by requirement ID and retriever name.

- [ ] **Step 5: Run planner tests**

```powershell
pytest -q -o addopts='' tests/core/test_explore_query_plan_and_sufficiency.py tests/core/test_unified_rag_adapter.py
```

Expected: PASS.

- [ ] **Step 6: Commit the query planner**

```powershell
git add backend/app/evidence/retrieval/query_planner.py backend/app/evidence/retrieval/router.py backend/tests/core/test_explore_query_plan_and_sufficiency.py
git commit -m "feat: plan evidence retrieval by requirement"
```

### Task 4: Implement bounded iterative gap closure

**Files:**
- Create: `backend/app/evidence/retrieval/controller.py`
- Modify: `backend/app/evidence/retrieval/evidence_service.py`
- Modify: `backend/app/evidence/retrieval/sufficiency.py`
- Create: `backend/tests/core/test_evidence_gap_controller.py`

**Interfaces:**
- Consumes: one `ExplorationRequest` and an async single-round retriever.
- Produces: merged `ExplorationResult`, `EvidenceCoverageReport`, round trace, and a typed stop reason.

- [ ] **Step 1: Write failing controller tests**

```python
import pytest

from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    ExplorationRequest,
    ExplorationResult,
)
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.evidence.retrieval.controller import close_evidence_gaps


def requirement(requirement_id: str) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id=requirement_id,
        statement=f"evidence for {requirement_id}",
        claim_type="constraint",
        hardness="hard",
        accepted_source_families=["planning_document"],
    )


def request_with(*requirement_ids: str) -> ExplorationRequest:
    return ExplorationRequest(
        run_id="run:test",
        request_type="evidence_gap",
        query="test evidence",
        requirements=[requirement(item) for item in requirement_ids],
    )


def result_with(*requirement_ids: str) -> ExplorationResult:
    facts = [
        EvidenceFact(
            statement=f"supported {item}",
            source_refs=[f"source:{item}"],
            fact_type="statement",
            requirement_ids=[item],
        )
        for item in requirement_ids
    ]
    return ExplorationResult(evidence_bundle=EvidenceBundle(request="test", facts=facts))


@pytest.mark.asyncio
async def test_controller_retries_only_missing_requirements() -> None:
    seen = []

    async def retrieve_round(request):
        seen.append([item.requirement_id for item in request.requirements])
        return result_with("req:a") if len(seen) == 1 else result_with("req:b")

    result = await close_evidence_gaps(request_with("req:a", "req:b"), retrieve_round, max_rounds=2)
    assert seen == [["req:a", "req:b"], ["req:b"]]
    assert result.coverage_report.sufficient is True


@pytest.mark.asyncio
async def test_controller_stops_with_explicit_budget_exhaustion() -> None:
    async def retrieve_round(request):
        return result_with()

    result = await close_evidence_gaps(request_with("req:hard"), retrieve_round, max_rounds=2)
    assert result.stop_reason == "budget_exhausted"
    assert result.coverage_report.sufficient is False
    assert len(result.retrieval_rounds) == 2
```

The tests build ordinary `ExplorationRequest` and `ExplorationResult` instances and do not mock the coverage model itself.

- [ ] **Step 2: Run the controller tests and verify the module is missing**

```powershell
cd backend
pytest -q -o addopts='' tests/core/test_evidence_gap_controller.py
```

Expected: collection FAIL.

- [ ] **Step 3: Implement controller contracts and loop**

Use:

```python
from typing import Awaitable, Callable, Literal


StopReason = Literal["sufficient", "source_exhausted", "human_required", "budget_exhausted"]


RoundRetriever = Callable[[ExplorationRequest], Awaitable[ExplorationResult]]


async def close_evidence_gaps(
    request: ExplorationRequest,
    retrieve_round: RoundRetriever,
    *,
    max_rounds: int = 2,
) -> ExplorationResult:
    if max_rounds < 1:
        raise ValueError("max_rounds must be positive")
    current = request
    merged: ExplorationResult | None = None
    traces: list[EvidenceRoundTrace] = []
    for round_index in range(max_rounds):
        one_round = await retrieve_round(current)
        merged = merge_exploration_results(merged, one_round)
        report = build_coverage_report(request, merged)
        remaining = [
            item.requirement_id
            for item in request.requirements
            if next(
                (coverage.status for coverage in report.coverages if coverage.requirement_id == item.requirement_id),
                "unavailable",
            ) != "supported"
        ]
        traces.append(build_round_trace(round_index, current, one_round, remaining))
        if report.sufficient:
            merged.coverage_report = report
            merged.retrieval_rounds = traces
            merged.stop_reason = "sufficient"
            return merged
        if not remaining:
            merged.coverage_report = report
            merged.retrieval_rounds = traces
            merged.stop_reason = "source_exhausted"
            return merged
        current = current.model_copy(update={
            "requirements": [
                item for item in request.requirements if item.requirement_id in remaining
            ],
            "query_purpose": "gap_resolution",
        })
    assert merged is not None
    merged.coverage_report = build_coverage_report(request, merged)
    merged.retrieval_rounds = traces
    merged.stop_reason = "budget_exhausted"
    return merged
```

Implement `merge_exploration_results`, `build_coverage_report`, and `build_round_trace` in the same module as pure deterministic functions. Deduplicate facts by normalized statement, sorted source refs, and fact type; deduplicate sources by source type, reference, snapshot ref, evidence role, and authority; carry forward the newest non-null spatial cognition and evidence packet.

The controller must deduplicate facts and sources using the same stable keys as the existing service, rerun coverage after each merge, and form the next request from requirements whose status is not `supported`.

- [ ] **Step 4: Split public orchestration from one retrieval round**

Rename the existing `retrieve_evidence` body to:

```python
async def _retrieve_evidence_round(
    session_id: str,
    request: ExplorationRequest,
    *,
    context: PlanningContext | None = None,
    source_versions: dict[str, str] | None = None,
    external_port: ExternalEvidencePort | None = None,
    external_policy: ExternalSearchPolicy | None = None,
) -> ExplorationResult:
    return await _run_existing_retrievers_once(
        session_id=session_id,
        request=request,
        context=context,
        source_versions=source_versions,
        external_port=external_port,
        external_policy=external_policy,
    )
```

`_run_existing_retrievers_once` is the existing `retrieve_evidence` body renamed without semantic changes; it is not a new second orchestration path.

The public `retrieve_evidence` constructs one closure around the existing arguments and calls `close_evidence_gaps`. It must not recursively call itself.

- [ ] **Step 5: Replace lexical sufficiency as the authoritative result**

Keep the current string/CJK checks as a legacy adapter for requests with no structured requirements. For structured requirements, `evaluate_sufficiency` must consume `EvidenceCoverageReport`; a hard requirement is sufficient only when its coverage status is `supported` and its accepted source-family count is met.

- [ ] **Step 6: Run controller, API, and external-fallback tests**

```powershell
pytest -q -o addopts='' tests/core/test_evidence_gap_controller.py tests/core/test_explore_query_plan_and_sufficiency.py tests/core/test_unified_external_evidence_fallback.py tests/core/test_evidence_query_api.py
```

Expected: PASS.

- [ ] **Step 7: Commit iterative retrieval**

```powershell
git add backend/app/evidence/retrieval/controller.py backend/app/evidence/retrieval/evidence_service.py backend/app/evidence/retrieval/sufficiency.py backend/tests/core/test_evidence_gap_controller.py
git commit -m "feat: close evidence gaps with bounded retrieval rounds"
```

### Task 5: Add embedding-optional rank fusion

**Files:**
- Create: `backend/app/evidence/retrieval/rank_fusion.py`
- Modify: `backend/app/evidence/retrieval/evidence_service.py`
- Modify: `backend/app/evidence/retrieval/retrievers/local_text_retriever.py`
- Modify: `backend/app/evidence/retrieval/retrievers/rag_retriever.py`
- Create: `backend/tests/core/test_evidence_rank_fusion.py`

**Interfaces:**
- Consumes: ranked fact IDs from lexical, dense, graph, and spatial retrievers.
- Produces: deterministic reciprocal-rank-fusion scores with no requirement for every channel to be present.

- [ ] **Step 1: Write failing RRF tests**

```python
from app.evidence.retrieval.rank_fusion import reciprocal_rank_fusion


def test_rrf_combines_available_channels() -> None:
    scores = reciprocal_rank_fusion({
        "lexical": ["a", "b", "c"],
        "dense": ["b", "d", "a"],
    })
    assert scores["b"] > scores["c"]
    assert scores["a"] > scores["d"]


def test_rrf_operates_without_dense_results() -> None:
    scores = reciprocal_rank_fusion({"lexical": ["a", "b"]})
    assert list(scores) == ["a", "b"]
```

- [ ] **Step 2: Implement deterministic reciprocal rank fusion**

```python
def reciprocal_rank_fusion(
    rankings: dict[str, list[str]],
    *,
    k: int = 60,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for channel in sorted(rankings):
        for rank, item_id in enumerate(rankings[channel], start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return dict(sorted(scores.items(), key=lambda item: (-item[1], item[0])))
```

- [ ] **Step 3: Expose ranked fact identity from lexical and RAG retrievers**

Store each retriever's normalized score and channel in `EvidenceFact.fields`:

```python
fields["retrieval_channel"] = "lexical"  # or "dense"
fields["retrieval_rank"] = str(rank)
```

Do not reinterpret vector distance as confidence; normalize it only for ranking and preserve the raw distance in metadata.

- [ ] **Step 4: Fuse before final packet truncation**

In `evidence_service.py`, group facts by requirement, build channel rankings, apply RRF, and only then apply per-role/source budgets. KG identity and authoritative spatial facts must not be dropped solely because a text channel ranks higher.

- [ ] **Step 5: Verify degraded operation**

```powershell
cd backend
pytest -q -o addopts='' tests/core/test_evidence_rank_fusion.py tests/core/test_unified_rag_adapter.py tests/core/test_multisource_semantic_evidence.py
```

Expected: PASS with RAG disabled and with mocked dense results.

- [ ] **Step 6: Commit rank fusion**

```powershell
git add backend/app/evidence/retrieval/rank_fusion.py backend/app/evidence/retrieval/evidence_service.py backend/app/evidence/retrieval/retrievers/local_text_retriever.py backend/app/evidence/retrieval/retrievers/rag_retriever.py backend/tests/core/test_evidence_rank_fusion.py
git commit -m "feat: fuse lexical and optional dense evidence rankings"
```

### Task 6: Add retrieval evaluation fixtures and acceptance gates

**Files:**
- Create: `backend/tests/fixtures/evidence_benchmark/requirements.json`
- Create: `backend/tests/fixtures/evidence_benchmark/expected_evidence.json`
- Create: `backend/scripts/evaluate_evidence_retrieval.py`
- Create: `backend/tests/characterization/test_evidence_benchmark.py`
- Modify: `docs/design/04_EVALUATION_AND_ACCEPTANCE.md`
- Modify: `docs/design/05_MIGRATION.md`

**Interfaces:**
- Consumes: benchmark queries, requirement IDs, acceptable fact/source/feature references.
- Produces: JSON metrics for claim recall, source-family coverage, locator accuracy, and spatial candidate recall.

- [ ] **Step 1: Add a minimum benchmark corpus**

Create at least 20 cases covering:

```text
exact place identity
alias and suffix normalization
ambiguous place
facility BSM
road identity
village scope versus exact boundary
hazard proximity
policy text
missing source
contradictory sources
embedding unavailable
external search denied
```

Each expected row must list `requirement_id`, acceptable `fact_ids` or `source_families`, and acceptable `feature_bsms` when spatial.

- [ ] **Step 2: Write the evaluator**

The script must emit:

```json
{
  "case_count": 20,
  "claim_recall_at_k": 0.0,
  "source_family_coverage": 0.0,
  "locator_accuracy": 0.0,
  "spatial_candidate_recall": 0.0,
  "embedding_degraded_case_pass_rate": 0.0
}
```

Values are calculated from actual results; the zeros above define keys, not expected scores.

- [ ] **Step 3: Add characterization assertions**

Set initial gates to:

```python
assert metrics["claim_recall_at_k"] >= 0.85
assert metrics["source_family_coverage"] >= 0.90
assert metrics["locator_accuracy"] >= 0.95
assert metrics["spatial_candidate_recall"] >= 0.90
assert metrics["embedding_degraded_case_pass_rate"] == 1.0
```

Raise thresholds only with benchmark evidence and an ADR.

- [ ] **Step 4: Run the evidence benchmark and focused regression suite**

```powershell
cd backend
pytest -q -o addopts='' tests/characterization/test_evidence_benchmark.py tests/core/test_evidence_gap_controller.py tests/core/test_evidence_rank_fusion.py tests/core/test_evidence_graph_join.py
```

Expected: PASS.

- [ ] **Step 5: Update migration evidence and commit**

Record the exact benchmark command and measured metrics in `docs/design/05_MIGRATION.md`; do not copy individual case results into design documents.

```powershell
git add backend/tests/fixtures/evidence_benchmark backend/scripts/evaluate_evidence_retrieval.py backend/tests/characterization/test_evidence_benchmark.py docs/design/04_EVALUATION_AND_ACCEPTANCE.md docs/design/05_MIGRATION.md
git commit -m "test: add decision-grade evidence retrieval benchmark"
```

### Task 7: Run the evidence convergence acceptance suite

**Files:**
- Verify: evidence contracts, retrieval controller, API, spatial evidence, and import boundaries.

**Interfaces:**
- Consumes: all prior evidence tasks.
- Produces: a reproducible acceptance record suitable for `docs/design/05_MIGRATION.md`.

- [ ] **Step 1: Run focused tests**

```powershell
cd backend
pytest -q -o addopts='' tests/contracts/test_evidence_requirement_contracts.py tests/core/test_evidence_import_boundaries.py tests/core/test_explore_query_plan_and_sufficiency.py tests/core/test_evidence_gap_controller.py tests/core/test_evidence_rank_fusion.py tests/core/test_evidence_query_api.py tests/core/test_unified_external_evidence_fallback.py tests/characterization/test_evidence_benchmark.py
```

Expected: PASS.

- [ ] **Step 2: Run the real spatial evidence acceptance separately**

```powershell
pytest -q -o addopts='' tests/acceptance/test_real_evidence_http.py tests/acceptance/test_real_spatial_stage_chain.py
```

Expected: PASS without importing `transformers` merely to retrieve a Bundle. If provider-dependent cases skip, record the exact skip reason and do not count them as passed.

- [ ] **Step 3: Check dependency and diff hygiene**

```powershell
cd ..
rg -n "infrastructure\.llm\.tools\.access\.shared" backend/app --glob '*.py'
git diff --check -- backend/app backend/tests docs/design/04_EVALUATION_AND_ACCEPTANCE.md docs/design/05_MIGRATION.md
```

Expected: only LLM access-tool modules may import or re-export `shared`; no whitespace errors.

- [ ] **Step 4: Commit final acceptance repairs if needed**

```powershell
git add backend/app backend/tests docs/design/04_EVALUATION_AND_ACCEPTANCE.md docs/design/05_MIGRATION.md
git commit -m "test: verify evidence retrieval convergence"
```
