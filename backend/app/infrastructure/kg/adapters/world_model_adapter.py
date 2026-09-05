"""Read-only adapter over generic KG cognition support nodes."""

from __future__ import annotations

import hashlib
from typing import Any

from rdflib import RDF, URIRef

from app.infrastructure.kg.ontology import PLN


_WORLD_GRAPH = "urn:planning:graph:world"


class _LazyNetworkRetryAdapter:
    """Defer the compatibility retry index until a road retry is requested."""

    def __init__(self, kg: Any) -> None:
        self._kg = kg
        self._adapter: Any | None = None

    def __call__(self, retry_payload: Any) -> Any:
        if self._adapter is None:
            from app.spatial.network import RDFLibKGSpatialRetryAdapter

            self._adapter = RDFLibKGSpatialRetryAdapter(self._kg)
        return self._adapter(retry_payload)


class KGWorldModelAdapter:
    def __init__(self, kg: Any):
        self._kg = kg
        self._index_token: tuple[Any, ...] | None = None
        self._entity_rows: dict[str, dict[str, Any]] = {}
        self._entity_order: tuple[str, ...] = ()
        self._entity_keys_by_ref: dict[str, set[str]] = {}
        self._entity_keys_by_source: dict[str, set[str]] = {}
        self._entity_keys_by_name: dict[str, set[str]] = {}
        self._representations_by_entity: dict[str, list[dict[str, Any]]] = {}
        self._identity_rows: dict[str, dict[str, Any]] = {}
        self._identity_order: tuple[str, ...] = ()
        self._identity_keys_by_mention: dict[str, set[str]] = {}
        self._identity_keys_by_entity: dict[str, set[str]] = {}
        self._identity_keys_by_status: dict[str, set[str]] = {}
        self._identity_keys_by_work_item: dict[str, set[str]] = {}
        self._identity_keys_by_source_mention: dict[str, set[str]] = {}
        self._identity_keys_by_dimension: dict[str, set[str]] = {}
        self._identity_keys_by_scope: dict[str, set[str]] = {}

    @staticmethod
    def _name_key(value: Any) -> str:
        return "".join(str(value or "").split()).casefold()

    def _representation_row(
        self,
        graph: Any,
        representation: Any,
        *,
        entity_part_ref: str,
    ) -> dict[str, Any]:
        component_refs = sorted({
            str(value)
            for value in graph.objects(representation, PLN.componentRef)
            if str(value).strip()
        })
        return {
            "entity_part_ref": entity_part_ref,
            "representation_ref": str(
                graph.value(representation, PLN.representationRef)
                or representation
            ),
            "resource_ref": str(
                graph.value(representation, PLN.resourceRef) or ""
            ),
            "geometry_ref": str(
                graph.value(representation, PLN.geometryRef) or ""
            ),
            "purpose": str(
                graph.value(representation, PLN.representationPurpose) or ""
            ),
            "geometry_kind": str(
                graph.value(representation, PLN.geometryKind) or ""
            ),
            "crs": str(graph.value(representation, PLN.crs) or ""),
            "source_crs": str(
                graph.value(representation, PLN.sourceCrs) or ""
            ),
            "normalized_crs": str(
                graph.value(representation, PLN.normalizedCrs) or ""
            ),
            "source_snapshot_ref": str(
                graph.value(representation, PLN.sourceSnapshotRef) or ""
            ),
            "content_digest": str(
                graph.value(representation, PLN.contentDigest) or ""
            ),
            "component_refs": component_refs,
            "component_representation_refs": sorted({
                str(value)
                for value in graph.objects(
                    representation,
                    PLN.componentRepresentationRef,
                )
                if str(value).strip()
            }),
            "representation_status": (
                "composite" if component_refs else "available"
            ),
        }

    def _ensure_indexes(self) -> None:
        graph = getattr(self._kg, "g", None)
        if graph is None:
            return
        token = (
            id(graph),
            len(graph),
            getattr(self._kg, "version", None),
            str(getattr(self._kg, "snapshot_digest", "") or ""),
        )
        if token == self._index_token:
            return

        entity_rows: dict[str, dict[str, Any]] = {}
        entity_keys_by_ref: dict[str, set[str]] = {}
        entity_keys_by_source: dict[str, set[str]] = {}
        entity_keys_by_name: dict[str, set[str]] = {}
        representations_by_entity: dict[str, list[dict[str, Any]]] = {}
        subjects = sorted(
            {subject for subject in graph.subjects(RDF.type, PLN.WorldEntity)},
            key=str,
        )
        for subject in subjects:
            subject_ref = str(subject)
            entity_identity = str(
                graph.value(subject, PLN.entityIdentity) or ""
            )
            parts: list[dict[str, Any]] = []
            representation_links: list[tuple[str, Any]] = []
            for part in graph.objects(subject, PLN.hasEntityPart):
                representation_links.extend(
                    (str(part), representation)
                    for representation in graph.objects(
                        part, PLN.hasSpatialRepresentation
                    )
                )
                source_refs = sorted({
                    str(value)
                    for value in graph.objects(part, PLN.sourceFeatureRef)
                    if str(value).strip()
                })
                if not source_refs:
                    continue
                dataset_ref = str(
                    graph.value(part, PLN.sourceDatasetRef) or ""
                )
                for source_ref in source_refs:
                    parts.append({
                        "entity_part_ref": str(part),
                        "source_feature_ref": source_ref,
                        "dataset_ref": dataset_ref,
                        "geometry_kind": str(
                            graph.value(part, PLN.geometryKind) or ""
                        ),
                    })
                    for source_key in (
                        source_ref,
                        f"{dataset_ref}:{source_ref}" if dataset_ref else "",
                        f"resource:{dataset_ref}:{source_ref}"
                        if dataset_ref
                        else "",
                    ):
                        if source_key:
                            entity_keys_by_source.setdefault(
                                source_key, set()
                            ).add(subject_ref)
            representation_links.extend(
                ("", representation)
                for representation in graph.objects(
                    subject, PLN.hasSpatialRepresentation
                )
            )
            seen_representations: set[str] = set()
            representations: list[dict[str, Any]] = []
            for entity_part_ref, representation in representation_links:
                representation_node_ref = str(representation)
                if representation_node_ref in seen_representations:
                    continue
                seen_representations.add(representation_node_ref)
                representations.append(
                    self._representation_row(
                        graph,
                        representation,
                        entity_part_ref=entity_part_ref,
                    )
                )
            canonical_name = str(
                graph.value(subject, PLN.canonicalName) or ""
            )
            aliases = sorted({
                str(value)
                for value in graph.objects(subject, PLN.alias)
                if str(value).strip()
            })
            concept_types = sorted({
                str(value)
                for value in graph.objects(subject, PLN.conceptType)
                if str(value).strip()
            })
            entity_rows[subject_ref] = {
                "entity_ref": subject_ref,
                "entity_identity": entity_identity,
                "canonical_name": canonical_name,
                "aliases": aliases,
                "concept_types": concept_types,
                "status": str(
                    graph.value(subject, PLN.entityStatus) or "unresolved"
                ),
                "parts": parts,
            }
            for entity_key in (subject_ref, entity_identity):
                if entity_key:
                    entity_keys_by_ref.setdefault(
                        entity_key, set()
                    ).add(subject_ref)
                    representations_by_entity.setdefault(
                        entity_key, representations
                    )
            for label in (canonical_name, *aliases):
                name_key = self._name_key(label)
                if name_key:
                    entity_keys_by_name.setdefault(
                        name_key, set()
                    ).add(subject_ref)

        self._entity_rows = entity_rows
        self._entity_order = tuple(sorted(entity_rows))
        self._entity_keys_by_ref = entity_keys_by_ref
        self._entity_keys_by_source = entity_keys_by_source
        self._entity_keys_by_name = entity_keys_by_name
        self._representations_by_entity = representations_by_entity
        identity_graph = getattr(self._kg, "identity_graph", graph)
        identity_rows: dict[str, dict[str, Any]] = {}
        identity_keys_by_mention: dict[str, set[str]] = {}
        identity_keys_by_entity: dict[str, set[str]] = {}
        identity_keys_by_status: dict[str, set[str]] = {}
        identity_keys_by_work_item: dict[str, set[str]] = {}
        identity_keys_by_source_mention: dict[str, set[str]] = {}
        identity_keys_by_dimension: dict[str, set[str]] = {}
        identity_keys_by_scope: dict[str, set[str]] = {}
        identity_subjects = sorted(
            set(identity_graph.subjects(RDF.type, PLN.IdentityBinding)),
            key=str,
        )
        for subject in identity_subjects:
            row = self._identity_binding_row(identity_graph, subject)
            key = row["binding_ref"]
            identity_rows[key] = row
            for index, values in (
                (identity_keys_by_mention, [row["mention_ref"]]),
                (
                    identity_keys_by_entity,
                    [
                        row["canonical_entity_ref"],
                        *row["candidate_entity_refs"],
                        *row["anchor_entity_refs"],
                    ],
                ),
                (identity_keys_by_status, [row["identity_status"]]),
                (identity_keys_by_work_item, [row["work_item_ref"]]),
                (
                    identity_keys_by_source_mention,
                    row["source_mention_refs"],
                ),
                (identity_keys_by_dimension, row["dimension_refs"]),
                (identity_keys_by_scope, row["scope_refs"]),
            ):
                for value in values:
                    if value:
                        index.setdefault(value, set()).add(key)
        self._identity_rows = identity_rows
        self._identity_order = tuple(sorted(identity_rows))
        self._identity_keys_by_mention = identity_keys_by_mention
        self._identity_keys_by_entity = identity_keys_by_entity
        self._identity_keys_by_status = identity_keys_by_status
        self._identity_keys_by_work_item = identity_keys_by_work_item
        self._identity_keys_by_source_mention = (
            identity_keys_by_source_mention
        )
        self._identity_keys_by_dimension = identity_keys_by_dimension
        self._identity_keys_by_scope = identity_keys_by_scope
        self._index_token = token

    def find_entities(
        self,
        *,
        identity: str = "",
        entity_ref: str = "",
        source_feature_ref: str = "",
        name: str = "",
        entity_type: str = "",
        limit: int = 50,
        **_: Any,
    ) -> list[dict[str, Any]]:
        self._ensure_indexes()
        result: list[dict[str, Any]] = []
        try:
            from app.infrastructure.cognition_runtime.world_model_store import (
                ASSERTION_GRAPH,
                WORLD_GRAPH,
            )

            allowed_graphs = {str(ASSERTION_GRAPH), str(WORLD_GRAPH)}
        except Exception:
            allowed_graphs = set()
        limit = max(1, int(limit))
        candidate_keys: set[str] | None = None

        def intersect(values: set[str]) -> None:
            nonlocal candidate_keys
            candidate_keys = (
                set(values)
                if candidate_keys is None
                else candidate_keys.intersection(values)
            )

        if entity_ref:
            intersect(
                self._entity_keys_by_ref.get(str(entity_ref), set())
            )
        if identity:
            intersect(self._entity_keys_by_ref.get(str(identity), set()))
        if source_feature_ref:
            intersect(
                self._entity_keys_by_source.get(
                    str(source_feature_ref), set()
                )
            )
        if name:
            intersect(
                self._entity_keys_by_name.get(
                    self._name_key(name), set()
                )
            )
        ordered_keys = (
            sorted(candidate_keys)
            if candidate_keys is not None
            else list(self._entity_order)
        )
        for key in ordered_keys:
            row = self._entity_rows.get(key)
            if row is None:
                continue
            if entity_type:
                wanted_type = str(entity_type).rsplit("#", 1)[-1].casefold()
                concepts = [
                    str(value).rsplit("#", 1)[-1].casefold()
                    for value in row.get("concept_types", ())
                ]
                if concepts and not any(wanted_type in concept or concept in wanted_type for concept in concepts):
                    continue
            result_row = dict(row)
            result_row["parts"] = [dict(part) for part in row.get("parts", ())]
            result.append(result_row)
            if len(result) >= limit:
                break
        return result

    def representations_for(self, entity_ref: str, *, limit: int = 50) -> list[dict[str, Any]]:
        self._ensure_indexes()
        rows = self._representations_by_entity.get(
            str(entity_ref), ()
        )
        return [
            dict(item)
            for item in rows[:max(1, int(limit))]
        ]

    def find_relations(
        self,
        *,
        subject_ref: str = "",
        object_ref: str = "",
        predicate: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Expose bounded KG assertions without leaking RDF to GROUND."""

        graph = getattr(self._kg, "g", None)
        if graph is None:
            return []
        allowed_graphs = {_WORLD_GRAPH}
        wanted_predicate = str(predicate or "").strip().casefold()
        result: list[dict[str, Any]] = []
        # Dataset iteration yields quads (the fourth item is the named graph),
        # while a plain Graph yields triples.  Keep the adapter usable for
        # both local implementations without making callers know the store
        # type.
        if callable(getattr(graph, "quads", None)):
            quad_iter = graph.quads((None, None, None, None))
        else:
            quad_iter = ((subject, pred, obj, None) for subject, pred, obj in graph)
        for subject, pred, obj, _graph_name in quad_iter:
            if _graph_name is not None and allowed_graphs and str(_graph_name) not in allowed_graphs:
                continue
            if pred == RDF.type or not isinstance(obj, URIRef):
                continue
            subject_text = str(subject)
            object_text = str(obj)
            predicate_text = str(pred)
            local_predicate = predicate_text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            if subject_ref and subject_text != str(subject_ref):
                continue
            if object_ref and object_text != str(object_ref):
                continue
            if wanted_predicate and (
                predicate_text.casefold() != wanted_predicate
                and local_predicate.casefold() != wanted_predicate
            ):
                continue
            relation_id = "relation:" + hashlib.sha256(
                f"{subject_text}|{predicate_text}|{object_text}".encode("utf-8")
            ).hexdigest()[:24]
            result.append({
                "relation_id": relation_id,
                "subject_ref": subject_text,
                "predicate": predicate_text,
                "object_ref": object_text,
                "snapshot_digest": str(getattr(self._kg, "snapshot_digest", "") or ""),
                "provenance_refs": [],
            })
            if len(result) >= max(1, int(limit)):
                break
        return result

    @staticmethod
    def _literal_values(graph: Any, subject: Any, predicate: Any) -> list[str]:
        return sorted({
            str(value).strip()
            for value in graph.objects(subject, predicate)
            if str(value).strip()
        })

    def _identity_binding_row(
        self,
        graph: Any,
        subject: Any,
    ) -> dict[str, Any]:
        expression = graph.value(subject, PLN.hasLocationExpression)
        confidence_text = str(
            graph.value(subject, PLN.bindingConfidence) or "0"
        )
        try:
            confidence = float(confidence_text)
        except (TypeError, ValueError):
            confidence = 0.0
        version_text = str(
            graph.value(subject, PLN.projectedAtWorldModelVersion) or "0"
        )
        try:
            projected_version = int(version_text)
        except (TypeError, ValueError):
            projected_version = 0
        return {
            "binding_ref": str(
                graph.value(subject, PLN.bindingRef) or subject
            ).strip(),
            "mention_ref": str(
                graph.value(subject, PLN.mentionRef) or ""
            ).strip(),
            "work_item_ref": str(
                graph.value(subject, PLN.workItemRef) or ""
            ).strip(),
            "canonical_entity_ref": str(
                graph.value(subject, PLN.canonicalEntityRef) or ""
            ).strip(),
            "identity_status": str(
                graph.value(subject, PLN.identityStatus) or "unresolved"
            ).strip().casefold(),
            "candidate_entity_refs": self._literal_values(
                graph, subject, PLN.candidateEntityRef
            ),
            "observation_refs": self._literal_values(
                graph, subject, PLN.observationRef
            ),
            "source_mention_refs": self._literal_values(
                graph, subject, PLN.sourceMentionRef
            ),
            "representation_refs": self._literal_values(
                graph, subject, PLN.representationRef
            ),
            "resource_refs": self._literal_values(
                graph, subject, PLN.resourceRef
            ),
            "entity_part_refs": self._literal_values(
                graph, subject, PLN.entityPartRef
            ),
            "source_feature_refs": self._literal_values(
                graph, subject, PLN.sourceFeatureRef
            ),
            "candidate_refs": self._literal_values(
                graph, subject, PLN.evidenceCandidateRef
            ),
            "evidence_refs": self._literal_values(
                graph, subject, PLN.evidenceRef
            ),
            "relation_evidence_refs": self._literal_values(
                graph, subject, PLN.relationEvidenceRef
            ),
            "dimension_refs": self._literal_values(
                graph, subject, PLN.dimensionRef
            ),
            "scope_refs": self._literal_values(
                graph, subject, PLN.scopeRef
            ),
            "relation_refs": self._literal_values(
                graph, subject, PLN.relationMentionRef
            ),
            "binding_status": str(
                graph.value(subject, PLN.bindingStatus) or "unresolved"
            ),
            "confidence": confidence,
            "uncertainty_reason": str(
                graph.value(subject, PLN.uncertaintyReason) or ""
            ),
            "spatial_hint": str(
                graph.value(subject, PLN.spatialHint) or ""
            ),
            "observed_name": str(
                graph.value(subject, PLN.observedName) or ""
            ).strip(),
            "location_expression_ref": str(
                graph.value(expression, PLN.locationExpressionRef) or ""
            ) if expression is not None else "",
            "location_expression_status": str(
                graph.value(expression, PLN.locationExpressionStatus)
                or "none"
            ).strip().casefold() if expression is not None else "none",
            "spatial_relation": str(
                graph.value(expression, PLN.spatialRelation) or ""
            ).strip() if expression is not None else "",
            "anchor_entity_refs": self._literal_values(
                graph, expression, PLN.anchorEntityRef
            ) if expression is not None else [],
            "anchor_work_item_refs": self._literal_values(
                graph, expression, PLN.anchorWorkItemRef
            ) if expression is not None else [],
            "distance_hint": str(
                graph.value(expression, PLN.distanceHint) or ""
            ).strip() if expression is not None else "",
            "projection_fingerprint": str(
                graph.value(subject, PLN.identityProjectionFingerprint)
                or ""
            ),
            "observation_snapshot_ref": str(
                graph.value(subject, PLN.observationSnapshotRef) or ""
            ),
            "source_world_model_snapshot_ref": str(
                graph.value(subject, PLN.sourceWorldModelSnapshotRef) or ""
            ),
            "source_world_model_snapshot_digest": str(
                graph.value(subject, PLN.sourceWorldModelSnapshotDigest) or ""
            ),
            "projected_world_model_version": projected_version,
            "world_model_snapshot_ref": str(
                getattr(self._kg, "snapshot_ref", "") or ""
            ),
            "world_model_snapshot_digest": str(
                getattr(self._kg, "snapshot_digest", "") or ""
            ),
        }

    def find_identity_bindings(
        self,
        *,
        mention_ref: str = "",
        entity_ref: str = "",
        status: str = "",
        work_item_ref: str = "",
        source_mention_ref: str = "",
        dimension_ref: str = "",
        scope_ref: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Read the current bounded L1 identity projection.

        Identity bindings live in a dedicated named graph and contain only
        references to DATA-backed WorldEntity/representation resources.  The
        adapter returns plain rows so L2/L3 can recall the relevant bindings
        without loading the complete L1 observation snapshot.
        """

        self._ensure_indexes()
        bounded_limit = min(64, max(1, int(limit)))
        wanted_mention = str(mention_ref or "").strip()
        wanted_entity = str(entity_ref or "").strip()
        wanted_status = str(status or "").strip().casefold()
        wanted_work_item = str(work_item_ref or "").strip()
        wanted_source_mention = str(
            source_mention_ref or ""
        ).strip()
        wanted_dimension = str(dimension_ref or "").strip()
        wanted_scope = str(scope_ref or "").strip()
        if not any((
            wanted_mention,
            wanted_entity,
            wanted_work_item,
            wanted_source_mention,
            wanted_dimension,
            wanted_scope,
        )):
            raise ValueError(
                "identity binding query requires an explicit dependency selector"
            )
        result: list[dict[str, Any]] = []
        candidate_keys: set[str] | None = None

        def intersect(values: set[str]) -> None:
            nonlocal candidate_keys
            candidate_keys = (
                set(values)
                if candidate_keys is None
                else candidate_keys.intersection(values)
            )

        for value, index in (
            (wanted_mention, self._identity_keys_by_mention),
            (wanted_entity, self._identity_keys_by_entity),
            (wanted_status, self._identity_keys_by_status),
            (wanted_work_item, self._identity_keys_by_work_item),
            (
                wanted_source_mention,
                self._identity_keys_by_source_mention,
            ),
            (wanted_dimension, self._identity_keys_by_dimension),
            (wanted_scope, self._identity_keys_by_scope),
        ):
            if value:
                intersect(index.get(value, set()))
        ordered_keys = (
            sorted(candidate_keys)
            if candidate_keys is not None
            else list(self._identity_order)
        )
        for key in ordered_keys:
            row = self._identity_rows.get(key)
            if row is None:
                continue
            limits = {
                "candidate_entity_refs": 16,
                "observation_refs": 32,
                "source_mention_refs": 32,
                "representation_refs": 32,
                "resource_refs": 32,
                "entity_part_refs": 32,
                "source_feature_refs": 32,
                "candidate_refs": 32,
                "evidence_refs": 64,
                "relation_evidence_refs": 32,
                "dimension_refs": 16,
                "scope_refs": 16,
                "relation_refs": 32,
                "anchor_entity_refs": 16,
                "anchor_work_item_refs": 16,
            }
            result_row: dict[str, Any] = {}
            truncated_fields: list[str] = []
            total_counts: dict[str, int] = {}
            for row_key, row_value in row.items():
                if not isinstance(row_value, list):
                    result_row[row_key] = row_value
                    continue
                field_limit = limits.get(row_key, 32)
                total_counts[row_key] = len(row_value)
                result_row[row_key] = list(row_value[:field_limit])
                if len(row_value) > field_limit:
                    truncated_fields.append(row_key)
            result_row["total_counts"] = total_counts
            result_row["truncated_fields"] = truncated_fields
            result.append(result_row)
            if len(result) >= bounded_limit:
                break
        return result

    def query_identity_binding_page(self, request: Any) -> Any:
        """Build one stable, authority-bound identity cognition page."""

        from app.contracts.cognition.query import (
            IdentityBindingProjectionPage,
            IdentityBindingProjectionRequest,
            IdentityBindingProjectionRow,
        )

        typed = IdentityBindingProjectionRequest.model_validate(request)
        snapshot_ref = str(
            getattr(self._kg, "snapshot_ref", "") or ""
        )
        snapshot_digest = str(
            getattr(self._kg, "snapshot_digest", "") or ""
        )
        if typed.world_model_snapshot_ref != snapshot_ref:
            raise ValueError(
                "identity projection World Model snapshot ref mismatch"
            )
        if typed.world_model_snapshot_digest != snapshot_digest:
            raise ValueError(
                "identity projection World Model digest mismatch"
            )
        self._ensure_indexes()

        candidate_keys: set[str] | None = None

        def intersect_union(
            values: tuple[str, ...],
            index: dict[str, set[str]],
        ) -> None:
            nonlocal candidate_keys
            selected: set[str] = set()
            for value in values:
                selected.update(index.get(str(value), set()))
            candidate_keys = (
                selected
                if candidate_keys is None
                else candidate_keys.intersection(selected)
            )

        selectors = (
            (
                typed.dependency_dimension_keys,
                self._identity_keys_by_dimension,
            ),
            (typed.work_item_refs, self._identity_keys_by_work_item),
            (typed.mention_refs, self._identity_keys_by_mention),
            (
                typed.source_mention_refs,
                self._identity_keys_by_source_mention,
            ),
            (typed.entity_refs, self._identity_keys_by_entity),
            (typed.scope_refs, self._identity_keys_by_scope),
            (typed.identity_statuses, self._identity_keys_by_status),
        )
        for values, index in selectors:
            if values:
                intersect_union(tuple(values), index)
        ordered_keys = sorted(candidate_keys or set())
        matched_total = len(ordered_keys)
        offset = 0
        if typed.cursor:
            cursor_digest, separator, cursor_offset = typed.cursor.rpartition(
                "@"
            )
            if (
                not separator
                or cursor_digest != typed.query_digest
                or not cursor_offset.isdigit()
            ):
                raise ValueError("identity projection cursor is stale or invalid")
            offset = int(cursor_offset)
            if offset < 0 or offset > matched_total:
                raise ValueError("identity projection cursor is out of range")
        page_size = min(32, max(1, typed.requested_page_size))
        page_keys = ordered_keys[offset:offset + page_size]

        rows: list[Any] = []
        diagnostics: set[str] = set()
        for key in page_keys:
            row = self._identity_rows[key]
            candidate_entity_refs = list(
                row.get("candidate_entity_refs") or []
            )
            canonical_entity_ref = str(
                row.get("canonical_entity_ref") or ""
            )
            canonical_rows = (
                self.find_entities(
                    entity_ref=canonical_entity_ref,
                    limit=1,
                )
                if canonical_entity_ref
                else []
            )
            canonical = canonical_rows[0] if canonical_rows else {}
            candidate_labels: list[str] = []
            for entity_ref in candidate_entity_refs[:3]:
                matches = self.find_entities(
                    entity_ref=entity_ref,
                    limit=1,
                )
                candidate = matches[0] if matches else {}
                label = str(
                    candidate.get("canonical_name")
                    or candidate.get("entity_identity")
                    or entity_ref
                )
                if label and label not in candidate_labels:
                    candidate_labels.append(label)
            anchor_entity_refs = list(
                row.get("anchor_entity_refs") or []
            )
            anchor_labels: list[str] = []
            for work_item_ref in list(
                row.get("anchor_work_item_refs") or []
            )[:4]:
                for anchor_key in sorted(
                    self._identity_keys_by_work_item.get(
                        str(work_item_ref), set()
                    )
                ):
                    observed_name = str(
                        self._identity_rows.get(anchor_key, {}).get(
                            "observed_name"
                        )
                        or ""
                    ).strip()
                    if (
                        observed_name
                        and observed_name not in anchor_labels
                    ):
                        anchor_labels.append(observed_name)
            if not anchor_labels:
                for entity_ref in anchor_entity_refs[:4]:
                    matches = self.find_entities(
                        entity_ref=entity_ref,
                        limit=1,
                    )
                    anchor = matches[0] if matches else {}
                    label = str(
                        anchor.get("canonical_name")
                        or anchor.get("entity_identity")
                        or entity_ref
                    )
                    if label and label not in anchor_labels:
                        anchor_labels.append(label)
            canonical_label = str(
                canonical.get("canonical_name")
                or canonical.get("entity_identity")
                or canonical_entity_ref
            )
            if (
                not canonical_label
                or canonical_label.startswith(("source:", "urn:"))
            ):
                canonical_label = str(
                    row.get("observed_name") or canonical_label
                )
            representations = (
                self.representations_for(
                    canonical_entity_ref,
                    limit=32,
                )
                if canonical_entity_ref
                else []
            )
            representation_total = len(
                self._representations_by_entity.get(
                    canonical_entity_ref,
                    (),
                )
            ) if canonical_entity_ref else 0
            if representation_total > len(representations):
                diagnostics.add("representation_inventory_truncated")
            resources = {
                str(item.get("resource_ref") or "")
                for item in representations
                if str(item.get("resource_ref") or "")
            }
            identity_status = str(
                row.get("identity_status") or "unresolved"
            ).casefold()
            if identity_status not in {
                "resolved", "ambiguous", "unresolved", "not_applicable",
            }:
                identity_status = "unresolved"
            expression_status = str(
                row.get("location_expression_status") or "none"
            ).casefold()
            if expression_status not in {
                "none", "bound", "ambiguous", "unresolved",
            }:
                expression_status = "unresolved"
            rows.append(IdentityBindingProjectionRow(
                row_ref="identity-row:" + hashlib.sha256(
                    f"{typed.query_digest}|{key}".encode("utf-8")
                ).hexdigest()[:24],
                binding_ref=str(row.get("binding_ref") or key),
                work_item_ref=str(row.get("work_item_ref") or ""),
                source_mention_refs=tuple(
                    list(row.get("source_mention_refs") or [])[:16]
                ),
                source_dimensions=tuple(
                    list(row.get("dimension_refs") or [])[:16]
                ),
                scope_refs=tuple(
                    list(row.get("scope_refs") or [])[:16]
                ),
                canonical_entity_ref=canonical_entity_ref,
                canonical_label=canonical_label,
                entity_types=tuple(
                    list(canonical.get("concept_types") or [])[:8]
                ),
                identity_status=identity_status,
                candidate_count=len(candidate_entity_refs),
                candidate_labels=tuple(candidate_labels),
                candidate_labels_truncated=(
                    len(candidate_entity_refs) > len(candidate_labels)
                ),
                evidence_refs=tuple(
                    list(row.get("evidence_refs") or [])[:8]
                ),
                relation_refs=tuple(
                    list(row.get("relation_refs") or [])[:8]
                ),
                spatial_hint=str(row.get("spatial_hint") or "")[:240],
                location_expression_ref=str(
                    row.get("location_expression_ref") or ""
                ),
                location_expression_status=expression_status,
                spatial_relation=str(
                    row.get("spatial_relation") or ""
                )[:80],
                anchor_entity_refs=tuple(anchor_entity_refs[:8]),
                anchor_work_item_refs=tuple(
                    list(row.get("anchor_work_item_refs") or [])[:8]
                ),
                anchor_labels=tuple(anchor_labels),
                distance_hint=str(
                    row.get("distance_hint") or ""
                )[:80],
                uncertainty=str(
                    row.get("uncertainty_reason") or ""
                )[:240],
                representation_count=representation_total,
                available_geometry_kinds=tuple(sorted({
                    str(item.get("geometry_kind") or "")
                    for item in representations
                    if str(item.get("geometry_kind") or "")
                })),
                resource_count=len(resources),
                resource_availability=(
                    "available" if resources else "none"
                ),
                gap_ref=(
                    f"ground-gap:{row.get('mention_ref') or key}"
                    if identity_status in {"ambiguous", "unresolved"}
                    else (
                        "ground-relation-gap:"
                        f"{row.get('mention_ref') or key}"
                        if expression_status in {
                            "ambiguous", "unresolved",
                        }
                        else ""
                    )
                ),
            ))
        next_offset = offset + len(page_keys)
        truncated = next_offset < matched_total
        if truncated:
            diagnostics.add("identity_projection_page_truncated")
        return IdentityBindingProjectionPage(
            world_model_snapshot_ref=snapshot_ref,
            world_model_snapshot_digest=snapshot_digest,
            query_digest=typed.query_digest,
            consumer_stage=typed.consumer_stage,
            consumer_dimension_key=typed.consumer_dimension_key,
            rows=tuple(rows),
            matched_total=matched_total,
            emitted_count=len(rows),
            truncated=truncated,
            next_cursor=(
                f"{typed.query_digest}@{next_offset}"
                if truncated
                else ""
            ),
            omitted_refs=tuple(
                ordered_keys[next_offset:next_offset + 16]
            ),
            diagnostics=tuple(sorted(diagnostics)),
        )

    def build_network_retry_adapter(self) -> Any:
        """Return a lazy road-retry view through the world-model port.

        Building the retry index scans every RDF subject and is not needed by
        DATA, WM current-view reads, or Evidence.  Keep the port available to
        later road execution while moving that cost to its first actual use.
        """

        return _LazyNetworkRetryAdapter(self._kg)


__all__ = ["KGWorldModelAdapter"]
