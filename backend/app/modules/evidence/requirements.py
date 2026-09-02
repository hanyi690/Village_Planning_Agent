"""Compile stable evidence requirements from the current request boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.contracts.evidence.requirement_contracts import EvidenceRequirement


def _normalized_values(request: ExplorationRequest) -> list[str]:
    values = [*request.required_facts, *request.questions, *request.evidence_gaps_to_resolve]
    if not values:
        values = [request.query]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value or "").split())
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _requirement_kind(request: ExplorationRequest, statement: str) -> str:
    text = f"{request.request_type} {statement}".casefold()
    if request.request_type == "spatial_lookup":
        return "spatial"
    if any(token in text for token in ("bsm", "编码", "身份", "feature", "entity")):
        return "identity"
    if any(token in text for token in ("覆盖", "容量", "距离", "成本", "cost", "metric")):
        return "metric"
    return "claim"


def _requirement_id(request: ExplorationRequest, index: int, statement: str) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "index": index,
        "statement": statement,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"evidence-req-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _policy_for_requirement(
    *,
    kind: str,
    evidence_role: str,
    statement: str,
) -> str:
    """Map requirement semantics to a closed, versioned policy."""

    text = f"{evidence_role} {statement}".casefold()
    if "execution_geometry" in text or "执行几何" in text:
        return "execution_geometry_support.v1"
    if "legal" in text or "法定" in text or kind == "constraint":
        return "legal_extent_support.v1"
    if "relation" in text or "关系" in text or kind == "relation":
        return "relation_support.v1"
    if kind == "spatial" or "location_binding" in text or "定位" in text:
        return "location_identity_support.v1"
    if kind == "identity":
        if "road" in text or "道路" in text:
            return "road_identity.v1"
        return "facility_existence.v1"
    return "source_semantic_support.v1"


def _request_revision(request: ExplorationRequest) -> str:
    raw = json.dumps(
        request.model_dump(mode="json", exclude={"requirements"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compile_requirements(request: ExplorationRequest) -> tuple[EvidenceRequirement, ...]:
    """Compile the request into semantic requirements.

    Source selection belongs to the evidence runtime.  This module only
    preserves producer-declared families and supplies neutral defaults when a
    request has not declared them.
    """

    if request.requirements:
        return _canonical_requirements(request.requirements)

    declared_families = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in getattr(request, "source_families", ())
            if str(item).strip()
        )
    )
    if declared_families:
        families = declared_families
    elif request.request_type == "spatial_lookup":
        families = ("data", "kg")
    else:
        families = ("report", "rag", "external")
    scope = tuple(dict.fromkeys(str(item).strip() for item in request.entity_scope if str(item).strip()))
    return tuple(
        EvidenceRequirement(
            requirement_id=_requirement_id(request, index, statement),
            requirement_ref=_requirement_id(request, index, statement),
            request_id=request.run_id,
            requesting_artifact_ref=request.run_id,
            requesting_artifact_revision=_request_revision(request),
            producer_stage=request.stage or "EXPLORE",
            statement=statement,
            kind=(kind := _requirement_kind(request, statement)),
            source_families=families,
            scope=scope,
            spatial_granularity="feature" if kind == "spatial" else "document",
            allowed_inference="exact" if kind == "spatial" else "text_only",
            evidence_role=("spatial_fact" if kind == "spatial" else "planning_background"),
            purpose=request.query_purpose or request.request_type,
            policy_ref=_policy_for_requirement(
                kind=kind,
                evidence_role=("spatial_fact" if kind == "spatial" else "planning_background"),
                statement=statement,
            ),
            success_condition="source-backed claim with locator and bounded coverage",
            metadata={
                "request_type": request.request_type,
                "stage": request.stage,
                "dimension_key": request.dimension_key,
            },
        )
        for index, statement in enumerate(_normalized_values(request))
    )


def _canonical_requirements(
    requirements: Iterable[EvidenceRequirement],
) -> tuple[EvidenceRequirement, ...]:
    """Deduplicate producer-owned requirements without changing their IDs."""

    by_id: dict[str, EvidenceRequirement] = {}
    for requirement in requirements:
        current = requirement
        if current.requirement_id not in by_id:
            by_id[current.requirement_id] = current
    return tuple(by_id[key] for key in sorted(by_id))


def _artifact_identity(artifact: Any, *, stage: str) -> tuple[str, str]:
    artifact_ref = str(
        getattr(artifact, "artifact_id", "")
        or getattr(artifact, "artifact_ref", "")
        or getattr(artifact, "program_ref", "")
        or ""
    ).strip()
    revision = str(
        getattr(artifact, "context_fingerprint", "")
        or getattr(artifact, "context_version", "")
        or getattr(artifact, "schema_version", "")
        or ""
    ).strip()
    return artifact_ref or f"{stage.lower()}-unpersisted", revision


def _artifact_requirement(
    *,
    stage: str,
    artifact: Any,
    index: int,
    statement: str,
    kind: str = "claim",
    required: bool = True,
    source_families: Iterable[str] = (),
    scope: Iterable[str] = (),
    spatial_granularity: str = "none",
    allowed_inference: str = "exact",
    evidence_role: str = "planning_background",
    purpose: str = "",
    policy_ref: str = "",
    success_condition: str = "",
    source_artifact_refs: Iterable[str] = (),
    metadata: dict[str, Any] | None = None,
) -> EvidenceRequirement:
    artifact_ref, revision = _artifact_identity(artifact, stage=stage)
    normalized_statement = " ".join(str(statement or "").split())
    payload = {
        "stage": stage,
        "artifact_ref": artifact_ref,
        "revision": revision,
        "index": index,
        "statement": normalized_statement,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    requirement_id = f"evidence-req-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"
    return EvidenceRequirement(
        requirement_id=requirement_id,
        requirement_ref=requirement_id,
        request_id=str(getattr(artifact, "artifact_id", "") or ""),
        requesting_artifact_ref=artifact_ref,
        requesting_artifact_revision=revision,
        producer_stage=stage,
        statement=normalized_statement,
        kind=kind,
        required=required,
        source_families=tuple(dict.fromkeys(str(item).strip() for item in source_families if str(item).strip())),
        scope=tuple(dict.fromkeys(str(item).strip() for item in scope if str(item).strip())),
        spatial_granularity=spatial_granularity,
        allowed_inference=allowed_inference,
        evidence_role=evidence_role,
        purpose=purpose or evidence_role,
        policy_ref=policy_ref or _policy_for_requirement(
            kind=kind,
            evidence_role=evidence_role,
            statement=normalized_statement,
        ),
        success_condition=success_condition,
        source_artifact_refs=tuple(dict.fromkeys(str(item).strip() for item in source_artifact_refs if str(item).strip())),
        metadata=metadata or {},
    )


def _kind_for_statement(statement: str, *, spatial: bool = False) -> str:
    text = str(statement or "").casefold()
    if spatial or any(token in text for token in ("地点", "位置", "地块", "空间", "geometry", "bsm")):
        return "spatial"
    if any(token in text for token in ("身份", "实体", "feature", "entity", "编码")):
        return "identity"
    if any(token in text for token in ("数量", "容量", "距离", "面积", "成本", "metric")):
        return "metric"
    return "claim"


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json", exclude_none=True)
        except TypeError:
            dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _nonempty_strings(values: Any) -> tuple[str, ...]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        return ()
    return tuple(dict.fromkeys(
        str(value).strip() for value in values if str(value).strip()
    ))


def _value_from_parameters(parameters: Any, key: str) -> str:
    mapping = _as_mapping(parameters)
    return str(mapping.get(key) or getattr(parameters, key, "") or "").strip()


def _append_structured_requirement(
    output: list[EvidenceRequirement],
    seen: set[tuple[str, str, tuple[str, ...]]],
    *,
    stage: str = "L3",
    artifact: Any,
    statement: str,
    kind: str,
    source_families: tuple[str, ...],
    scope: tuple[str, ...] = (),
    spatial_granularity: str = "feature",
    evidence_role: str,
    success_condition: str,
    source_artifact_refs: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> None:
    normalized = " ".join(str(statement or "").split())
    normalized_scope = tuple(dict.fromkeys(item for item in scope if item))
    key = (evidence_role, normalized, normalized_scope)
    if not normalized or key in seen:
        return
    seen.add(key)
    output.append(
        _artifact_requirement(
            stage=stage,
            artifact=artifact,
            index=len(output),
            statement=normalized,
            kind=kind,
            required=True,
            source_families=source_families,
            scope=normalized_scope,
            spatial_granularity=spatial_granularity,
            allowed_inference="exact",
            evidence_role=evidence_role,
            success_condition=success_condition,
            source_artifact_refs=source_artifact_refs,
            metadata=metadata,
        )
    )


def _append_spatial_requirement_inputs(
    output: list[EvidenceRequirement],
    seen: set[tuple[str, str, tuple[str, ...]]],
    *,
    stage: str = "L3",
    artifact: Any,
    target_id: str,
    requirements: Any,
    relation_context: str = "",
    metadata_context: dict[str, Any] | None = None,
    scope_context: tuple[str, ...] = (),
) -> None:
    spatial = _as_mapping(requirements)
    if not spatial:
        return
    target_scope = tuple(dict.fromkeys(
        item for item in ((target_id,) if target_id else ()) + scope_context if item
    ))
    metadata_context = metadata_context or {}
    source_ref_values = _nonempty_strings(spatial.get("required_input_refs"))
    for ref in source_ref_values:
        _append_structured_requirement(
            output,
            seen,
            stage=stage,
            artifact=artifact,
            statement=f"Resolve required planning input {ref} for {target_id or 'target'}",
            kind="source",
            source_families=("artifact", "data", "kg"),
            scope=(*target_scope, ref),
            spatial_granularity="feature",
            evidence_role="l3_required_input",
            success_condition="required input is source-bound and available in the current snapshot",
            source_artifact_refs=(ref,),
            metadata={**metadata_context, "target_id": target_id, "input_ref": ref},
        )

    ref_fields = (
        ("shared_resource_refs", "shared_resource", "Resolve shared parcel/resource"),
        ("parcel_membership_refs", "parcel_membership", "Resolve parcel membership"),
        ("competing_parcel_refs", "parcel_membership", "Resolve competing parcel"),
        ("network_refs", "network_snapshot", "Resolve network snapshot"),
    )
    for field, role, prefix in ref_fields:
        for ref in _nonempty_strings(spatial.get(field)):
            _append_structured_requirement(
                output,
                seen,
                stage=stage,
                artifact=artifact,
                statement=f"{prefix} {ref} for {target_id or 'target'}",
                kind="spatial",
                source_families=("data", "artifact", "kg"),
                scope=(*target_scope, ref),
                spatial_granularity="feature" if role != "network_snapshot" else "network",
                evidence_role=f"l3_{role}",
                success_condition=(
                    "source-backed parcel resource and eligible geometry are bound"
                    if role in {"shared_resource", "parcel_membership"}
                    else "canonical network snapshot is available and fingerprinted"
                ),
                source_artifact_refs=(ref,),
                metadata={
                    **metadata_context,
                    "target_id": target_id,
                    "ref": ref,
                    "relation": relation_context,
                },
            )

    for grounding in _nonempty_strings(spatial.get("grounding_requirements")):
        role_map = {
            "place_binding": ("spatial", "l3_place_binding", "Resolve authoritative place identity and geometry"),
            "candidate_geometry": ("spatial", "l3_candidate_geometry", "Resolve candidate geometry"),
            "demand_points": ("metric", "l3_demand_points", "Resolve explicit demand points and units"),
            "parcel_membership": ("spatial", "l3_parcel_membership", "Resolve source parcel membership and capacity"),
            "network_snapshot": ("spatial", "l3_network_snapshot", "Resolve network graph snapshot"),
            "topology": ("spatial", "l3_topology", "Resolve declared topology and adjacency evidence"),
        }
        kind, role, prefix = role_map.get(
            grounding,
            ("claim", "l3_grounding_input", "Resolve typed grounding input"),
        )
        _append_structured_requirement(
            output,
            seen,
            stage=stage,
            artifact=artifact,
            statement=f"{prefix} for {target_id or 'target'}",
            kind=kind,
            source_families=("data", "artifact", "kg", "report"),
            scope=target_scope,
            spatial_granularity="feature" if grounding != "network_snapshot" else "network",
            evidence_role=role,
            success_condition="typed grounding input is available or explicitly routed to HUMAN",
            source_artifact_refs=source_ref_values,
            metadata={
                **metadata_context,
                "target_id": target_id,
                "grounding_requirement": grounding,
            },
        )

    for relation in spatial.get("relations", []) or []:
        relation_map = _as_mapping(relation)
        template = str(relation_map.get("relation_template") or "").strip()
        relation_id = str(relation_map.get("relation_id") or "").strip()
        relation_label = relation_id or template or "relation"
        params = relation_map.get("parameters")
        network_ref = _value_from_parameters(params, "network_ref")
        demand_ref = _value_from_parameters(params, "demand_ref")
        relation_scope = tuple(dict.fromkeys(
            item for item in (
                *target_scope,
                str(relation_map.get("subject_ref") or "").strip(),
                str(relation_map.get("object_ref") or "").strip(),
            ) if item
        ))
        if network_ref:
            _append_structured_requirement(
                output,
                seen,
                stage=stage,
                artifact=artifact,
                statement=f"Resolve network snapshot {network_ref} for relation {relation_label}",
                kind="spatial",
                 source_families=("data", "artifact", "kg"),
                scope=(*relation_scope, network_ref),
                spatial_granularity="network",
                evidence_role="l3_relation_network",
                success_condition="network snapshot and required endpoint/route inputs are bound",
                source_artifact_refs=(network_ref,),
                metadata={
                    **metadata_context,
                    "target_id": target_id,
                    "relation_id": relation_id,
                    "template": template,
                },
            )
        if demand_ref:
            _append_structured_requirement(
                output,
                seen,
                stage=stage,
                artifact=artifact,
                statement=f"Resolve explicit demand snapshot {demand_ref} for relation {relation_label}",
                kind="metric",
                 source_families=("data", "artifact"),
                scope=(*relation_scope, demand_ref),
                spatial_granularity="feature",
                evidence_role="l3_relation_demand",
                success_condition="demand points have identity, value, unit and source geometry",
                source_artifact_refs=(demand_ref,),
                metadata={
                    **metadata_context,
                    "target_id": target_id,
                    "relation_id": relation_id,
                    "template": template,
                },
            )
        if template in {"part_of", "co_locate", "mutually_exclusive"}:
            _append_structured_requirement(
                output,
                seen,
                stage=stage,
                artifact=artifact,
                statement=f"Resolve topology evidence for relation {relation_label}",
                kind="spatial",
                 source_families=("kg", "data", "artifact"),
                scope=relation_scope,
                spatial_granularity="feature",
                evidence_role="l3_relation_topology",
                success_condition="declared topology relation has source evidence and evaluable members",
                source_artifact_refs=_nonempty_strings(relation_map.get("evidence_refs")),
                metadata={
                    **metadata_context,
                    "target_id": target_id,
                    "relation_id": relation_id,
                    "template": template,
                },
            )
        if (
            template in {"connect_network", "provide_access", "serve", "near"}
            and not network_ref
            and template != "near"
        ):
            _append_structured_requirement(
                output,
                seen,
                stage=stage,
                artifact=artifact,
                statement=f"Resolve missing network input for relation {relation_label}",
                kind="spatial",
                 source_families=("artifact", "data", "kg"),
                scope=relation_scope,
                spatial_granularity="network",
                evidence_role="l3_relation_network_missing",
                success_condition="network reference and typed endpoint/service parameters are supplied or routed to HUMAN",
                source_artifact_refs=_nonempty_strings(relation_map.get("evidence_refs")),
                metadata={
                    **metadata_context,
                    "target_id": target_id,
                    "relation_id": relation_id,
                    "template": template,
                },
            )


def _gap_text(gap: Any) -> str:
    return str(
        getattr(gap, "required_fact", "")
        or getattr(gap, "description", "")
        or getattr(gap, "message", "")
        or ""
    ).strip()


def _location_scope_rows(location: Any) -> list[tuple[str, str, str]]:
    return sorted({
        (
            str(
                getattr(scope, "normalized_name", "")
                or getattr(scope, "name", "")
                or ""
            ).strip(),
            str(getattr(scope, "role", "") or "").strip(),
            str(
                getattr(scope, "relation_to_target", "") or ""
            ).strip(),
        )
        for scope in (getattr(location, "scopes", None) or ())
        if str(
            getattr(scope, "normalized_name", "")
            or getattr(scope, "name", "")
            or ""
        ).strip()
    })


def l1_location_work_item_key(location: Any) -> str:
    """Stable identity-retrieval key independent of dimension/source rows."""

    existing = str(getattr(location, "work_item_ref", "") or "").strip()
    if existing.startswith("l1-location-work-item:"):
        return existing
    mention = str(
        getattr(location, "normalized_name", "")
        or getattr(location, "mention", "")
        or ""
    ).strip()
    role = str(getattr(location, "role", "") or "").strip()
    work_material = json.dumps(
        {
            "mention": "".join(mention.casefold().split()),
            "role": role.casefold(),
            "scopes": _location_scope_rows(location),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "l1-location-work-item:"
        + hashlib.sha256(work_material.encode("utf-8")).hexdigest()[:20]
    )


def requirements_from_l1(snapshot: Any) -> tuple[EvidenceRequirement, ...]:
    """Produce requirements for unresolved L1 observations and evidence gaps."""

    output: list[EvidenceRequirement] = []
    for index, gap in enumerate(getattr(snapshot, "evidence_gaps", None) or []):
        if (
            str(getattr(gap, "subject_ref", "") or "").startswith(
                "l1-location-work-item:"
            )
            and str(getattr(gap, "requirement_id", "") or "")
            and str(getattr(gap, "outcome_status", "") or "") != "open"
        ):
            # This is the persisted outcome of the location work item's own
            # identity requirement.  Regenerate that one identity request
            # below; do not create a second generic gap request for it.
            continue
        statement = _gap_text(gap)
        if not statement:
            continue
        dimension = str(getattr(gap, "dimension", "") or "").strip()
        is_spatial_gap = dimension.casefold() in {"spatial", "location", "gis"}
        gap_kind = _kind_for_statement(statement, spatial=is_spatial_gap)
        output.append(
            _artifact_requirement(
                stage="L1",
                artifact=snapshot,
                index=index,
                statement=statement,
                kind=gap_kind,
                source_families=(
                    "report",
                    "artifact",
                    "kg",
                    "data",
                    "gis",
                    *(("external_map_cache",) if is_spatial_gap else ()),
                ),
                scope=(dimension,),
                spatial_granularity="feature" if is_spatial_gap else "document",
                allowed_inference="exact",
                evidence_role="l1_gap",
                success_condition="source-backed claim with locator and snapshot context",
                source_artifact_refs=(str(getattr(gap, "gap_id", "") or ""),),
                metadata={
                    "gap_id": str(getattr(gap, "gap_id", "") or ""),
                    "recovery_generation": int(
                        getattr(gap, "recovery_generation", 0) or 0
                    ),
                },
            )
        )
    # The same observed place commonly appears in several L1 dimensions.
    # Retrieve one Evidence candidate set per semantic work item, then let the
    # L1 aggregate attach the immutable receipt to every source mention.  The
    # key includes role and source-declared scopes so same-name places in
    # different areas are never collapsed merely to save requests.
    location_groups: dict[str, dict[str, Any]] = {}
    for location_index, location in enumerate(
        getattr(snapshot, "location_mentions", None) or [],
    ):
        # A report/source reference proves where the mention was observed; it
        # does not prove that the named object has been spatially resolved.
        # Only a resolved LocationMention can leave the GROUND identity queue.
        if str(getattr(location, "resolution_state", "") or "") == "resolved":
            continue
        mention = str(getattr(location, "normalized_name", "") or getattr(location, "mention", "") or "").strip()
        if not mention:
            continue
        role = str(getattr(location, "role", "") or "").strip()
        scope_rows = _location_scope_rows(location)
        work_key = l1_location_work_item_key(location)
        group = location_groups.setdefault(work_key, {
            "mention": mention,
            "role": role,
            "scope_rows": scope_rows,
            "indexes": [],
            "dimension_keys": [],
            "source_report_refs": [],
        })
        group["indexes"].append(location_index)
        dimension_key = str(
            getattr(location, "dimension_key", "") or ""
        ).strip()
        source_report_ref = str(
            getattr(location, "source_report_ref", "") or ""
        ).strip()
        if dimension_key:
            group["dimension_keys"].append(dimension_key)
        if source_report_ref:
            group["source_report_refs"].append(source_report_ref)

    location_requirement_offset = len(output)
    for group_index, work_key in enumerate(sorted(location_groups)):
        group = location_groups[work_key]
        mention = str(group["mention"])
        scope_names = [str(row[0]) for row in group["scope_rows"]]
        output.append(
            _artifact_requirement(
                stage="L1",
                artifact=snapshot,
                index=location_requirement_offset + group_index,
                statement=f"Retrieve bounded identity candidates for {mention}",
                kind="identity",
                source_families=(
                    "data",
                    "gis",
                    "kg",
                    "artifact",
                    "external_map_cache",
                ),
                scope=(mention, *scope_names),
                spatial_granularity="feature",
                evidence_role="l1_location_identity",
                success_condition=(
                    "one bounded local DATA/KG candidate is supported by exact "
                    "provenance; final entity and representation remain for GROUND"
                ),
                source_artifact_refs=tuple(dict.fromkeys(
                    group["source_report_refs"]
                )),
                metadata={
                    "mention": mention,
                    "normalized_name": mention,
                    "role": group["role"],
                    "location_work_item_key": work_key,
                    "location_mention_indexes": group["indexes"],
                    "dimension_keys": list(dict.fromkeys(
                        group["dimension_keys"]
                    )),
                    "source_report_refs": list(dict.fromkeys(
                        group["source_report_refs"]
                    )),
                    "scope_names": scope_names,
                    "selection_cardinality": "one",
                    "external_geometry_authority": "advisory_only",
                },
            )
        )
    return _canonical_requirements(output)


def requirements_from_l2(strategy: Any) -> tuple[EvidenceRequirement, ...]:
    """Produce requirements for L2 goals without source-backed justification."""

    output: list[EvidenceRequirement] = []
    gaps = list(getattr(strategy, "evidence_gaps", None) or [])
    for index, gap in enumerate(gaps):
        statement = _gap_text(gap)
        if not statement:
            continue
        output.append(
            _artifact_requirement(
                stage="L2",
                artifact=strategy,
                index=index,
                statement=statement,
                kind=_kind_for_statement(statement),
                source_families=("report", "artifact", "external"),
                scope=(str(getattr(gap, "dimension", "") or ""),),
                evidence_role="l2_gap",
                success_condition="strategy premise has source-backed support or explicit downgrade",
                source_artifact_refs=(str(getattr(gap, "gap_id", "") or ""),),
                metadata={"gap_id": str(getattr(gap, "gap_id", "") or "")},
            )
        )
    for offset, goal in enumerate(getattr(strategy, "development_goals", None) or [], start=len(output)):
        statement = str(goal or "").strip()
        if not statement:
            continue
        output.append(
            _artifact_requirement(
                stage="L2",
                artifact=strategy,
                index=offset,
                statement=statement,
                required=not bool(getattr(strategy, "evidence_refs", None)),
                source_families=("report", "artifact", "external"),
                evidence_role="l2_goal",
                success_condition="goal rationale is traceable to L1 or external evidence",
                source_artifact_refs=getattr(strategy, "evidence_refs", None) or (),
            )
        )
    return _canonical_requirements(output)


def requirements_from_l3(program: Any) -> tuple[EvidenceRequirement, ...]:
    """Produce requirements for L3 claims and typed intervention premises."""

    from app.modules.l3.claim_adapter import admission_reasons_for_intervention
    from app.contracts.workflow.recovery_pointer import RecoveryPointer

    output: list[EvidenceRequirement] = []
    admitted_claim_ids = {
        str(claim_id)
        for intervention in getattr(program, "interventions", None) or []
        if not admission_reasons_for_intervention(
            intervention,
            list(getattr(program, "claims", None) or []),
        )
        for claim_id in getattr(intervention, "claim_refs", None) or []
    }
    pending_claim_ids = {
        str(getattr(claim, "claim_id", "") or "")
        for claim in getattr(program, "pending_grounding_claims", None) or []
    }
    missing_by_claim_id = {
        str(getattr(item, "claim_id", "") or ""): tuple(
            _nonempty_strings(getattr(item, "missing_requirements", None))
        )
        for item in getattr(program, "claim_dispositions", None) or []
        if str(getattr(item, "status", "") or "") == "pending_grounding"
    }
    for index, claim in enumerate(getattr(program, "claims", None) or []):
        statement = str(getattr(claim, "statement", "") or "").strip()
        if not statement:
            continue
        claim_id = str(getattr(claim, "claim_id", "") or "")
        pending = claim_id in pending_claim_ids
        spatial = claim_id in admitted_claim_ids or pending
        missing_requirements = missing_by_claim_id.get(claim_id, ())
        metadata = {"claim_id": claim_id}
        if pending:
            source_input_refs = tuple(_nonempty_strings((
                getattr(program, "l1_snapshot_ref", ""),
                *list(getattr(claim, "source_fact_refs", None) or []),
                *list(getattr(claim, "source_refs", None) or []),
                *list(getattr(claim, "location_hints", None) or []),
            )))
            recovery = RecoveryPointer(
                item_id=claim_id,
                item_kind="claim",
                source_stage="l3",
                return_stage="l3",
                source_artifact_key="planning_program",
                source_artifact_ref=str(getattr(program, "artifact_id", "") or ""),
                source_input_refs=list(source_input_refs),
                missing_requirements=list(missing_requirements),
                expected_artifact_key="planning_program",
                reason_code="pending_grounding_claim",
            )
            metadata.update(
                {
                    "pending_grounding": True,
                    "missing_requirements": list(missing_requirements),
                    "source_input_refs": list(source_input_refs),
                    "return_stage": "l3",
                    "expected_artifact_key": "planning_program",
                    "recovery": recovery.model_dump(mode="json"),
                }
            )
        output.append(
            _artifact_requirement(
                stage="L3",
                artifact=program,
                index=index,
                statement=statement,
                kind=_kind_for_statement(statement, spatial=spatial),
                required=True,
                source_families=("artifact", "report", "data", "kg") if spatial else ("artifact", "report"),
                scope=getattr(claim, "location_hints", None) or (),
                spatial_granularity="feature" if spatial else "document",
                allowed_inference="exact" if spatial else "text_only",
                evidence_role="l3_claim",
                success_condition="claim references authoritative source facts before target projection",
                source_artifact_refs=(
                    *list(getattr(claim, "source_fact_refs", None) or []),
                    *list(getattr(claim, "source_refs", None) or []),
                ),
                metadata=metadata,
            )
        )
        if not pending:
            continue
        spatial_inputs = _as_mapping(getattr(claim, "spatial_requirements", None))
        grounding = list(_nonempty_strings(spatial_inputs.get("grounding_requirements")))
        for requirement in ("place_binding", "candidate_geometry"):
            if requirement not in grounding:
                grounding.append(requirement)
        output_kind = str(getattr(claim, "suggested_output_kind", "") or "")
        category = str(getattr(claim, "suggested_category", "") or "")
        if output_kind in {"parcel", "polygon"} and "parcel_membership" not in grounding:
            grounding.append("parcel_membership")
        if (output_kind == "line" or category in {"road", "axis"}) and "network_snapshot" not in grounding:
            grounding.append("network_snapshot")
        relations = spatial_inputs.get("relations", []) or []
        if any(
            str(_as_mapping(relation).get("relation_template") or "")
            in {"part_of", "co_locate", "mutually_exclusive"}
            for relation in relations
        ) and "topology" not in grounding:
            grounding.append("topology")
        spatial_inputs["grounding_requirements"] = grounding
        _append_spatial_requirement_inputs(
            output,
            seen={(item.evidence_role, item.statement, tuple(item.scope)) for item in output},
            artifact=program,
            target_id=claim_id,
            requirements=spatial_inputs,
            relation_context="pending_grounding_claim",
            metadata_context={
                **metadata,
                "place_hints": list(_nonempty_strings(getattr(claim, "location_hints", None))),
                "relation_context": "pending_grounding_claim",
            },
            scope_context=_nonempty_strings(getattr(claim, "location_hints", None)),
        )
        source_metadata = {**metadata, "requirement_scope": "source_lineage"}
        if "project_package_ref" in missing_requirements:
            _append_structured_requirement(
                output,
                {(item.evidence_role, item.statement, tuple(item.scope)) for item in output},
                artifact=program,
                statement=f"Resolve project package identity for {claim_id}",
                kind="source",
                source_families=("artifact", "report", "data", "kg"),
                scope=(claim_id,),
                evidence_role="l3_pending_package_identity",
                success_condition="project package identity is source-bound before intervention admission",
                metadata={**source_metadata, "missing_requirement": "project_package_ref"},
            )
        if "evidence_or_source_lineage" in missing_requirements:
            _append_structured_requirement(
                output,
                {(item.evidence_role, item.statement, tuple(item.scope)) for item in output},
                artifact=program,
                statement=f"Resolve evidence and source lineage for {claim_id}",
                kind="source",
                source_families=("artifact", "report", "data", "kg"),
                scope=(claim_id,),
                evidence_role="l3_pending_source_lineage",
                success_condition="claim evidence is source-bound before intervention admission",
                metadata={**source_metadata, "missing_requirement": "evidence_or_source_lineage"},
            )
    # The authoritative spatial inputs are copied onto admitted interventions
    # by claim_adapter.  Compile them into source-routed requirements here so
    # RETRIEVE can resolve network, demand, parcel and topology inputs before
    # TARGET/GROUND.  Do not infer these requirements from claim prose.
    for intervention in getattr(program, "interventions", None) or []:
        target_id = str(
            getattr(intervention, "target_id", "")
            or getattr(intervention, "intervention_id", "")
            or ""
        ).strip()
        _append_spatial_requirement_inputs(
            output,
            seen={(item.evidence_role, item.statement, tuple(item.scope)) for item in output},
            artifact=program,
            target_id=target_id,
            requirements=getattr(intervention, "spatial_requirements", None),
            relation_context="l3_intervention",
        )
    for offset, gap in enumerate(getattr(program, "evidence_gaps", None) or [], start=len(output)):
        statement = _gap_text(gap)
        if statement:
            output.append(
                _artifact_requirement(
                    stage="L3",
                    artifact=program,
                    index=offset,
                    statement=statement,
                    kind=_kind_for_statement(statement),
                    source_families=("artifact", "report", "data", "kg"),
                    evidence_role="l3_gap",
                    success_condition="gap is resolved or explicitly routed to HUMAN",
                    source_artifact_refs=(str(getattr(gap, "gap_id", "") or ""),),
                    metadata={"gap_id": str(getattr(gap, "gap_id", "") or "")},
                )
            )
    return _canonical_requirements(output)


def requirements_from_target_projection(result: Any) -> tuple[EvidenceRequirement, ...]:
    """Produce requirements for formal targets and pending claim intake."""

    output: list[EvidenceRequirement] = []
    spec_entries = [
        (spec, False)
        for spec in getattr(result, "spatial_reference_specs", None) or []
    ] + [
        (spec, True)
        for spec in getattr(result, "pending_grounding_specs", None) or []
    ]
    for index, (spec, pending) in enumerate(spec_entries):
        target_id = str(getattr(spec, "target_id", "") or getattr(spec, "intervention_id", "") or "").strip()
        scopes = tuple(getattr(spec, "retrieval_scopes", None) or ())
        terms = tuple(getattr(spec, "semantic_terms", None) or ())
        reference = getattr(spec, "reference", None)
        filter_values = getattr(reference, "filter", None) or {} if reference is not None else {}
        label = str(filter_values.get("label_contains", "") or "").strip()
        statement = "Resolve spatial target"
        if target_id:
            statement += f" {target_id}"
        if label:
            statement += f" near {label}"
        elif terms:
            statement += " " + " ".join(str(item) for item in terms[:4])
        source_snapshot_ref = str(
            getattr(spec, "source_snapshot_ref", "") or ""
        ).strip()
        source_snapshot_digest = str(
            getattr(spec, "source_snapshot_digest", "") or ""
        ).strip()
        source_input_refs = list(_nonempty_strings((
            source_snapshot_ref,
            source_snapshot_digest,
            *list(getattr(spec, "l1_fact_refs", None) or []),
        )))
        metadata = {
            "target_id": target_id,
            "spec_id": str(getattr(spec, "spec_id", "") or ""),
            "mention": label,
            "semantic_terms": [str(item) for item in terms if str(item)],
            "selection_cardinality": "one",
            "pending_grounding": pending,
            "claim_id": target_id if pending else "",
            "source_artifact_key": "planning_program" if pending else "target_projection",
            "source_input_refs": source_input_refs,
            "return_stage": "l3" if pending else "target_projection",
            "expected_artifact_key": "planning_program" if pending else "target_projection",
        }
        if pending:
            from app.contracts.workflow.recovery_pointer import RecoveryPointer

            recovery = RecoveryPointer(
                item_id=target_id,
                item_kind="claim",
                source_stage="l3",
                return_stage="l3",
                source_artifact_key="planning_program",
                source_artifact_ref=str(getattr(result, "program_ref", "") or ""),
                source_input_refs=source_input_refs,
                missing_requirements=[
                    "place_binding",
                    "candidate_geometry",
                    "typed_intervention_parameters",
                ],
                expected_artifact_key="planning_program",
                reason_code="pending_claim_grounding",
            )
            metadata["recovery"] = recovery.model_dump(mode="json")
        output.append(
            _artifact_requirement(
                stage="TARGET_PROJECTION",
                artifact=result,
                index=index,
                statement=statement,
                kind="spatial",
                source_families=("data", "gis", "kg", "artifact"),
                scope=(*scopes, label),
                spatial_granularity="feature",
                evidence_role=(
                    "target_pending_grounding" if pending
                    else "target_spatial_binding"
                ),
                required=True,
                success_condition="typed spatial reference resolves to snapshot-bound entity/feature candidates",
                source_artifact_refs=(
                    str(getattr(result, "program_ref", "") or ""),
                    source_snapshot_ref,
                    source_snapshot_digest,
                    *list(_nonempty_strings(getattr(spec, "l1_fact_refs", None))),
                ),
                metadata=metadata,
            )
        )
    pending_claim_ids = {
        str(getattr(claim, "claim_id", "") or "")
        for claim in getattr(result, "pending_grounding_claims", None) or []
    }
    for claim in getattr(result, "claims", None) or []:
        claim_id = str(getattr(claim, "claim_id", "") or "").strip()
        if claim_id in pending_claim_ids:
            continue
        spatial_requirements = getattr(claim, "spatial_requirements", None)
        if spatial_requirements is None:
            continue
        _append_spatial_requirement_inputs(
            output,
            seen={(item.evidence_role, item.statement, tuple(item.scope)) for item in output},
            stage="TARGET_PROJECTION",
            artifact=result,
            target_id=claim_id,
            requirements=spatial_requirements,
            relation_context="target_claim",
        )
    graph = getattr(result, "intent_graph", None)
    if graph is not None:
        graph_shared_refs = _nonempty_strings(getattr(graph, "shared_resource_refs", None))
        if graph_shared_refs:
            _append_spatial_requirement_inputs(
                output,
                seen={(item.evidence_role, item.statement, tuple(item.scope)) for item in output},
                stage="TARGET_PROJECTION",
                artifact=result,
                target_id="",
                requirements={"shared_resource_refs": list(graph_shared_refs)},
                relation_context="target_intent_graph",
            )
        for relation in getattr(graph, "relations", None) or []:
            if str(getattr(relation, "source", "") or "") == "pending_grounding_claim":
                # Pending-claim relation inputs are owned by the L3 claim
                # requirement set.  The same relation is present in the
                # GROUND-facing graph so it can become a deferred factor, but
                # it must not be reclassified as a TARGET_PROJECTION source.
                continue
            subject = str(getattr(relation, "subject_ref", "") or "").strip()
            relation_payload = {
                "relations": [
                    relation.model_dump(mode="json")
                    if hasattr(relation, "model_dump")
                    else relation
                ]
            }
            _append_spatial_requirement_inputs(
                output,
                seen={(item.evidence_role, item.statement, tuple(item.scope)) for item in output},
                stage="TARGET_PROJECTION",
                artifact=result,
                target_id=subject,
                requirements=relation_payload,
                relation_context="target_intent_graph",
            )
    task_graph = getattr(result, "planning_task_graph", None)
    if task_graph is not None:
        task_role_map = {
            "evidence": "planning_task_evidence",
            "candidate_producer": "planning_task_candidate_producer",
            "solver_subproblem": "planning_task_solver_subproblem",
            "validation": "planning_task_validation",
        }
        task_kind_map = {
            "evidence": "spatial",
            "candidate_producer": "spatial",
            "solver_subproblem": "spatial",
            "validation": "constraint",
        }
        for index, task in enumerate(getattr(task_graph, "tasks", None) or [], start=len(output)):
            task_id = str(getattr(task, "task_id", "") or "").strip()
            task_kind = str(getattr(task, "task_kind", "") or "").strip()
            if not task_id or task_kind not in task_role_map:
                continue
            target_refs = _nonempty_strings(getattr(task, "target_refs", None))
            relation_refs = _nonempty_strings(getattr(task, "relation_refs", None))
            required_inputs = _nonempty_strings(getattr(task, "required_inputs", None))
            statement = f"Execute typed planning task {task_id}"
            if required_inputs:
                statement += " with inputs " + ", ".join(required_inputs)
            _append_structured_requirement(
                output,
                {(item.evidence_role, item.statement, tuple(item.scope)) for item in output},
                stage="TARGET_PROJECTION",
                artifact=result,
                statement=statement,
                kind=task_kind_map[task_kind],
                 source_families=("data", "artifact", "kg", "report"),
                scope=(*target_refs, *relation_refs, task_id),
                spatial_granularity="network" if "network" in str(getattr(task, "capability", "")) else "feature",
                evidence_role=task_role_map[task_kind],
                success_condition="typed task inputs are source-bound and the task output is available to the next planning stage",
                source_artifact_refs=(str(getattr(task_graph, "fingerprint", "") or ""),),
                metadata={
                    "task_id": task_id,
                    "task_kind": task_kind,
                    "capability": str(getattr(task, "capability", "") or ""),
                    "required_inputs": list(required_inputs),
                    "produced_artifact_refs": list(getattr(task, "produced_artifact_refs", None) or []),
                    "dependency_task_ids": list(getattr(task, "dependency_task_ids", None) or []),
                    "planning_task_graph_fingerprint": str(getattr(task_graph, "fingerprint", "") or ""),
                },
            )
    return _canonical_requirements(output)


def requirements_from_ground(problem: Any) -> tuple[EvidenceRequirement, ...]:
    """Produce requirements for unresolved GROUND candidate/geometry inputs."""

    output: list[EvidenceRequirement] = []
    for index, domain in enumerate(getattr(problem, "target_domains", None) or []):
        target_id = str(getattr(domain, "target_id", "") or "").strip()
        status = str(getattr(domain, "status", "") or "unresolved")
        if status == "resolved" and getattr(domain, "candidate_site_refs", None) and getattr(domain, "geometry_roles", None):
            continue
        statement = f"Complete candidate identity and geometry for {target_id or 'target'}"
        output.append(
            _artifact_requirement(
                stage="GROUND",
                artifact=problem,
                index=index,
                statement=statement,
                kind="spatial",
                 source_families=("data", "kg", "artifact"),
                scope=(target_id,),
                spatial_granularity="feature",
                evidence_role="ground_candidate_completeness",
                success_condition="candidate domain is resolved with geometry refs and uncertainty",
                source_artifact_refs=getattr(domain, "evidence_refs", None) or (),
                metadata={"target_id": target_id, "status": status},
            )
        )
    for offset, finding in enumerate(getattr(problem, "unresolved", None) or [], start=len(output)):
        statement = str(getattr(finding, "message", "") or getattr(finding, "code", "") or "").strip()
        if not statement:
            continue
        output.append(
            _artifact_requirement(
                stage="GROUND",
                artifact=problem,
                index=offset,
                statement=statement,
                kind="spatial",
                 source_families=("data", "kg", "artifact"),
                scope=(str(getattr(finding, "target_id", "") or ""),),
                spatial_granularity="feature",
                evidence_role="ground_unresolved",
                success_condition="finding resolved or routed to HUMAN without fabrication",
                metadata={"code": str(getattr(finding, "code", "") or "")},
            )
        )
    return _canonical_requirements(output)


def requirement_set_fingerprint(requirements: tuple[EvidenceRequirement, ...]) -> str:
    payload = [item.model_dump(mode="json") for item in requirements]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "compile_requirements",
    "l1_location_work_item_key",
    "requirement_set_fingerprint",
    "requirements_from_l1",
    "requirements_from_l2",
    "requirements_from_l3",
    "requirements_from_target_projection",
    "requirements_from_ground",
]
