# OpenCode Go Stable Structured Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenCode Go use the configured `deepseek-v4-flash` model and make critical structured LLM results reliable through typed validation, bounded retries, timeouts, and provider-aware configuration.

**Architecture:** Keep ordinary chat and tool-calling flows on LangChain. Add one asynchronous application-level structured-output runner backed by Instructor and Pydantic. Route core domain contracts through that runner, while retaining best-effort text fallbacks only in non-critical extraction paths.

**Tech Stack:** Python, FastAPI, LangGraph, Pydantic, Instructor, LangChain OpenAI-compatible Chat Completions, pytest.

## Global Constraints

- Never print or commit API keys, raw authorization headers, or full provider responses.
- Use the OpenCode Go Chat Completions endpoint with the raw model id `deepseek-v4-flash`.
- Keep validation retries bounded and separate from transport/business retries.
- Preserve existing tool-calling behavior for agent actions.
- Use minimal file edits and run syntax, diff, and targeted tests before any live smoke request.

---

## 1. Normalize OpenCode Go configuration

- [ ] Update application defaults and environment examples to `deepseek-v4-flash`.
- [ ] Activate the already-configured local OpenCode Go provider without changing the key value.
- [ ] Pass the same provider settings through Docker Compose.
- [ ] Update provider tests to assert the correct model and endpoint.

## 2. Build the typed structured-output runner

- [ ] Refactor the Instructor client cache to be provider/base-url aware.
- [ ] Add provider-aware model resolution for OpenCode Go, MiniMax, and existing defaults.
- [ ] Add an async runner that executes Instructor in a worker thread, applies Pydantic validation, bounded reasks, and an optional timeout.
- [ ] Ensure errors remain typed and do not log sensitive payloads.

## 3. Migrate critical structured contracts

- [ ] Migrate assessment L1 output and planning L3 claims.
- [ ] Migrate program classification and semantic repair outputs.
- [ ] Migrate the structured spatial extraction/grounding/mapping paths.
- [ ] Leave agent tool binding and non-critical textual fallback paths intact where they are part of resilience behavior.

## 4. Add regression coverage

- [ ] Add unit tests for runner arguments, provider-aware Instructor configuration, retry bounds, and timeout behavior.
- [ ] Keep provider tests network-free and update them for `deepseek-v4-flash`.
- [ ] Run targeted tests plus source compilation without generating bytecode artifacts.

## 5. Verify real provider behavior

- [ ] Confirm the local environment has an OpenCode Go key without printing it.
- [ ] Run one minimal structured-output smoke request against `deepseek-v4-flash` if credentials and network access are available.
- [ ] Report exact changed files, verification results, and any provider limitation separately from code failures.

## 6. Grounding long-tail hardening (2026-08-17)

- [x] Give one grounding execution an independent best-effort budget:
  `GROUND_MAX_LLM_CALLS=8`, `GROUND_LLM_CALL_TIMEOUT_S=30`, and
  `GROUND_LLM_MAX_CONCURRENT=4`.
- [x] Count semaphore queue wait inside the per-call timeout; use the same
  bounded policy in async grounding and the synchronous compatibility resolver.
- [x] Run independent location candidate decisions concurrently and batch the
  orientation/route rebind pass instead of awaiting it in the serial commit
  loop.
- [x] When the grounding budget is exhausted, keep the existing deterministic
  bundle/KG best-effort path for villages, roads, and water; do not invent
  geometry.  Facility mentions without authoritative candidates remain
  unresolved.
- [x] Protect shared call reservations with a lock and add regression tests for
  concurrency limits, budget exhaustion, and synchronous queue timeout.

The provider-facing L1/L2/L3 dimensions retain their separate provider and
graph concurrency budgets.  Grounding's four-way cap is intentionally an
independent, smaller best-effort pool: it prevents optional location
disambiguation from consuming the main planning concurrency or extending the
run through a serial tail.

## 7. Real-run evidence (2026-08-17)

The one controlled OpenCode Go run used the real `mvp_village` GIS bundle
(660 land-use parcels, 131 roads, and the uploaded protection/hazard layers).
The main provider semaphore was observed at 12.  Eleven of twelve L1
dimensions completed and were persisted; `villager_wishes` alone reached the
configured 600-second provider request boundary and failed once with
`Request timed out`.  The checkpoint retained the completed dimensions and
entered the explicit HUMAN/diagnostic path; it did not re-call the eleven
successful dimensions, and the run did not reach GROUND.

This separates two issues that must not be conflated:

1. Grounding's previous serial per-location tail is fixed and covered by
   local/fixture tests.
2. The remaining real-run blocker is a single slow L1 provider request.  A
   later change should give L1 a stage-specific output/request budget or an
   explicit one-dimension resume policy; it must not be addressed by blindly
   rerunning the whole layer.

The older real artifact used for offline replay is `PlanningProgram` schema
2.0, while the current authoritative contract is schema 4.0.  No runtime
 migration implementation exists despite ADR-005 describing one, so that
historical artifact is correctly rejected at the contract boundary rather
than being coerced into the current spatial chain.

