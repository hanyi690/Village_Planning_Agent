"""Replay provider for a previously completed real L1/L2/L3 run.

The provider is deliberately test-only.  It does not invent planning content:
L2 and L3 values are loaded from the recorded CAS payloads and L1 values are
projected back from the recorded typed ``L1Fact`` records into the exact
discriminated union accepted by the L1 observe pass.  Spatial identity is
still resolved by the live source index, KG/evidence services and GROUND.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from langchain_core.messages import AIMessageChunk


_CAS_DIGESTS = {
    "l1": "aa81723a5f32bdff6f8335963da13bef6b2309936f656af37a831efbf209a8a5",
    "l2": "16e13728179eb4debc369f0b0928e16cd22015729f49ee09a6f87263dedd5b9c",
    "program": "8a094156cecc3ace64d636411c56428524216fac50f6ac0bdc55cb001f7ee764",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _claim_component_kind(claim: Any) -> str:
    category = _text(getattr(claim, "suggested_category", ""))
    if category in {"facility", "road", "axis", "site_area"}:
        return category
    if category == "restoration":
        return "restoration_overlay"
    if category == "protection":
        return "protection_overlay"
    if category == "zone":
        parameters = getattr(claim, "polygon_parameters", None)
        role = _text(getattr(parameters, "materialization_role", ""))
        return {
            "land_use_assignment": "land_use_assignment",
            "protection_overlay": "protection_overlay",
            "restoration_overlay": "restoration_overlay",
            "site_footprint": "site_area",
        }.get(role, "zone")
    return "non_spatial_action"


def _claims_as_provider_output(response_model: type[Any], claims: Iterable[Any]) -> Any:
    rows = []
    for claim in claims:
        row = claim.model_dump(mode="python", exclude_none=True)
        row["component_kind"] = _claim_component_kind(claim)
        rows.append(row)
    return response_model.model_validate({"claims": rows})


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [_text(item) for item in value if _text(item)]


def _split_source_refs(source_refs: Iterable[Any]) -> tuple[list[str], list[str], str]:
    """Recover the input refs, L1 segment refs and report id from a fact.

    The L1 compiler appends the report id after ``source_refs`` and
    ``source_segment_ids``.  The CAS preserves that order, so replay can
    reconstruct the provider envelope without parsing prose or guessing IDs.
    """

    refs = _as_list(list(source_refs))
    if not refs:
        return [], [], ""
    report_id = refs[-1]
    body = refs[:-1]
    segment_refs = [ref for ref in body if ref.startswith("l1:")]
    input_refs = [ref for ref in body if not ref.startswith("l1:")]
    return input_refs, segment_refs, report_id


def _recover_locator_fields(record: dict[str, Any], attrs: dict[str, Any]) -> tuple[str, str]:
    """Recover provider locator values from the compiler's typed statement.

    ``attributes`` is intentionally open-ended.  A model may use an attribute
    named ``location`` for a prose description while the typed locator carries
    the canonical place.  The compiler's semicolon-delimited projection is the
    stable, typed boundary available in the recorded CAS, so we use its field
    order rather than text matching or dimension-specific exceptions.
    """

    parts = [_text(value) for value in _text(record.get("statement")).split("；")]
    name = _text(attrs.get("name"))
    description = _text(attrs.get("description"))
    cursor = 1 if parts and parts[0] == name else 0
    if description and cursor < len(parts) and parts[cursor] == description:
        cursor += 1
    tail = parts[cursor:]
    value = record.get("value")
    unit = _text(record.get("unit"))
    if value is not None and tail:
        value_suffix = f"{value}{unit}"
        if tail[-1].endswith(value_suffix) and "=" in tail[-1]:
            tail = tail[:-1]
    relation = _text(attrs.get("relation"))
    if relation and relation in tail:
        tail = [part for part in tail if part != relation]
    location = tail[0] if tail else _text(attrs.get("location"))
    return location, relation


def _record_to_observation(record: dict[str, Any]) -> dict[str, Any] | None:
    """Invert one CAS L1Fact into the provider's typed union payload."""

    attrs = dict(record.get("attributes") or {})
    fact_type = _text(attrs.get("fact_type"))
    if not fact_type:
        return None
    source_refs, source_segment_ids, report_id = _split_source_refs(
        record.get("source_refs") or []
    )
    if report_id:
        source_refs.append(report_id)
    common: dict[str, Any] = {
        "semantic_type": _text(record.get("semantic_type")),
        "description": _text(attrs.get("description")),
        "attributes": attrs,
        "value": record.get("value"),
        "unit": _text(record.get("unit")),
        "counting_basis": _text(record.get("counting_basis")),
        "related_observation_ids": _as_list(attrs.get("related_observation_ids")),
        "constraint_refs": _as_list(attrs.get("constraint_refs")),
        "source_feature_ids": _as_list(record.get("source_feature_ids")),
        "source_segment_ids": source_segment_ids,
        "source_quote": _text(record.get("source_span")),
        "source_refs": source_refs,
        "confidence": record.get("confidence"),
        "status": "confirmed",
        "fact_type": fact_type,
    }
    name = _text(attrs.get("name"))
    location, relation = _recover_locator_fields(record, attrs)
    scope = _text(record.get("subject_scope"))

    if fact_type == "spatial_entity":
        common.update({
            "entity_type": _text(attrs.get("entity_type")),
            "name": name,
            "locator": {
                "place_names": [location] if location else [],
                "relation": relation,
                "source_feature_ids": _as_list(record.get("source_feature_ids")),
            },
            "scale": _text(attrs.get("scale")),
        })
    elif fact_type == "spatial_relation":
        common.update({
            "subject_ref": name,
            "predicate": relation,
            "object_ref": location,
        })
    elif fact_type == "scoped_metric":
        common.update({
            "metric": _text(attrs.get("metric")) or name,
            "scope": scope,
        })
    elif fact_type == "demand":
        spatial_requirement = _text(attrs.get("spatial_requirement"))
        if spatial_requirement not in {"none", "place_binding", "demand_points"}:
            spatial_requirement = "place_binding" if location else "none"
        common.update({
            "demand_type": name,
            "scope": scope,
            "beneficiary": _text(attrs.get("beneficiary")),
            "spatial_requirement": spatial_requirement,
            "locator": {
                "place_names": [location] if location else [],
                "relation": relation,
                "source_feature_ids": _as_list(record.get("source_feature_ids")),
            },
        })
    elif fact_type == "constraint":
        strength = _text(attrs.get("strength"))
        if strength not in {"hard", "soft", "unknown"}:
            strength = "unknown"
        common.update({
            "constraint_type": name,
            "applies_to_scope": scope,
            "strength": strength,
            "locator": {
                "place_names": [location] if location else [],
                "relation": relation,
                "source_feature_ids": _as_list(record.get("source_feature_ids")),
            },
        })
    elif fact_type in {"risk", "opportunity"}:
        common.update({
            "subject": name,
            "scope": scope,
            "locator": {
                "place_names": [location] if location else [],
                "relation": relation,
                "source_feature_ids": _as_list(record.get("source_feature_ids")),
            },
        })
    elif fact_type == "document_observation":
        common.update({"subject": name, "scope": scope})
    else:
        return None
    return common


