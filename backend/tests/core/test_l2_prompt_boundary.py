from __future__ import annotations

import asyncio


def test_structured_l2_prompt_uses_runtime_context_without_legacy_skeleton() -> None:
    from app.infrastructure.llm.prompts.concept import get_dimension_prompt

    prompt = get_dimension_prompt(
        "planning_positioning",
        analysis_report="现状报告：村域有传统建筑。",
        task_description="形成村庄规划定位",
        constraints="保护现状资源",
        professional_data="传统建筑事实",
        layer2_contexts="资源禀赋已完成",
        structured=True,
    )

    assert "现状报告：村域有传统建筑。" in prompt
    assert "传统建筑事实" in prompt
    assert "l1:fact:abc" not in prompt
    assert "资源禀赋已完成" in prompt
    assert "输出骨架" not in prompt
    assert "默认4.0‰" not in prompt
    assert "2035年" not in prompt


def test_l2_fact_reference_rules_expose_only_the_runtime_closed_set() -> None:
    from app.domain.validation.l1_fact_catalog import build_l1_fact_catalog
    from app.domain.objectives.worker import (
        _l2_fact_reference_final_guardrail,
        _l2_fact_reference_rules,
    )

    catalog = build_l1_fact_catalog([
        {
            "fact_id": "l1:fact:one",
            "statement": "空间事实",
            "fact_kind": "spatial_observation",
        },
        {
            "fact_id": "l1:fact:two",
            "statement": "文本事实",
            "fact_kind": "document_observation",
        },
        {"fact_id": "l1:legacy:three", "statement": "历史身份"},
    ])
    prompt = _l2_fact_reference_rules({
        "fact_catalog": catalog,
    })

    assert '"l1:fact:one"' in prompt
    assert '"l1:fact:two"' in prompt
    assert '"allowed_l1_facts":' in prompt
    assert '"statement": "空间事实"' in prompt
    assert 'EXPLORE 的 L1_facts' in prompt
    assert "spatial=true" in prompt
    assert "allowed_l1_fact_ids" not in prompt
    assert "l1:legacy:three" not in prompt
    assert f"catalog_digest: {catalog.digest}" in prompt
    assert "使用 proposed 或省略对象" in prompt
    guardrail = _l2_fact_reference_final_guardrail({"fact_catalog": catalog})
    assert "L2 source_fact_refs 最终硬校验" in guardrail
    assert "re-*、EXPLORE、lineage" in guardrail
    assert "allowed_l1_fact_count=2" in guardrail


def test_l2_fact_reference_rules_fail_closed_when_snapshot_has_no_fact_ids() -> None:
    from app.domain.objectives.worker import _l2_fact_reference_rules

    prompt = _l2_fact_reference_rules({"fact_ids": []})

    assert "没有可引用的 canonical L1 fact_id" in prompt
    assert "source_fact_refs 必须为 []" in prompt


def test_l2_snapshot_section_does_not_duplicate_catalog_fact_body(monkeypatch) -> None:
    from app.contracts.domain.l1_contracts import L1Fact, L1Snapshot
    from app.domain.objectives.worker import _load_l1_fact_section
    from app.domain.validation.l1_fact_catalog import validate_l1_fact_catalog

    snapshot = L1Snapshot(
        fact_records=[
            L1Fact(
                fact_id="l1:fact:road",
                statement="现状道路穿过村域",
                fact_kind="spatial_observation",
                dimension_key="traffic",
                source_refs=["report:traffic"],
            ),
            L1Fact(
                fact_id="l1:fact:background",
                statement="交通组织存在短板",
                fact_kind="document_observation",
                dimension_key="traffic",
                source_refs=["report:traffic"],
            ),
            L1Fact(
                fact_id="l1:legacy:unusable",
                statement="历史身份不能成为引用",
                fact_kind="document_observation",
                dimension_key="traffic",
                source_refs=["report:traffic"],
            ),
            L1Fact(
                fact_id="l1:fact:other-dimension",
                statement="其他 L1 维度的事实也属于当前快照",
                fact_kind="document_observation",
                dimension_key="ecological_green",
                source_refs=["report:ecological_green"],
            ),
        ]
    )
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda _state, _key: snapshot,
    )

    section, audit = _load_l1_fact_section(
        {"artifact_refs": {"l1_snapshot": {"digest": "snapshot-1"}}},
        dimension_key="planning_positioning",
        source_dimensions=["traffic"],
    )

    assert section == ""
    assert audit["allowed_fact_ids"] == [
        "l1:fact:background",
        "l1:fact:road",
    ]
    assert audit["spatial_fact_ids"] == ["l1:fact:road"]
    assert audit["catalog_record_count"] == 2
    assert audit["snapshot_fact_record_count"] == 4
    assert audit["catalog_digest"] == audit["fact_catalog"].digest
    assert validate_l1_fact_catalog(audit["fact_catalog"]).accepted


def test_l2_closed_set_validation_reasks_once_without_rewriting_refs() -> None:
    from app.contracts.domain.l2_contracts import L2DecisionSet, PlanningObjective
    from app.domain.validation.l1_fact_catalog import build_l1_fact_catalog
    from app.domain.objectives.worker import (
        _validate_l2_decision_with_one_closed_set_reask,
    )

    invalid = L2DecisionSet(
        dimension_key="planning_positioning",
        objectives=[
            PlanningObjective(
                objective_id="objective-1",
                statement="提升公共服务可达性",
                kind="goal",
                status="observed",
                source_fact_refs=["l1:fact:invented"],
            )
        ],
    )
    valid = invalid.model_copy(
        deep=True,
        update={
            "objectives": [
                invalid.objectives[0].model_copy(
                    update={"source_fact_refs": ["l1:fact:known"]}
                )
            ]
        },
    )
    feedback: list[str] = []

    async def run_decision(message: str):
        feedback.append(message)
        return valid

    catalog = build_l1_fact_catalog([{"fact_id": "l1:fact:known"}])
    result, error = asyncio.run(
        _validate_l2_decision_with_one_closed_set_reask(
            invalid,
            catalog=catalog,
            catalog_digest=catalog.digest,
            run_decision=run_decision,
        )
    )

    assert error == ""
    assert feedback and "invented" in feedback[0]
    assert catalog.digest in feedback[0]
    assert result.objectives[0].source_fact_refs == ["l1:fact:known"]
