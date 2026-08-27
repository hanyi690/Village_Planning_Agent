# Documentation Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the overlapping, date-coupled design corpus with one small canonical documentation set that separates target architecture, current implementation, migration, and verification evidence.

**Architecture:** Active documentation is reduced to six target-design documents and three current-implementation documents. Historical audits, ledgers, superseded module blueprints, and dated status pages move to a recoverable archive; active pages link to code, contracts, tests, and generated API schemas instead of copying them.

**Tech Stack:** Markdown, Mermaid, Python 3.12, pytest, ripgrep, Git.

## Global Constraints

- Preserve all user-authored content by moving superseded documents under `docs/_archive/design/2026-08-21-pre-v2/`; do not permanently delete it.
- Treat `backend/app/**`, `frontend/src/**`, Pydantic contracts, OpenAPI, and reproducible tests as implementation truth.
- Active design documents describe target behavior and invariants; active architecture documents describe only behavior that exists in the current worktree.
- Do not use a date in the filename of any active status or architecture document.
- Keep Markdown files LF-terminated and keep Mermaid node labels quoted when they contain punctuation.
- Do not edit generated API schemas by hand.
- Do not commit unrelated changes from the existing dirty worktree.

---

## Target File Structure

```text
docs/
├── README.md
├── design/
│   ├── README.md
│   ├── 00_SYSTEM_DESIGN.md
│   ├── 01_CONTRACTS_AND_INVARIANTS.md
│   ├── 02_EVIDENCE_AND_GROUNDING.md
│   ├── 03_PLANNING_EXECUTION.md
│   ├── 04_EVALUATION_AND_ACCEPTANCE.md
│   └── 05_MIGRATION.md
├── architecture/
│   ├── README.md
│   ├── CURRENT_RUNTIME.md
│   ├── API_AND_STATE.md
│   └── OPERATIONS.md
├── adr/
├── guides/
├── reference/
├── contracts/
└── _archive/design/2026-08-21-pre-v2/
```

### Task 1: Encode the active-document contract

**Files:**
- Create: `backend/tests/contracts/test_documentation_convergence.py`
- Test: `backend/tests/contracts/test_documentation_convergence.py`

**Interfaces:**
- Consumes: repository root discovered from `Path(__file__).parents[3]`.
- Produces: an executable allowlist for active design and architecture Markdown files.

- [ ] **Step 1: Write the failing documentation contract test**

```python
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"

ACTIVE_DESIGN = {
    "README.md",
    "00_SYSTEM_DESIGN.md",
    "01_CONTRACTS_AND_INVARIANTS.md",
    "02_EVIDENCE_AND_GROUNDING.md",
    "03_PLANNING_EXECUTION.md",
    "04_EVALUATION_AND_ACCEPTANCE.md",
    "05_MIGRATION.md",
}

ACTIVE_ARCHITECTURE = {
    "README.md",
    "CURRENT_RUNTIME.md",
    "API_AND_STATE.md",
    "OPERATIONS.md",
}


def test_active_document_sets_are_small_and_canonical() -> None:
    design = {path.name for path in (DOCS / "design").glob("*.md")}
    architecture = {path.name for path in (DOCS / "architecture").glob("*.md")}
    assert design == ACTIVE_DESIGN
    assert architecture == ACTIVE_ARCHITECTURE


def test_active_docs_do_not_link_to_retired_status_ledgers() -> None:
    retired = re.compile(
        r"10_IMPLEMENTATION_STATUS|27_IMPLEMENTATION_VS_DESIGN|"
        r"RELATION_AWARE_MODIFICATION_LEDGER|IMPLEMENTATION_GAP_AUDIT"
    )
    active = [DOCS / "README.md"]
    active += list((DOCS / "design").glob("*.md"))
    active += list((DOCS / "architecture").glob("*.md"))
    violations = [str(path.relative_to(ROOT)) for path in active if retired.search(path.read_text(encoding="utf-8"))]
    assert violations == []


def test_active_docs_declare_status_and_authority() -> None:
    active = list((DOCS / "design").glob("*.md")) + list((DOCS / "architecture").glob("*.md"))
    missing = []
    for path in active:
        text = path.read_text(encoding="utf-8")
        if "Status:" not in text or "Authority:" not in text:
            missing.append(str(path.relative_to(ROOT)))
    assert missing == []
```