def _measure(value: Any, unit: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"value": value, "unit": unit}


def _normalized_claim_to_draft(
    raw: dict[str, Any],
    *,
    source_fact_index: dict[str, tuple[str, ...]] | None = None,
) -> Any:
    """Project an authoritative CAS claim back to the provider draft shape."""

    from app.contracts.program import PlanningClaim
    from app.domain.program.claim_draft import PlanningClaimDraft

    source_fact_index = source_fact_index or {}
    source_fact_refs = []
    for source_ref in raw.get("source_fact_refs") or []:
        source_ref = _text(source_ref)
        mapped = source_fact_index.get(source_ref)
        if mapped:
            source_fact_refs.extend(mapped)
        else:
            source_fact_refs.append(source_ref)
    raw = {**raw, "source_fact_refs": list(dict.fromkeys(source_fact_refs))}
    claim = PlanningClaim.model_validate(raw)
    payload = claim.model_dump(mode="json")
    facility = payload.get("facility_parameters")
    if facility:
        payload["facility_parameters"] = {
            "facility_type": facility.get("facility_type", ""),
            "action": facility.get("action", "new"),
            "service_radius": _measure(facility.get("service_radius_m"), "m"),
            "capacity": _measure(facility.get("capacity"), facility.get("capacity_unit", "")),
            "footprint_area": _measure(facility.get("footprint_area_m2"), "m2"),
        }
    road = payload.get("road_parameters")
    if road:
        payload["road_parameters"] = {
            "action": road.get("action", "new"),
            "road_level": road.get("road_level", ""),
            "length": _measure(road.get("length_m"), "m"),
            "roadbed_width": _measure(road.get("roadbed_width_m"), "m"),
            "pavement_width": _measure(road.get("pavement_width_m"), "m"),
            "alignment_refs": road.get("alignment_refs") or [],
            "connects": road.get("connects") or [],
        }
    linear = payload.get("linear_parameters")
    if linear:
        payload["linear_parameters"] = {
            "action": linear.get("action", "new"),
            "length": _measure(linear.get("length_m"), "m"),
            "diameter": _measure(linear.get("diameter_mm"), "mm"),
            "material": linear.get("material", ""),
            "alignment_refs": linear.get("alignment_refs") or [],
            "connects": linear.get("connects") or [],
        }
    axis = payload.get("axis_parameters")
    if axis:
        payload["axis_parameters"] = {
            "action": axis.get("action", "new"),
            "axis_type": axis.get("axis_type", "primary"),
            "direction": axis.get("direction", ""),
            "reference_features": axis.get("reference_features") or [],
            "connects": axis.get("connects") or [],
            "corridor_width": _measure(axis.get("corridor_width_m"), "m"),
        }
    polygon = payload.get("polygon_parameters")
    if polygon:
        area = payload.get("area_range_ha")
        payload["polygon_parameters"] = {
            "materialization_role": polygon.get("materialization_role"),
            "planning_zone": polygon.get("planning_zone", ""),
            "land_use": polygon.get("land_use", ""),
            "area_range": (
                {"minimum": area[0], "maximum": area[1], "unit": "ha"}
                if isinstance(area, (list, tuple)) and len(area) == 2
                else None
            ),
        }
    site = payload.get("site_area_parameters")
    if site:
        payload["site_area_parameters"] = {
            "site_type": site.get("site_type", ""),
            "action": site.get("action", "new"),
            "capacity": _measure(site.get("capacity"), site.get("capacity_unit", "")),
            "footprint_area": _measure(site.get("footprint_area_m2"), "m2"),
        }
    return PlanningClaimDraft.model_validate(payload)


