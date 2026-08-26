"""Village-cluster mapper regression tests.

Clusters are derived from real 宅基地 bundle parcels (no fabrication).  A
name is never assigned by list/size order when report evidence is unavailable.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.spatial.grounding.village_cluster_mapper import (
    build_village_clusters,
    map_villages,
    stable_entity_ref,
)


def _parcel(bsm, lon, dlbm="1340"):
    return SimpleNamespace(
        bsm=bsm,
        name="",
        dlbm=dlbm,
        area_sqm=800.0,
        geometry={
            "type": "Polygon",
            "coordinates": [[[lon, 23.0], [lon + 0.001, 23.0],
                             [lon + 0.001, 23.001], [lon, 23.001], [lon, 23.0]]],
        },
    )


def _parcels():
    out = []
    for i, lon in enumerate([113.00 + 0.0005 * j for j in range(4)]):
        out.append(_parcel(f"a{i}", lon))
    for i, lon in enumerate([113.05 + 0.0005 * j for j in range(6)]):
        out.append(_parcel(f"b{i}", lon))
    out.append(_parcel("c0", 113.2))
    out.append(_parcel("farm", 113.3, dlbm="1100"))
    return out


def test_build_village_clusters_uses_residential_parcels():
    clusters = build_village_clusters(_parcels())
    assert len(clusters) == 3
    assert clusters[0].parcel_count == 6
    assert clusters[1].parcel_count == 4
    assert clusters[2].parcel_count == 1
    all_bsms = [b for c in clusters for b in c.bsms]
    assert "farm" not in all_bsms


def test_missing_report_evidence_keeps_names_unresolved():
    clusters = build_village_clusters(_parcels())
    mapping = asyncio.run(map_villages(clusters, ["园寨", "田坑", "社前"], llm=None))
    assert set(mapping) == {
        stable_entity_ref("village", name) for name in ["园寨", "田坑", "社前"]
    }
    assert all(item["status"] == "unresolved" for item in mapping.values())
    assert all(item["reason_code"] == "report_evidence_missing" for item in mapping.values())


def test_untyped_flash_text_is_not_promoted_to_spatial_mapping():
    class FakeLLM:
        async def ainvoke(self, _prompt):
            return SimpleNamespace(
                content='{"田坑": {"cluster_index": 1, "evidence": "田坑位于村域西部"}}'
            )

    clusters = build_village_clusters(_parcels())
    mapping = asyncio.run(
        map_villages(
            clusters,
            ["田坑", "社前"],
            report_text="现状调查显示：田坑位于村域西部。",
            llm=FakeLLM(),
        )
    )

    assert set(mapping) == {
        stable_entity_ref("village", name) for name in ["田坑", "社前"]
    }
    assert all(item["status"] == "pending" for item in mapping.values())
    assert all(item["candidate_ids"] == [] for item in mapping.values())


def _span(text: str, mention: str) -> dict:
    start = text.index(mention)
    quote = text[start:start + len(mention)]
    return {
        "segment_id": "report",
        "start": start,
        "end": start + len(mention),
        "quote_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
    }


class _StableMappingLLM:
    def __init__(self, names, candidates, report_text, *, mode="valid"):
        self.names = names
        self.candidates = candidates
        self.report_text = report_text
        self.mode = mode
        self.calls = 0
        self.prompts = []

    def with_structured_output(self, schema, **_kwargs):
        owner = self

        class _Runner:
            async def ainvoke(self, messages):
                owner.calls += 1
                prompt = messages[-1]["content"]
                owner.prompts.append(prompt)
                refs = [stable_entity_ref("village", name) for name in owner.names]
                if owner.mode == "invalid_batch":
                    return schema.model_validate({
                        "decisions": [
                            {
                                "entity_ref": refs[0],
                                "status": "unresolved",
                                "reason_code": "no_evidence",
                            },
                            {
                                "entity_ref": refs[0],
                                "status": "unresolved",
                                "reason_code": "duplicate",
                            },
                            {
                                "entity_ref": "village:unknown",
                                "status": "unresolved",
                                "reason_code": "unknown",
                            },
                        ]
                    })
                return schema.model_validate({
                    "decisions": [
                        {
                            "entity_ref": ref,
                            "status": "mapped",
                            "candidate_ids": [owner.candidates[i].cluster_id],
                            "source_span": _span(owner.report_text, name),
                        }
                        for i, (ref, name) in enumerate(zip(refs, owner.names))
                    ]
                })

        return _Runner()


def test_stable_id_batch_requires_source_span_and_exposes_dynamic_candidate_digest():
    clusters = build_village_clusters(_parcels())
    report = "田坑位于村域西部，社前位于村域东部。"
    llm = _StableMappingLLM(["田坑", "社前"], clusters, report)

    mapping = asyncio.run(map_villages(
        clusters,
        ["田坑", "社前"],
        report_text=report,
        llm=llm,
    ))

    assert set(mapping) == {
        stable_entity_ref("village", "田坑"),
        stable_entity_ref("village", "社前"),
    }
    assert all(item["status"] == "mapped" for item in mapping.values())
    assert all(item["candidate_ids"] for item in mapping.values())
    assert all(item["source_span"]["segment_id"] == "report" for item in mapping.values())
    assert mapping.candidate_set_digest
    assert "candidate_indexes" not in llm.prompts[0]
    assert "candidate_set_digest=" in llm.prompts[0]
    assert all(cluster.cluster_id in llm.prompts[0] for cluster in clusters)


def test_missing_duplicate_and_unknown_batch_members_are_pending_not_repaired():
    clusters = build_village_clusters(_parcels())
    report = "田坑位于村域西部。"
    llm = _StableMappingLLM(["田坑", "社前"], clusters, report, mode="invalid_batch")

    mapping = asyncio.run(map_villages(
        clusters,
        ["田坑", "社前"],
        report_text=report,
        llm=llm,
    ))

    assert mapping[stable_entity_ref("village", "田坑")]["reason_code"] == "duplicate_entity_ref"
    assert mapping[stable_entity_ref("village", "社前")]["reason_code"] == "unknown_entity_ref_in_batch"
    assert mapping.unknown_refs == ["village:unknown"]
    assert all(item["status"] == "pending" for item in mapping.values())


def test_cache_requires_schema_input_and_candidate_digests(tmp_path):
    clusters = build_village_clusters(_parcels())
    report = "田坑位于村域西部。"
    cache = tmp_path / "mapping.json"
    first_llm = _StableMappingLLM(["田坑"], clusters, report)

    first = asyncio.run(map_villages(
        clusters, ["田坑"], report_text=report, llm=first_llm, cache=cache,
    ))
    assert first_llm.calls == 1
    raw = json.loads(cache.read_text(encoding="utf-8"))
    assert set(raw) >= {
        "schema_version", "schema_digest", "input_digest", "candidate_set_digest", "value",
    }

    second_llm = _StableMappingLLM(["田坑"], clusters, report)
    second = asyncio.run(map_villages(
        clusters, ["田坑"], report_text=report, llm=second_llm, cache=cache,
    ))
    assert second_llm.calls == 0
    assert second == first

    cache.write_text(json.dumps({"key": "legacy", "map": {}}), encoding="utf-8")
    bad_cache_llm = _StableMappingLLM(["田坑"], clusters, report)
    asyncio.run(map_villages(
        clusters, ["田坑"], report_text=report, llm=bad_cache_llm, cache=cache,
    ))
    assert bad_cache_llm.calls == 1

    clusters[0].bsms.append("changed-input")
    third_llm = _StableMappingLLM(["田坑"], clusters, report)
    asyncio.run(map_villages(
        clusters, ["田坑"], report_text=report, llm=third_llm, cache=cache,
    ))
    assert third_llm.calls == 1


def test_mapping_schema_forbids_positional_or_free_form_fields():
    from pydantic import ValidationError
    from app.spatial.grounding.village_cluster_mapper import _GMappingSet

    with pytest.raises(ValidationError):
        _GMappingSet.model_validate({
            "decisions": [{
                "entity_ref": "village:stable",
                "status": "pending",
                "reason_code": "abstain",
                "candidate_indexes": [0],
            }]
        })
