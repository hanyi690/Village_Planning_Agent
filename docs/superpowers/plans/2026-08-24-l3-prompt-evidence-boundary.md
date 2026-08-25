# L3 Prompt Evidence Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the L3 claims pass receive the correct typed upstream evidence and an unambiguous claims-only contract, then verify with a fresh real provider run whether the complete planning-layer path can proceed.

**Architecture:** Keep L1 facts, KG retrieval, grounding, selection, and delivery semantics unchanged until the prompt evidence is proven to be the limiting boundary. The production L3 worker will derive allowed source dimensions from the configured `layer_depends_on` contract, render compact typed facts without losing exact IDs, and use one claims-only prompt contract; the old report/table prompt path is removed from the production call chain rather than kept as a compatibility fallback. Spatial anchors remain optional for non-spatial claims; spatial claims may be executable only when their typed locator/evidence requirements are present. A fresh provider run is the acceptance check, and its prompt/raw-claim/artifact evidence is recorded independently of prior runs.

**Tech Stack:** Python 3, Pydantic/domain contracts, pytest, existing Minimax provider, CAS run artifacts, PowerShell test commands.

## Global Constraints

- Do not restore or add `CurrentAsset`, `DemandRegisterRow`, `CoverageDecision`, or other removed compatibility records.
- Do not convert every L3 prose target into a spatial target; only claims whose semantics require a location use the structured spatial path.
- Do not use keyword/regular-expression parsing to decide planning meaning; use configured typed contracts and the model's claims output.
- Do not make a failed dense retrieval or an unavailable optional LLM parser block typed spatial analysis.
- Do not accept model-emitted identifiers unless they match the hydrated L1/KG evidence identity space; semantic location hints remain retrieval hints, not fact IDs.
- Every real-provider acceptance run must use a new run root and report its actual reached stages; old run records cannot be used as proof.

---

### Task 1: Capture the prompt failure as deterministic regression tests

**Files:**
- Create: `backend/tests/core/test_l3_claim_prompt_boundary.py`
- Inspect: `backend/app/domain/program/worker.py`
- Inspect: `backend/app/infrastructure/llm/prompts/detailed.py`

**Interfaces:**
- Consumes: `ProgramWorker._build_prompt`, `get_dimension_prompt`, a minimal hydrated L1 context, and the existing phase configuration.
- Produces: failing tests that identify prompt assembly defects without asserting a particular provider response.

- [ ] **Step 1: Write the failing tests**

```python
def test_claims_prompt_uses_configured_source_dimensions_and_exact_ids():
    prompt = build_prompt_for_dimension("heritage", source_dimension="historical_culture")
    assert '"dimension": "historical_culture"' in prompt
    assert "l1:fact:historical-culture-001" in prompt
    assert "source_report_ref:foreign-id" not in prompt


def test_claims_prompt_has_no_unbound_metric_placeholders_or_legacy_output_order():
    prompt = build_claims_only_prompt("heritage")
    assert "{landuse_metrics_farmland}" not in prompt
    assert "claims-only" in prompt
    assert "旧报告模板中的表格和‘至少列出’不是本轮输出指令" in prompt


def test_non_spatial_claims_are_not_required_to_have_spatial_anchors():
    prompt = build_claims_only_prompt("socio_economic")
    assert "非空间指标可以没有 locator" in prompt
    assert "空间干预 claim 才需要" in prompt
```

The test helper must construct the same `SimpleNamespace`-style context shape used by the worker, with one exact `spatial_observation` fact in `historical_culture`, one unrelated fact, and one location hint whose `source_report_ref` is deliberately not a fact ID. It must call the production prompt builder rather than duplicating prompt text.

- [ ] **Step 2: Run the focused tests and record the expected failures**

Run from `F:\project\Village_Planning_Agent\backend`:

```powershell
pytest tests/core/test_l3_claim_prompt_boundary.py -q -o addopts=''
```

Expected before implementation: the heritage prompt does not expose the configured `historical_culture` fact in the compact typed section, the nested GIS placeholders remain literal, and the old professional output instructions precede the claims-only contract.

- [ ] **Step 3: Keep the tests provider-independent**

Assert only prompt text and evidence identity placement. Do not assert a fixed number of claims, a specific model sentence, or a fixed spatial anchor count; provider randomness is intentionally outside this unit test.

---

### Task 2: Align typed evidence with the L3 dependency contract

**Files:**
- Modify: `backend/app/domain/program/worker.py` (`_typed_l1_fact_evidence`, location evidence construction, `_build_prompt`, semantic-repair prompt construction)
- Modify: `backend/app/domain/assessment/dimension_contracts.py` (render the configured upstream source dimensions in the semantic contract if the existing contract object does not already expose them)
- Test: `backend/tests/core/test_l3_claim_prompt_boundary.py`

