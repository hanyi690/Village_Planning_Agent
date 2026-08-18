from __future__ import annotations


def test_observations_keep_independent_ids_and_bind_to_one_entity():
    from app.contracts.evidence.identity_contracts import (
        EvidenceObservation,
        EvidenceObservationSnapshot,
        GroundedEntityBinding,
    )

    first = EvidenceObservation(
        observation_id="obs-1",
        mention="老小学",
        normalized_name="老小学",
        role="facility",
        source_document_ref="report-1",
        source_span="社前村老小学改造",
    )
    second = first.model_copy(
        update={"observation_id": "obs-2", "source_document_ref": "report-2"}
    )
    snapshot = EvidenceObservationSnapshot(
        observations=[first, second],
        provenance_refs=["report-1", "report-2"],
    )
    binding = GroundedEntityBinding(
        binding_id="binding-1",
        mention_ref="canonical:old-school",
        canonical_entity_ref="http://village-planning.org/ontology#Facility_1",
        observation_refs=["obs-1", "obs-2"],
        status="resolved",
        geometry_granularity="exact_feature",
    )

    assert [item.observation_id for item in snapshot.observations] == ["obs-1", "obs-2"]
    assert binding.observation_refs == ["obs-1", "obs-2"]


def test_village_anchor_is_scope_not_exact_feature():
    from app.contracts.spatial.grounding_contracts import GroundedAnchor

    anchor = GroundedAnchor(
        location_fact_ref="fact-1",
        mention="卫生室",
        normalized_name="卫生室",
        role="facility",
        geometry_ref="village_anchor:社前村",
        source_bsms=["parcel-1", "parcel-2"],
        best_effort=True,
    )

    assert anchor.geometry_granularity == "village_scope"
    assert anchor.geometry_granularity != "exact_feature"


def test_observation_snapshot_can_be_stored_and_reloaded(tmp_path):
    from app.contracts.evidence.identity_contracts import EvidenceObservation
    from app.evidence.identity.observation_store import ObservationStore

    state = {
        "session_id": "identity-session",
        "run_id": "identity-run",
        "branch_id": "main",
        "artifact_refs": {},
        "context_ref": {"session_id": "identity-session", "version": "1"},
        "artifact_schema_version": "3",
    }
    observations = [
        EvidenceObservation(
            observation_id="obs-1",
            mention="社前村",
            normalized_name="社前村",
            role="village",
            source_document_ref="report-1",
        )
    ]
    store = ObservationStore(base_dir=tmp_path)
    ref = store.put_snapshot(state, observations, parent_digest="parent-1")
    state["artifact_refs"]["l1_observations"] = ref.model_dump(mode="json")
    loaded = store.load_snapshot(state)

    assert [item.observation_id for item in loaded] == ["obs-1"]
    assert ref.digest


def test_binding_store_persists_resolution_without_repeating_llm(tmp_path):
    from types import SimpleNamespace

    from app.contracts.domain.l1_contracts import L1LocationFact
    from app.contracts.ports.place_resolution_contracts import (
        PlaceResolutionCandidate,
        PlaceResolutionResult,
    )
    from app.evidence.identity.binding_store import BindingStore

    candidate = PlaceResolutionCandidate(
        entity_ref="http://village-planning.org/ontology#Facility_old_school",
        entity_type="facility",
        canonical_name="老小学",
        geometry_ref="POINT(116 39)",
        source_bsms=["P-1"],
        score=0.92,
        evidence_refs=["kg:name", "bundle:point"],
        relation_refs=["pln:serves:cluster-1"],
    )
    result = PlaceResolutionResult(
        mention="老小学",
        normalized_name="老小学",
        status="resolved",
        selected_entity_ref=candidate.entity_ref,
        candidates=[candidate],
        query_trace=[{"step": "exact"}],
    )
    fact = L1LocationFact(
        mention="老小学",
        normalized_name="老小学",
        role="facility",
        source_report_ref="report-1",
    )
    context = SimpleNamespace(
        location_facts=[fact],
        evidence_index=SimpleNamespace(resolve_mention=lambda *args, **kwargs: result),
    )
    bindings = BindingStore.from_context(context)
    assert len(bindings) == 1
    assert bindings[0].status == "resolved"
    assert bindings[0].geometry_granularity == "exact_feature"
    assert bindings[0].relation_evidence_refs == ["pln:serves:cluster-1"]

    state = {
        "session_id": "binding-session",
        "run_id": "binding-run",
        "branch_id": "main",
        "artifact_refs": {},
        "context_ref": {"session_id": "binding-session", "version": "1"},
        "artifact_schema_version": "3",
    }
    store = BindingStore(base_dir=tmp_path)
    ref = store.put_snapshot(state, bindings, observation_snapshot_ref="obs-digest")
    state["artifact_refs"]["l1_bindings"] = ref.model_dump(mode="json")
    loaded = store.load_snapshot(state)
    assert loaded[0].canonical_entity_ref == candidate.entity_ref
