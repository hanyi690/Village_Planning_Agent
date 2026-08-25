from __future__ import annotations


def test_l3_claim_lineage_metric_counts_all_typed_source_channels() -> None:
    from app.contracts.program import PlanningClaim
    from app.domain.program.worker import _claim_lineage_present

    assert _claim_lineage_present(
        PlanningClaim(
            claim_id="fact",
            statement="已核验事实",
            source_fact_refs=["l1:fact:1"],
        )
    )
    assert _claim_lineage_present(
        PlanningClaim(
            claim_id="source",
            statement="来源约束",
            source_refs=["report:current"],
        )
    )
    assert _claim_lineage_present(
        PlanningClaim(
            claim_id="evidence",
            statement="证据约束",
            evidence_refs=["kg:topology:road_network"],
        )
    )
    assert not _claim_lineage_present(
        PlanningClaim(claim_id="unresolved", statement="待 grounding")
    )
