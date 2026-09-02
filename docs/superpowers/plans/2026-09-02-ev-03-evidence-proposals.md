# EV-03 Evidence Proposals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已完成 EV-02 的 `EvidencePacket + Coverage + Sufficiency` 编译为四类可重放、可审计、交给 Cognition 的 support proposal，并把 proposal 持久化在 Evidence retrieval artifact 中。

**Architecture:** `modules/evidence/proposals.py` 是纯确定性编译器，只消费冻结的 `ExplorationResult` 和明确的 round/WM parent 上下文，不导入 Cognition writer，也不执行任何 WM mutation。四类 Evidence proposal 使用一个不可变公共审计基类加上最小的类型专属字段；随后通过显式 adapter 转成现有 Cognition `AssertionProposal`，由 Cognition 自己完成 decision/commit。Evidence artifact 保存 proposal batch，CAS replay 同时校验它。

**Tech Stack:** Python 3、Pydantic v2、现有 Evidence `EvidencePacket`/`EvidenceCoverage`/EV-02 reasoning contracts、现有 Cognition v0.5 `AssertionProposal`、pytest。

## Global Constraints

- Evidence 不直接写 World Model；proposal 必须经过 Cognition decision 和 `WorldModelCommitPort`。
- Proposal 只能来自 EV-02 `sufficient` 的 requirement decision；`partial`、`insufficient`、`contradicted`、`human_required`、`not_available`、`failed` 不得生成可提交 proposal。
- absence 只有在 EV-02 `conclusion_kind=absence` 且 `absence_authorized=true` 时才能成为 proposal value；`SUCCESS_EMPTY` 本身不产生 absence proposal。
- Proposal 必须闭合到 candidate、observation/claim、source、requirement、policy、packet digest、WM parent digest；禁止从自然语言或外源坐标制造 canonical/entity/geometry ref。
- 外源证据只能生成 locator/property support；representation support 只接受已具备明确 DATA geometry authority 的 representation ref。
- 相同输入必须生成相同 proposal refs/fingerprint；created-at 等易变字段不参与业务 fingerprint。

---

### Task 1: Add immutable Evidence proposal contracts

**Files:**
- Create: `backend/app/contracts/evidence/proposal_contracts.py`
- Modify: `backend/app/contracts/evidence/__init__.py`
- Test: `tests/test_evidence_proposal_contracts.py`

**Interfaces:**
- Produces `EvidenceProposalBase`, `EntitySupportProposal`, `RelationSupportProposal`, `PropertyAssertionProposal`, `RepresentationSupportProposal`, `EvidenceProposal`, and `EvidenceProposalBatch`.
- `EvidenceProposalBatch` exposes `proposal_fingerprint` and contains `round_id`, `wm_epoch`, `parent_world_model_digest`, `requirement_set_digest`, `evidence_packet_digest`, and immutable proposal tuples.
- The four concrete proposal types use proposal kinds `entity_support`, `relation_support`, `property_assertion`, and `representation_support`.

- [ ] **Step 1: Write the failing contract tests**

```python
def test_proposal_batch_is_immutable_and_has_all_round_lineage():
    proposal = EntitySupportProposal(
        proposal_ref="evidence.proposal.entity.req-1.candidate-1",
        requirement_ref="req-1",
        policy_ref="facility_existence",
        policy_version="1",
        subject_ref="candidate-1",
        candidate_refs=("candidate-1",),
        observation_refs=("observation-1",),
        source_refs=("source-1",),
        evidence_refs=("claim-1",),
        authority={"source": "authoritative"},
        parent_world_model_digest="wm-1",
        evidence_packet_digest="packet-1",
    )
    batch = EvidenceProposalBatch(
        round_id="round-1",
        wm_epoch="wm-epoch-1",
        parent_world_model_digest="wm-1",
        requirement_set_digest="requirements-1",
        evidence_packet_digest="packet-1",
        proposals=(proposal,),
    )
    assert batch.proposal_fingerprint.startswith("sha256:")
    with pytest.raises((TypeError, ValidationError)):
        proposal.subject_ref = "other"


def test_absence_proposal_requires_explicit_authorization():
    with pytest.raises(ValidationError, match="absence"):
        PropertyAssertionProposal(
            proposal_ref="evidence.proposal.property.req-1.candidate-1",
            requirement_ref="req-1",
            policy_ref="absence_claim",
            policy_version="1",
            subject_ref="road:R1",
            predicate="exists",
            value=None,
            conclusion_kind="absence",
            authority={"source": "authoritative"},
            parent_world_model_digest="wm-1",
            evidence_packet_digest="packet-1",
        )
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest -q tests/test_evidence_proposal_contracts.py`