- [ ] **Step 2: Run the test and verify that the existing document corpus fails the allowlist**

Run:

```powershell
cd backend
pytest -q -o addopts='' tests/contracts/test_documentation_convergence.py
```

Expected: FAIL because the existing `design/` and `architecture/` roots contain additional active Markdown files and do not consistently declare authority.

- [ ] **Step 3: Commit only the documentation contract test**

```powershell
git add backend/tests/contracts/test_documentation_convergence.py
git commit -m "test: define canonical documentation surface"
```

### Task 2: Rewrite the product and system design

**Files:**
- Replace: `docs/design/00_SYSTEM_DESIGN.md`
- Create: `docs/design/01_CONTRACTS_AND_INVARIANTS.md`
- Replace: `docs/design/README.md`

**Interfaces:**
- Consumes: the verified runtime chain in `backend/app/workflow/root_graph.py`, current contracts under `backend/app/contracts/`, and the evidence/planning findings recorded on 2026-08-21.
- Produces: the sole target architecture and the normative cross-stage invariants used by every later document.

- [ ] **Step 1: Rewrite `00_SYSTEM_DESIGN.md` around planning outcomes rather than existing modules**

The document must use this top-level structure exactly:

```markdown
# Village Planning Agent System Design

> Status: TARGET
> Authority: Normative target architecture; implementation claims belong in `../architecture/CURRENT_RUNTIME.md`.

## 1. Product outcome and non-goals
## 2. Bounded completeness
## 3. Three-plane architecture
## 4. End-to-end planning loop
## 5. Stage responsibilities
## 6. Human authority and fail-closed behavior
## 7. Completion definition
## 8. Explicitly retired designs
```

The three-plane section must define:

```text
Evidence plane: requirements, retrieval, provenance, contradiction, sufficiency
Decision plane: grounded candidates, hard/soft constraints, alternatives, optimization
Execution plane: approval, immutable scenario, materialization, validation, reconciliation
```

The completion definition must distinguish these states:

```text
evidence_sufficient
candidate_complete
scenario_feasible
scenario_optimal_or_bounded
execution_complete
validation_passed
delivery_complete
```

- [ ] **Step 2: Create `01_CONTRACTS_AND_INVARIANTS.md`**

Define the following normative contracts and ownership rules without duplicating Pydantic field lists:

```text
PlanningProblemSpec
EvidenceRequirement
EvidenceClaim
EvidenceCoverage
SpatialQuery
GroundedPlanningProblem
ConstraintSpec
ScenarioSet
PlanningScenario
ExecutionPlan
ValidationCertificate
DeliveryManifest
```

For each contract, record:

```text
owner
producer
consumer
stable identity
snapshot/version fields
failure state
forbidden behavior
```

Include these invariants verbatim:

```text
INV-01 No planning claim becomes complete without supporting evidence identifiers.
INV-02 No spatial target becomes executable without an authoritative or explicitly degraded geometry reference.
INV-03 GROUND recalls and binds candidates; it never selects the final scenario.
INV-04 SELECT/solver never creates coordinates or silently changes source membership.
INV-05 EXECUTE consumes an approved immutable scenario and never re-selects a location.
INV-06 VALIDATE measures the materialized result independently from generation.
INV-07 Open-world retrieval reports scope and unresolved gaps; it never claims absolute completeness.
INV-08 Embedding failure degrades dense recall only and never disables structured, lexical, graph, or spatial retrieval.
INV-09 A complete scenario has zero unresolved hard constraints.
INV-10 Delivery is complete only when the same run-root and snapshot lineage reaches map layers, reports, and exports.
```

- [ ] **Step 3: Replace `docs/design/README.md` with the canonical navigation page**