@dataclass
class RecordedPlanningProvider:
    """Quota-free provider that replays one real CAS run."""

    run_root: str | Path
    session_dir: str | Path
    claim_ids: frozenset[str] | set[str] | None = None
    calls: dict[str, int] = field(default_factory=dict)
    replay_mode: str = field(init=False)
    source_artifact_ref: str = field(init=False)
    source_lineage: dict[str, tuple[str, ...]] = field(init=False)

    def __post_init__(self) -> None:
        self.run_root = Path(self.run_root)
        self.session_dir = Path(self.session_dir)
        self.claim_ids = frozenset(self.claim_ids or ()) or None
        self.replay_mode = "recorded_cas_source_lineage"
        self.source_artifact_ref = (
            f"replay://{self.session_dir.name}/cas/sha256/{_CAS_DIGESTS['l1']}"
        )
        self._l1 = self._load_cas(_CAS_DIGESTS["l1"])
        self._l2 = self._load_cas(_CAS_DIGESTS["l2"])
        self._program = self._load_cas(_CAS_DIGESTS["program"])
        self._facts_by_dimension: dict[str, list[dict[str, Any]]] = {}
        source_fact_index: dict[str, set[str]] = {}
        for record in self._l1.get("fact_records") or []:
            dimension = _text(record.get("dimension_key"))
            if dimension:
                self._facts_by_dimension.setdefault(dimension, []).append(record)
            fact_id = _text(record.get("fact_id"))
            if fact_id:
                source_fact_index.setdefault(fact_id, set()).add(fact_id)
                for source_ref in record.get("source_refs") or []:
                    source_ref = _text(source_ref)
                    if source_ref:
                        source_fact_index.setdefault(source_ref, set()).add(fact_id)
                        if not source_ref.startswith("l1:fact:"):
                            source_fact_index.setdefault(f"l1:fact:{source_ref}", set()).add(fact_id)
        self._source_fact_index = {
            key: tuple(sorted(values)) for key, values in source_fact_index.items()
        }
        self.source_lineage = {}
        for raw in self._program.get("claims") or []:
            for source_ref in raw.get("source_fact_refs") or []:
                source_ref = _text(source_ref)
                mapped = self._source_fact_index.get(source_ref)
                if mapped:
                    self.source_lineage[source_ref] = mapped
        self._claims_by_dimension: dict[str, list[Any]] = {}
        for raw in self._program.get("claims") or []:
            claim = _normalized_claim_to_draft(
                raw,
                source_fact_index=self._source_fact_index,
            )
            if self.claim_ids is not None and claim.claim_id not in self.claim_ids:
                continue
            self._claims_by_dimension.setdefault(claim.dimension_key, []).append(claim)

    def _count(self, key: str) -> None:
        self.calls[key] = self.calls.get(key, 0) + 1

    def authoritative_l1_snapshot(self) -> Any:
        from app.contracts.domain.l1_contracts import L1Snapshot

        return L1Snapshot.model_validate(self._l1)

    def authoritative_source_index(self) -> Any:
        """Build the explicit replay-only source transport from CAS facts.

        The original upload body is not part of the recorded session.  This
        index therefore uses only the CAS fact's original segment IDs, source
        refs and quoted spans.  It is installed by the acceptance harness,
        never by production source-index construction or source validation.
        """

        import hashlib

        from app.contracts.domain.l1_contracts import L1SourceIndex, L1SourceSegment

        segment_rows: dict[str, dict[str, Any]] = {}
        for record in self._l1.get("fact_records") or []:
            input_refs, segment_refs, _report_id = _split_source_refs(
                record.get("source_refs") or []
            )
            quote = _text(record.get("source_span")) or _text(record.get("statement"))
            for index, segment_id in enumerate(segment_refs):
                source_ref = (
                    input_refs[index]
                    if index < len(input_refs)
                    else (input_refs[0] if input_refs else segment_id)
                )
                source_key = source_ref.split(":", 2)[1] if source_ref.startswith("input:") else "recorded"
                row = segment_rows.setdefault(
                    segment_id,
                    {
                        "source_key": source_key,
                        "source_ref": source_ref,
                        "quotes": [],
                    },
                )
                if quote and quote not in row["quotes"]:
                    row["quotes"].append(quote)

        source_segments = [
            L1SourceSegment(
                segment_id=segment_id,
                source_key=str(row["source_key"]),
                source_ref=str(row["source_ref"]),
                content_digest=_CAS_DIGESTS["l1"],
                start_char=0,
                end_char=sum(len(value) for value in row["quotes"]),
                start_line=1,
                end_line=max(1, len(row["quotes"])),
                text="\n".join(row["quotes"]) or segment_id,
                section_path=["recorded_cas", str(row["source_key"])],
            )
            for segment_id, row in sorted(segment_rows.items())
        ]
        source_documents = sorted({
            str(item.get("reference") or "")
            for item in self._l1.get("sources") or []
            if isinstance(item, dict) and str(item.get("reference") or "").strip()
        })
        digest = hashlib.sha256(
            json.dumps(
                [
                    {
                        "segment_id": item.segment_id,
                        "source_ref": item.source_ref,
                        "text": item.text,
                    }
                    for item in source_segments
                ],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return L1SourceIndex(
            source_documents=source_documents,
            source_digest=f"replay-source:{digest}",
            source_segments=source_segments,
            diagnostics=[
                "replay_only_source_index",
                f"source_artifact_ref:{self.source_artifact_ref}",
            ],
        )

    def _load_cas(self, digest: str) -> dict[str, Any]:
        path = self.run_root / "blobs" / "sha256" / digest
        if not path.is_file():
            raise FileNotFoundError(f"recorded CAS payload missing: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError(f"recorded CAS payload must be an object: {path}")
        return payload

    def _report_body(self, dimension_key: str) -> str:
        records = self._facts_by_dimension.get(dimension_key) or []
        facts = self._l1.get("facts_by_dimension", {}).get(dimension_key) or []
        lines = [f"【{dimension_key}·recorded L1 report】"]
        lines.extend(_text(value) for value in facts if _text(value))
        if not facts and records:
            lines.extend(_text(record.get("statement")) for record in records if _text(record.get("statement")))
        if not lines[1:]:
            lines.append("【证据边界】本维度没有已核验的结构化事实。")
        return "\n".join(lines)

    def l1_observation_output(self, dimension_key: str) -> Any:
        from app.domain.assessment.observation_draft import L1ObservationPassOutput

        self._count(f"L1:observe:{dimension_key}")
        observations = [
            raw
            for record in self._facts_by_dimension.get(dimension_key, [])
            if (raw := _record_to_observation(record)) is not None
        ]
        return L1ObservationPassOutput(observations=observations)

    def l1_report_output(self, dimension_key: str) -> Any:
        from app.domain.assessment.observation_draft import L1ReportOutput

        self._count(f"L1:report:{dimension_key}")
        return L1ReportOutput(report_body=self._report_body(dimension_key))

    def _dimension_from_prompt(self, prompt: str) -> str:
        marker = "dimension_key="
        if marker not in prompt:
            raise AssertionError("recorded replay prompt is missing dimension_key")
        value = prompt.split(marker, 1)[1]
        return value.split("】", 1)[0].split("\n", 1)[0].strip()

    async def structured_output(
        self,
        response_model: type[Any],
        messages: list[dict[str, Any]],
        **_: Any,
    ) -> Any:
        name = getattr(response_model, "__name__", "")
        prompt = "\n".join(_text(item.get("content")) for item in messages)
        if name == "SourceFeatureSemanticProposalBatch":
            from app.contracts.evidence.source_semantic_contracts import (
                SourceFeatureSemanticProposal,
                SourceFeatureSemanticProposalBatch,
            )

            self._count("source_semantic:identity")
            payload = json.loads(_text(messages[-1].get("content")) or "{}")
            return SourceFeatureSemanticProposalBatch(
                proposals=[
                    SourceFeatureSemanticProposal(
                        source_feature_id=_text(item.get("source_feature_id"))
                    )
                    for item in payload.get("source_items") or []
                ]
            )

        dimension_key = self._dimension_from_prompt(prompt)
        if name.startswith(("L1ObservationPassOutput", "L1ObservationProviderOutput")):
            result = self.l1_observation_output(dimension_key)
            return response_model.model_validate(result.model_dump(mode="python"))
        if name == "L1ReportOutput":
            return self.l1_report_output(dimension_key)
        if name == "L2DecisionSet":
            from app.contracts.domain.l2_contracts import L2DecisionSet

            self._count(f"L2:{dimension_key}")
            raw = next(
                item for item in self._l2.get("decision_sets") or []
                if _text(item.get("dimension_key")) == dimension_key
            )
            return L2DecisionSet.model_validate(raw)
        if name.startswith("L3ClaimOutput"):
            self._count(f"L3:claims:{dimension_key}")
            return _claims_as_provider_output(
                response_model,
                self._claims_by_dimension.get(dimension_key) or [],
            )
        if name == "L3ReportOutput":
            from app.domain.program.claim_draft import L3ReportOutput

            self._count(f"L3:report:{dimension_key}")
            report_dir = self.session_dir / "l3-projection-cache" / "report" / dimension_key
            bodies: list[str] = []
            if report_dir.is_dir():
                for path in report_dir.glob("*.json"):
                    try:
                        raw = json.loads(path.read_text(encoding="utf-8"))
                        body = _text(raw.get("report_body"))
                        if body:
                            bodies.append(body)
                    except (OSError, ValueError, TypeError):
                        continue
            body = max(bodies, key=len) if bodies else self._report_body(dimension_key)
            return L3ReportOutput(report_body=body)
        raise AssertionError(f"unhandled recorded structured contract: {name}")

    async def astream(self, prompt: str):
        dimension_key = self._dimension_from_prompt(prompt)
        raw = next(
            item for item in self._l2.get("decision_sets") or []
            if _text(item.get("dimension_key")) == dimension_key
        )
        text = json.dumps(raw, ensure_ascii=False)
        self._count(f"L2:stream:{dimension_key}")
        for index in range(0, len(text), 240):
            yield AIMessageChunk(content=text[index:index + 240])


__all__ = ["RecordedPlanningProvider"]
