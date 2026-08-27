"""Compile typed intent into the GROUND/SELECT planning work graph.

This compiler is intentionally small and closed over the typed intent graph.
It never looks at ``name`` or other natural-language fields.  A task denotes a
prerequisite or a future computation; it does not mean that evidence or
geometry has already been found.
"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from typing import Any, Sequence

from app.contracts.planning.intent_graph import PlanRelationIntent, PlanTargetNode, PlanningIntentGraph
from app.contracts.program import PlanningClaim
from app.contracts.planning.relation_parameters import RelationParameters
from app.contracts.planning.task_graph import PlanningTask, PlanningTaskGraph
from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
from pydantic import TypeAdapter, ValidationError


_SOURCE_OPERATIONS = frozenset({
    "preserve",
    "upgrade",
    "expand",
    "relocate",
    "repair",
    "demolish",
})
_RELATION_TEMPLATES = frozenset({
    "near",
    "serve",
    "provide_access",
    "connect_network",
    "follow_alignment",
    "preserve_existing",
    "upgrade_existing",
    "part_of",
    "co_locate",
    "mutually_exclusive",
    "precedes",
    "within_allowed_area",
    "avoid_constraint",
    "contains",
    "located_in",
    "adjacent_to",
    "intersects",
    "overlaps",
})
_CLAIM_KIND_MAP = {
    "facility": "facility",
    "road": "road",
    "axis": "axis",
    "zone": "zone",
    "site_area": "site_area",
    "restoration": "site_area",
    "protection": "site_area",
}
_RELATION_PARAMETERS = TypeAdapter(RelationParameters)


def _target_ref(node: PlanTargetNode) -> str:
    return str(node.target_id or "").strip()


def _task_id(target_id: str, suffix: str) -> str:
    return f"task:{target_id}:{suffix}"


def _task(
    *,
    task_id: str,
    task_kind: str,
    target_refs: Iterable[str] = (),
    relation_refs: Iterable[str] = (),
    capability: str = "",
    required_inputs: Iterable[str] = (),
    produced_artifact_refs: Iterable[str] = (),
    dependency_task_ids: Iterable[str] = (),
    solver_kind: str | None = None,
    diagnostics: Iterable[str] = (),
) -> PlanningTask:
    return PlanningTask(
        task_id=task_id,
        task_kind=task_kind,
        target_refs=list(target_refs),
        relation_refs=list(relation_refs),
        capability=capability,
        required_inputs=list(required_inputs),
        produced_artifact_refs=list(produced_artifact_refs),
        dependency_task_ids=list(dependency_task_ids),
        solver_kind=solver_kind,
        diagnostics=list(diagnostics),
    )


def _known_input_diagnostic(
    node: PlanTargetNode,
    *,
    input_name: str,
    present: bool,
) -> list[str]:
    if present:
        return []
    target_id = _target_ref(node) or "<missing-target-id>"
    return [f"missing_input:{input_name}:{target_id}"]


def _pending_claim_node(claim: PlanningClaim) -> PlanTargetNode:
    """Project a pending claim into a non-executable typed target node."""

    endpoint_refs: list[str] = []
    for parameter_block in (
        claim.road_parameters,
        claim.linear_parameters,
        claim.axis_parameters,
    ):
        endpoint_refs.extend(
            str(value)
            for value in (getattr(parameter_block, "connects", None) or [])
            if str(value).strip()
        )
    evidence_refs = [
        *claim.evidence_refs,
        *claim.source_fact_refs,
        *claim.source_refs,
    ]
    locator_refs = [
        *claim.location_hints,
        *claim.affected_parcel_refs,
        *claim.source_fact_refs,
        *claim.source_refs,
    ]
    return PlanTargetNode(
        target_id=claim.claim_id,
        target_kind=_CLAIM_KIND_MAP.get(claim.suggested_category, "action"),
        asset_kind=claim.asset_kind,
        operation={"widen": "upgrade", "harden": "upgrade"}.get(
            claim.intervention_action, claim.intervention_action
        ),
        evidence_refs=evidence_refs,
        claim_refs=[claim.claim_id],
        required_capabilities=[],
        endpoint_refs=endpoint_refs,
        locator_refs=locator_refs,
    )


def _pending_claim_relations(
    claim: PlanningClaim,
    *,
    known_target_ids: set[str] | None = None,
) -> list[PlanRelationIntent]:
    requirements = claim.spatial_requirements
    if requirements is None:
        return []
    known_target_ids = set(known_target_ids or ())
    relations: list[PlanRelationIntent] = []
    for index, raw in enumerate(requirements.relations):
        relation_id = str(raw.relation_id or f"relation:{index}").strip()
        relation_id = f"pending:{claim.claim_id}:{relation_id}"
        raw_subject = str(raw.subject_ref or "").strip()
        subject_ref = (
            raw_subject
            if raw_subject in known_target_ids
            else claim.claim_id
        )
        object_ref = str(raw.object_ref or "").strip()
        object_ref_kind = raw.object_ref_kind
        if object_ref in known_target_ids:
            object_ref_kind = "target"
        parameters = None
        parameter_status = "missing"
        raw_parameters = dict(raw.parameters or {})
        if raw_parameters:
            try:
                parameters = _RELATION_PARAMETERS.validate_python(raw_parameters)
                parameter_status = "provided"
            except (ValidationError, TypeError, ValueError):
                parameter_status = "invalid"
        relations.append(
            PlanRelationIntent(
                relation_id=relation_id,
                relation_template=raw.relation_template,
                subject_ref=subject_ref,
                object_ref=object_ref,
                object_ref_kind=object_ref_kind,
                criticality=raw.criticality,
                claim_refs=[claim.claim_id, *raw.source_claim_refs],
                source="pending_grounding_claim",
                parameters=parameters,
                parameter_status=parameter_status,
                geometry_scope=raw.geometry_scope,
                weight=raw.weight,
            )
        )
    return relations


def intent_graph_with_pending_claims(
    intent_graph: PlanningIntentGraph,
    pending_claims: Sequence[PlanningClaim],
) -> PlanningIntentGraph:
    """Add pending spatial targets/relations to the GROUND-facing intent graph.

    Pending claims are not executable targets, but their typed relations are
    still planning constraints.  Keeping them in the graph lets GROUND create
    explicit deferred factors and lets SELECT report the missing prerequisite
    instead of silently evaluating only the admitted subset.
    """

    pending = tuple(sorted(pending_claims, key=lambda item: item.claim_id))
    if not pending:
        return intent_graph
    existing_ids = {
        str(node.target_id or "")
        for node in intent_graph.nodes
        if str(node.target_id or "")
    }
    known_target_ids = existing_ids | {claim.claim_id for claim in pending}
    pending_nodes = [
        _pending_claim_node(claim)
        for claim in pending
        if claim.claim_id not in existing_ids
    ]
    existing_relation_ids = {
        str(relation.relation_id or "")
        for relation in intent_graph.relations
        if str(relation.relation_id or "")
    }
    pending_relations = [
        relation
        for claim in pending
        for relation in _pending_claim_relations(
            claim,
            known_target_ids=known_target_ids,
        )
        if relation.relation_id not in existing_relation_ids
    ]
    return PlanningIntentGraph(
        nodes=[*intent_graph.nodes, *pending_nodes],
        relations=[*intent_graph.relations, *pending_relations],
        diagnostics=[
            *intent_graph.diagnostics,
            *[
                f"pending_relation:{relation.relation_id}"
                for relation in pending_relations
            ],
        ],
        source_program_ref=intent_graph.source_program_ref,
        solver_kind=intent_graph.solver_kind,
        solver_kind_reasons=list(intent_graph.solver_kind_reasons),
        shared_resource_refs=list(intent_graph.shared_resource_refs),
    )


def _pending_claim_fingerprint(pending_claims: Sequence[PlanningClaim]) -> str:
    payload = [
        claim.model_dump(mode="json")
        for claim in sorted(pending_claims, key=lambda item: item.claim_id)
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_PENDING_RETRIEVAL_SCOPES = {
    "facility": ["facilities", "parcels"],
    "road": ["roads"],
    "axis": ["roads", "zones"],
    "zone": ["zones", "parcels"],
    "site_area": ["parcels", "zones"],
    "restoration": ["zones", "parcels"],
    "protection": ["zones", "parcels"],
}
_PENDING_RDF_TYPES = {
    "facility": "Facility",
    "road": "Road",
    "axis": "Road",
    "zone": "Zone",
    "site_area": "Parcel",
    "restoration": "Zone",
    "protection": "Zone",
}


def pending_claim_grounding_specs(
    claims: Sequence[PlanningClaim],
) -> list[SpatialReferenceSpec]:
    """Create internal GROUND work specs for pending spatial claims.

    The returned specs are deliberately separate from formal projection specs:
    they carry only typed category/output/location-hint fields and never a
    fabricated BSM, coordinate, or geometry.  GROUND may resolve them to a
    candidate domain or record an explicit unresolved result.
    """

    result: list[SpatialReferenceSpec] = []
    for claim in sorted(claims, key=lambda item: item.claim_id):
        if claim.planning_role != "spatial_intervention":
            continue
        category = str(claim.suggested_category or "").strip()
        scopes = list(_PENDING_RETRIEVAL_SCOPES.get(category, []))
        common = {
            "semantic_terms": [category] if category else [],
            "retrieval_scopes": scopes,
            "target_id": claim.claim_id,
            "intervention_id": claim.claim_id,
            "project_ref": claim.project_package_ref or None,
            "materialization_role": claim.materialization_role,
            "unresolved_reason": "pending_grounding",
            "l1_fact_refs": list(claim.source_fact_refs),
        }
        hints = list(dict.fromkeys(
            str(item).strip()
            for item in claim.location_hints
            if str(item).strip()
        ))
        if len(hints) == 1:
            spec = SpatialReferenceSpec(
                **common,
                type="attributive",
                spec_id=f"pending-grounding:{claim.claim_id}",
                reference=RefObject(
                    kind="place_name",
                    filter={"label_contains": hints[0]},
                ),
            )
        elif hints:
            children = [
                SpatialReferenceSpec(
                    **common,
                    type="attributive",
                    spec_id=f"pending-grounding:{claim.claim_id}:{index}",
                    reference=RefObject(
                        kind="place_name",
                        filter={"label_contains": hint},
                    ),
                )
                for index, hint in enumerate(hints)
            ]
            spec = SpatialReferenceSpec(
                **common,
                type="composed",
                op="or",
                children=children,
                spec_id=f"pending-grounding:{claim.claim_id}",
            )
        else:
            rdf_type = _PENDING_RDF_TYPES.get(category, "")
            reference = (
                RefObject(kind="entity_type", filter={"rdf_type": rdf_type})
                if rdf_type else None
            )
            spec = SpatialReferenceSpec(
                **common,
                type="attributive",
                spec_id=f"pending-grounding:{claim.claim_id}",
                reference=reference,
            )
        result.append(spec)
    return result


def _compile_target_tasks(
    node: PlanTargetNode,
) -> tuple[list[PlanningTask], str, list[str]]:
    """Return target tasks, the terminal task id, and graph diagnostics."""

    target_id = _target_ref(node)
    if not target_id:
        # Keep the malformed node visible in diagnostics while allowing the
        # graph contract to remain valid and deterministic.
        diagnostic = "missing_target_id"
        task = _task(
            task_id="task:missing-target-id:validation",
            task_kind="validation",
            capability="planning.target_validation",
            required_inputs=["target_id"],
            produced_artifact_refs=["validation:missing-target-id"],
            diagnostics=[diagnostic],
        )
        return [task], task.task_id, [diagnostic]

    target_refs = [target_id]
    if node.target_kind == "action":
        task = _task(
            task_id=_task_id(target_id, "action"),
            task_kind="solver_subproblem",
            target_refs=target_refs,
            capability="non_spatial_action",
            required_inputs=[f"action:{target_id}"],
            produced_artifact_refs=[f"action_plan:{target_id}"],
            solver_kind="single_choice",
        )
        return [task], task.task_id, []

    if node.target_kind == "facility":
        existing = node.operation in _SOURCE_OPERATIONS
        evidence_kind = "source_identity" if existing else "demand"
        evidence_input = (
            f"source_identity:{node.existing_entity_ref}"
            if existing and node.existing_entity_ref
            else f"{evidence_kind}:{target_id}"
        )
        evidence_artifact = f"evidence:{evidence_kind}:{target_id}"
        evidence_diagnostics = _known_input_diagnostic(
            node,
            input_name=evidence_kind,
            present=bool(node.existing_entity_ref) if existing else bool(node.evidence_refs),
        )
        evidence = _task(
            task_id=_task_id(target_id, f"evidence:{evidence_kind}"),
            task_kind="evidence",
            target_refs=target_refs,
            capability=f"evidence.{evidence_kind}",
            required_inputs=[evidence_input],
            produced_artifact_refs=[evidence_artifact],
            diagnostics=[
                *evidence_diagnostics,
                *[
                    f"pending_locator:{ref}"
                    for ref in node.locator_refs
                    if ref
                ],
            ],
        )
        candidate = _task(
            task_id=_task_id(target_id, "candidate:facility"),
            task_kind="candidate_producer",
            target_refs=target_refs,
            capability="facility.placement",
            required_inputs=[evidence_artifact],
            produced_artifact_refs=[f"candidate_domain:{target_id}"],
            dependency_task_ids=[evidence.task_id],
            diagnostics=evidence_diagnostics,
        )
        solver = _task(
            task_id=_task_id(target_id, "solver:facility"),
            task_kind="solver_subproblem",
            target_refs=target_refs,
            capability="facility.placement",
            required_inputs=[f"candidate_domain:{target_id}"],
            produced_artifact_refs=[f"solver_subproblem:{target_id}"],
            dependency_task_ids=[candidate.task_id],
            solver_kind="single_choice",
        )
        return [evidence, candidate, solver], solver.task_id, []

    if node.target_kind in {"road", "linear", "axis"} and node.operation in _SOURCE_OPERATIONS:
        source_identity_artifact = f"evidence:source_identity:{target_id}"
        source_identity = _task(
            task_id=_task_id(target_id, "evidence:source_identity"),
            task_kind="evidence",
            target_refs=target_refs,
            capability="evidence.source_identity",
            required_inputs=[f"source_identity:{target_id}"],
            produced_artifact_refs=[source_identity_artifact],
            diagnostics=[
                *[f"pending_locator:{ref}" for ref in node.locator_refs if ref],
            ],
        )
        candidate = _task(
            task_id=_task_id(target_id, "candidate:source_geometry"),
            task_kind="candidate_producer",
            target_refs=target_refs,
            capability=node.required_capabilities[0] if node.required_capabilities else "network.candidate",
            required_inputs=[source_identity_artifact],
            produced_artifact_refs=[f"candidate_domain:{target_id}"],
            dependency_task_ids=[source_identity.task_id],
            diagnostics=[
                *[f"pending_locator:{ref}" for ref in node.locator_refs if ref],
            ],
        )
        solver = _task(
            task_id=_task_id(target_id, "solver:source_geometry"),
            task_kind="solver_subproblem",
            target_refs=target_refs,
            capability=node.required_capabilities[0] if node.required_capabilities else "network.solver",
            required_inputs=[f"candidate_domain:{target_id}"],
            produced_artifact_refs=[f"solver_subproblem:{target_id}"],
            dependency_task_ids=[candidate.task_id],
            solver_kind="network_path" if node.target_kind == "road" else "auto",
        )
        return [source_identity, candidate, solver], solver.task_id, []

    if node.target_kind in {"road", "linear", "axis"}:
        endpoint_artifact = f"evidence:endpoint_binding:{target_id}"
        network_artifact = f"evidence:network_snapshot:{target_id}"
        endpoint_diagnostics = _known_input_diagnostic(
            node,
            input_name="endpoint_refs",
            present=bool(node.endpoint_refs),
        )
        endpoint = _task(
            task_id=_task_id(target_id, "evidence:endpoint_binding"),
            task_kind="evidence",
            target_refs=target_refs,
            capability="evidence.endpoint_binding",
            required_inputs=[
                f"endpoint_refs:{target_id}",
                *[f"endpoint:{ref}" for ref in node.endpoint_refs],
            ],
            produced_artifact_refs=[endpoint_artifact],
            diagnostics=[
                *endpoint_diagnostics,
                *[f"pending_locator:{ref}" for ref in node.locator_refs if ref],
            ],
        )
        network = _task(
            task_id=_task_id(target_id, "evidence:network_snapshot"),
            task_kind="evidence",
            target_refs=target_refs,
            capability="evidence.network_snapshot",
            required_inputs=[f"network_snapshot:{target_id}"],
            produced_artifact_refs=[network_artifact],
        )
        candidate = _task(
            task_id=_task_id(target_id, "candidate:network"),
            task_kind="candidate_producer",
            target_refs=target_refs,
            capability=node.required_capabilities[0] if node.required_capabilities else "network.candidate",
            required_inputs=[endpoint_artifact, network_artifact],
            produced_artifact_refs=[f"candidate_domain:{target_id}"],
            dependency_task_ids=[endpoint.task_id, network.task_id],
            diagnostics=endpoint_diagnostics,
        )
        solver = _task(
            task_id=_task_id(target_id, "solver:network"),
            task_kind="solver_subproblem",
            target_refs=target_refs,
            capability=node.required_capabilities[0] if node.required_capabilities else "network.solver",
            required_inputs=[f"candidate_domain:{target_id}"],
            produced_artifact_refs=[f"solver_subproblem:{target_id}"],
            dependency_task_ids=[candidate.task_id],
            solver_kind="network_path",
        )
        return [endpoint, network, candidate, solver], solver.task_id, []

    if node.target_kind in {"zone", "site_area"}:
        resource_artifact = f"evidence:parcel_resource_pool:{target_id}"
        resource_diagnostics = _known_input_diagnostic(
            node,
            input_name="parcel_resource_pool",
            present=bool(node.evidence_refs),
        )
        evidence = _task(
            task_id=_task_id(target_id, "evidence:parcel_resource_pool"),
            task_kind="evidence",
            target_refs=target_refs,
            capability="evidence.parcel_resource_pool",
            required_inputs=[f"parcel_resource_pool:{target_id}"],
            produced_artifact_refs=[resource_artifact],
            diagnostics=[
                *resource_diagnostics,
                *[f"pending_locator:{ref}" for ref in node.locator_refs if ref],
            ],
        )
        candidate = _task(
            task_id=_task_id(target_id, "candidate:parcel"),
            task_kind="candidate_producer",
            target_refs=target_refs,
            capability=node.required_capabilities[0] if node.required_capabilities else "land.design",
            required_inputs=[resource_artifact],
            produced_artifact_refs=[f"candidate_domain:{target_id}"],
            dependency_task_ids=[evidence.task_id],
            diagnostics=resource_diagnostics,
        )
        solver = _task(
            task_id=_task_id(target_id, "solver:parcel"),
            task_kind="solver_subproblem",
            target_refs=target_refs,
            capability=node.required_capabilities[0] if node.required_capabilities else "land.design",
            required_inputs=[f"candidate_domain:{target_id}"],
            produced_artifact_refs=[f"solver_subproblem:{target_id}"],
            dependency_task_ids=[candidate.task_id],
            solver_kind="parcel_assignment",
        )
        return [evidence, candidate, solver], solver.task_id, []

    diagnostic = f"unsupported_target_kind:{node.target_kind}"
    task = _task(
        task_id=_task_id(target_id, "validation"),
        task_kind="validation",
        target_refs=target_refs,
        capability="planning.target_validation",
        required_inputs=[f"target_kind:{target_id}"],
        produced_artifact_refs=[f"validation:{target_id}"],
        diagnostics=[diagnostic],
    )
    return [task], task.task_id, [diagnostic]


def _compile_relation_task(
    relation: PlanRelationIntent,
    terminal_by_target: dict[str, str],
) -> tuple[PlanningTask, list[str]]:
    target_refs = [relation.subject_ref]
    dependency_ids: list[str] = []
    diagnostics: list[str] = []
    for target_ref in (relation.subject_ref, relation.object_ref):
        if relation.object_ref == target_ref and relation.object_ref_kind != "target":
            continue
        if target_ref in terminal_by_target:
            dependency_ids.append(terminal_by_target[target_ref])
        elif target_ref:
            diagnostics.append(f"missing_target_ref:{target_ref}:{relation.relation_id}")
    if relation.object_ref_kind == "target" and relation.object_ref:
        target_refs.append(relation.object_ref)
    required_inputs = [
        f"relation:{relation.relation_id}",
        f"relation_evaluation:{relation.relation_id}",
    ]
    if relation.parameter_status not in {"provided", "not_required"}:
        required_inputs.append(f"relation_parameters:{relation.relation_id}")
        diagnostics.append(f"missing_input:relation_parameters:{relation.relation_id}")
    else:
        parameters = relation.parameters
        parameter_type = str(getattr(parameters, "parameter_type", "") or "")
        if parameter_type == "service":
            required_inputs.extend([
                f"demand:{parameters.demand_ref}",
                f"network:{parameters.network_ref}",
            ])
        elif parameter_type in {"access", "connect"}:
            required_inputs.append(f"network:{parameters.network_ref}")
        elif parameter_type == "alignment":
            required_inputs.append(f"alignment:{parameters.alignment_ref}")
        elif parameter_type == "existing_asset":
            required_inputs.append(f"existing_entity:{parameters.existing_ref}")
        elif parameter_type == "allowed_area":
            required_inputs.extend(
                f"allowed_area:{area_ref}" for area_ref in parameters.area_refs
            )
        elif parameter_type == "avoid_constraint":
            required_inputs.extend(
                f"constraint:{constraint_ref}"
                for constraint_ref in parameters.constraint_refs
            )
        elif parameter_type == "distance" and parameters.network_ref:
            required_inputs.append(f"network:{parameters.network_ref}")
        elif parameter_type == "part_of":
            required_inputs.append(f"parent:{parameters.parent_ref}")
        elif parameter_type == "precedes":
            required_inputs.append(f"event:{parameters.required_event}")
    task = _task(
        task_id=f"task:relation:{relation.relation_id}:validation",
        task_kind="validation",
        target_refs=target_refs,
        relation_refs=[relation.relation_id],
        capability=f"planning.relation.{relation.relation_template}",
        required_inputs=required_inputs,
        produced_artifact_refs=[f"validation:{relation.relation_id}"],
        dependency_task_ids=dependency_ids,
        diagnostics=diagnostics,
    )
    return task, diagnostics


def compile_planning_task_graph(
    intent_graph: PlanningIntentGraph,
    *,
    pending_claims: Sequence[PlanningClaim] = (),
) -> PlanningTaskGraph:
    """Expand typed intent into deterministic prerequisite and solver tasks."""

    tasks: list[PlanningTask] = []
    diagnostics: list[str] = []
    terminal_by_target: dict[str, str] = {}
    typed_pending_claims = tuple(
        sorted(pending_claims, key=lambda item: item.claim_id)
    )
    existing_node_ids = {node.target_id for node in intent_graph.nodes}
    nodes = [
        *intent_graph.nodes,
        *[
            _pending_claim_node(claim)
            for claim in typed_pending_claims
            if claim.claim_id not in existing_node_ids
        ],
    ]
    for node in sorted(nodes, key=lambda item: item.target_id):
        node_tasks, terminal_task_id, node_diagnostics = _compile_target_tasks(node)
        tasks.extend(node_tasks)
        if node.target_id:
            terminal_by_target[node.target_id] = terminal_task_id
        diagnostics.extend(node_diagnostics)

    for relation in sorted(intent_graph.relations, key=lambda item: item.relation_id):
        if relation.relation_template not in _RELATION_TEMPLATES:
            continue
        relation_task, relation_diagnostics = _compile_relation_task(
            relation,
            terminal_by_target,
        )
        tasks.append(relation_task)
        diagnostics.extend(relation_diagnostics)

    graph_relation_ids = {relation.relation_id for relation in intent_graph.relations}
    for relation in sorted(
        [
            relation
            for claim in typed_pending_claims
            for relation in _pending_claim_relations(
                claim,
                known_target_ids=set(terminal_by_target),
            )
            if relation.relation_id not in graph_relation_ids
        ],
        key=lambda item: item.relation_id,
    ):
        if relation.relation_template not in _RELATION_TEMPLATES:
            continue
        relation_task, relation_diagnostics = _compile_relation_task(
            relation,
            terminal_by_target,
        )
        tasks.append(relation_task)
        diagnostics.extend(relation_diagnostics)

    source_fingerprint = intent_graph.fingerprint
    if typed_pending_claims:
        source_fingerprint = (
            f"{source_fingerprint}:pending:{_pending_claim_fingerprint(typed_pending_claims)}"
        )

    return PlanningTaskGraph(
        tasks=tasks,
        diagnostics=diagnostics,
        source_intent_fingerprint=source_fingerprint,
    )


__all__ = [
    "compile_planning_task_graph",
    "intent_graph_with_pending_claims",
    "pending_claim_grounding_specs",
]