The page must contain only:

- the distinction between TARGET and CURRENT;
- links to the six design files;
- links to `../architecture/README.md`, ADRs, references, and archive;
- a rule that new module blueprints require an ADR or a change to an existing canonical document.

- [ ] **Step 4: Run a content check**

Run:

```powershell
rg -n "Evidence plane|Decision plane|Execution plane|INV-10|bounded completeness" docs/design/00_SYSTEM_DESIGN.md docs/design/01_CONTRACTS_AND_INVARIANTS.md
```

Expected: every required term is present once in its authoritative document.

- [ ] **Step 5: Commit the normative design documents**

```powershell
git add docs/design/00_SYSTEM_DESIGN.md docs/design/01_CONTRACTS_AND_INVARIANTS.md docs/design/README.md
git commit -m "docs: replace overlapping blueprints with canonical system design"
```

### Task 3: Write evidence, planning, and evaluation specifications

**Files:**
- Create: `docs/design/02_EVIDENCE_AND_GROUNDING.md`
- Create: `docs/design/03_PLANNING_EXECUTION.md`
- Create: `docs/design/04_EVALUATION_AND_ACCEPTANCE.md`

**Interfaces:**
- Consumes: invariants from `01_CONTRACTS_AND_INVARIANTS.md`.
- Produces: implementation-independent behavior for the evidence controller, spatial grounding, multi-scenario solver, execution, and acceptance gates.

- [ ] **Step 1: Write `02_EVIDENCE_AND_GROUNDING.md`**

Use these sections:

```markdown
## 1. Evidence requirements, not raw queries
## 2. Source families and authority
## 3. Query decomposition and routing
## 4. Hybrid retrieval and embedding degradation
## 5. Claim-evidence graph and contradiction handling
## 6. Structured sufficiency and gap loop
## 7. Natural-language spatial query AST
## 8. Feature identity, geometry, CRS, scale, and uncertainty
## 9. External evidence policy
## 10. Output contract and stop conditions
```

The retrieval loop must be specified as:

```text
compile requirements
→ retrieve per requirement/source family
→ fuse and rerank
→ bind claims and spatial identities
→ judge supported/contradicted/ambiguous/unavailable
→ generate only missing subqueries
→ stop at sufficient, source-exhausted, human-required, or budget-exhausted
```

- [ ] **Step 2: Write `03_PLANNING_EXECUTION.md`**

Use these sections:

```markdown
## 1. From evidence to formal planning problem
## 2. Candidate generation and ownership
## 3. Hard constraints, soft preferences, and objectives
## 4. ScenarioSet and Pareto alternatives
## 5. Solver and external critics
## 6. Approval and immutable execution input
## 7. Atomic materialization
## 8. Independent validation and repair routing
## 9. Delivery and replay
## 10. Forbidden shortcuts
```

Explicitly state that a single weighted winner is not a sufficient planning product and that an infeasible result is a valid outcome when it carries a constraint-conflict explanation.

- [ ] **Step 3: Write `04_EVALUATION_AND_ACCEPTANCE.md`**

Define four benchmark layers:

```text
retrieval benchmark
spatial grounding benchmark
planning/solver benchmark
execution/replay benchmark
```

Define at least these metrics:

```text
claim_recall_at_k
context_precision
source_family_coverage
locator_accuracy
entity_top_k_recall
exact_vs_inferred_geometry_error
hard_constraint_violation_count
feasible_scenario_recall
optimality_gap_or_bound_status
selected_to_materialized_coverage
lineage_completeness
replay_fingerprint_stability
```

Define `complete` acceptance as zero unresolved hard constraints, 100% selected-to-materialized coverage, 100% required lineage, and a validation certificate tied to the same snapshot digests.

- [ ] **Step 4: Verify that responsibilities do not overlap**

Run:

```powershell
rg -n "final location|重新选址|re-select|coordinates|坐标" docs/design/02_EVIDENCE_AND_GROUNDING.md docs/design/03_PLANNING_EXECUTION.md
```

