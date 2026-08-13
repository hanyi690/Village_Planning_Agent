"""GROUND stage service: resolve projected spatial references to evidence."""

from __future__ import annotations

from typing import Any, Dict

from app.infrastructure.logging import get_logger
from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _adopt_context,
    _load_ref_artifact,
    _require_context,
    _retry_patch,
    stage_completion_patch,
)

logger = get_logger(__name__)


def _to_typed(data: Any, cls: type) -> Any:
    if data is None or isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


async def ground_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate."""
    from app.domain.ground.aggregate import ground_aggregate, retrieve_evidence
    from app.domain.ground.gate import evaluate_ground_gate
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec

    retry_patch = _retry_patch(state, "ground")
    context = await _require_context(state)
    compilation = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    projection_ref = (state.get("artifact_refs") or {}).get("target_projection")
    specs = [
        _to_typed(item, SpatialReferenceSpec)
        for item in (getattr(compilation, "spatial_reference_specs", None) or [])
    ]

    # GROUND owns gazetteer/KG anchor resolution for the typed intent.  Fill
    # road candidate_bsms and start/end anchors from connects (村北/村南) so
    # the road worker / Stage 2.6 has endpoints, then persist the enriched
    # intent back into the target_projection artifact for SELECT/EXECUTE.
    try:
        from app.contracts.workflow.parse_contracts import SpatialPlanningIntent

        intent = _to_typed(
            getattr(compilation, "typed_intent", None) or compilation,
            SpatialPlanningIntent,
        )
        if intent is not None:
            from app.spatial.grounding.resolver import SpatialResolver

            resolver = SpatialResolver(context)
            village_cluster_map = await _village_cluster_map_for_context(context, intent)
            resolved_anchors = resolver.resolve_anchors(
                intent,
                village_cluster_map=village_cluster_map,
            )
            if resolved_anchors > 0:
                working_compilation = compilation.model_copy(
                    update={"typed_intent": intent}
                )
                ref = persist_stage_artifact(
                    state,
                    "target_projection",
                    "IntentCompilationResult",
                    working_compilation,
                )
                if ref:
                    projection_ref = ref
                    compilation = working_compilation
                logger.info(
                    "[workflow:ground] intent anchors resolved: %d entities",
                    resolved_anchors,
                )
    except Exception as exc:  # noqa: BLE001 - anchor enrichment must not break GROUND
        logger.warning("[workflow:ground] intent anchor resolution failed: %s", exc)
    evidence = []
    if retry_patch:
        prior_gate = state.get("ground_gate")
        requests = getattr(prior_gate, "evidence_requests", None)
        if requests is None and isinstance(prior_gate, dict):
            requests = prior_gate.get("evidence_requests")
        try:
            evidence = await retrieve_evidence(context, requests or None)
        except Exception as exc:
            logger.warning("[workflow:ground] retrieve_evidence failed: %s", exc)
    result = ground_aggregate(specs, context)

    # GROUND flash-LLM mention enhancement: for specs that could not bind any
    # BSM, ask the flash model to segment the raw prose into concrete locatable
    # mentions, then re-resolve through the same evidence index.  The model
    # only supplies text; BSMs still come from the index/gazetteer/bundle.
    # Results are cached per content hash so resume/replay does not repeat the
    # call.  On any failure the deterministic result is kept unchanged.
    try:
        enhanced = await _flash_enhance_unresolved(compilation, result, state)
        if enhanced:
            re_result = ground_aggregate(specs, context, mention_enhancements=enhanced)
            # Only adopt the enhanced result when it strictly reduces the
            # unresolved count; otherwise keep the deterministic baseline.
            if len(re_result.unresolved) < len(result.unresolved):
                result = re_result
    except Exception as exc:  # noqa: BLE001 - enhancement must never break GROUND
        logger.warning("[workflow:ground] flash mention enhancement failed: %s", exc)

    if evidence and hasattr(result, "spatial_query_evidence"):
        result.spatial_query_evidence.extend(evidence)
        refs = [ref for item in evidence for ref in item.result_refs if ref]
        if refs:
            for candidate in (getattr(result, "candidates", None) or []):
                if hasattr(candidate, "evidence_refs"):
                    candidate.evidence_refs.extend(refs)
    gate = evaluate_ground_gate(result, expected_spec_count=len(specs))
    ref = persist_stage_artifact(state, "ground", "GroundingResult", result)
    output_refs = {"grounding_result": ref}
    if projection_ref:
        output_refs["target_projection"] = projection_ref
    return stage_completion_patch(
        state,
        "ground",
        output_refs=output_refs,
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )


async def _flash_enhance_unresolved(
    compilation: Any,
    result: Any,
    state: Dict[str, Any],
) -> Dict[str, list[str]]:
    """Ask the flash LLM to segment raw prose for unresolved specs.

    Returns ``{target_id: [mention, ...]}`` or ``{}`` when there is nothing to
    enhance, the model is unavailable, or every call failed.  The mention
    cache is persisted under the session run directory so LangGraph replay /
    resume does not repeat flash calls for the same text.
    """
    if not getattr(result, "unresolved", None):
        return {}
    unresolved_target_ids = {
        str(getattr(issue, "related_artifact_id", "") or "")
        for issue in result.unresolved
    }
    unresolved_target_ids.discard("")
    if not unresolved_target_ids:
        return {}

    raw_by_target: Dict[str, str] = {}
    intent = getattr(compilation, "typed_intent", None) or {}
    if isinstance(intent, dict):
        target_lists = [
            intent.get("zone_targets") or [],
            intent.get("facilities") or [],
            intent.get("development_axes") or [],
            intent.get("road_targets") or [],
            intent.get("project_targets") or [],
        ]
    else:
        target_lists = [
            getattr(intent, "zone_targets", None) or [],
            getattr(intent, "facilities", None) or [],
            getattr(intent, "development_axes", None) or [],
            getattr(intent, "road_targets", None) or [],
            getattr(intent, "project_targets", None) or [],
        ]
    for target_list in target_lists:
        for target in target_list or []:
            target_id = str(getattr(target, "target_id", "") or "")
            if target_id not in unresolved_target_ids:
                continue
            semantic = getattr(target, "semantic", None) or {}
            raw = ""
            if isinstance(semantic, dict):
                raw = " ".join(
                    str(part or "")
                    for part in (
                        semantic.get("raw_text", ""),
                        semantic.get("spatial_hint", ""),
                        semantic.get("natural_language_description", ""),
                    )
                ).strip()
            else:
                raw = " ".join(
                    str(part or "")
                    for part in (
                        getattr(semantic, "raw_text", ""),
                        getattr(semantic, "spatial_hint", ""),
                        getattr(semantic, "natural_language_description", ""),
                    )
                ).strip()
            if raw:
                raw_by_target[target_id] = raw

    if not raw_by_target:
        return {}

    from app.infrastructure.paths import session_run_dir
    from app.spatial.grounding.flash_mention_extractor import MentionCache, extract_mentions

    run_root = None
    try:
        run_root = run_tmp_root()
    except Exception:  # noqa: BLE001
        run_root = None
    cache_path = None
    if run_root is not None:
        cache_path = (run_root / "ground-mention-cache.json").resolve()
    cache = MentionCache(cache_path)

    enhanced: Dict[str, list[str]] = {}
    for target_id, raw in raw_by_target.items():
        mentions = await extract_mentions(raw, cache=cache)
        candidates = [
            m.mention for m in mentions if m.mention and len(m.mention) >= 2
        ]
        if candidates:
            enhanced[target_id] = list(dict.fromkeys(candidates))
    return enhanced


async def _village_cluster_map_for_context(
    context: Any,
    intent: Any,
) -> Dict[str, Any]:
    """Pre-resolve natural-village -> residential-cluster mapping (cached).

    Bundle-derived clusters give road/facility anchors for named villages that
    are absent from the KG gazetteer.  The flash mapping is cached under the
    run root so LangGraph replay/resume does not repeat the model call.
    """
    try:
        workspace = getattr(context, "workspace", None)
        if workspace is None:
            return {}
        names = await _settlement_mentions_for_cluster_mapping(context, intent)
        if not names:
            return {}
        parcels = list(workspace.current_parcels() or [])
        if not parcels:
            return {}
        from app.spatial.grounding.village_cluster_mapper import (
            build_village_clusters,
            map_villages,
        )

        clusters = build_village_clusters(parcels)
        if not clusters:
            return {}
        from app.infrastructure.paths import session_run_dir
        from app.spatial.grounding.flash_mention_extractor import (
            create_flash_llm_safe,
        )

        cache = None
        try:
            cache = session_run_dir(str(getattr(context, "session_id", "") or "ground")) / "village-cluster-map.json"
        except Exception:
            cache = None
        report_text = _context_report_text(context)
        llm = create_flash_llm_safe()
        snapshot = getattr(workspace, "snapshot", None)
        landuse_collection = (
            snapshot.collection("landuse_current_geojson") if snapshot else None
        )
        return await map_villages(
            clusters,
            names,
            report_text=report_text,
            cache=cache,
            llm=llm,
            source_artifact_ref=(
                f"bundle-snapshot:{snapshot.snapshot_id}" if snapshot else ""
            ),
            source_artifact_digest=(
                str(
                    getattr(landuse_collection, "digest", "")
                    or getattr(snapshot, "digest", "")
                )
                if snapshot
                else ""
            ),
        )
    except Exception as exc:  # noqa: BLE001 - cluster mapping must never break GROUND
        logger.warning("[workflow:ground] village cluster mapping failed: %s", exc)
        return {}


def _context_report_text(context: Any) -> str:
    parts: list[str] = []
    for payload in dict(getattr(context, "reports", {}) or {}).values():
        if isinstance(payload, dict):
            parts.append(str(payload.get("content") or payload.get("summary") or ""))
        else:
            parts.append(str(payload or ""))
    return "\n".join(part for part in parts if part)[:12000]


async def _settlement_mentions_for_cluster_mapping(
    context: Any,
    intent: Any,
) -> list[str]:
    """Collect settlement names from typed facts and one cached flash pass."""

    names: list[str] = []
    settlement_types = {
        "AdministrativeVillage",
        "ResidentialCluster",
        "administrative_village",
        "residential_cluster",
        "village",
    }
    for fact in list(getattr(context, "location_facts", []) or []):
        kind = str(
            getattr(fact, "entity_type", "")
            or getattr(fact, "place_type", "")
            or getattr(fact, "role", "")
            or ""
        )
        name = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "name", "")
            or ""
        ).strip()
        if name and kind in settlement_types:
            names.append(name)

    texts: list[str] = []
    fields = (
        "zone_targets",
        "facilities",
        "development_axes",
        "road_targets",
        "project_targets",
    )
    for field in fields:
        targets = intent.get(field, []) if isinstance(intent, dict) else getattr(intent, field, [])
        for target in list(targets or []):
            semantic = target.get("semantic", {}) if isinstance(target, dict) else getattr(target, "semantic", None)
            for attr in ("raw_text", "spatial_hint", "natural_language_description"):
                value = semantic.get(attr, "") if isinstance(semantic, dict) else getattr(semantic, attr, "")
                if value:
                    texts.append(str(value))
            for attr in ("location_hint", "connects"):
                value = target.get(attr) if isinstance(target, dict) else getattr(target, attr, None)
                if isinstance(value, list):
                    texts.extend(str(item) for item in value if item)
                elif value:
                    texts.append(str(value))

    combined = "\n".join(texts)[:5000]
    if combined:
        from app.infrastructure.paths import session_run_dir
        from app.spatial.grounding.flash_mention_extractor import MentionCache, extract_mentions

        cache = MentionCache(run_tmp_root() / "settlement-mention-cache.json")
        for mention in await extract_mentions(combined, cache=cache):
            if mention.role == "village" and mention.mention:
                names.append(mention.mention)
    return list(dict.fromkeys(names))


__all__ = ["ground_node"]
