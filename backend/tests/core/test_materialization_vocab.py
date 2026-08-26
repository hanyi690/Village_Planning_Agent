from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.contracts.domain.custom_zone_contracts import Vocabulary
from app.domain.materialization.vocab_extractor import (
    _VocabularyOutput,
    _compile_vocabulary_output,
    extract_vocabulary_from_reports,
    register_session_vocabulary,
)


class _LayerGroup:
    def __init__(self, layers: dict[str, list[object]]) -> None:
        self._layers = layers

    def get(self, key: str) -> list[object]:
        return list(self._layers.get(key, []))

    def keys(self) -> list[str]:
        return list(self._layers.keys())


def _bundle() -> SimpleNamespace:
    parcels = [
        SimpleNamespace(
            bsm="P001",
            dlbm="0101",
            area_sqm=10000.0,
            zone_type="农业生产区",
            planning_zone="农业生产区",
            primary_zone="农业空间",
            slope_deg=12.0,
            road_distance_m=180.0,
            poi_hits=["poi-teahouse"],
        ),
        SimpleNamespace(
            bsm="P002",
            dlbm="0201",
            area_sqm=15000.0,
            zone_type="生态保护区",
            planning_zone="生态保护区",
            primary_zone="生态空间",
            slope_deg=28.0,
            road_distance_m=850.0,
            poi_hits=[],
        ),
    ]
    points = [
        SimpleNamespace(bsm="poi-teahouse", facility_name="poi-teahouse", facility_type="service"),
    ]
    roads = [
        SimpleNamespace(bsm="road-main", road_name="road-main"),
    ]
    zones = [
        SimpleNamespace(bsm="zone-1", zone_name="农业生产区", subtype="农业生产区"),
    ]
    return SimpleNamespace(
        polygons=_LayerGroup({
            "landuse_current": parcels,
            "land_use_zone": zones,
        }),
        points=_LayerGroup({
            "facilities_current": points,
        }),
        lines=_LayerGroup({
            "roads_current": roads,
        }),
    )


class _StructuredLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, _prompt: str) -> dict:
        return self.payload


def test_compile_accepts_valid_typed_rules_and_runs_dry_run() -> None:
    payload = _VocabularyOutput.model_validate({
        "categories": [
            {
                "name_zh": "农业生产区",
                "color": "#112233",
                "source_span": "功能分区表：农业生产区",
                "rules": [
                    {
                        "rule": "all",
                        "children": [
                            {"rule": "dlbm_in", "dlbm_ids": ["0101"], "source_span": "耕地"},
                            {"rule": "within_zone", "zone_id": "农业生产区", "source_span": "农业生产区"},
                            {"rule": "road_distance_lt", "max_distance_m": 300, "road_id": "road-main"},
                            {"rule": "near_poi", "poi_id": "poi-teahouse"},
                        ],
                    }
                ],
            }
        ]
    })

    result = _compile_vocabulary_output(payload, bundle=_bundle())

    assert [category.name_zh for category in result.vocabulary.categories] == ["农业生产区"]
    assert result.vocabulary.categories[0].typing_rules[0].kind == "and"
    assert result.dry_run[0].matched_bsms == ["P001"]
    assert result.dry_run[0].matched_area_ha == 1.0
    assert result.dry_run[0].source_span == "功能分区表：农业生产区"
    assert result.quarantine == []


def test_typed_rule_union_requires_discriminator_and_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _VocabularyOutput.model_validate({
            "categories": [
                {
                    "name_zh": "旧格式区",
                    "rules": [
                        {"kind": "dlbm_in", "value": ["0101"]},
                    ],
                }
            ]
        })

    with pytest.raises(ValidationError):
        _VocabularyOutput.model_validate({
            "categories": [
                {
                    "name_zh": "额外字段区",
                    "rules": [
                        {
                            "rule": "dlbm_in",
                            "dlbm_ids": ["0101"],
                            "unexpected": "forbid-me",
                        }
                    ],
                }
            ]
        })


