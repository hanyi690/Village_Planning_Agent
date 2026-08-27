"""Execute the deterministic GROUND portion of a planning task DAG."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from app.contracts.planning.task_graph import PlanningTask, PlanningTaskBinding, PlanningTaskGraph


def _ref_digest(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("digest") or ref.get("descriptor_digest") or "").strip()
    return str(getattr(ref, "digest", "") or getattr(ref, "descriptor_digest", "")).strip()


def _sorted_refs(values: Iterable[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _source_artifact_refs(artifact_refs: dict[str, Any] | None) -> list[str]:
    return _sorted_refs(
        f"cas:{key}:{digest}"
        for key, ref in sorted((artifact_refs or {}).items())
        if (digest := _ref_digest(ref))
    )


def _binding(
    label: str,
    kind: str,
    artifact_ref: Any,
    json_pointer: str,
    source_refs: list[str],
) -> PlanningTaskBinding | None:
    if not _ref_digest(artifact_ref):
        return None
    return PlanningTaskBinding(
        binding_id=f"binding:{kind}:{label}",
        label=label,
        binding_kind=kind,
        artifact_ref=artifact_ref,
        json_pointer=json_pointer,
        source_artifact_refs=source_refs,
    )


def _ground_bindings(
    problem: Any,
    source_refs: list[str],
    task_graph: PlanningTaskGraph,
    artifact_refs: dict[str, Any],
) -> list[PlanningTaskBinding]:
    """Map only source-backed GROUND facts to compiler input labels."""

    bindings: list[PlanningTaskBinding] = []
    candidate_geometries = {
        str(getattr(item, "candidate_id", "") or ""): (index, item)
        for index, item in enumerate(
            list(getattr(problem, "candidate_geometries", None) or [])
        )
        if str(getattr(item, "candidate_id", "") or "").strip()
    }

    def append(label: str, kind: str, fragment: str) -> None:
        value = _binding(
            label,
            kind,
            artifact_refs.get("grounding_result"),
            fragment,
            source_refs,
        )
        if value is not None:
            bindings.append(value)

    for index, domain in enumerate(list(getattr(problem, "candidate_domains", None) or [])):
        target_id = str(getattr(domain, "target_id", "") or "").strip()
        if not target_id:
            continue
        fragment = f"/problem/candidate_domains/{index}"
        candidate_ids = list(getattr(domain, "candidate_ids", None) or [])
        geometry_refs = list(getattr(domain, "candidate_geometry_refs", None) or [])
        if str(getattr(domain, "status", "") or "") == "resolved" and candidate_ids:
            append(f"candidate_domain:{target_id}", "candidate_domain", fragment)
            for candidate_id in candidate_ids:
                geometry_entry = candidate_geometries.get(str(candidate_id))
                if geometry_entry is None:
                    continue
                geometry_index, geometry = geometry_entry
                if (
                    str(getattr(geometry, "kind", "") or "") == "line"
                    and str(getattr(geometry, "role", "") or "") == "execution_geometry"
                    and str(getattr(geometry, "spatial_domain_kind", "") or "") == "exact_feature"
                    and bool(str(getattr(geometry, "wkt", "") or "").strip())
                    and bool(
                        getattr(geometry, "source_feature_ids", None)
                        or getattr(geometry, "source_refs", None)
                        or getattr(geometry, "source_bsms", None)
                    )
                ):
                    append(
                        f"source_identity:{target_id}",
                        "geometry",
                        f"/problem/candidate_geometries/{geometry_index}",
                    )
                    break
        if geometry_refs:
            append(f"geometry:{target_id}", "geometry", fragment)
    for index, domain in enumerate(list(getattr(problem, "target_domains", None) or [])):
        target_id = str(getattr(domain, "target_id", "") or "").strip()
        if target_id and list(getattr(domain, "evidence_refs", None) or []):
            append(f"evidence:target:{target_id}", "evidence", f"/problem/target_domains/{index}")
    for index, item in enumerate(list(getattr(problem, "bindings", None) or [])):
        entity_ref = str(getattr(item, "entity_ref", "") or "").strip()
        target_id = str(getattr(item, "target_id", "") or "").strip()
        fragment = f"/problem/bindings/{index}"
        if entity_ref:
            append(f"existing_entity:{entity_ref}", "entity", fragment)
            append(f"source_identity:{entity_ref}", "entity", fragment)
            append(f"endpoint:{entity_ref}", "entity", fragment)
        if target_id:
            append(f"endpoint:{target_id}", "entity", fragment)
        if target_id and str(getattr(item, "geometry_ref", "") or "").strip():
            append(f"geometry:{target_id}", "geometry", fragment)
    for index, network_ref in enumerate(list(getattr(problem, "network_refs", None) or [])):
        value = str(network_ref or "").strip()
        if value:
            append(f"network:{value}", "network", f"/problem/network_refs/{index}")
    if list(getattr(problem, "network_refs", None) or []):
        for index, domain in enumerate(list(getattr(problem, "candidate_domains", None) or [])):
            target_id = str(getattr(domain, "target_id", "") or "").strip()
            if target_id:
                append(f"network_snapshot:{target_id}", "network", f"/problem/candidate_domains/{index}")
    pool = getattr(problem, "parcel_resource_pool", None)
    if pool is not None and list(getattr(pool, "resources", None) or []):
        for index, domain in enumerate(list(getattr(problem, "candidate_domains", None) or [])):
            target_id = str(getattr(domain, "target_id", "") or "").strip()
            if target_id:
                append(f"parcel_resource_pool:{target_id}", "parcel_resource_pool", "/problem/parcel_resource_pool")
    for task in task_graph.tasks:
        for relation_ref in task.relation_refs:
            value = _binding(
                f"relation:{relation_ref}",
                "relation",
                artifact_refs.get("target_projection"),
                f"/intent_graph/relations/{relation_ref}",
                source_refs,
            )
            if value is not None:
                bindings.append(value)
    for index, relation in enumerate(list(getattr(problem, "relation_satisfaction", None) or [])):
        relation_id = str(getattr(relation, "relation_id", "") or "").strip()
        if relation_id:
            append(
                f"relation_evaluation:{relation_id}",
                "evidence",
                f"/problem/relation_satisfaction/{index}",
            )
    return sorted({item.binding_id: item for item in bindings}.values(), key=lambda item: item.binding_id)


def _missing_inputs(task: PlanningTask, bindings_by_label: dict[str, PlanningTaskBinding]) -> list[str]:
    return sorted({label for label in task.required_inputs if label not in bindings_by_label})


def _select_owned(missing: list[str]) -> list[str]:
    return [label for label in missing if label.startswith(("demand:", "event:"))]


def _derived_outputs(task: PlanningTask, bindings_by_label: dict[str, PlanningTaskBinding], source_refs: list[str]) -> list[PlanningTaskBinding]:
    """Bind outputs to an existing CAS fragment; never manufacture a domain."""

    if task.task_kind == "candidate_producer":
        return [bindings_by_label[item] for item in task.produced_artifact_refs if item in bindings_by_label]
    inputs = [bindings_by_label[item] for item in task.required_inputs if item in bindings_by_label]
    if not inputs:
        return []
    return [
        value
        for label in task.produced_artifact_refs
        if (value := _binding(
            label,
            "derived_evidence",
            inputs[0].artifact_ref,
            inputs[0].json_pointer,
            source_refs,
        )) is not None
    ]


def execute_planning_task_graph(
    task_graph: PlanningTaskGraph,
    *,
    grounded_problem: Any | None,
    artifact_refs: dict[str, Any] | None = None,
) -> PlanningTaskGraph:
    """Topologically bind the graph to replayable GROUND artifacts.

    GROUND cannot create candidate domains, demand portfolios, or execution
    events. Candidate producers resolve only from a typed, resolved candidate
    domain. Missing source input blocks; demand/event input is explicitly
    deferred to its later owner. Solver units remain SELECT-owned.
    """

    source_refs = _source_artifact_refs(artifact_refs)
    bindings = _ground_bindings(
        grounded_problem,
        source_refs,
        task_graph,
        dict(artifact_refs or {}),
    )
    bindings_by_label = {item.label: item for item in bindings}
    by_id = {task.task_id: task for task in task_graph.tasks}
    resolved: dict[str, PlanningTask] = {}
    pending = set(by_id)
    diagnostics = list(task_graph.diagnostics)

    while pending:
        progressed = False
        for task_id in sorted(tuple(pending)):
            task = by_id[task_id]
            dependencies = [resolved.get(item) for item in task.dependency_task_ids]
            if any(item is None for item in dependencies):
                continue
            input_ids = [bindings_by_label[item].binding_id for item in task.required_inputs if item in bindings_by_label]
            ready = task.transition_to(
                "ready",
                reason="dependencies_satisfied",
                input_artifact_refs=source_refs,
                lineage_refs=[*task.dependency_task_ids, task_graph.fingerprint],
                input_binding_ids=input_ids,
            )
            non_resolved = [item.task_id for item in dependencies if item is not None and item.status != "resolved"]
            if non_resolved:
                resolved[task_id] = ready.transition_to(
                    "deferred",
                    reason="dependency_not_resolved:" + ",".join(non_resolved),
                    input_artifact_refs=source_refs,
                    lineage_refs=non_resolved,
                )
            elif task.task_kind == "solver_subproblem":
                resolved[task_id] = ready.transition_to(
                    "deferred",
                    reason="solver_owned_by_select",
                    input_artifact_refs=source_refs,
                    lineage_refs=[task_graph.fingerprint],
                )
            else:
                missing = _missing_inputs(task, bindings_by_label)
                later_inputs = _select_owned(missing)
                if later_inputs:
                    resolved[task_id] = ready.transition_to(
                        "deferred",
                        reason="select_owned_prerequisites:" + ",".join(later_inputs),
                        input_artifact_refs=source_refs,
                        lineage_refs=[task_graph.fingerprint],
                    )
                elif missing:
                    resolved[task_id] = ready.transition_to(
                        "blocked",
                        reason="missing_ground_prerequisites:" + ",".join(missing),
                        input_artifact_refs=source_refs,
                        lineage_refs=[task_graph.fingerprint],
                    )
                else:
                    output_bindings = _derived_outputs(task, bindings_by_label, source_refs)
                    if task.produced_artifact_refs and not output_bindings:
                        resolved[task_id] = ready.transition_to(
                            "blocked",
                            reason="missing_ground_output_binding",
                            input_artifact_refs=source_refs,
                            lineage_refs=[task_graph.fingerprint],
                        )
                    else:
                        running = ready.transition_to(
                            "running",
                            reason="ground_inputs_bound",
                            input_artifact_refs=source_refs,
                            lineage_refs=[task_graph.fingerprint],
                        )
                        for binding in output_bindings:
                            bindings_by_label[binding.label] = binding
                        resolved[task_id] = running.transition_to(
                            "resolved",
                            reason="ground_binding_complete",
                            input_artifact_refs=source_refs,
                            output_artifact_refs=_sorted_refs(
                                f"cas:{item.artifact_ref.digest}#{item.json_pointer}"
                                for item in output_bindings
                            ),
                            lineage_refs=[task_graph.fingerprint],
                            output_binding_ids=[item.binding_id for item in output_bindings],
                        )
            pending.remove(task_id)
            progressed = True
        if progressed:
            continue
        for task_id in sorted(pending):
            task = by_id[task_id]
            resolved[task_id] = task.transition_to(
                "failed",
                reason="scheduler_dependency_resolution_failed",
                input_artifact_refs=source_refs,
                lineage_refs=[task_graph.fingerprint],
            )
            diagnostics.append(f"task_scheduler_failed:{task_id}")
        pending.clear()

    all_bindings = sorted({item.binding_id: item for item in bindings_by_label.values()}.values(), key=lambda item: item.binding_id)
    counts = Counter(task.status for task in resolved.values())
    diagnostics.append("task_execution_counts:" + ",".join(f"{status}={counts[status]}" for status in sorted(counts)))
    return PlanningTaskGraph(
        tasks=[resolved[task.task_id] for task in task_graph.tasks],
        diagnostics=diagnostics,
        source_intent_fingerprint=task_graph.source_intent_fingerprint,
        bindings=all_bindings,
    )


__all__ = ["execute_planning_task_graph"]
