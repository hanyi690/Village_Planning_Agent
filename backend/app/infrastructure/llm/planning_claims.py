"""Provider-aware adapter for the non-executable L3 claims contract.

The planning workflow owns the meaning of ``PlanningClaimSet``.  This adapter
owns how a configured provider returns that contract.  MiniMax M2.x exposes
function/tool calling through its OpenAI-compatible API; it does not expose
the JSON-schema response format used by ``method='json_schema'``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from functools import lru_cache
from typing import Annotated, Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from app.core.settings import LLM_MAX_CONCURRENT, LLM_STREAM_TIMEOUT, MAX_TOKENS
from app.infrastructure.llm.structured import run_structured_output, structured_failure_code


class PlanningClaimGenerator:
    """Generate and validate one evidence-bearing claim set."""

    def __init__(self) -> None:
        self._llm: Any | None = None
        self._max_concurrent = max(
            1,
            int(os.getenv("L3_LLM_MAX_CONCURRENT", str(LLM_MAX_CONCURRENT))),
        )
        self._slots = asyncio.Semaphore(
            self._max_concurrent
        )

    def _get_llm(self) -> Any | None:
        """Return an injected adapter when tests or a controlled caller provide one."""
        return self._llm

    async def _generate_projection(
        self,
        response_model: Any,
        prompt: str,
        *,
        instruction: str,
        validation_feedback: list[str] | None = None,
    ) -> Any:
        """Run one bounded provider call for one semantic projection only."""

        await asyncio.wait_for(self._slots.acquire(), timeout=LLM_STREAM_TIMEOUT)
        try:
            report_projection = response_model.__name__ == "L3ReportOutput"
            configured_max_tokens = max(
                256,
                int(
                    os.getenv(
                        "L3_REPORT_MAX_TOKENS" if report_projection else "L3_MAX_TOKENS",
                        str(min(MAX_TOKENS, 4096) if report_projection else MAX_TOKENS),
                    )
                ),
            )
            incomplete_output_max_tokens = max(
                configured_max_tokens,
                int(
                    os.getenv(
                        "L3_INCOMPLETE_OUTPUT_MAX_TOKENS",
                        str(configured_max_tokens),
                    )
                ),
            )
            retry_count = max(0, int(os.getenv("L3_PROVIDER_PARSE_RETRIES", "0")))
            transient_retries = max(
                0, int(os.getenv("L3_TRANSIENT_RETRIES", "0"))
            )
            transient_retry_backoff_s = max(
                0.0, float(os.getenv("L3_TRANSIENT_RETRY_BACKOFF_S", "2.0"))
            )
            last_error: Exception | None = None
            for attempt in range(retry_count + 1):
                try:
                    feedback_text = ""
                    if validation_feedback:
                        feedback_text = (
                            "\nCorrect only these deterministic closed-set findings; "
                            "do not add new claims or report content:\n- "
                            + "\n- ".join(validation_feedback[:40])
                        )
                    retry_text = ""
                    if attempt > 0 and last_error is not None:
                        retry_text = (
                            "\nThe previous structured arguments were invalid. Return only "
                            "valid arguments for the declared response model:\n"
                            + str(last_error)[:6000]
                        )
                    result = await run_structured_output(
                        response_model,
                        [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": instruction + retry_text + feedback_text},
                        ],
                        # The caller owns the only semantic reask.  Do not let
                        # Instructor replay the same invalid structured request
                        # before the failure reaches the quality boundary.
                        max_retries=0,
                        timeout=float(LLM_STREAM_TIMEOUT),
                        temperature=0.1,
                        max_tokens=configured_max_tokens,
                        incomplete_output_max_tokens=incomplete_output_max_tokens,
                        llm=self._get_llm(),
                        max_concurrent=self._max_concurrent,
                        semaphore_scope="l3",
                        transient_retries=transient_retries,
                        transient_retry_backoff_s=transient_retry_backoff_s,
                    )
                    if result is None:
                        error = ValueError(
                            "L3 structured provider returned no typed projection"
                        )
                        setattr(error, "structured_failure_code", "TOOL_CALL_MISSING")
                        raise error
                    if isinstance(result, response_model):
                        return result
                    return response_model.model_validate(result)
                except Exception as exc:
                    failure_code = structured_failure_code(exc)
                    if failure_code == "TIMEOUT":
                        raise
                    if failure_code and not isinstance(exc, ValidationError):
                        error = ValueError(
                            f"L3 structured output failed: {failure_code}"
                        )
                        setattr(error, "structured_failure_code", failure_code)
                        raise error from exc
                    last_error = exc
                    if attempt >= retry_count:
                        raise
            assert last_error is not None
            raise last_error
        finally:
            self._slots.release()

    async def generate_claims(
        self,
        prompt: str,
        *,
        source_fact_ids: Sequence[str],
        spatial_source_fact_ids: Sequence[str],
        validation_feedback: list[str] | None = None,
    ) -> Any:
        """Generate only typed L3 claims; report synthesis is a later call."""

        response_model = _dynamic_claim_output_model(
            source_fact_ids,
            spatial_source_fact_ids,
        )

        return await self._generate_projection(
            response_model,
            prompt,
            instruction=(
                "Return only the complete structured claims array. Do not return "
                "report_body, Markdown, explanations, coordinates, BSM IDs or geometry."
            ),
            validation_feedback=validation_feedback,
        )

    async def generate_report(
        self,
        prompt: str,
        *,
        validation_feedback: list[str] | None = None,
    ) -> Any:
        """Synthesize only the human L3 report from already validated claims."""

        from app.domain.program.claim_draft import L3ReportOutput

        return await self._generate_projection(
            L3ReportOutput,
            prompt,
            instruction=(
                "Return only report_body as a human-readable planning report. "
                "Do not create or change claims, targets, locations, geometry, quantities "
                "or source facts; do not return a claims array."
            ),
            validation_feedback=validation_feedback,
        )


_GENERATOR: PlanningClaimGenerator | None = None
_GENERATOR_LOCK = threading.Lock()


class _L3RelationDraftBase(BaseModel):
    """Provider-facing relation proposal without runtime identities."""

    model_config = ConfigDict(extra="forbid")

    relation_template: str
    object_ref: str = ""
    object_ref_kind: str
    criticality: Literal["hard", "soft", "informational"] = "soft"
    geometry_scope: str = "pair"
    parameters: Any = None


class _L3SpatialRequirementsDraftBase(BaseModel):
    """Only semantic requirements may cross the L3 provider boundary."""

    model_config = ConfigDict(extra="forbid")

    relations: list[Any] = Field(default_factory=list)
    grounding_requirements: list[
        Literal[
            "place_binding",
            "candidate_geometry",
            "demand_points",
            "parcel_membership",
            "network_snapshot",
            "topology",
        ]
    ] = Field(default_factory=list)


def _l3_relation_subject_kind(component_kind: str) -> str:
    """Map provider component names to the target relation vocabulary."""

    normalized = str(component_kind or "").strip().lower()
    return {
        "restoration_overlay": "site_area",
        "restorationoverlay": "site_area",
        "protection_overlay": "site_area",
        "protectionoverlay": "site_area",
        "land_use_assignment": "zone",
        "landuseassignment": "zone",
    }.get(normalized, normalized)


def _l3_relation_parameter_annotation(parameter_types: Sequence[str]) -> Any:
    """Build the smallest typed parameter union for one relation template."""

    from app.contracts.planning.relation_parameters import (
        AccessParameters,
        AllowedAreaParameters,
        AvoidConstraintParameters,
        CoLocateParameters,
        ConnectParameters,
        DistanceParameters,
        EmptyRelationParameters,
        ExistingAssetParameters,
        FollowAlignmentParameters,
        MutuallyExclusiveParameters,
        PartOfParameters,
        PrecedesParameters,
        ServiceParameters,
    )

    parameter_models = {
        "access": AccessParameters,
        "allowed_area": AllowedAreaParameters,
        "avoid_constraint": AvoidConstraintParameters,
        "co_locate": CoLocateParameters,
        "connect": ConnectParameters,
        "distance": DistanceParameters,
        "empty": EmptyRelationParameters,
        "existing_asset": ExistingAssetParameters,
        "alignment": FollowAlignmentParameters,
        "mutually_exclusive": MutuallyExclusiveParameters,
        "part_of": PartOfParameters,
        "precedes": PrecedesParameters,
        "service": ServiceParameters,
    }
    models = [
        parameter_models[item]
        for item in sorted(set(parameter_types))
        if item in parameter_models
    ]
    if not models:
        return None
    parameter_union = models[0]
    for model in models[1:]:
        parameter_union = parameter_union | model
    if len(models) > 1:
        parameter_union = Annotated[
            parameter_union,
            Field(discriminator="parameter_type"),
        ]
    return parameter_union | None


def _dynamic_spatial_requirements_model(subject_kind: str) -> type[Any]:
    return _cached_dynamic_spatial_requirements_model(
        _l3_relation_subject_kind(subject_kind)
    )


@lru_cache(maxsize=16)
def _cached_dynamic_spatial_requirements_model(
    normalized_subject_kind: str,
) -> type[Any]:
    """Build relation choices from the current subject's closed catalogue."""

    from app.domain.program.target_projection.relation_catalog import (
        relation_options,
        relation_spec,
    )

    relation_models: list[type[Any]] = []
    for candidate in relation_options(normalized_subject_kind):
        spec = relation_spec(candidate.template)
        if spec is None:
            continue
        # TARGET IDs are created only after claims are accepted.  L3 cannot
        # select one without a current closed endpoint catalogue, so target
        # endpoints are intentionally deferred to GROUND/compilation.
        object_ref_kinds = tuple(sorted(spec.object_ref_kinds - {"target"}))
        if not object_ref_kinds:
            continue
        parameter_annotation = _l3_relation_parameter_annotation(
            spec.parameter_types
        )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "template": candidate.template,
                    "object_ref_kinds": object_ref_kinds,
                    "parameter_types": sorted(spec.parameter_types),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        relation_models.append(
            create_model(
                f"L3Relation_{candidate.template}_{digest}",
                __base__=_L3RelationDraftBase,
                relation_template=(Literal[candidate.template], ...),
                object_ref_kind=(Literal.__getitem__(object_ref_kinds), ...),
                criticality=(
                    Literal["hard", "soft", "informational"],
                    spec.default_criticality,
                ),
                geometry_scope=(Literal[spec.geometry_scope], spec.geometry_scope),
                parameters=(parameter_annotation, None),
            )
        )

    if relation_models:
        relation_union = relation_models[0]
        for model in relation_models[1:]:
            relation_union = relation_union | model
        relation_type: Any = Annotated[
            relation_union,
            Field(discriminator="relation_template"),
        ]
    else:
        relation_type = Literal[None]
    digest = hashlib.sha256(
        (
            normalized_subject_kind
            + "\n"
            + "\n".join(model.__name__ for model in relation_models)
        ).encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    return create_model(
        f"L3SpatialRequirements_{digest}",
        __base__=_L3SpatialRequirementsDraftBase,
        relations=(list[relation_type], Field(default_factory=list)),
    )


def _dynamic_claim_output_model(
    source_fact_ids: Sequence[str],
    spatial_source_fact_ids: Sequence[str],
) -> type[Any]:
    """Build the L3 claim schema from this invocation's current fact catalog."""

    from app.domain.program.claim_draft import (
        AxisComponentDraft,
        FacilityComponentDraft,
        LandUseAssignmentComponentDraft,
        LinearComponentDraft,
        L3ClaimOutput,
        NonSpatialActionComponentDraft,
        ProtectionOverlayComponentDraft,
        PolygonPlanningParametersDraft,
        RestorationOverlayComponentDraft,
        RoadComponentDraft,
        SiteAreaComponentDraft,
        ZoneComponentDraft,
    )

    all_ids = tuple(sorted(dict.fromkeys(str(item).strip() for item in source_fact_ids if str(item).strip())))
    spatial_ids = tuple(
        sorted(
            set(str(item).strip() for item in spatial_source_fact_ids if str(item).strip())
            & set(all_ids)
        )
    )
    def component_model(base: type[Any], allowed_ids: Sequence[str]) -> type[Any]:
        values = tuple(allowed_ids)
        fact_id_type = (
            Literal.__getitem__(values)
            if values
            else Literal[None]
        )
        digest = hashlib.sha256(
            (base.__name__ + "\n" + "\n".join(values)).encode("utf-8")
        ).hexdigest()[:12]
        fields: dict[str, Any] = {
            "source_fact_refs": (
                list[fact_id_type],
                Field(default_factory=list, max_length=0) if not values
                else Field(default_factory=list),
            ),
        }
        if base.__name__ == "NonSpatialActionComponentDraft":
            fields["spatial_requirements"] = (type(None), None)
        else:
            spatial_requirements_model = _dynamic_spatial_requirements_model(
                base.__name__.removesuffix("ComponentDraft")
            )
            fields["spatial_requirements"] = (
                spatial_requirements_model | None,
                None,
            )
        fixed_polygon_roles = {
            "RestorationOverlayComponentDraft": "restoration_overlay",
            "ProtectionOverlayComponentDraft": "protection_overlay",
            "LandUseAssignmentComponentDraft": "land_use_assignment",
        }
        fixed_polygon_role = fixed_polygon_roles.get(base.__name__)
        if fixed_polygon_role:
            polygon_model = create_model(
                f"L3PolygonParameters_{fixed_polygon_role}",
                __base__=PolygonPlanningParametersDraft,
                materialization_role=(Literal[fixed_polygon_role], fixed_polygon_role),
            )
            fields["polygon_parameters"] = (polygon_model | None, None)
        return create_model(f"{base.__name__}_{digest}", __base__=base, **fields)

    spatial_bases = (
        FacilityComponentDraft,
        RoadComponentDraft,
        LinearComponentDraft,
        AxisComponentDraft,
        RestorationOverlayComponentDraft,
        ProtectionOverlayComponentDraft,
        ZoneComponentDraft,
        LandUseAssignmentComponentDraft,
        SiteAreaComponentDraft,
    )
    component_models = [
        component_model(base, spatial_ids) for base in spatial_bases
    ]
    component_models.append(
        component_model(NonSpatialActionComponentDraft, all_ids)
    )
    component_union = component_models[0]
    for item in component_models[1:]:
        component_union = component_union | item
    discriminated_union = Annotated[
        component_union,
        Field(discriminator="component_kind"),
    ]
    digest = hashlib.sha256(
        json.dumps(
            {"all": all_ids, "spatial": spatial_ids},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return create_model(
        f"L3ClaimOutput_{digest}",
        __base__=L3ClaimOutput,
        claims=(list[discriminated_union], Field(default_factory=list)),
    )


def get_planning_claim_generator() -> PlanningClaimGenerator:
    global _GENERATOR
    if _GENERATOR is None:
        with _GENERATOR_LOCK:
            if _GENERATOR is None:
                _GENERATOR = PlanningClaimGenerator()
    return _GENERATOR


__all__ = ["PlanningClaimGenerator", "get_planning_claim_generator"]