**Interfaces:**
- Consumes: `PhaseConfig.layer_depends_on`/dimension contract, hydrated `l1_fact_records`, and `location_facts`.
- Produces: `_typed_l1_fact_evidence(state, dim_key, source_dimensions=None) -> str` and prompt sections that preserve exact typed fact IDs for the configured upstream dimensions.

- [ ] **Step 1: Define the source-dimension set at the worker boundary**

Add one small helper next to the existing evidence helper:

```python
def _l3_source_dimensions(cfg: Any, dim_key: str) -> set[str]:
    configured = getattr(cfg, "layer_depends_on", ()) or ()
    return {str(value) for value in configured if str(value).strip()} | {
        dim_key,
        "location",
        "spatial",
        "",
    }
```

Use the phase configuration as the authority; do not hand-maintain an alias table such as `heritage -> historical_culture`.

- [ ] **Step 2: Pass the source-dimension set into typed fact and location retrieval**

Change the helper signature to accept `source_dimensions: Iterable[str] | None = None`, use the supplied set when present, and keep the current `dim_key` fallback for callers outside the production path. Apply the same set to the location-fact block so historical-cultural place hints are available to heritage, traffic facts to traffic planning, and so on.

- [ ] **Step 3: Make compact evidence preserve identity-bearing rows**

Order rows by typed spatial identity first (`spatial_observation`, `gis_observation`, and KG canonical rows with a stable identity), then by configured source dimension, then by stable fact ID. Render bounded fields (`fact_id`, `statement`, `kind`, `dimension`, `semantic`, `scope`, `source_feature_ids`, `evidence_refs`, and a bounded snapshot) and omit oversized free-form attributes. Keep the exact fact ID in every emitted row. This is a context-budget change, not a semantic validator.

- [ ] **Step 4: Expose the source dimensions in the semantic contract**

When rendering the existing dimension semantic contract, include a short machine-readable line such as `upstream_source_dimensions: [historical_culture]`. The line is informational and must not turn every allowed fact into a required spatial anchor.

- [ ] **Step 5: Update all worker call sites**

In `_build_prompt` and the semantic-repair path, compute `_l3_source_dimensions(cfg, dim_key)` once and pass it to both typed fact and location evidence helpers. Preserve the existing RAG call and EvidenceGraph/KG injection; this change only removes the accidental exact-L3-key filter.

- [ ] **Step 6: Run the focused tests**

```powershell
pytest tests/core/test_l3_claim_prompt_boundary.py -q -o addopts=''
```

Expected: the identity and non-spatial-anchor tests pass once Task 3's claims-only prompt is active; no provider call is needed.

---

### Task 3: Give the provider a dedicated claims-only prompt boundary

**Files:**
- Modify: `backend/app/infrastructure/llm/prompts/detailed.py` (`get_dimension_prompt` and a claims-only prompt branch)
- Modify: `backend/app/domain/program/worker.py` (request the claims-only branch for production L3 claims generation)
- Test: `backend/tests/core/test_l3_claim_prompt_boundary.py`

**Interfaces:**
- Consumes: project/task context, L1/L2/RAG evidence sections, rendered semantic contract, and location hints.
- Produces: `get_dimension_prompt(..., claims_only=True) -> str`, whose authoritative output contract is the typed claims schema and whose old report templates are explicitly background only.

- [ ] **Step 1: Add an explicit claims-only prompt branch**

Make the production `get_dimension_prompt` path compose one compact claims-only prompt in this order; do not retain a `claims_only=False` compatibility switch:

1. role and dimension key;
2. high-priority claims-only instruction;
3. rendered semantic contract and configured upstream source dimensions;
4. typed L1/KG/RAG evidence sections;
5. location hints labelled retrieval-only;
6. the existing typed claims output guide and final JSON-only reminder.

Do not include the legacy `WRITING_RULES`, nested GIS metric template, or report/table output structure in the production prompt. Remove the old report/table branch from the active function instead of preserving a compatibility fallback.

- [ ] **Step 2: State the spatial boundary without forcing anchors**

The claims-only instruction must say, in Chinese, that non-spatial indicators and observations may omit a locator; only a claim that proposes or constrains a spatial intervention needs a typed spatial kind/parameters and an exact evidence lineage when one is available. A missing locator must remain a reviewable/deferred claim, not be fabricated.

- [ ] **Step 3: Eliminate nested placeholder leakage**

Ensure the claims-only branch never contains literal `{landuse_metrics_farmland}`, `{intent_targets_farmland}`, or other unbound format fields. If the legacy branch still formats `GIS_TOOL_GUIDE`, format it in its own call with explicit `N/A` values rather than relying on recursive `str.format` behavior.

