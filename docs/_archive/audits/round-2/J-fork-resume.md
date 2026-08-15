# Round-2 Audit: J — Split fork-vs-resume in the resume path

Date: 2026-08-12
Scope: `backend/app/application/commands/resume_checkpoint.py`,
`backend/app/application/commands/submit_human_decision.py`,
`backend/app/services/resume_service.py`. No edits outside scope; no server / LLM.

## Files changed

- `resume_service.py` — additive pure helpers: `mark_plan_fork` (annotates a
  plan with a fresh `fork branch=<id>` marker), `fork_branch_from_plan`,
  `plan_blocked`, `FORK_BRANCH_MARKER`, `ResumeService.fork_required`.
- `resume_checkpoint.py` — new pure snapshot classifier `build_resume_plan`
  (dict- or object-shaped snapshot); `_PlanBuilderDefault` routes the checkpoint
  command through it with `requested_mode=CHECKPOINT`.
- `submit_human_decision.py` — explicit typed CAS guard `assert_event_id_matches`
  + `HumanEventIdMismatchError`, enforced before forwarding.

## Mode classification (`build_resume_plan`, priority order)

1. Pending interrupt (`tasks[].interrupts.value`) -> `resume_interrupt`.
   - Plain checkpoint requested -> `blocked` (interrupt channel required).
   - Interrupt requested without `expected_event_id` -> `blocked`.
   - `expected_event_id != pending event_id` -> `blocked` (typed event_id CAS).
2. No interrupt but interrupt requested -> `blocked` ("no pending HUMAN interrupt").
3. Context/checksum/parent mismatch -> `rerun_from_stage` at earliest affected
   stage (delegated to `resume_contracts.build_resume_plan`).
4. Terminal (`diagnostic_terminal` -> `blocked`; `phase == completed` -> `completed`).
5. Otherwise -> `resume_checkpoint`.

## Fork-vs-resume handling

- `resume_checkpoint`/`rerun_from_stage` plans are annotated with a new branch_id
  via `mark_plan_fork`; the caller reads it back with `fork_branch_from_plan` and
  passes it to the runtime fork path (which runs `fork_artifact_refs` +
  `Command(update=...)`, never `Command(resume=...)`).
- `resume_interrupt` plans carry `interrupt_id` (the pending event_id); this is
  the only path allowed to `Command(resume=...)`.

## event_id CAS

`submit_human_decision` fetches current values and calls `assert_event_id_matches`
(mismatch -> `HumanEventIdMismatchError`, consumed -> `HumanDecisionConflictError`)
before forwarding; the runtime lock re-validates the token.

## Verification

Import: `OK`
Smoke (fake snapshot, no interrupts, consistent checksums):
```
CHECKPOINT ok, fork= fork-4e43d2cca4b94676 reuse= ['l1_snapshot', 'l2_strategy']
INTERRUPT ok / MISMATCH blocked / PLAIN-on-HUMAN blocked
```
Service + CAS: `service ok, mode= resume_checkpoint`; human cursor blocked via
checkpoint path; `CAS forward ok / mismatch raised / consumed raised`.
Files verified LF (CRLF=0). Constraints: LF, 4-space indent, double quotes, no tests.
