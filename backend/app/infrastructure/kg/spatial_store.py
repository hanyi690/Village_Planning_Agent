"""Storage/index boundary for the spatial KG.

The RDFLib graph remains the small, deterministic local implementation used
by tests and single-village demos.  This module gives it the same indexed
lookup surface as the production PostGIS implementation so callers do not
scan RDF triples or run geometry predicates directly.

PostGIS is an implementation of the KG entity/relation store, not a second
topology database.  The SQL schema deliberately keeps entities and relations
in one snapshot namespace and records the geometry authority/provenance on
each row.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class SpatialKGEntity:
    entity_ref: str
    entity_type: str = ""
    canonical_name: str = ""
    aliases: tuple[str, ...] = ()
    feature_bsm: str | None = None
    source_feature_id: str | None = None
    source_layer: str | None = None
    geometry_wkt: str | None = None
    geometry_crs: str = "EPSG:4326"
    snapshot_digest: str = ""
    properties: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SpatialKGRelation:
    relation_id: str
    subject_ref: str
    predicate: str
    object_ref: str
    metric_value: float | None = None
    metric_unit: str | None = None
    tolerance: float | None = None
    crs: str = "EPSG:4326"
    method: str = ""
    snapshot_digest: str = ""
    provenance_refs: tuple[str, ...] = ()


class SpatialKGStore(Protocol):
    """Consumer-facing storage surface shared by local KG and PostGIS."""

    def find_entities(
        self,
        *,
        entity_ref: str = "",
        name: str = "",
        entity_type: str = "",
        feature_bsm: str = "",
        source_feature_id: str = "",
        limit: int = 50,
    ) -> list[SpatialKGEntity]: ...

    def find_relations(
        self,
        *,
        subject_ref: str = "",
        object_ref: str = "",
        predicate: str = "",
        limit: int = 200,
    ) -> list[SpatialKGRelation]: ...


class RdfSpatialKGIndex:
    """Indexed lookup projection over a ``PlanningKG`` RDF graph.

    It is rebuilt once after KG materialization and then queried by exact
    identity/name keys.  This removes repeated ``Graph.triples`` scans from
    the evidence hot path while preserving RDFLib as the local source graph.
    """

    def __init__(self) -> None:
        self._entities: dict[str, SpatialKGEntity] = {}
        self._by_name: dict[str, set[str]] = {}
        self._by_type: dict[str, set[str]] = {}
        self._by_bsm: dict[str, set[str]] = {}
        self._by_source_feature: dict[str, set[str]] = {}
        self._relations: list[SpatialKGRelation] = []
        self._relations_by_subject: dict[str, list[SpatialKGRelation]] = {}
        self._relations_by_object: dict[str, list[SpatialKGRelation]] = {}

    def rebuild(self, graph: Any) -> None:
        from rdflib import RDF

        from .ontology import PLN, Relations

        self.__init__()
        subjects = set(graph.subjects())
        for subject in subjects:
            entity_ref = str(subject)
            types = tuple(sorted(str(item) for item in graph.objects(subject, RDF.type)))
            entity_type = types[0] if types else ""
            name = str(graph.value(subject, PLN.name) or "")
            aliases = tuple(
                sorted(
                    {
                        str(value)
                        for predicate in (PLN.alias, PLN.facility_type)
                        for value in graph.objects(subject, predicate)
                        if str(value).strip()
                    }
                )
            )
            feature_bsm = str(graph.value(subject, PLN.bsm) or "").strip() or None
            source_feature_id = str(graph.value(subject, PLN.source_feature_id) or "").strip() or None
            entity = SpatialKGEntity(
                entity_ref=entity_ref,
                entity_type=entity_type,
                canonical_name=name,
                aliases=aliases,
                feature_bsm=feature_bsm,
                source_feature_id=source_feature_id,
                source_layer=str(graph.value(subject, PLN.source_layer) or "").strip() or None,
                properties=tuple(sorted(
                    (str(predicate), str(value))
                    for predicate, value in graph.predicate_objects(subject)
                    if getattr(value, "datatype", None) is not None
                    or not str(value).startswith("http")
                )),
            )
            if name or types or feature_bsm or source_feature_id:
                self._entities[entity_ref] = entity
                for key in (name, *aliases):
                    if key.strip():
                        self._by_name.setdefault(key.strip().casefold(), set()).add(entity_ref)
                for value in types:
                    self._by_type.setdefault(value, set()).add(entity_ref)
                if feature_bsm:
                    self._by_bsm.setdefault(feature_bsm, set()).add(entity_ref)
                if source_feature_id:
                    self._by_source_feature.setdefault(source_feature_id, set()).add(entity_ref)

        spatial_predicates = Relations.spatial() | {Relations.serves, Relations.derived_from}
        for subject, predicate, obj in graph:
            if predicate not in spatial_predicates:
                continue
            if str(subject) not in self._entities or str(obj) not in self._entities:
                continue
            relation = SpatialKGRelation(
                relation_id=f"{subject}|{predicate}|{obj}",
                subject_ref=str(subject),
                predicate=str(predicate),
                object_ref=str(obj),
            )
            self._relations.append(relation)
            self._relations_by_subject.setdefault(relation.subject_ref, []).append(relation)
            self._relations_by_object.setdefault(relation.object_ref, []).append(relation)

    def find_entities(
        self,
        *,
        entity_ref: str = "",
        name: str = "",
        entity_type: str = "",
        feature_bsm: str = "",
        source_feature_id: str = "",
        limit: int = 50,
    ) -> list[SpatialKGEntity]:
        candidate_refs: set[str] | None = None
        for refs in (
            {entity_ref} if entity_ref else None,
            self._by_name.get(name.strip().casefold(), set()) if name else None,
            self._by_type.get(entity_type, set()) if entity_type else None,
            self._by_bsm.get(feature_bsm, set()) if feature_bsm else None,
            self._by_source_feature.get(source_feature_id, set()) if source_feature_id else None,
        ):
            if refs is None:
                continue
            candidate_refs = set(refs) if candidate_refs is None else candidate_refs & refs
        if candidate_refs is None:
            candidate_refs = set(self._entities)
        return [
            self._entities[ref]
            for ref in sorted(candidate_refs)
            if ref in self._entities
        ][: max(0, limit)]

    def find_relations(
        self,
        *,
        subject_ref: str = "",
        object_ref: str = "",
        predicate: str = "",
        limit: int = 200,
    ) -> list[SpatialKGRelation]:
        if subject_ref:
            relations: Iterable[SpatialKGRelation] = self._relations_by_subject.get(subject_ref, ())
        elif object_ref:
            relations = self._relations_by_object.get(object_ref, ())
        else:
            relations = self._relations
        result = [
            relation
            for relation in relations
            if (not object_ref or relation.object_ref == object_ref)
            and (not predicate or relation.predicate == predicate)
        ]
        return result[: max(0, limit)]


class PostGISKGStore:
    """Synchronous PostGIS adapter over a caller-owned SQLAlchemy connection.

    The adapter is intentionally connection-scoped: application lifecycle
    code owns pooling, transactions, and disposal.  This keeps tests on the
    RDFLib adapter and prevents a hidden database connection from surviving a
    resumed/closed planning session.
    """

    def __init__(self, connection: Any, *, snapshot_digest: str) -> None:
        if connection is None:
            raise ValueError("PostGISKGStore requires a SQLAlchemy connection")
        if not snapshot_digest:
            raise ValueError("snapshot_digest is required")
        self.connection = connection
        self.snapshot_digest = snapshot_digest

    def _text(self, statement: str) -> Any:
        from sqlalchemy import text

        return text(statement)

    def ensure_schema(self) -> None:
        for statement in POSTGIS_KG_SCHEMA_SQL:
            self.connection.execute(self._text(statement))

    def upsert_entity(
        self,
        entity: SpatialKGEntity,
        *,
        properties: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            self._text(
                """
                INSERT INTO kg_entities (
                    snapshot_digest, entity_ref, entity_type, canonical_name,
                    aliases, feature_bsm, source_feature_id, source_layer,
                    geometry, geometry_crs, properties
                ) VALUES (
                    :snapshot_digest, :entity_ref, :entity_type, :canonical_name,
                    CAST(:aliases AS jsonb), :feature_bsm, :source_feature_id,
                    :source_layer,
                    CASE WHEN :geometry_wkt IS NULL THEN NULL
                         ELSE ST_GeomFromText(:geometry_wkt, 4326) END,
                    :geometry_crs, CAST(:properties AS jsonb)
                )
                ON CONFLICT (snapshot_digest, entity_ref) DO UPDATE SET
                    entity_type = EXCLUDED.entity_type,
                    canonical_name = EXCLUDED.canonical_name,
                    aliases = EXCLUDED.aliases,
                    feature_bsm = EXCLUDED.feature_bsm,
                    source_feature_id = EXCLUDED.source_feature_id,
                    source_layer = EXCLUDED.source_layer,
                    geometry = EXCLUDED.geometry,
                    geometry_crs = EXCLUDED.geometry_crs,
                    properties = EXCLUDED.properties
                """
            ),
            {
                "snapshot_digest": self.snapshot_digest,
                "entity_ref": entity.entity_ref,
                "entity_type": entity.entity_type,
                "canonical_name": entity.canonical_name,
                "aliases": json.dumps(list(entity.aliases), ensure_ascii=False),
                "feature_bsm": entity.feature_bsm,
                "source_feature_id": entity.source_feature_id,
                "source_layer": entity.source_layer,
                "geometry_wkt": entity.geometry_wkt,
                "geometry_crs": entity.geometry_crs,
                "properties": json.dumps(properties or {}, ensure_ascii=False),
            },
        )

    def upsert_relation(self, relation: SpatialKGRelation) -> None:
        self.connection.execute(
            self._text(
                """
                INSERT INTO kg_relations (
                    snapshot_digest, relation_id, subject_ref, predicate,
                    object_ref, metric_value, metric_unit, tolerance, crs,
                    method, provenance_refs
                ) VALUES (
                    :snapshot_digest, :relation_id, :subject_ref, :predicate,
                    :object_ref, :metric_value, :metric_unit, :tolerance, :crs,
                    :method, CAST(:provenance_refs AS jsonb)
                )
                ON CONFLICT (snapshot_digest, relation_id) DO UPDATE SET
                    metric_value = EXCLUDED.metric_value,
                    metric_unit = EXCLUDED.metric_unit,
                    tolerance = EXCLUDED.tolerance,
                    crs = EXCLUDED.crs,
                    method = EXCLUDED.method,
                    provenance_refs = EXCLUDED.provenance_refs
                """
            ),
            {
                "snapshot_digest": self.snapshot_digest,
                "relation_id": relation.relation_id,
                "subject_ref": relation.subject_ref,
                "predicate": relation.predicate,
                "object_ref": relation.object_ref,
                "metric_value": relation.metric_value,
                "metric_unit": relation.metric_unit,
                "tolerance": relation.tolerance,
                "crs": relation.crs,
                "method": relation.method,
                "provenance_refs": json.dumps(
                    list(relation.provenance_refs), ensure_ascii=False
                ),
            },
        )

    def find_entities(
        self,
        *,
        entity_ref: str = "",
        name: str = "",
        entity_type: str = "",
        feature_bsm: str = "",
        source_feature_id: str = "",
        limit: int = 50,
    ) -> list[SpatialKGEntity]:
        filters = ["snapshot_digest = :snapshot_digest"]
        params: dict[str, Any] = {"snapshot_digest": self.snapshot_digest, "limit": max(0, limit)}
        for column, value in (
            ("entity_ref", entity_ref),
            ("canonical_name", name),
            ("entity_type", entity_type),
            ("feature_bsm", feature_bsm),
            ("source_feature_id", source_feature_id),
        ):
            if value:
                filters.append(f"{column} = :{column}")
                params[column] = value
        rows = self.connection.execute(
            self._text(
                """SELECT entity_ref, entity_type, canonical_name, aliases,
                        feature_bsm, source_feature_id, source_layer,
                        ST_AsText(geometry) AS geometry_wkt, geometry_crs, properties
                   FROM kg_entities
                  WHERE """ + " AND ".join(filters) +
                " ORDER BY entity_ref LIMIT :limit"
            ),
            params,
        )
        result = []
        for row in rows:
            data = row._mapping
            aliases = data["aliases"] or []
            if isinstance(aliases, str):
                aliases = json.loads(aliases)
            result.append(
                SpatialKGEntity(
                    entity_ref=str(data["entity_ref"]),
                    entity_type=str(data["entity_type"] or ""),
                    canonical_name=str(data["canonical_name"] or ""),
                    aliases=tuple(str(value) for value in aliases),
                    feature_bsm=data["feature_bsm"],
                    source_feature_id=data["source_feature_id"],
                    source_layer=data["source_layer"],
                    geometry_wkt=data["geometry_wkt"],
                    geometry_crs=str(data["geometry_crs"] or "EPSG:4326"),
                    snapshot_digest=self.snapshot_digest,
                    properties=tuple(
                        (str(key), str(value))
                        for key, value in (json.loads(data["properties"]) if isinstance(data["properties"], str) else (data["properties"] or {})).items()
                    ),
                )
            )
        return result

    def find_relations(
        self,
        *,
        subject_ref: str = "",
        object_ref: str = "",
        predicate: str = "",
        limit: int = 200,
    ) -> list[SpatialKGRelation]:
        filters = ["snapshot_digest = :snapshot_digest"]
        params: dict[str, Any] = {"snapshot_digest": self.snapshot_digest, "limit": max(0, limit)}
        for column, value in (
            ("subject_ref", subject_ref),
            ("object_ref", object_ref),
            ("predicate", predicate),
        ):
            if value:
                filters.append(f"{column} = :{column}")
                params[column] = value
        rows = self.connection.execute(
            self._text(
                """SELECT relation_id, subject_ref, predicate, object_ref,
                        metric_value, metric_unit, tolerance, crs, method,
                        provenance_refs
                   FROM kg_relations
                  WHERE """ + " AND ".join(filters) +
                " ORDER BY relation_id LIMIT :limit"
            ),
            params,
        )
        result = []
        for row in rows:
            data = row._mapping
            refs = data["provenance_refs"] or []
            if isinstance(refs, str):
                refs = json.loads(refs)
            result.append(
                SpatialKGRelation(
                    relation_id=str(data["relation_id"]),
                    subject_ref=str(data["subject_ref"]),
                    predicate=str(data["predicate"]),
                    object_ref=str(data["object_ref"]),
                    metric_value=data["metric_value"],
                    metric_unit=data["metric_unit"],
                    tolerance=data["tolerance"],
                    crs=str(data["crs"] or "EPSG:4326"),
                    method=str(data["method"] or ""),
                    snapshot_digest=self.snapshot_digest,
                    provenance_refs=tuple(str(value) for value in refs),
                )
            )
        return result


# PostgreSQL/PostGIS schema for the same KG entity + relation model.  Geometry
# is indexed for filtering, while relation topology is stored in kg_relations.
POSTGIS_KG_SCHEMA_SQL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS postgis",
    """
    CREATE TABLE IF NOT EXISTS kg_entities (
        snapshot_digest TEXT NOT NULL,
        entity_ref TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT '',
        canonical_name TEXT NOT NULL DEFAULT '',
        aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
        feature_bsm TEXT,
        source_feature_id TEXT,
        source_layer TEXT,
        geometry geometry(Geometry, 4326),
        geometry_crs TEXT NOT NULL DEFAULT 'EPSG:4326',
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY (snapshot_digest, entity_ref)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities (snapshot_digest, canonical_name)",
    "CREATE INDEX IF NOT EXISTS idx_kg_entities_bsm ON kg_entities (snapshot_digest, feature_bsm)",
    "CREATE INDEX IF NOT EXISTS idx_kg_entities_source_id ON kg_entities (snapshot_digest, source_feature_id)",
    "CREATE INDEX IF NOT EXISTS idx_kg_entities_geom ON kg_entities USING GIST (geometry)",
    """
    CREATE TABLE IF NOT EXISTS kg_relations (
        snapshot_digest TEXT NOT NULL,
        relation_id TEXT NOT NULL,
        subject_ref TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object_ref TEXT NOT NULL,
        metric_value DOUBLE PRECISION,
        metric_unit TEXT,
        tolerance DOUBLE PRECISION,
        crs TEXT NOT NULL DEFAULT 'EPSG:4326',
        method TEXT NOT NULL DEFAULT '',
        provenance_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (snapshot_digest, relation_id),
        FOREIGN KEY (snapshot_digest, subject_ref)
            REFERENCES kg_entities (snapshot_digest, entity_ref),
        FOREIGN KEY (snapshot_digest, object_ref)
            REFERENCES kg_entities (snapshot_digest, entity_ref)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_kg_relations_subject ON kg_relations (snapshot_digest, subject_ref, predicate)",
    "CREATE INDEX IF NOT EXISTS idx_kg_relations_object ON kg_relations (snapshot_digest, object_ref, predicate)",
)


__all__ = [
    "SpatialKGEntity",
    "SpatialKGRelation",
    "SpatialKGStore",
    "RdfSpatialKGIndex",
    "PostGISKGStore",
    "POSTGIS_KG_SCHEMA_SQL",
]