## 8. L1 long-tail boundary (2026-08-17)

- [x] Give L1 dimensions their own request/output budget:
  `L1_LLM_TIMEOUT_S=480` and `L1_MAX_TOKENS=12288`.  The cap was raised from
  8K after the v33 real run showed that the dual report/observation contract
  could be incomplete at 8K; it remains below the global/L3 16K ceiling and
  cannot auto-expand.
- [x] Give L1 its own eight-way provider gate
  (`L1_LLM_MAX_CONCURRENT=8`) while leaving the default/L2/L3 budget at the
  configured twelve-way profile.
- [x] Permit one request-level retry only for transient 429/5xx responses
  (`L1_TRANSIENT_RETRIES=1`, two-second backoff).  Timeouts, malformed
  structured output, and business validation failures do not receive this
  retry; they remain exact-dimension checkpoint failures.
- [x] Keep the provider transport and L3 budgets unchanged
  (`LLM_PROVIDER_REQUEST_TIMEOUT=600`, `LLM_STREAM_TIMEOUT=900`, and
  `MAX_TOKENS=16384` in the OpenCode Go profile).
- [x] Convert an L1 timeout into one merge-safe provider failure for the exact
  dimension.  The existing checkpoint/resume path can then retry only that
  dimension after an explicit operator decision; it never replays the eleven
  dimensions that already persisted successfully.

The 480-second value is intentionally above the observed successful L1
maximum (~198 seconds) with a safety margin, while remaining below the
provider's 600-second transport timeout.  It is not a context-window setting:
it bounds one L1 request, including provider semaphore queue wait and bounded
Instructor validation reasks.  Grounding remains separately bounded at eight
calls, 30 seconds per call, and four concurrent calls, followed by the
existing deterministic best-effort resolver.

The v32 real run showed why this separation is needed: twelve simultaneous
large L1 prompts produced real 500/503 responses and several requests close to
the 480-second wall.  The recovery change is scoped backpressure plus a single
transient-status retry, not a blind increase in workflow retries.

The v34 real run added a separate L3 finding: all eleven L3 claim requests
timed out at the provider's 600-second transport boundary when the L3 local
slot budget was 12.  The OpenCode Go profile therefore uses
`L3_LLM_MAX_CONCURRENT=8` for large claim-generation requests, while keeping
the task fan-out and L3 900-second workflow budget intact.  This is measured
stage-specific backpressure, not a global concurrency reduction.

## 9. Provider quota is a terminal diagnostic, not a retryable outage (2026-08-17)

- [x] Recognize OpenCode Go weekly-limit/insufficient-balance responses before
  generic 429 retry handling.
- [x] Stop L3 semantic repair immediately on `GoUsageLimitError`; preserve one
  `llm_provider_quota_exhausted` issue with the original diagnostic and make no
  further provider calls for that repair.
- [x] Mark the same condition on an L3 dimension as
  `llm_provider_quota_exhausted` without opening the session circuit and without
  adding the dimension to provider-resume.
- [x] Add network-free regression coverage for both the structured runner and
  semantic repair call counts.

The v34 artifact confirms this was a real provider boundary, not a Pydantic or
grounding defect: L1 completed 12/12, grounding completed with bounded
best-effort fallbacks, L2 completed 4/4, and L3 produced a partial typed
`PlanningProgram`; the subsequent semantic repair received the provider's
weekly-limit 429.  The persisted checkpoint is resumable from L3, but the
provider quota had not reset at the time of this audit, so launching another
live run before reset would only reproduce the same external failure.

The persistent acceptance runner now distinguishes two resume cases: pending
LangGraph tasks use the official deepest-subgraph checkpoint recovery; a
terminalized quota diagnostic with `next_stage=L3` creates one descendant at
the authorized `provider_resume_dispatch` entry and supplies only the missing
L3 dimensions.  It does not reset the session to L1 or replay completed
dimensions.

## 10. Live resume boundary findings (2026-08-17)

- [x] Keep the OpenCode Go transport proxy-aware: plain `httpx` clients with
  `trust_env=True` and `http_socket_options=()` are used so the deployment's
  `HTTP(S)_PROXY` is not disabled by LangChain's socket-options transport.
- [x] Make provider-resume dispatch dependency-aware.  A restore request with
  nine missing L3 dimensions now emits only the ready wave and retains
  dependants in `provider_resume_dimensions` for the next wave.
- [x] Route the retained provider-resume list back through the same cognitive
  dispatch node after each completed wave, while preserving fatal/provider
  failures as HUMAN/diagnostic boundaries.

Live evidence after the quota window: the first preflight succeeded once after
the proxy fix and the resume checkpoint was reopened without creating a new
session.  The first attempted state-entry exposed a real scheduler defect —
`project_bank` was sent before its same-layer `industry` report and the
dependency guard stopped the run.  That was fixed and covered by the core
suite (`485 passed`); a later preflight again hit the provider's 30-second
network response boundary before any new L3 wave.  The remaining live blocker
is therefore provider response stability, not grounding serialization,
concurrency, checkpoint reuse, or dependency ordering.