Expected: FAIL because the proposal contract module and models do not exist.

- [ ] **Step 3: Implement strict immutable contracts**

Use `ConfigDict(frozen=True, extra="forbid")`, deterministic sorted/deduplicated reference tuples, explicit `conclusion_kind`/`absence_authorized` validation, and a batch fingerprint computed from stable business fields only. Do not add a compatibility union or legacy field aliases.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `pytest -q tests/test_evidence_proposal_contracts.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/contracts/evidence/proposal_contracts.py backend/app/contracts/evidence/__init__.py tests/test_evidence_proposal_contracts.py
git commit -m "feat(evidence): add proposal contracts"
```

### Task 2: Compile EV-02 output into four proposal kinds

**Files:**
- Create: `backend/app/modules/evidence/proposals.py`
- Test: `tests/test_evidence_proposals.py`

**Interfaces:**
- `build_evidence_proposals(result: ExplorationResult, *, round_id: str, wm_epoch: str, parent_world_model_digest: str, evidence_artifact_ref: str = "") -> EvidenceProposalBatch`.
- `to_cognition_assertion_proposals(batch: EvidenceProposalBatch) -> tuple[AssertionProposal, ...]`.
- The compiler must return an empty proposal tuple for non-sufficient requirements and must never call a Cognition store or commit port.

- [ ] **Step 1: Write failing compiler tests**

Cover these cases with typed fixtures containing `EvidenceObservationSnapshot`, `EvidenceCoverage.sufficiency_decision`, claims, candidates, sources, and a packet:

```python
def test_sufficient_identity_requirement_produces_entity_support():
    batch = build_evidence_proposals(
        sufficient_identity_result,
        round_id="round-1",
        wm_epoch="7",
        parent_world_model_digest="wm-7",
    )
    assert [item.proposal_kind for item in batch.proposals] == ["entity_support"]
    assert batch.proposals[0].source_refs == ("source-1",)
    assert batch.proposals[0].observation_refs == ("observation-1",)


def test_relation_property_and_local_representation_are_distinct_proposals():
    batch = build_evidence_proposals(mixed_sufficient_result, round_id="r", wm_epoch="8", parent_world_model_digest="wm-8")
    assert {item.proposal_kind for item in batch.proposals} == {
        "relation_support", "property_assertion", "representation_support"
    }


@pytest.mark.parametrize("status", ["partial", "insufficient", "human_required", "failed"])
def test_non_sufficient_decision_produces_no_wm_proposal(status):
    assert build_evidence_proposals(result_with_status(status), round_id="r", wm_epoch="8", parent_world_model_digest="wm-8").proposals == ()


def test_absence_requires_ev02_authorization_and_complete_lineage():
    batch = build_evidence_proposals(authorized_absence_result, round_id="r", wm_epoch="8", parent_world_model_digest="wm-8")
    assert batch.proposals[0].conclusion_kind == "absence"
    assert batch.proposals[0].absence_authorized is True
    assert build_evidence_proposals(unexhausted_empty_result, round_id="r", wm_epoch="8", parent_world_model_digest="wm-8").proposals == ()


def test_external_locator_cannot_become_representation_support():
    batch = build_evidence_proposals(external_only_representation_result, round_id="r", wm_epoch="8", parent_world_model_digest="wm-8")
    assert all(item.proposal_kind != "representation_support" for item in batch.proposals)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest -q tests/test_evidence_proposals.py`

Expected: FAIL because the compiler does not exist.

- [ ] **Step 3: Implement the deterministic compiler**

Resolve each sufficient requirement decision by `requirement_ref`, select only candidate rows with matching requirement refs and supported status, derive typed proposal subjects/objects/values only from explicit candidate/claim/packet fields, attach both supporting and opposing refs, and reject any proposal whose required lineage is incomplete. Use `hashlib` over canonical JSON for proposal refs. Keep the module independent of `app.infrastructure.cognition_runtime` and do not import `CognitionCommitPort`.

- [ ] **Step 4: Implement the explicit Cognition adapter**

Map each typed Evidence proposal to the existing `AssertionProposal`, preserving `proposal_ref`, kind, subject/predicate/object/value, source/evidence/requirement refs, authority, valid time, and parent digest. The adapter is conversion-only; it must not evaluate decisions or commit.

- [ ] **Step 5: Run tests and verify they pass**

Run: `pytest -q tests/test_evidence_proposal_contracts.py tests/test_evidence_proposals.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/modules/evidence/proposals.py tests/test_evidence_proposals.py
git commit -m "feat(evidence): compile sufficiency into cognition proposals"
```

### Task 3: Persist proposal batches with retrieval artifacts