Expected: evidence/GROUND explicitly forbids final selection and EXECUTE explicitly forbids re-selection.

- [ ] **Step 5: Commit the subsystem specifications**

```powershell
git add docs/design/02_EVIDENCE_AND_GROUNDING.md docs/design/03_PLANNING_EXECUTION.md docs/design/04_EVALUATION_AND_ACCEPTANCE.md
git commit -m "docs: specify evidence planning and acceptance contracts"
```

### Task 4: Replace dated status ledgers with one migration document and one current-runtime map

**Files:**
- Create: `docs/design/05_MIGRATION.md`
- Create: `docs/architecture/CURRENT_RUNTIME.md`
- Create: `docs/architecture/API_AND_STATE.md`
- Create: `docs/architecture/OPERATIONS.md`
- Replace: `docs/architecture/README.md`

**Interfaces:**
- Consumes: current code paths and test evidence.
- Produces: one current implementation map and one ordered target-to-current migration backlog.

- [ ] **Step 1: Write `05_MIGRATION.md` as a capability migration table**

Use one row per capability with these columns:

```text
Capability | Current evidence | Target contract | Gap | Retirement action | Acceptance command | Status
```

Include rows for:

```text
bundle-access dependency inversion
structured evidence requirements
iterative gap closure
hybrid retrieval
spatial query AST/PostGIS
single authoritative scenario solver
multi-scenario ScenarioSet
immutable execution input
atomic materialization
validation certificate
retrieval/spatial/planning benchmarks
```

Use statuses only from `CURRENT`, `PARTIAL`, `GAP`, `RETIRE`, and `BLOCKED`.

- [ ] **Step 2: Write `CURRENT_RUNTIME.md` from code entry points**

Document:

```text
FastAPI startup
session/runtime service
four workflow segments
L1/L2/L3 artifacts
TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
horizontal evidence calls
artifact store and snapshot lineage
current known partial boundaries
```

Every CURRENT statement must name a code path or a reproducible test.

- [ ] **Step 3: Consolidate API/state and operations documentation**

`API_AND_STATE.md` owns HTTP, SSE envelope/internal event vocabulary, `WorkflowState`, artifact refs, resume, and delivery projection. `OPERATIONS.md` owns local startup, configuration categories, RAG/embedding health, tests, and degraded operation. Neither page may copy endpoint schemas from `docs/contracts/openapi-v1.json`.

- [ ] **Step 4: Replace `docs/architecture/README.md`**

Link only to `CURRENT_RUNTIME.md`, `API_AND_STATE.md`, `OPERATIONS.md`, generated contracts, code-level READMEs, and target design.

- [ ] **Step 5: Commit current implementation and migration documents**

```powershell
git add docs/design/05_MIGRATION.md docs/architecture/README.md docs/architecture/CURRENT_RUNTIME.md docs/architecture/API_AND_STATE.md docs/architecture/OPERATIONS.md
git commit -m "docs: consolidate runtime status and migration evidence"
```

### Task 5: Archive superseded active documents and repair links

**Files:**
- Move: superseded `docs/design/*.md`, `docs/design/modules/**`, and old `docs/architecture/*.md`
- Modify: `docs/README.md`
- Modify: `README.md`
- Modify: `backend/tests/fixtures/mvp_village/README.md`
- Modify: active code-level README files only when they link to retired documents

**Interfaces:**
- Consumes: canonical documents created in Tasks 2–4.
- Produces: a small active documentation surface with recoverable historical content.

- [ ] **Step 1: Verify the exact archive source and destination paths**

Run:

```powershell
$root = (Resolve-Path '.').Path
$destination = Join-Path $root 'docs\_archive\design\2026-08-21-pre-v2'
$sources = @(
  'docs\design\10_IMPLEMENTATION_STATUS_CURRENT_20260818.md',
  'docs\design\27_IMPLEMENTATION_VS_DESIGN.md',
  'docs\design\RELATION_AWARE_MODIFICATION_LEDGER.md',
  'docs\design\modules',
  'docs\architecture\agent-graph.md',
  'docs\architecture\backend-api.md',
  'docs\architecture\backend-state-contract.md',
  'docs\architecture\deployment.md',
  'docs\architecture\rag-system.md',
  'docs\architecture\structure.md'
)
$sources | ForEach-Object {
  $resolved = Resolve-Path -LiteralPath $_
  if (-not $resolved.Path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Archive source escapes workspace: $resolved"
  }
  $resolved.Path
}
$destination
```

Expected: every source resolves inside the workspace and the destination is exactly under `docs/_archive/design/2026-08-21-pre-v2`.

- [ ] **Step 2: Move the verified superseded documents into the archive**

Run with PowerShell `Move-Item -LiteralPath` for each verified source. Preserve the `modules/` subtree under the archive and do not move `00_SYSTEM_DESIGN.md`, the newly created canonical design files, ADRs, references, contracts, guides, or domain source documents.

- [ ] **Step 3: Rewrite root navigation links**

`docs/README.md` and the repository `README.md` must link to:

```text
docs/design/00_SYSTEM_DESIGN.md
docs/design/05_MIGRATION.md
docs/architecture/CURRENT_RUNTIME.md
docs/contracts/openapi-v1.json
docs/reference/terminology.md
```

Replace any active link to a dated status page, gap audit, or modification ledger with the corresponding canonical document.

- [ ] **Step 4: Check all remaining references to retired active paths**

Run:

```powershell
rg -n --glob '*.md' --glob '!docs/_archive/**' --glob '!docs/superpowers/**' "10_IMPLEMENTATION_STATUS|27_IMPLEMENTATION_VS_DESIGN|RELATION_AWARE_MODIFICATION_LEDGER|modules/spatial-execution|modules/explore"
```

Expected: no matches.

- [ ] **Step 5: Commit the archive move and link repair**

```powershell
git add docs README.md backend/tests/fixtures/mvp_village/README.md
git commit -m "docs: archive superseded design and status ledgers"
```

### Task 6: Validate the converged documentation surface

**Files:**
- Test: `backend/tests/contracts/test_documentation_convergence.py`
- Verify: all active Markdown files

**Interfaces:**
- Consumes: the completed documentation structure.
- Produces: evidence that the active corpus is small, internally linked, and consistent with the code boundary.

- [ ] **Step 1: Run the documentation contract tests**

```powershell
cd backend
pytest -q -o addopts='' tests/contracts/test_documentation_convergence.py
```

Expected: PASS.

- [ ] **Step 2: Scan active documentation for retired code paths**

```powershell
cd ..
rg -n --glob '*.md' --glob '!docs/_archive/**' --glob '!docs/superpowers/**' "app/agent|app/modules|app/services|spatial_ops|schema/contracts"
```

Expected: no CURRENT description points to retired paths; a migration statement may mention them only in `05_MIGRATION.md` and must label them `RETIRE`.

- [ ] **Step 3: Validate Markdown links with a local script**

Run:

```powershell
python -c "from pathlib import Path; import re; root=Path('docs'); bad=[]; [bad.append((str(p),t)) for p in root.rglob('*.md') if '_archive' not in p.parts and 'superpowers' not in p.parts for t in re.findall(r'\[[^]]+\]\(([^)#]+)',p.read_text(encoding='utf-8')) if not re.match(r'^[a-z]+://',t) and not (p.parent/t).resolve().exists()]; print(bad); raise SystemExit(bool(bad))"
```

Expected: `[]` and exit code 0.

- [ ] **Step 4: Run diff hygiene**

```powershell
git diff --check -- docs README.md backend/tests/contracts/test_documentation_convergence.py backend/tests/fixtures/mvp_village/README.md
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit final documentation verification repairs if needed**

```powershell
git add docs README.md backend/tests/contracts/test_documentation_convergence.py backend/tests/fixtures/mvp_village/README.md
git commit -m "test: verify canonical documentation architecture"
```
