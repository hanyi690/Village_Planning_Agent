from __future__ import annotations

import asyncio
import hashlib

import pytest

from app.contracts.artifacts.ref import ArtifactRef
from app.modules.l2.application import L2Application, L2RunRequest
from app.modules.l3.application import L3Application, L3RunRequest


def ref(schema_id: str, seed: str | None = None) -> dict:
    digest = hashlib.sha256((seed or schema_id).encode()).hexdigest()
    value = f"sha256:{digest}"
    return ArtifactRef(
        digest=value,
        descriptor_digest=value,
        semantic_digest=value,
        size_bytes=0,
        schema_id=schema_id,
        schema_version="3",
        producer_stage="test",
        run_id="run-1",
        branch_id="main",
    ).model_dump(mode="json")


def state_without_manifest() -> dict:
    return {
        "run_id": "run-1",
        "session_id": "session-1",
        "context_version": "context-1",
        "artifact_refs": {
            "l1_snapshot": ref("L1ObservationSnapshot"),
        },
    }


def state_with_manifest() -> dict:
    state = state_without_manifest()
    state["artifact_refs"]["l1_product_manifest"] = ref(
        "L1ProductManifest", "manifest"
    )
    return state


def test_l2_request_requires_l1_product_manifest() -> None:
    with pytest.raises(RuntimeError, match="L1ProductManifest"):
        L2RunRequest.from_state(state_without_manifest())


def test_l3_request_requires_l1_product_manifest() -> None:
    state = state_without_manifest()
    state["artifact_refs"]["l2_strategy"] = ref("L2Strategy")
    with pytest.raises(RuntimeError, match="L1ProductManifest"):
        L3RunRequest.from_state(state)


def test_l2_rejects_non_ready_manifest_before_aggregate(monkeypatch) -> None:
    import app.modules.l2.application as l2_application

    async def aggregate_must_not_run(_state):
        raise AssertionError("L2 aggregate must not run")

    monkeypatch.setattr(
        l2_application,
        "load_ready_l1_product_manifest",
        lambda _state: (_ for _ in ()).throw(
            RuntimeError("L2 requires a ready L1ProductManifest; current status=partial")
        ),
    )
    monkeypatch.setattr(
        "app.workflow.stages.support.require_upstream_gates",
        lambda _state, _stages: None,
    )
    monkeypatch.setattr(l2_application, "l2_aggregate", aggregate_must_not_run, raising=False)

    with pytest.raises(RuntimeError, match="ready"):
        asyncio.run(L2Application().run(state_with_manifest()))


def test_l3_rejects_non_ready_manifest_before_aggregate(monkeypatch) -> None:
    import app.modules.l3.application as l3_application

    state = state_with_manifest()
    state["artifact_refs"]["l2_strategy"] = ref("L2Strategy")
    monkeypatch.setattr(
        l3_application,
        "load_ready_l1_product_manifest",
        lambda _state: (_ for _ in ()).throw(
            RuntimeError("L3 requires a ready L1ProductManifest; current status=partial")
        ),
    )
    monkeypatch.setattr(
        "app.workflow.stages.support.require_upstream_gates",
        lambda _state, _stages: None,
    )

    with pytest.raises(RuntimeError, match="ready"):
        asyncio.run(L3Application().run(state))