**Files:**
- Modify: `backend/app/contracts/evidence/evidence_contracts.py`
- Modify: `backend/app/contracts/evidence/retrieval_artifact_contracts.py`
- Modify: `backend/app/infrastructure/evidence_runtime/artifact_store.py`
- Modify: `backend/app/modules/evidence/application.py`
- Test: `tests/test_evidence_proposal_persistence.py`

**Interfaces:**
- `ExplorationResult.proposal_batch` and `EvidenceRetrievalArtifact.proposal_batch` are optional only for pre-EV-03 callers; committed retrieval artifacts must populate the batch when the result has a valid EV-02 coverage.
- `_commit_retrieval_artifact` derives the batch before `write_once`; `_result_from_retrieval_artifact` reloads it unchanged.
- CAS semantic comparison includes `proposal_batch`, so a same retrieval fingerprint cannot silently return different proposals.

- [ ] **Step 1: Write failing persistence tests**

Assert that a normalized sufficient retrieval stores a batch with its packet digest and WM parent digest, a reload returns the same fingerprint, and artifact semantic mismatch in proposals is rejected by the existing CAS path.

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `pytest -q tests/test_evidence_proposal_persistence.py`

Expected: FAIL because result/artifact contracts do not yet carry proposal batches.

- [ ] **Step 3: Add the typed field and wire compile/reload/CAS**

Use the retrieval authority's `world_model_snapshot_digest` as the proposal parent digest, the retrieval fingerprint as the evidence artifact identity, and deterministic round/epoch values derived from the retrieval context only where the current runtime has no explicit CognitionRound carrier. Do not invent an accepted decision or commit request in Evidence.

- [ ] **Step 4: Run focused and regression tests**

Run: `pytest -q tests/test_evidence_proposal_contracts.py tests/test_evidence_proposals.py tests/test_evidence_proposal_persistence.py tests/test_evidence_policy_sufficiency.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/contracts/evidence/evidence_contracts.py backend/app/contracts/evidence/retrieval_artifact_contracts.py backend/app/infrastructure/evidence_runtime/artifact_store.py backend/app/modules/evidence/application.py tests/test_evidence_proposal_persistence.py
git commit -m "feat(evidence): persist cognition proposal batch"
```

### Task 4: Document and verify the Evidence→Cognition handoff

**Files:**
- Modify: `docs/design/04_EVIDENCE.md`
- Modify: `backend/app/modules/evidence/README.md`
- Test: `tests/test_evidence_proposal_boundary.py`

**Interfaces:**
- Documentation records EV-03 as implemented, the proposal-to-Cognition handoff, the absence gate, and the non-writer boundary.
- Boundary test statically verifies `modules/evidence/proposals.py` has no WM store/commit import and that conversion does not mutate its input batch.

- [ ] **Step 1: Write the failing boundary test**

Check that the proposal compiler module contains no import/reference to `WorldModelCommitPort`, `commit_assertion_transaction`, or `world_model_store`, and that `to_cognition_assertion_proposals` leaves the batch unchanged.

- [ ] **Step 2: Run it and verify the boundary is enforced**

Run: `pytest -q tests/test_evidence_proposal_boundary.py`

Expected: PASS after the compiler is implemented; fail if a later edit adds a direct writer dependency.

- [ ] **Step 3: Update the design status tables and module README**

Replace the EV-02-era “proposal not touched” status with the actual EV-03 implementation and state that Cognition owns decisions/commit. Remove obsolete statements that imply Evidence stops at `ObservationSnapshot/Receipt`.

- [ ] **Step 4: Run the proportionate full suite and checks**

Run:

```powershell
python -m compileall -q backend/app
git diff --check
pytest -q tests --ignore=tests/test_data_change_set_boundary.py
```

Expected: compile and diff checks pass; the focused/normal test suite passes. Known repository-wide optional dependency failures outside the Evidence scope should be reported separately if encountered.

- [ ] **Step 5: Commit**

```powershell
git add docs/design/04_EVIDENCE.md backend/app/modules/evidence/README.md tests/test_evidence_proposal_boundary.py
git commit -m "docs(evidence): define cognition proposal handoff"
```

## Self-review checklist

- [ ] Every proposal has policy, requirement, candidate, observation/claim, source, packet, and parent WM lineage.
- [ ] Four proposal kinds are distinct and map to existing Cognition `AssertionProposal` without duplicating the WM transaction contract.
- [ ] No Evidence code path calls the WM writer.
- [ ] Absence is emitted only after the EV-02 final gate has authorized it.
- [ ] External coordinates never become executable geometry through this handoff.
- [ ] Artifact replay compares proposal semantics and returns the same immutable batch.