def test_compile_quarantines_unknown_bundle_ids() -> None:
    payload = _VocabularyOutput.model_validate({
        "categories": [
            {
                "name_zh": "产业区",
                "color": "#445566",
                "source_span": "产业区原文",
                "rules": [
                    {"rule": "near_poi", "poi_id": "poi-missing", "source_span": "靠近未知设施"},
                ],
            }
        ]
    })

    result = _compile_vocabulary_output(payload, bundle=_bundle())

    assert result.vocabulary.categories == []
    assert result.quarantine[0].name_zh == "产业区"
    assert result.quarantine[0].reason == "unknown_poi_id:poi-missing"
    assert result.quarantine[0].source_span == "靠近未知设施"
    with pytest.raises(ValueError, match="vocabulary_has_no_verified_categories"):
        register_session_vocabulary("session-1", result.vocabulary)


def test_compile_quarantines_excessive_rule_depth() -> None:
    payload = _VocabularyOutput.model_validate({
        "categories": [
            {
                "name_zh": "深层规则区",
                "rules": [
                    {
                        "rule": "not",
                        "children": [
                            {
                                "rule": "not",
                                "children": [
                                    {
                                        "rule": "not",
                                        "children": [
                                            {
                                                "rule": "not",
                                                "children": [
                                                    {
                                                        "rule": "not",
                                                        "children": [
                                                            {
                                                                "rule": "not",
                                                                "children": [
                                                                    {"rule": "dlbm_in", "dlbm_ids": ["0101"]},
                                                                ],
                                                            }
                                                        ],
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    })

    result = _compile_vocabulary_output(payload, bundle=_bundle(), max_rule_depth=6)

    assert result.vocabulary.categories == []
    assert result.quarantine[0].reason == "rule_depth_exceeded:7>6"


def test_compile_quarantines_excessive_rule_nodes() -> None:
    payload = _VocabularyOutput.model_validate({
        "categories": [
            {
                "name_zh": "超节点规则区",
                "rules": [
                    {
                        "rule": "all",
                        "children": [
                            {"rule": "dlbm_in", "dlbm_ids": ["0101"]}
                            for _ in range(12)
                        ],
                    }
                ],
            }
        ]
    })

    result = _compile_vocabulary_output(payload, bundle=_bundle(), max_rule_nodes=8)

    assert result.vocabulary.categories == []
    assert result.quarantine[0].reason == "rule_nodes_exceeded:13>8"


def test_compile_runs_dry_run_sanity_hook() -> None:
    payload = _VocabularyOutput.model_validate({
        "categories": [
            {
                "name_zh": "农业生产区",
                "rules": [
                    {"rule": "dlbm_in", "dlbm_ids": ["0101"]},
                ],
            }
        ]
    })

    result = _compile_vocabulary_output(
        payload,
        bundle=_bundle(),
        sanity_hook=lambda dry_run: "matched_count_below_2" if dry_run.matched_count < 2 else None,
    )

    assert result.vocabulary.categories[0].name_zh == "农业生产区"
    assert "matched_count_below_2" in result.dry_run[0].diagnostics


@pytest.mark.asyncio
async def test_extract_vocabulary_from_reports_rejects_legacy_payload_and_keeps_valid_categories() -> None:
    bad_llm = _StructuredLLM({
        "categories": [
            {
                "name_zh": "旧格式区",
                "color": "#abcdef",
                "rules": [
                    {"kind": "dlbm_in", "value": ["0101"]},
                ],
            }
        ]
    })

    with pytest.raises(RuntimeError, match="typed_vocabulary_extraction_failed"):
        await extract_vocabulary_from_reports(
            {"report-1": "示例报告"},
            llm=bad_llm,
            bundle=_bundle(),
        )

    llm = _StructuredLLM({
        "categories": [
            {
                "name_zh": "农业生产区",
                "color": "#abcdef",
                "source_span": "功能分区表农业生产区",
                "rules": [
                    {"rule": "dlbm_in", "dlbm_ids": ["0101"], "source_span": "耕地"},
                ],
            },
            {
                "name_zh": "无效产业区",
                "color": "#123456",
                "source_span": "功能分区表无效产业区",
                "rules": [
                    {"rule": "within_zone", "zone_id": "zone-missing", "source_span": "未知分区"},
                ],
            },
        ]
    })

    vocab = await extract_vocabulary_from_reports(
        {"report-1": "示例报告"},
        llm=llm,
        bundle=_bundle(),
    )

    assert isinstance(vocab, Vocabulary)
    assert [category.name_zh for category in vocab.categories] == ["农业生产区"]
