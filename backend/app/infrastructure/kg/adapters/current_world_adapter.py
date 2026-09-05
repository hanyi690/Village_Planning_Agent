"""Bounded current-world read adapter for the WM v0 projection."""

from __future__ import annotations

from typing import Any

from rdflib import RDF

from app.infrastructure.kg.ontology import PLN


class CurrentWorldQueryAdapter:
    """Read only the source and world named graphs of one WM snapshot.

    The adapter deliberately does not expose the RDF dataset, assertion graph,
    identity graph, intent graph, planned graph, or network retry helpers. The
    generic ``KGWorldModelAdapter`` remains an internal migration surface for
    existing write/projection code; current-view consumers must use this
    adapter instead.
    """

    def __init__(self, store: Any):
        self._store = store
        self._metadata_token = ""
        self._current_world_digest_cache = ""
        self._source_geometry_refs_token = ""
        self._source_geometry_refs_cache: dict[str, tuple[str, ...]] = {}
        self._entity_rows_token = ""
        self._entity_rows_cache: tuple[
            dict[str, dict[str, Any]],
            dict[str, set[str]],
            dict[str, set[str]],
            dict[str, set[str]],
        ] | None = None
        self._bounded_entity_rows_token = ""
        self._bounded_entity_rows_cache: tuple[
            dict[str, dict[str, Any]],
            dict[str, set[str]],
            dict[str, set[str]],
            dict[str, set[str]],
        ] | None = None

    @property
    def snapshot_ref(self) -> str:
        return str(getattr(self._store, "snapshot_ref", "") or "")

    @property
    def snapshot_digest(self) -> str:
        return str(getattr(self._store, "snapshot_digest", "") or "")

    @property
    def current_world_digest(self) -> str:
        return str(
            getattr(self._store, "current_world_digest", "") or ""
        )

    @staticmethod
    def _text(graph: Any, subject: Any, predicate: Any) -> str:
        return str(graph.value(subject, predicate) or "").strip()

    @staticmethod
    def _values(graph: Any, subject: Any, predicate: Any) -> list[str]:
        return sorted({
            str(value).strip()
            for value in graph.objects(subject, predicate)
            if str(value).strip()
        })

    @staticmethod
    def _name_key(value: Any) -> str:
        return "".join(str(value or "").split()).casefold()

    def _metadata(
        self,
        row: dict[str, Any],
        *,
        include_current_digest: bool = True,
    ) -> dict[str, Any]:
        if include_current_digest:
            token = self.snapshot_digest
            if token != self._metadata_token:
                self._metadata_token = token
                self._current_world_digest_cache = str(
                    getattr(self._store, "current_world_digest", "") or ""
                )
        row["snapshot_ref"] = self.snapshot_ref
        row["snapshot_digest"] = self.snapshot_digest
        if include_current_digest:
            row["current_world_digest"] = self._current_world_digest_cache
        return row

    def _source_geometry_refs(self, source_record: Any) -> list[str]:
        token = self.snapshot_digest
        if token != self._source_geometry_refs_token:
            world = self._store.world_graph
            index: dict[str, set[str]] = {}
            for representation in world.subjects(RDF.type, PLN.SpatialRepresentation):
                geometry_ref = self._text(world, representation, PLN.geometryRef)
                if not geometry_ref:
                    continue
                for record in world.objects(
                    representation,
                    PLN.derivedFromSourceRecord,
                ):
                    index.setdefault(str(record), set()).add(geometry_ref)
            self._source_geometry_refs_token = token
            self._source_geometry_refs_cache = {
                key: tuple(sorted(values))
                for key, values in index.items()
            }
        return list(self._source_geometry_refs_cache.get(str(source_record), ()))

    def find_source_records(
        self,
        *,
        source_record_ref: str = "",
        source_feature_ref: str = "",
        dataset_ref: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return bounded, stable source records from ``SOURCE_GRAPH``."""

        graph = self._store.source_graph
        wanted_record = str(source_record_ref or "").strip()
        wanted_feature = str(source_feature_ref or "").strip()
        wanted_dataset = str(dataset_ref or "").strip()
        rows: list[dict[str, Any]] = []
        catalog = getattr(self._store, "catalog", None)
        snapshot = getattr(catalog, "snapshot", None)
        snapshot_id = str(getattr(snapshot, "snapshot_id", "") or "")
        for subject in sorted(
            set(graph.subjects(RDF.type, PLN.SourceRecord)),
            key=str,
        ):
            record_ref = str(subject)
            feature_ref = self._text(graph, subject, PLN.sourceFeatureRef)
            record_dataset = self._text(graph, subject, PLN.sourceDatasetRef)
            if wanted_record and record_ref != wanted_record:
                continue
            if wanted_feature and feature_ref != wanted_feature:
                continue
            if wanted_dataset and record_dataset != wanted_dataset:
                continue
            row = {
                "source_record_ref": record_ref,
                "dataset_ref": record_dataset,
                "collection_ref": self._text(
                    graph,
                    subject,
                    PLN.sourceCollectionRef,
                ),
                "source_feature_ref": feature_ref,
                "source_snapshot_ref": self._text(
                    graph,
                    subject,
                    PLN.sourceSnapshotRef,
                ) or snapshot_id,
                "raw_attribute_ref": self._text(
                    graph,
                    subject,
                    PLN.rawAttributeRef,
                ),
                "source_geometry_refs": self._source_geometry_refs(subject),
                "valid_time": self._text(graph, subject, PLN.validTime),
                "input_role": self._text(graph, subject, PLN.inputRole)
                or "current_evidence",
                "admission_status": self._text(
                    graph,
                    subject,
                    PLN.admissionStatus,
                ) or "admitted",
                "source_digest": self._text(
                    graph,
                    subject,
                    PLN.sourceFeatureDigest,
                ) or self._text(graph, subject, PLN.contentDigest),
            }
            rows.append(self._metadata(row))
            if len(rows) >= max(1, int(limit)):
                break
        return rows

    def _representation_row(
        self,
        representation: Any,
        *,
        entity_part_ref: str = "",
        include_current_digest: bool = True,
    ) -> dict[str, Any]:
        graph = self._store.world_graph
        source_record_refs = self._values(
            graph,
            representation,
            PLN.derivedFromSourceRecord,
        )
        row = {
            "entity_ref": self._text(graph, representation, PLN.entityRef),
            "entity_part_ref": entity_part_ref,
            "representation_ref": self._text(
                graph,
                representation,
                PLN.representationRef,
            ) or str(representation),
            "dataset_ref": self._text(graph, representation, PLN.sourceDatasetRef),
            "source_feature_ref": self._text(
                graph,
                representation,
                PLN.sourceFeatureRef,
            ),
            "source_record_refs": source_record_refs,
            "resource_ref": self._text(graph, representation, PLN.resourceRef),
            "geometry_ref": self._text(graph, representation, PLN.geometryRef),
            "purpose": self._text(
                graph,
                representation,
                PLN.representationPurpose,
            ) or self._text(graph, representation, PLN.sourceRepresentationPurpose),
            "geometry_kind": self._text(graph, representation, PLN.geometryKind),
            "crs": self._text(graph, representation, PLN.crs),
            "source_crs": self._text(graph, representation, PLN.sourceCrs),
            "normalized_crs": self._text(
                graph,
                representation,
                PLN.normalizedCrs,
            ),
            "source_snapshot_ref": self._text(
                graph,
                representation,
                PLN.sourceSnapshotRef,
            ),
            "content_digest": self._text(
                graph,
                representation,
                PLN.contentDigest,
            ) or self._text(graph, representation, PLN.sourceFeatureDigest),
            "component_refs": self._values(
                graph,
                representation,
                PLN.componentRef,
            ),
            "component_representation_refs": self._values(
                graph,
                representation,
                PLN.componentRepresentationRef,
            ),
            "representation_status": (
                "composite"
                if list(graph.objects(representation, PLN.componentRef))
                else "available"
            ),
        }
        return self._metadata(
            row,
            include_current_digest=include_current_digest,
        )

    def _entity_rows(
        self,
        *,
        limit: int | None = None,
        include_current_digest: bool = True,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, set[str]],
        dict[str, set[str]],
        dict[str, set[str]],
    ]:
        token = f"{self.snapshot_digest}:{int(include_current_digest)}"
        bounded = limit is not None
        if bounded:
            if (
                self._bounded_entity_rows_cache is not None
                and token == self._bounded_entity_rows_token
                and len(self._bounded_entity_rows_cache[0]) >= max(1, int(limit or 1))
            ):
                return self._bounded_entity_rows_cache
        elif self._entity_rows_cache is not None and token == self._entity_rows_token:
            return self._entity_rows_cache
        graph = self._store.world_graph
        rows: dict[str, dict[str, Any]] = {}
        by_ref: dict[str, set[str]] = {}
        by_source: dict[str, set[str]] = {}
        by_name: dict[str, set[str]] = {}
        subjects = sorted(
            set(graph.subjects(RDF.type, PLN.WorldEntity)),
            key=str,
        )
        if bounded:
            subjects = subjects[:max(1, int(limit or 1))]
        for subject in subjects:
            entity_ref = str(subject)
            entity_identity = self._text(graph, subject, PLN.entityIdentity)
            parts: list[dict[str, Any]] = []
            representation_nodes: list[tuple[str, Any]] = []
            for part in sorted(
                set(graph.objects(subject, PLN.hasEntityPart)),
                key=str,
            ):
                source_refs = self._values(graph, part, PLN.sourceFeatureRef)
                source_record_refs = self._values(
                    graph,
                    part,
                    PLN.describedBySourceRecord,
                )
                for representation in graph.objects(
                    part,
                    PLN.hasSpatialRepresentation,
                ):
                    representation_nodes.append((str(part), representation))
                parts.append(self._metadata({
                    "entity_part_ref": str(part),
                    "part_ref": str(part),
                    "entity_ref": entity_ref,
                    "source_record_refs": source_record_refs,
                    "source_feature_refs": source_refs,
                    "source_feature_ref": source_refs[0] if source_refs else "",
                    "dataset_ref": self._text(
                        graph,
                        part,
                        PLN.sourceDatasetRef,
                    ),
                    "geometry_kind": self._text(graph, part, PLN.geometryKind),
                    "status": self._text(graph, part, PLN.entityPartStatus)
                    or "observed",
                }, include_current_digest=include_current_digest))
                for source_ref in source_refs:
                    by_source.setdefault(source_ref, set()).add(entity_ref)
                    dataset = self._text(graph, part, PLN.sourceDatasetRef)
                    if dataset:
                        by_source.setdefault(
                            f"{dataset}:{source_ref}",
                            set(),
                        ).add(entity_ref)
            representations: list[dict[str, Any]] = []
            for part_ref, representation in representation_nodes:
                representations.append(
                    self._representation_row(
                        representation,
                        entity_part_ref=part_ref,
                        include_current_digest=include_current_digest,
                    )
                )
            for representation in graph.objects(
                subject,
                PLN.hasSpatialRepresentation,
            ):
                representations.append(self._representation_row(
                    representation,
                    include_current_digest=include_current_digest,
                ))
            deduped_representations = {
                row["representation_ref"]: row
                for row in representations
            }
            canonical_name = self._text(graph, subject, PLN.canonicalName)
            aliases = self._values(graph, subject, PLN.alias)
            concept_types = self._values(graph, subject, PLN.conceptType)
            row = self._metadata({
                "entity_ref": entity_ref,
                "entity_identity": entity_identity,
                "canonical_name": canonical_name,
                "canonical_label": canonical_name,
                "aliases": aliases,
                "concept_types": concept_types,
                "concept_refs": concept_types,
                "status": self._text(graph, subject, PLN.entityStatus)
                or "provisional",
                "identity_status": self._text(
                    graph,
                    subject,
                    PLN.identityStatus,
                ) or "provisional",
                "semantic_status": self._text(
                    graph,
                    subject,
                    PLN.semanticStatus,
                ) or "unresolved",
                "parts": sorted(parts, key=lambda item: item["part_ref"]),
                "representations": [
                    deduped_representations[key]
                    for key in sorted(deduped_representations)
                ],
            }, include_current_digest=include_current_digest)
            rows[entity_ref] = row
            for key in (entity_ref, entity_identity):
                if key:
                    by_ref.setdefault(key, set()).add(entity_ref)
            for label in (canonical_name, *aliases):
                key = self._name_key(label)
                if key:
                    by_name.setdefault(key, set()).add(entity_ref)
        result = (rows, by_ref, by_source, by_name)
        if bounded:
            self._bounded_entity_rows_token = token
            self._bounded_entity_rows_cache = result
        else:
            self._entity_rows_token = token
            self._entity_rows_cache = result
        return result

    def find_entities(
        self,
        *,
        identity: str = "",
        entity_ref: str = "",
        source_feature_ref: str = "",
        name: str = "",
        entity_type: str = "",
        limit: int = 50,
        include_current_digest: bool = True,
    ) -> list[dict[str, Any]]:
        """Return bounded entity/part rows from ``WORLD_GRAPH`` only."""

        has_filter = bool(identity or entity_ref or source_feature_ref or name or entity_type)
        rows, by_ref, by_source, by_name = self._entity_rows(
            limit=limit if not has_filter else None,
            include_current_digest=include_current_digest,
        )
        candidates: set[str] | None = None

        def intersect(values: set[str]) -> None:
            nonlocal candidates
            candidates = set(values) if candidates is None else candidates & values

        if identity:
            intersect(by_ref.get(str(identity), set()))
        if entity_ref:
            intersect(by_ref.get(str(entity_ref), set()))
        if source_feature_ref:
            intersect(by_source.get(str(source_feature_ref), set()))
        if name:
            intersect(by_name.get(self._name_key(name), set()))
        ordered = sorted(candidates if candidates is not None else rows)
        result: list[dict[str, Any]] = []
        for key in ordered:
            row = rows[key]
            if entity_type:
                wanted = str(entity_type).rsplit("#", 1)[-1].casefold()
                concepts = [
                    value.rsplit("#", 1)[-1].casefold()
                    for value in row["concept_types"]
                ]
                if concepts and not any(
                    wanted in concept or concept in wanted
                    for concept in concepts
                ):
                    continue
            result.append({
                **row,
                "parts": [dict(part) for part in row["parts"]],
                "representations": [
                    dict(representation)
                    for representation in row["representations"]
                ],
            })
            if len(result) >= max(1, int(limit)):
                break
        return result

    def representations_for(
        self,
        entity_ref: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return representations linked to one current-world entity."""

        entities = self.find_entities(entity_ref=str(entity_ref), limit=1)
        if not entities:
            return []
        rows = entities[0].get("representations", ())
        return [dict(row) for row in rows[:max(1, int(limit))]]


__all__ = ["CurrentWorldQueryAdapter"]
