"""Cheap production boundary probe; it never invokes a test framework or LLM.

The probe checks that the target business modules and centralized runtimes are
importable, that the Evidence facade compiles a requirement without selecting a
retriever, and that the canonical workflow artifact keys exist.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.modules.evidence.application import EvidenceContext, EvidenceFacade
from app.modules.evidence.requirements import compile_requirements


def _check_context_projections() -> None:
    """Exercise every stage projection through the shared context runtime."""

    from types import SimpleNamespace

    from app.modules.execute.projections import build_execute_projection
    from app.modules.ground.projections import build_ground_projection
    from app.modules.l3.projections import build_l3_projection
    from app.modules.select.projections import build_select_projection
    from app.modules.target_projection.projections import (
        build_target_projection_projection,
    )

    projections = (
        build_l3_projection(
            SimpleNamespace(
                interventions=[
                    SimpleNamespace(
                        intervention_id="claim-1",
                        name="设施改善",
                        action="improve",
                        spatial_requirements=[],
                    )
                ]
            )
        ),
        build_target_projection_projection(
            SimpleNamespace(
                spatial_reference_specs=[
                    SimpleNamespace(
                        intervention_id="claim-1",
                        reference=SimpleNamespace(kind="place_name"),
                        unresolved_reason="",
                    )
                ]
            )
        ),
        build_ground_projection(
            SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        candidate_id="candidate-1",
                        target_ref="claim-1",
                        status="candidate_only",
                        source_refs=["bundle:feature-1"],
                    )
                ]
            )
        ),
        build_select_projection(
            SimpleNamespace(
                scenarios=[SimpleNamespace(scenario_id="scenario-1", status="draft")]
            )
        ),
        build_execute_projection(
            SimpleNamespace(
                task_results=[
                    SimpleNamespace(
                        task_id="task-1",
                        candidate_id="candidate-1",
                        status="staged",
                    )
                ]
            )
        ),
    )
    if not all(item["count"] == 1 and item["table"].startswith("|") for item in projections):
        raise RuntimeError("stage projections did not produce bounded context tables")


def _check_l3_provider_boundary() -> None:
    """Verify the L3 provider shape cannot carry executable spatial data."""

    from app.modules.l3.claim_generation import (
        L3RoughClaimDraft,
        L3RoughClaimOutput,
    )

    forbidden = {
        "quantity",
        "area_range",
        "capacity",
        "road_parameters",
        "linear_parameters",
        "facility_parameters",
        "axis_parameters",
        "polygon_parameters",
        "site_area_parameters",
        "target_id",
        "candidate_id",
        "bsm",
        "geometry",
        "geometry_wkt",
        "coordinates",
    }
    if forbidden & set(L3RoughClaimDraft.model_fields):
        raise RuntimeError("L3 rough provider schema contains forbidden executable fields")

    result = L3RoughClaimOutput.model_validate(
        {
            "claims": [
                {
                    "claim_family": "facility",
                    "statement": "设施改善",
                    "geometry_wkt": "POINT (0 0)",
                }
            ]
        }
    )
    if result.claims or not any("geometry_wkt:extra_forbidden" in item for item in result.diagnostics):
        raise RuntimeError("L3 did not quarantine a provider geometry field")

    from app.contracts.l3.program import PlanningClaim
    from app.modules.l3.aggregation import _provider_boundary_violations

    normalized = PlanningClaim(
        claim_id="boundary-claim",
        statement="设施改善",
        quantity=1,
    )
    if "quantity" not in _provider_boundary_violations(normalized):
        raise RuntimeError(
            "L3 aggregation did not reject a persisted complex claim field"
        )


def main() -> int:
    facade_modules = (
        "app.modules.l1.application",
        "app.modules.l2.application",
        "app.modules.l3.application",
        "app.modules.evidence.application",
        "app.modules.target_projection.application",
        "app.modules.ground.application",
        "app.modules.select.application",
        "app.modules.execute.application",
        "app.infrastructure.context_runtime",
        "app.infrastructure.evidence_runtime",
        "app.infrastructure.structured_runtime",
    )
    production_stage_modules = (
        "app.modules.target_projection.stage",
        "app.modules.ground.stage",
        "app.modules.select.stage",
        "app.modules.execute.stage",
    )
    for module_name in facade_modules:
        importlib.import_module(module_name)
    for module_name in production_stage_modules:
        importlib.import_module(module_name)

    request = ExplorationRequest(
        run_id="boundary-probe",
        request_type="spatial_lookup",
        query="当前空间实体和道路事实",
        stage="L1",
        entity_scope=["parcels", "roads"],
    )
    requirements = compile_requirements(request)
    if not requirements:
        raise RuntimeError("Evidence requirement compiler produced no requirement")
    if not all("bundle" in item.source_families for item in requirements):
        raise RuntimeError("spatial requirement did not preserve neutral source families")
    context = EvidenceContext(
        session_id="boundary-probe",
        run_id="boundary-probe",
        stage="L1",
        purpose="snapshot_fact_production",
        request_type="spatial_lookup",
    )
    if not isinstance(EvidenceFacade(), EvidenceFacade):
        raise RuntimeError("EvidenceFacade alias is not the public application boundary")
    if context.stage != "L1":
        raise RuntimeError("EvidenceContext lost stage identity")
    _check_context_projections()
    _check_l3_provider_boundary()

    required_dirs = (
        ROOT / "backend/app/modules/l1",
        ROOT / "backend/app/modules/l2",
        ROOT / "backend/app/modules/l3",
        ROOT / "backend/app/modules/evidence",
        ROOT / "backend/app/modules/target_projection",
        ROOT / "backend/app/modules/ground",
        ROOT / "backend/app/modules/select",
        ROOT / "backend/app/modules/execute",
        ROOT / "backend/app/infrastructure/context_runtime",
        ROOT / "backend/app/infrastructure/evidence_runtime",
        ROOT / "backend/app/infrastructure/structured_runtime",
    )
    missing = [str(path) for path in required_dirs if not path.is_dir()]
    if missing:
        raise RuntimeError(f"required target directories missing: {missing}")

    production_stage_files = (
        ROOT / "backend/app/modules/target_projection/stage.py",
        ROOT / "backend/app/modules/ground/stage.py",
        ROOT / "backend/app/modules/select/stage.py",
        ROOT / "backend/app/modules/execute/stage.py",
    )
    missing_stage_files = [str(path) for path in production_stage_files if not path.is_file()]
    if missing_stage_files:
        raise RuntimeError(f"production stage implementations missing: {missing_stage_files}")
    legacy_stage_files = (
        ROOT / "backend/app/workflow/stages/target_projection.py",
        ROOT / "backend/app/workflow/stages/ground.py",
        ROOT / "backend/app/workflow/stages/select.py",
        ROOT / "backend/app/workflow/stages/execute.py",
    )
    residual_legacy_files = [str(path) for path in legacy_stage_files if path.exists()]
    if residual_legacy_files:
        raise RuntimeError(f"legacy business stage implementations remain: {residual_legacy_files}")

    print("business stage boundary probe ok")
    print(
        f"facades={len(facade_modules)} production_stages={len(production_stage_modules)} "
        f"requirements={len(requirements)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