- [ ] **Step 4: Make the worker use the branch**

Use the claims-only prompt from the active L3 claims-generation path and the semantic-repair path. Do not alter the report synthesis path; it already consumes claims and must not invent new claims or locations.

- [ ] **Step 5: Run prompt tests and the existing L3 contract tests**

```powershell
pytest tests/core/test_l3_claim_prompt_boundary.py tests/core/test_l3_claim_lineage_metrics.py tests/core/test_unified_rag_adapter.py -q -o addopts=''
```

Expected: all focused tests pass, and no test requires a deterministic provider wording.

---

### Task 4: Run a fresh real provider workflow and inspect the complete artifact chain

**Files:**
- Modify: none
- Read: `backend/tests/acceptance/test_real_graph_resume_delivery.py`, the newly generated run report, resume diagnostic, prompt traces, and CAS blobs

**Interfaces:**
- Consumes: the prompt/evidence changes from Tasks 2–3 and the real Minimax credential already configured for this workspace.
- Produces: a new run root, a report of reached stages, prompt hashes/sections, raw L3 claims, target projection, grounding, scenario/selection artifacts, and an explicit delivery status.

- [ ] **Step 1: Start a new real run with no persistent resume state**

From `backend`:

```powershell
$line = Get-Content ..\.env | Where-Object { $_ -match '^MINIMAX_API_KEY=' } | Select-Object -First 1
$env:MINIMAX_API_KEY = ($line -split '=',2)[1].Trim()
$env:LLM_PROVIDER = 'minimax'
$env:RUN_REAL_GRAPH_RESUME = '1'
$env:GROUND_LLM_ENABLED = 'false'
$env:REAL_RUN_PERSISTENT = ''
pytest tests/acceptance/test_real_graph_resume_delivery.py -q -o addopts='' -s
```

Record the printed run root and do not reuse the earlier `5c77a088-85ff-4b47-bff9-7cc33e0bcf78` directory.

- [ ] **Step 2: Verify each phase from artifacts, not only the pytest result**

Check the new report and CAS index for L1, L2, all configured L3 keys, `TARGET_PROJECTION`, `GROUND`, `SELECT`, `EXECUTE`, `VALIDATE`, `RECONCILE`, and `DELIVER`. Record `delivery_status`, claim/disposition counts, unresolved references, scenario feasibility, and whether a recommended scenario exists.

- [ ] **Step 3: Compare prompt and raw-claim evidence**

Confirm that the prompt contains the configured upstream source dimension and exact fact IDs, that raw claims use only exact hydrated IDs, and that non-spatial claims are not rejected merely for lacking a locator. Treat any remaining provider variation as evidence to analyze, not as a reason to add brittle regex or fixed-output normalization.

- [ ] **Step 4: Stop at the first honest boundary**

If SELECT remains infeasible, report the concrete certificate/constraint or missing evidence that prevents a complete planning layer. Do not mark the workflow complete by auto-approving a diagnostic-only result, and do not change solver semantics in this prompt-first pass.

---

### Task 5: Decide the next bounded change from the fresh run

**Files:**
- Create or modify: `docs/analysis/2026-08-24-l3-prompt-evidence-run.md`
- Modify: none unless the fresh run identifies a prompt-only defect with a failing test

**Interfaces:**
- Consumes: Task 4's new report, prompt traces, raw claims, and existing KG/grounding/selection artifacts.
- Produces: an evidence-backed decision: either the prompt boundary is sufficient for the next planning stage, or a separate plan is required for grounding/solver orchestration.

- [ ] **Step 1: Write the fresh-run findings**

Include the run ID, actual stage list, exact failure phase if any, L1/L2/L3 counts, target projection task counts, grounding candidate/unresolved counts, scenario feasibility, and delivery status. Link to the local report and artifact files.

- [ ] **Step 2: Classify remaining issues by layer**

Use these explicit categories: prompt assembly, provider schema adherence, typed evidence identity, target projection admission, grounding candidate resolution, solver feasibility/certificate, or delivery orchestration. A problem moves to a new implementation plan only when the fresh evidence places it outside prompt assembly.

- [ ] **Step 3: Run the repository checks affected by the prompt boundary**

```powershell
pytest tests/core/test_l3_claim_prompt_boundary.py tests/core/test_l3_claim_lineage_metrics.py tests/core/test_unified_rag_adapter.py -q -o addopts=''
```

Do not claim complete planning delivery unless the fresh run actually reaches `DELIVER` with a non-diagnostic delivery status and every required output family has an artifact.
