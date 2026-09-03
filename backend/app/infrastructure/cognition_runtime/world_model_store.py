"""DATA-backed cognitive World Model store.

The World Model is the KG projection of the normalized DATA catalog.  This
module is intentionally independent from ``VillageBundle``, parcel fields and
the legacy ``KGManager``.  A context receives one store for one DATA snapshot;
the store exposes the read/write ports used by GROUND and EXECUTE while the
RDF graph remains an implementation detail.

The store keeps a process-local handle for fast reuse and also persists each
immutable TriG snapshot through the existing content-addressed repository.
The named ``world_model`` ref is updated with compare-and-set, so a new
process can restore the latest DATA-matching graph without changing business
modules.  Parent history/current-pointer replay remains an operational layer
above this boundary.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any

from rdflib import BNode, Dataset, Literal, RDF, URIRef
from rdflib.plugins.serializers.trig import TrigSerializer

from app.infrastructure.kg.adapters.source_catalog_adapter import project_source_catalog
from app.infrastructure.kg.adapters.current_world_adapter import CurrentWorldQueryAdapter
from app.infrastructure.kg.adapters.world_model_adapter import KGWorldModelAdapter
from app.infrastructure.kg.ontology import GEO, PLN, PLN_NS
from app.infrastructure.logging import get_logger
from app.infrastructure.artifacts.fingerprint import semantic_checksum


logger = get_logger(__name__)


_STORE_LOCK = RLock()
_STORES: dict[tuple[str, str, str, str, str], "WorldModelKGStore"] = {}

SOURCE_GRAPH = URIRef("urn:planning:graph:source")
ASSERTION_GRAPH = URIRef("urn:planning:graph:assertion")
WORLD_GRAPH = URIRef("urn:planning:graph:world")
INTENT_GRAPH = URIRef("urn:planning:graph:intent")
PLANNED_GRAPH = URIRef("urn:planning:graph:planned")
IDENTITY_GRAPH = URIRef("urn:planning:graph:identity-binding")

# These markers are part of the persisted World Model contract.  A DATA
# digest alone is not enough to restore a graph safely: projection code and
# ontology/schema changes can alter entity/representation semantics while the
# source bytes remain identical.  Bump the code marker whenever the
# source-catalog projection changes in a non-backward-compatible way.
WORLD_MODEL_PROJECTION_VERSION = "source-catalog-projection-v11"
WORLD_MODEL_SCHEMA_VERSION = "world-model-trig-v12"
WORLD_MODEL_CODE_VERSION = "world-model-store-v12"
WORLD_MODEL_DIGEST_ALGORITHM = "sha256-sorted-rdflib-n3-quads-v1"
_VIEW_METADATA_PREDICATES = frozenset({
    PLN.worldModelVersion,
    PLN.worldModelProjectionVersion,
    PLN.worldModelSchemaVersion,
    PLN.worldModelCodeVersion,
    PLN.worldModelDigestAlgorithm,
})


class _RoundTripTrigSerializer(TrigSerializer):
    """Preserve each Literal lexical form already held by the RDF graph.

    This boundary does not recover precision discarded before Literal
    construction.  It prevents the stock Turtle shorthand formatter from
    applying a second, six-digit float rounding during CAS serialization.
    """

    def label(self, node: Any, position: int) -> str:
        if isinstance(node, Literal):
            return node.n3(self.store.namespace_manager)
        return super().label(node, position)


def _roundtrip_trig(dataset: Dataset) -> bytes:
    stream = BytesIO()
    _RoundTripTrigSerializer(dataset).serialize(stream, encoding="utf-8")
    return stream.getvalue()


def _stable_graph_digest(dataset: Dataset) -> str:
    rows: list[str] = []
    for context in dataset.graphs():
        for subject, predicate, obj in context:
            terms = (context.identifier, subject, predicate, obj)
            if any(isinstance(term, BNode) for term in terms):
                raise RuntimeError(
                    "World Model persistence requires stable URI/Literal terms; "
                    "blank nodes are not permitted"
                )
            rows.append(json.dumps(
                [term.n3() for term in terms],
                ensure_ascii=False,
                separators=(",", ":"),
            ))
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()


def _stable_context_digest(*contexts: Any) -> str:
    """Digest only the named graphs that form one logical view."""

    rows: list[str] = []
    for context in contexts:
        for subject, predicate, obj in context:
            if predicate in _VIEW_METADATA_PREDICATES:
                continue
            terms = (context.identifier, subject, predicate, obj)
            if any(isinstance(term, BNode) for term in terms):
                raise RuntimeError(
                    "World Model view persistence requires stable terms"
                )
            rows.append(json.dumps(
                [term.n3() for term in terms],
                ensure_ascii=False,
                separators=(",", ":"),
            ))
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _model_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        try:
            result = dumper(mode="json")
        except TypeError:
            result = dumper()
        return result if isinstance(result, dict) else {}
    return {
        str(key): item
        for key, item in vars(value).items()
        if not str(key).startswith("_")
    } if hasattr(value, "__dict__") else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


class WorldModelKGStore:
    """KG-backed World Model for one normalized DATA snapshot."""

    def __init__(
        self,
        session_id: str,
        village_name: str,
        catalog: Any,
        *,
        schema_mapping_snapshot: Any = None,
        schema_mapping_artifact_ref: str = "",
        artifact_root: str = "",
    ) -> None:
        self.session_id = _text(session_id)
        self.village_name = _text(village_name)
        self.catalog = catalog
        self.schema_mapping_snapshot = schema_mapping_snapshot
        self.schema_mapping_artifact_ref = _text(schema_mapping_artifact_ref)
        if artifact_root:
            self.artifact_root = Path(str(artifact_root)).resolve()
        else:
            from app.infrastructure.paths import run_tmp_root

            self.artifact_root = run_tmp_root()
        self.g = Dataset(default_union=True)
        self.source_graph = self.g.graph(SOURCE_GRAPH)
        self.assertion_graph = self.g.graph(ASSERTION_GRAPH)
        self.world_graph = self.g.graph(WORLD_GRAPH)
        self.intent_graph = self.g.graph(INTENT_GRAPH)
        self.planned_graph = self.g.graph(PLANNED_GRAPH)
        self.identity_graph = self.g.graph(IDENTITY_GRAPH)
        self.session_ref = f"world-model:{self.session_id or 'anonymous'}"
        self._cas_run_id = f"wm-{hashlib.sha256(self.session_ref.encode('utf-8')).hexdigest()[:32]}"
        self._cas_branch_id = "main"
        self._descriptor_digest = ""
        self._committed_payload = b""
        self.projection_version = WORLD_MODEL_PROJECTION_VERSION
        self.schema_version = WORLD_MODEL_SCHEMA_VERSION
        self.code_version = WORLD_MODEL_CODE_VERSION
        self.digest_algorithm = WORLD_MODEL_DIGEST_ALGORITHM
        snapshot = getattr(catalog, "snapshot", catalog)
        self.data_digest = _text(getattr(snapshot, "digest", ""))
        self.schema_mapping_digest = _text(
            getattr(schema_mapping_snapshot, "mapping_fingerprint", "")
            or getattr(schema_mapping_snapshot, "decision_fingerprint", "")
            or getattr(schema_mapping_snapshot, "candidate_digest", "")
        )
        self.version = 1
        self._write_lock = RLock()
        initialization_started = perf_counter()
        restore_started = perf_counter()
        restored = self._restore_persisted_snapshot()
        restore_ms = (perf_counter() - restore_started) * 1000
        projection_ms = 0.0
        if not restored:
            projection_started = perf_counter()
            self._project_catalog()
            projection_ms = (perf_counter() - projection_started) * 1000
        self._write_version_marker()
        self.snapshot_digest = self._graph_digest()
        persistence_ms = 0.0
        if not restored:
            try:
                persistence_started = perf_counter()
                self._persist_snapshot(parent_descriptor=self._descriptor_digest)
                persistence_ms = (perf_counter() - persistence_started) * 1000
            except Exception as exc:
                if self._restore_persisted_snapshot():
                    self.snapshot_digest = self._graph_digest()
                else:
                    raise RuntimeError(
                        "world-model initial CAS conflict could not be reloaded"
                    ) from exc
        self.current_world = CurrentWorldQueryAdapter(self)
        self.current_world_port = self.current_world
        # The generic adapter remains private to the store's deferred
        # identity/intent write implementation. Current-view consumers are
        # wired to ``current_world`` by Context Runtime.
        self.read_port = KGWorldModelAdapter(self)
        logger.info(
            "[WorldModelKGStore] initialized session=%s restored=%s triples=%d "
            "restore_ms=%.1f projection_ms=%.1f persistence_ms=%.1f total_ms=%.1f",
            self.session_id,
            restored,
            len(self.g),
            restore_ms,
            projection_ms,
            persistence_ms,
            (perf_counter() - initialization_started) * 1000,
        )

    @property
    def snapshot_ref(self) -> str:
        return f"world-model://{self.session_id or 'anonymous'}/{self.version}/{self.snapshot_digest}"

    def _graph_digest(self) -> str:
        return _stable_graph_digest(self.g)

    @property
    def current_world_digest(self) -> str:
        """Digest of source + current world view, excluding planned state."""

        return _stable_context_digest(self.source_graph, self.world_graph)

    def _snapshot_quads(self) -> list[tuple[Any, Any, Any, Any]]:
        return [
            (subject, predicate, obj, context.identifier)
            for context in self.g.contexts()
            for subject, predicate, obj in context
        ]

    def _restore_quads(self, quads: list[tuple[Any, Any, Any, Any]]) -> None:
        for context in list(self.g.contexts()):
            context.remove((None, None, None))
        for subject, predicate, obj, graph_id in quads:
            self.g.graph(graph_id).add((subject, predicate, obj))

    def _recover_after_commit_failure(
        self,
        quads: list[tuple[Any, Any, Any, Any]],
        *,
        version: int,
        snapshot_digest: str,
        descriptor_digest: str,
    ) -> None:
        """Restore the last local graph, then follow a newer CAS pointer."""

        self._restore_quads(quads)
        self.version = version
        self.snapshot_digest = snapshot_digest
        self._descriptor_digest = descriptor_digest
        if self._restore_persisted_snapshot():
            self.snapshot_digest = self._graph_digest()

    def _repository(self) -> Any:
        from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository

        return ContentAddressedArtifactRepository(
            self.artifact_root / "world_model_cas"
        )

    def _restore_local_committed_payload(
        self,
        *,
        version: int,
        snapshot_digest: str,
        descriptor_digest: str,
    ) -> bool:
        """Recover the last published graph when the repository is unavailable."""

        if not self._committed_payload or not snapshot_digest:
            return False
        try:
            candidate = Dataset(default_union=True)
            candidate.parse(
                data=self._committed_payload.decode("utf-8"),
                format="trig",
            )
            if _stable_graph_digest(candidate) != snapshot_digest:
                return False
            world = candidate.graph(WORLD_GRAPH)
            session_nodes = tuple(set(
                world.subjects(PLN.sessionRef, Literal(self.session_ref))
            ))
            if len(session_nodes) != 1:
                return False
            self.g = candidate
            self.source_graph = self.g.graph(SOURCE_GRAPH)
            self.assertion_graph = self.g.graph(ASSERTION_GRAPH)
            self.world_graph = world
            self.intent_graph = self.g.graph(INTENT_GRAPH)
            self.planned_graph = self.g.graph(PLANNED_GRAPH)
            self.identity_graph = self.g.graph(IDENTITY_GRAPH)
            self.session_node = session_nodes[0]
            self.version = version
            self.snapshot_digest = snapshot_digest
            self._descriptor_digest = descriptor_digest
            return True
        except Exception as exc:
            logger.warning(
                "[WorldModelKGStore] local committed snapshot restore failed: %s",
                type(exc).__name__,
            )
            return False

    def _restore_persisted_snapshot(self) -> bool:
        """Restore the latest DATA-matching immutable graph, if available."""

        try:
            from rdflib import Dataset

            repository = self._repository()
            descriptor = repository.get_named_ref(
                self._cas_run_id,
                self._cas_branch_id,
                "world_model",
            )
            if descriptor is None:
                return False
            # This is the exact named-ref version observed by this writer.
            # Keep it even when the graph belongs to another DATA snapshot so
            # a subsequent initial projection can advance the pointer with a
            # real compare-and-set instead of treating the branch as empty.
            self._descriptor_digest = descriptor.descriptor_digest
            expected_provenance = {
                "session_ref": self.session_ref,
                "projection_version": self.projection_version,
                "schema_version": self.schema_version,
                "code_version": self.code_version,
                "digest_algorithm": self.digest_algorithm,
                "schema_mapping_artifact_ref": self.schema_mapping_artifact_ref,
                "schema_mapping_digest": self.schema_mapping_digest,
            }
            actual_provenance = dict(descriptor.provenance or {})
            if any(
                str(actual_provenance.get(key) or "") != str(expected or "")
                for key, expected in expected_provenance.items()
            ):
                return False
            parents = dict(descriptor.parent_digests or {})
            if str(parents.get("data_snapshot") or "") != self.data_digest:
                return False
            if str(descriptor.schema_id or "") != "session_world_model_trig":
                return False
            if str(descriptor.schema_version or "") != self.schema_version:
                return False
            payload = repository.get_bytes(descriptor)
            candidate = Dataset(default_union=True)
            candidate.parse(data=payload.decode("utf-8"), format="trig")
            world = candidate.graph(WORLD_GRAPH)
            data_digest = next(
                (
                    str(obj)
                    for _subject, _predicate, obj in world.triples(
                        (None, PLN.dataSnapshotDigest, None)
                    )
                ),
                "",
            )
            if data_digest != self.data_digest:
                return False
            schema_mapping_digest = next(
                (
                    str(obj)
                    for _subject, _predicate, obj in world.triples(
                        (None, PLN.schemaMappingDigest, None)
                    )
                ),
                "",
            )
            if schema_mapping_digest != self.schema_mapping_digest:
                return False
            schema_mapping_artifact_ref = next(
                (
                    str(obj)
                    for _subject, _predicate, obj in world.triples(
                        (None, PLN.schemaMappingArtifactRef, None)
                    )
                ),
                "",
            )
            if schema_mapping_artifact_ref != self.schema_mapping_artifact_ref:
                return False
            # Old snapshots (or snapshots produced by a different projection
            # implementation) must not silently become the current graph just
            # because they happen to reference the same DATA digest.
            marker_values = {
                "projection_version": next(
                    (
                        str(obj)
                        for _subject, _predicate, obj in world.triples(
                            (None, PLN.worldModelProjectionVersion, None)
                        )
                    ),
                    "",
                ),
                "schema_version": next(
                    (
                        str(obj)
                        for _subject, _predicate, obj in world.triples(
                            (None, PLN.worldModelSchemaVersion, None)
                        )
                    ),
                    "",
                ),
                "code_version": next(
                    (
                        str(obj)
                        for _subject, _predicate, obj in world.triples(
                            (None, PLN.worldModelCodeVersion, None)
                        )
                    ),
                    "",
                ),
                "digest_algorithm": next(
                    (
                        str(obj)
                        for _subject, _predicate, obj in world.triples(
                            (None, PLN.worldModelDigestAlgorithm, None)
                        )
                    ),
                    "",
                ),
            }
            if marker_values != {
                "projection_version": self.projection_version,
                "schema_version": self.schema_version,
                "code_version": self.code_version,
                "digest_algorithm": self.digest_algorithm,
            }:
                return False
            persisted_graph_digest = str(
                actual_provenance.get("graph_digest") or ""
            )
            if (
                not persisted_graph_digest
                or _stable_graph_digest(candidate) != persisted_graph_digest
            ):
                logger.warning(
                    "[WorldModelKGStore] persisted graph digest mismatch; "
                    "rebuilding from DATA snapshot"
                )
                return False
            session_nodes = tuple(set(
                world.subjects(PLN.sessionRef, Literal(self.session_ref))
            ))
            if len(session_nodes) != 1:
                return False
            version_values = tuple(
                world.objects(session_nodes[0], PLN.worldModelVersion)
            )
            if (
                len(version_values) != 1
                or not str(version_values[0]).isdigit()
            ):
                return False
            restored_version = int(str(version_values[0]))
            if str(actual_provenance.get("world_model_version") or "") != str(
                restored_version
            ):
                return False
            self.g = candidate
            self.source_graph = self.g.graph(SOURCE_GRAPH)
            self.assertion_graph = self.g.graph(ASSERTION_GRAPH)
            self.world_graph = self.g.graph(WORLD_GRAPH)
            self.intent_graph = self.g.graph(INTENT_GRAPH)
            self.planned_graph = self.g.graph(PLANNED_GRAPH)
            self.identity_graph = self.g.graph(IDENTITY_GRAPH)
            self.session_node = session_nodes[0]
            self.version = restored_version
            self._committed_payload = payload
            return True
        except Exception as exc:
            logger.warning("[WorldModelKGStore] persisted snapshot restore skipped: %s", type(exc).__name__)
            return False

    def _write_version_marker(self) -> None:
        """Keep the session's committed graph version inside the graph.

        Planned feature nodes also carry a version, but a snapshot can be
        changed by an intent or semantic assertion without creating a planned
        node.  The session marker is therefore the single durable version
        cursor used when restoring the World Model in a fresh process.
        """

        self.world_graph.set((self.session_node, PLN.worldModelVersion, Literal(self.version)))
        self.world_graph.set(
            (
                self.session_node,
                PLN.worldModelProjectionVersion,
                Literal(self.projection_version),
            )
        )
        self.world_graph.set(
            (self.session_node, PLN.worldModelSchemaVersion, Literal(self.schema_version))
        )
        self.world_graph.set(
            (self.session_node, PLN.worldModelCodeVersion, Literal(self.code_version))
        )
        self.world_graph.set((
            self.session_node,
            PLN.worldModelDigestAlgorithm,
            Literal(self.digest_algorithm),
        ))
        self.world_graph.set((
            self.session_node,
            PLN.schemaMappingDigest,
            Literal(self.schema_mapping_digest),
        ))
        self.world_graph.set((
            self.session_node,
            PLN.schemaMappingArtifactRef,
            Literal(self.schema_mapping_artifact_ref),
        ))

    def _persist_snapshot(
        self,
        *,
        parent_descriptor: str = "",
        commit_parents: dict[str, str] | None = None,
        commit_provenance: dict[str, Any] | None = None,
    ) -> str:
        """Write an immutable TriG blob and update the branch pointer atomically."""

        repository = self._repository()
        self.snapshot_digest = self._graph_digest()
        payload = _roundtrip_trig(self.g)
        descriptor = repository.put_bytes(
            payload,
            schema_id="session_world_model_trig",
            schema_version=self.schema_version,
            producer_stage="COGNITION",
            run_id=self._cas_run_id,
            branch_id=self._cas_branch_id,
            parent_digests={
                "data_snapshot": self.data_digest,
                **(
                    {"schema_mapping": self.schema_mapping_artifact_ref}
                    if self.schema_mapping_artifact_ref
                    else {}
                ),
                **(
                    {"schema_mapping_semantic": self.schema_mapping_digest}
                    if self.schema_mapping_digest
                    else {}
                ),
                **({"world_model": parent_descriptor} if parent_descriptor else {}),
                **dict(commit_parents or {}),
            },
            provenance={
                "session_ref": self.session_ref,
                "world_model_version": self.version,
                "projection_version": self.projection_version,
                "schema_version": self.schema_version,
                "code_version": self.code_version,
                "digest_algorithm": self.digest_algorithm,
                "graph_digest": self.snapshot_digest,
                "schema_mapping_artifact_ref": self.schema_mapping_artifact_ref,
                "schema_mapping_digest": self.schema_mapping_digest,
                **dict(commit_provenance or {}),
            },
        )
        repository.compare_and_set_named_ref(
            self._cas_run_id,
            self._cas_branch_id,
            "world_model",
            descriptor,
            expected_descriptor_digest=self._descriptor_digest or None,
        )
        self._descriptor_digest = descriptor.descriptor_digest
        self._committed_payload = payload
        return descriptor.descriptor_digest

    def refresh_snapshot(self) -> str:
        """Refresh the immutable-snapshot identifier after an external projection."""
        with self._write_lock:
            digest = self._graph_digest()
            if digest != self.snapshot_digest:
                previous_version = self.version
                previous_snapshot_digest = self.snapshot_digest
                previous_descriptor = self._descriptor_digest
                self.version += 1
                self._write_version_marker()
                self.snapshot_digest = self._graph_digest()
                try:
                    self._persist_snapshot(parent_descriptor=previous_descriptor)
                except Exception:
                    # A CAS conflict means another writer committed first.
                    # Discard this unpublished in-memory projection and move
                    # to the current immutable snapshot before returning the
                    # conflict to the caller.
                    if self._restore_persisted_snapshot():
                        self.snapshot_digest = self._graph_digest()
                    elif not self._restore_local_committed_payload(
                        version=previous_version,
                        snapshot_digest=previous_snapshot_digest,
                        descriptor_digest=previous_descriptor,
                    ):
                        self.snapshot_digest = ""
                        raise RuntimeError(
                            "World Model commit failed and no committed graph "
                            "could be restored"
                        )
                    raise
            return self.snapshot_ref

    def snapshot_contract(self) -> Any:
        """Return a bounded serializable descriptor of the current graph."""

        from app.contracts.cognition.snapshot import SessionWorldModelSnapshot

        return SessionWorldModelSnapshot(
            snapshot_ref=self.snapshot_ref,
            session_id=self.session_id,
            version=self.version,
            source_catalog_ref=_text(getattr(self.catalog.snapshot, "snapshot_id", "")),
            source_catalog_digest=self.data_digest,
            schema_mapping_ref=self.schema_mapping_artifact_ref,
            schema_mapping_digest=self.schema_mapping_digest,
            graph_digest=self.snapshot_digest,
            current_world_digest=self.current_world_digest,
            source_record_refs=tuple(sorted(
                str(item)
                for item in self.source_graph.subjects(
                    RDF.type,
                    PLN.SourceRecord,
                )
            )),
            entity_refs=tuple(sorted(
                str(item)
                for item in self.world_graph.subjects(
                    RDF.type,
                    PLN.WorldEntity,
                )
            )),
            representation_refs=tuple(sorted(
                str(item)
                for item in self.world_graph.subjects(
                    RDF.type,
                    PLN.SpatialRepresentation,
                )
            )),
            assertion_refs=tuple(sorted(
                str(item)
                for item in self.assertion_graph.subjects(
                    RDF.type,
                    PLN.SemanticAssertion,
                )
            )),
            identity_binding_refs=tuple(sorted(
                str(item)
                for item in self.identity_graph.subjects(
                    RDF.type,
                    PLN.IdentityBinding,
                )
            )),
            planned_refs=tuple(sorted(str(item) for item in self.planned_graph.subjects(RDF.type, PLN.PlannedFeature))),
            data_dependency_graph_digest=str(getattr(self.catalog, "data_dependency_graph_digest", "") or ""),
        )

    def _project_catalog(self) -> None:
        projected = project_source_catalog(
            self.source_graph,
            self.catalog,
            world_graph=self.world_graph,
            schema_mapping_snapshot=self.schema_mapping_snapshot,
        )
        session_node = URIRef(f"{PLN_NS}session_{_digest(self.session_ref)[:24]}")
        self.world_graph.add((session_node, RDF.type, PLN.WorldModelSession))
        self.world_graph.add((session_node, PLN.sessionRef, Literal(self.session_ref)))
        self.world_graph.add((session_node, PLN.villageName, Literal(self.village_name)))
        self.world_graph.add((session_node, PLN.dataSnapshotDigest, Literal(self.data_digest)))
        self.world_graph.add((session_node, PLN.projectedFeatureCount, Literal(projected)))
        self.session_node = session_node

    def find_entities(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.read_port.find_entities(**kwargs)

    def representations_for(self, entity_ref: str, **kwargs: Any) -> list[dict[str, Any]]:
        return self.read_port.representations_for(entity_ref, **kwargs)

    def find_relations(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.read_port.find_relations(**kwargs)

    def find_identity_bindings(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.read_port.find_identity_bindings(**kwargs)

    def query_identity_binding_page(self, request: Any) -> Any:
        return self.read_port.query_identity_binding_page(request)

    def build_network_retry_adapter(self) -> Any:
        return self.read_port.build_network_retry_adapter()

    def ensure_intent(self, intent: Any) -> dict[str, Any]:
        """Commit a bounded, inspectable intent record without legacy builders."""

        with self._write_lock:
            payload = _model_dict(intent)
            intent_ref = _text(payload.get("intent_ref") or payload.get("target_ref"))
            if not intent_ref:
                intent_ref = f"intent:{_digest(payload)[:32]}"
            node = URIRef(f"{PLN_NS}intent_{_digest(intent_ref)[:24]}")
            before = len(self.g)
            graph_snapshot = self._snapshot_quads()
            previous_version = self.version
            previous_snapshot_digest = self.snapshot_digest
            self.intent_graph.add((node, RDF.type, PLN.PlanningIntent))
            self.intent_graph.add((node, PLN.intentRef, Literal(intent_ref)))
            self.intent_graph.add((node, PLN.inWorldModelSession, self.session_node))
            for key, value in sorted(payload.items(), key=lambda item: str(item[0])):
                if value in (None, "", [], {}, ()):
                    continue
                predicate = URIRef(f"{PLN_NS}intent_{_text(key)}")
                self.intent_graph.add((node, predicate, Literal(json.dumps(value, ensure_ascii=False, default=str, sort_keys=True))))
            if len(self.g) == before:
                return {"status": "committed", "intent_ref": intent_ref, "triple_delta": 0, "world_model_version": self.version}
            previous_digest = self._descriptor_digest
            self.version += 1
            self._write_version_marker()
            self.snapshot_digest = self._graph_digest()
            try:
                self._persist_snapshot(parent_descriptor=previous_digest)
            except Exception:
                self._recover_after_commit_failure(
                    graph_snapshot,
                    version=previous_version,
                    snapshot_digest=previous_snapshot_digest,
                    descriptor_digest=previous_digest,
                )
                raise
            return {
                "status": "committed",
                "intent_ref": intent_ref,
                "triple_delta": max(0, len(self.g) - before),
                "world_model_version": self.version,
                "world_model_snapshot_ref": self.snapshot_ref,
            }

    def commit_planned_state(self, planned_state: Any) -> dict[str, Any]:
        """Atomically append generic planned features and record lineage.

        ``features`` is the canonical output.  Other typed lists are retained
        as JSON records for compatibility, but are never required to be parcel
        records and never need a BSM.
        """

        with self._write_lock:
            payload = _model_dict(planned_state)
            recognized_fields = ("features", "zones", "overlays", "facilities", "roads", "axes", "parcels")
            if not any(payload.get(field) for field in recognized_fields):
                return {
                    "status": "noop",
                    "committed": True,
                    "written": 0,
                    "world_model_version": self.version,
                    "world_model_snapshot_ref": self.snapshot_ref,
                }
            graph_snapshot = self._snapshot_quads()
            previous_version = self.version
            previous_digest = self.snapshot_digest
            previous_descriptor = self._descriptor_digest
            try:
                written = 0
                commit_version = self.version + 1
                for feature in payload.get("features") or []:
                    feature_payload = _model_dict(feature)
                    feature_id = _text(feature_payload.get("feature_id"))
                    if not feature_id:
                        raise ValueError("planned feature requires feature_id")
                    self._validate_planned_lineage(feature_payload)
                    node = URIRef(f"{PLN_NS}planned_feature_{_digest(feature_id)[:20]}_v{commit_version}")
                    self._write_planned_feature(node, feature_payload, version=commit_version)
                    written += 1
                for field in ("zones", "overlays", "facilities", "roads", "axes", "parcels"):
                    for index, record in enumerate(payload.get(field) or []):
                        record_payload = _model_dict(record)
                        identity = _text(
                            record_payload.get("feature_id")
                            or record_payload.get("target_ref")
                            or record_payload.get("name")
                            or f"{field}:{index}"
                        )
                        node = URIRef(f"{PLN_NS}planned_record_{_digest(field + ':' + identity)[:20]}_v{commit_version}")
                        self._write_planned_record(node, field, identity, record_payload, version=commit_version)
                        written += 1
            except Exception as exc:
                self._restore_quads(graph_snapshot)
                return {"status": "aborted", "committed": False, "error_type": type(exc).__name__}
            self.version += 1
            self._write_version_marker()
            self.snapshot_digest = self._graph_digest()
            try:
                self._persist_snapshot(parent_descriptor=previous_descriptor)
            except Exception as exc:
                self._recover_after_commit_failure(
                    graph_snapshot,
                    version=previous_version,
                    snapshot_digest=previous_digest,
                    descriptor_digest=previous_descriptor,
                )
                return {"status": "aborted", "committed": False, "error_type": type(exc).__name__}
            return {
                "status": "committed",
                "committed": True,
                "written": written,
                "world_model_version": self.version,
                "world_model_snapshot_ref": self.snapshot_ref,
            }

    def commit_identity_bindings(self, envelope: Any) -> Any:
        """Replace the current L1 identity assertion plane atomically.

        This commit can only reference existing DATA-backed entities, parts
        and representations.  Evidence-provider candidates remain literal
        provenance refs; they can never create an entity or geometry here.
        """

        from app.contracts.cognition.identity_projection import (
            IdentityBindingCommitEnvelope,
            IdentityBindingCommitResult,
        )

        try:
            typed = IdentityBindingCommitEnvelope.model_validate(envelope)
        except Exception as exc:
            return IdentityBindingCommitResult(
                status="aborted",
                committed=False,
                error_type=f"invalid_commit_envelope:{type(exc).__name__}",
            )

        projection_fingerprint = "sha256:" + semantic_checksum({
            "run_id": typed.run_id,
            "branch_id": typed.branch_id,
            "l1_snapshot": typed.l1_snapshot_artifact_ref.descriptor_digest,
            "source_world_model": (
                typed.source_world_model_artifact_ref.descriptor_digest
            ),
            "observations": typed.observation_artifact_ref.descriptor_digest,
            "bindings": typed.binding_artifact_ref.descriptor_digest,
        })
        parent_ref = typed.source_world_model_snapshot.snapshot_ref
        parent_digest = typed.source_world_model_snapshot.graph_digest

        def aborted(error_type: str) -> Any:
            return IdentityBindingCommitResult(
                status="aborted",
                committed=False,
                error_type=error_type,
                projection_fingerprint=projection_fingerprint,
                parent_world_model_snapshot_ref=parent_ref,
                parent_world_model_snapshot_digest=parent_digest,
                world_model_version=self.version,
                world_model_snapshot_ref=self.snapshot_ref,
                world_model_snapshot_digest=self.snapshot_digest,
            )

        with self._write_lock:
            marker = URIRef(
                f"{PLN_NS}identity_projection_"
                f"{_digest(self.session_ref)[:24]}"
            )
            existing_fingerprint = _text(
                self.identity_graph.value(
                    marker,
                    PLN.identityProjectionFingerprint,
                )
            )
            projected_version_text = _text(
                self.identity_graph.value(
                    marker,
                    PLN.projectedAtWorldModelVersion,
                )
            )
            projected_version = (
                int(projected_version_text)
                if projected_version_text.isdigit()
                else 0
            )
            if existing_fingerprint == projection_fingerprint:
                if projected_version != self.version:
                    return aborted(
                        "identity_projection_replay_after_world_model_advanced"
                    )
                snapshot = self.snapshot_contract().model_copy(update={
                    "parent_snapshot_ref": parent_ref,
                    "parent_snapshot_digest": parent_digest,
                })
                return IdentityBindingCommitResult(
                    status="noop",
                    committed=True,
                    written=0,
                    projection_fingerprint=projection_fingerprint,
                    parent_world_model_snapshot_ref=parent_ref,
                    parent_world_model_snapshot_digest=parent_digest,
                    world_model_version=self.version,
                    world_model_snapshot_ref=self.snapshot_ref,
                    world_model_snapshot_digest=self.snapshot_digest,
                    internal_cas_descriptor_digest=self._descriptor_digest,
                    world_model_snapshot=snapshot,
                )

            if parent_ref != self.snapshot_ref:
                return aborted("stale_parent_world_model_snapshot_ref")
            if parent_digest != self.snapshot_digest:
                return aborted("stale_parent_world_model_snapshot_digest")
            if typed.source_world_model_snapshot.session_id != self.session_id:
                return aborted("foreign_world_model_session")
            for ref, value, label in (
                (
                    typed.source_world_model_artifact_ref,
                    typed.source_world_model_snapshot,
                    "source_world_model",
                ),
                (
                    typed.observation_artifact_ref,
                    typed.observation_snapshot,
                    "observation_snapshot",
                ),
                (
                    typed.binding_artifact_ref,
                    typed.binding_snapshot,
                    "binding_snapshot",
                ),
            ):
                expected_semantic = "sha256:" + semantic_checksum(value)
                if ref.semantic_digest != expected_semantic:
                    return aborted(f"{label}_semantic_digest_mismatch")
            if (
                typed.l1_snapshot_artifact_ref.digest
                not in set(typed.observation_snapshot.provenance_refs)
            ):
                return aborted("observation_snapshot_l1_lineage_mismatch")
            if (
                typed.binding_snapshot.parent_digest
                != typed.observation_artifact_ref.digest
            ):
                return aborted("binding_snapshot_parent_digest_mismatch")

            observations: dict[str, dict[str, Any]] = {}
            for raw_observation in typed.observation_snapshot.observations:
                observation = _model_dict(raw_observation)
                keys = {
                    _text(observation.get("observation_id")),
                    _text(observation.get("work_item_ref")),
                }
                keys.update(
                    _text(value)
                    for value in observation.get("source_mention_refs") or []
                )
                for key in keys:
                    if key:
                        observations[key] = observation

            prepared: list[tuple[URIRef, dict[str, Any], dict[str, Any]]] = []
            known_entity_count = len(set(
                self.world_graph.subjects(RDF.type, PLN.WorldEntity)
            ))
            known_representation_count = len(set(
                self.world_graph.subjects(
                    RDF.type,
                    PLN.SpatialRepresentation,
                )
            ))
            known_geometry_count = len(set(
                self.g.subjects(RDF.type, GEO.Geometry)
            ))
            for raw_binding in typed.binding_snapshot.bindings:
                binding = _model_dict(raw_binding)
                binding_ref = _text(binding.get("binding_id"))
                mention_ref = _text(binding.get("mention_ref"))
                if not binding_ref or not mention_ref:
                    return aborted("identity_binding_missing_identity")
                observation = observations.get(mention_ref)
                if observation is None:
                    return aborted("identity_binding_observation_missing")
                candidate_entities = list(dict.fromkeys(
                    _text(value)
                    for value in (
                        binding.get("candidate_entity_refs") or []
                    )
                    if _text(value)
                ))
                canonical_entity = _text(
                    binding.get("canonical_entity_ref")
                )
                if canonical_entity and canonical_entity not in candidate_entities:
                    return aborted("canonical_entity_not_in_candidates")
                entity_rows: dict[str, dict[str, Any]] = {}
                for entity_ref in candidate_entities:
                    rows = self.find_entities(
                        entity_ref=entity_ref,
                        limit=1,
                    )
                    if not rows:
                        return aborted("identity_binding_foreign_entity_ref")
                    entity_rows[entity_ref] = rows[0]
                for anchor_entity_ref in sorted({
                    _text(value)
                    for value in binding.get("anchor_entity_refs") or []
                    if _text(value)
                }):
                    rows = self.find_entities(
                        entity_ref=anchor_entity_ref,
                        limit=1,
                    )
                    if not rows:
                        return aborted(
                            "relative_location_foreign_anchor_entity_ref"
                        )

                known_parts = {
                    _text(part.get("entity_part_ref"))
                    for entity in entity_rows.values()
                    for part in entity.get("parts") or []
                    if _text(part.get("entity_part_ref"))
                }
                known_features = {
                    _text(part.get("source_feature_ref"))
                    for entity in entity_rows.values()
                    for part in entity.get("parts") or []
                    if _text(part.get("source_feature_ref"))
                }
                representations = [
                    representation
                    for entity_ref in candidate_entities
                    for representation in self.representations_for(
                        entity_ref,
                        limit=256,
                    )
                ]
                known_representations = {
                    _text(item.get("representation_ref"))
                    for item in representations
                    if _text(item.get("representation_ref"))
                }
                known_resources = {
                    _text(item.get("resource_ref"))
                    for item in representations
                    if _text(item.get("resource_ref"))
                }
                for field, known in (
                    ("entity_part_refs", known_parts),
                    ("source_feature_ids", known_features),
                    ("representation_refs", known_representations),
                    ("resource_refs", known_resources),
                ):
                    supplied = {
                        _text(value)
                        for value in binding.get(field) or []
                        if _text(value)
                    }
                    if supplied - known:
                        return aborted(
                            f"identity_binding_foreign_{field}"
                        )
                node = URIRef(
                    f"{PLN_NS}identity_binding_{_digest(binding_ref)[:24]}"
                )
                prepared.append((node, binding, observation))

            graph_snapshot = self._snapshot_quads()
            previous_version = self.version
            previous_digest = self.snapshot_digest
            previous_descriptor = self._descriptor_digest
            try:
                self.identity_graph.remove((None, None, None))
                commit_version = self.version + 1
                self.identity_graph.add((
                    marker,
                    RDF.type,
                    PLN.IdentityProjectionCommit,
                ))
                self.identity_graph.add((
                    marker,
                    PLN.inWorldModelSession,
                    self.session_node,
                ))
                for predicate, value in (
                    (
                        PLN.identityProjectionFingerprint,
                        projection_fingerprint,
                    ),
                    (PLN.sourceWorldModelSnapshotRef, parent_ref),
                    (PLN.sourceWorldModelSnapshotDigest, parent_digest),
                    (
                        PLN.sourceL1ObservationSnapshotArtifactDigest,
                        typed.l1_snapshot_artifact_ref.digest,
                    ),
                    (
                        PLN.observationSnapshotRef,
                        typed.observation_artifact_ref.digest,
                    ),
                    (
                        PLN.bindingSnapshotRef,
                        typed.binding_artifact_ref.digest,
                    ),
                ):
                    self.identity_graph.add((
                        marker,
                        predicate,
                        Literal(value),
                    ))
                self.identity_graph.add((
                    marker,
                    PLN.projectedAtWorldModelVersion,
                    Literal(commit_version),
                ))

                for node, binding, observation in prepared:
                    self.identity_graph.add((
                        node,
                        RDF.type,
                        PLN.IdentityBinding,
                    ))
                    self.identity_graph.add((
                        node,
                        PLN.inWorldModelSession,
                        self.session_node,
                    ))
                    scalar_values = (
                        (PLN.bindingRef, _text(binding.get("binding_id"))),
                        (PLN.mentionRef, _text(binding.get("mention_ref"))),
                        (
                            PLN.workItemRef,
                            _text(observation.get("work_item_ref"))
                            or _text(binding.get("mention_ref")),
                        ),
                        (
                            PLN.canonicalEntityRef,
                            _text(binding.get("canonical_entity_ref")),
                        ),
                        (
                            PLN.identityStatus,
                            _text(binding.get("identity_status"))
                            or "unresolved",
                        ),
                        (
                            PLN.bindingStatus,
                            _text(binding.get("status")) or "unresolved",
                        ),
                        (
                            PLN.uncertaintyReason,
                            _text(binding.get("uncertainty_reason")),
                        ),
                        (
                            PLN.spatialHint,
                            _text(observation.get("spatial_hint")),
                        ),
                        (
                            PLN.observedName,
                            _text(observation.get("normalized_name"))
                            or _text(observation.get("mention")),
                        ),
                        (
                            PLN.sourceWorldModelSnapshotRef,
                            parent_ref,
                        ),
                        (
                            PLN.sourceWorldModelSnapshotDigest,
                            parent_digest,
                        ),
                        (
                            PLN.observationSnapshotRef,
                            typed.observation_artifact_ref.digest,
                        ),
                        (
                            PLN.bindingSnapshotRef,
                            typed.binding_artifact_ref.digest,
                        ),
                        (
                            PLN.identityProjectionFingerprint,
                            projection_fingerprint,
                        ),
                    )
                    for predicate, value in scalar_values:
                        if value:
                            self.identity_graph.add((
                                node,
                                predicate,
                                Literal(value),
                            ))
                    self.identity_graph.add((
                        node,
                        PLN.bindingConfidence,
                        Literal(float(binding.get("confidence") or 0.0)),
                    ))
                    self.identity_graph.add((
                        node,
                        PLN.projectedAtWorldModelVersion,
                        Literal(commit_version),
                    ))
                    repeated_values = (
                        (
                            PLN.candidateEntityRef,
                            binding.get("candidate_entity_refs") or [],
                        ),
                        (
                            PLN.observationRef,
                            binding.get("observation_refs") or [],
                        ),
                        (
                            PLN.sourceMentionRef,
                            observation.get("source_mention_refs") or [],
                        ),
                        (
                            PLN.dimensionRef,
                            observation.get("dimension_keys") or [],
                        ),
                        (
                            PLN.scopeRef,
                            observation.get("scope_refs") or [],
                        ),
                        (
                            PLN.relationMentionRef,
                            observation.get("relation_mentions") or [],
                        ),
                        (
                            PLN.representationRef,
                            binding.get("representation_refs") or [],
                        ),
                        (
                            PLN.resourceRef,
                            binding.get("resource_refs") or [],
                        ),
                        (
                            PLN.entityPartRef,
                            binding.get("entity_part_refs") or [],
                        ),
                        (
                            PLN.sourceFeatureRef,
                            binding.get("source_feature_ids") or [],
                        ),
                        (
                            PLN.evidenceCandidateRef,
                            binding.get("candidate_refs") or [],
                        ),
                        (
                            PLN.evidenceRef,
                            [
                                *(binding.get("evidence_refs") or []),
                                *(observation.get("evidence_refs") or []),
                            ],
                        ),
                        (
                            PLN.relationEvidenceRef,
                            binding.get("relation_evidence_refs") or [],
                        ),
                    )
                    for predicate, values in repeated_values:
                        for value in sorted({
                            _text(item) for item in values if _text(item)
                        }):
                            self.identity_graph.add((
                                node,
                                predicate,
                                Literal(value),
                            ))

                    expression_ref = _text(
                        binding.get("location_expression_ref")
                    )
                    expression_status = _text(
                        binding.get("location_expression_status")
                    ) or "none"
                    if expression_ref and expression_status != "none":
                        expression = URIRef(
                            f"{PLN_NS}relative_location_expression_"
                            f"{_digest(expression_ref)[:24]}"
                        )
                        self.identity_graph.add((
                            node,
                            PLN.hasLocationExpression,
                            expression,
                        ))
                        self.identity_graph.add((
                            expression,
                            RDF.type,
                            PLN.RelativeLocationExpression,
                        ))
                        self.identity_graph.add((
                            expression,
                            PLN.inWorldModelSession,
                            self.session_node,
                        ))
                        for predicate, value in (
                            (PLN.locationExpressionRef, expression_ref),
                            (PLN.locationExpressionStatus, expression_status),
                            (
                                PLN.spatialRelation,
                                _text(binding.get("spatial_relation")),
                            ),
                            (
                                PLN.distanceHint,
                                _text(binding.get("distance_hint")),
                            ),
                        ):
                            if value:
                                self.identity_graph.add((
                                    expression,
                                    predicate,
                                    Literal(value),
                                ))
                        for predicate, values in (
                            (
                                PLN.anchorEntityRef,
                                binding.get("anchor_entity_refs") or [],
                            ),
                            (
                                PLN.anchorWorkItemRef,
                                binding.get("anchor_work_item_refs") or [],
                            ),
                        ):
                            for value in sorted({
                                _text(item)
                                for item in values
                                if _text(item)
                            }):
                                self.identity_graph.add((
                                    expression,
                                    predicate,
                                    Literal(value),
                                ))

                if len(set(self.world_graph.subjects(
                    RDF.type,
                    PLN.WorldEntity,
                ))) != known_entity_count:
                    raise RuntimeError("identity commit changed entity count")
                if len(set(self.world_graph.subjects(
                    RDF.type,
                    PLN.SpatialRepresentation,
                ))) != known_representation_count:
                    raise RuntimeError(
                        "identity commit changed representation count"
                    )
                if len(set(self.g.subjects(
                    RDF.type,
                    GEO.Geometry,
                ))) != known_geometry_count:
                    raise RuntimeError("identity commit changed geometry count")

                self.version = commit_version
                self._write_version_marker()
                self.snapshot_digest = self._graph_digest()
                internal_descriptor = self._persist_snapshot(
                    parent_descriptor=previous_descriptor,
                    commit_parents={
                        "l1_snapshot": (
                            typed.l1_snapshot_artifact_ref.descriptor_digest
                        ),
                        "l1_observations": (
                            typed.observation_artifact_ref.descriptor_digest
                        ),
                        "l1_bindings": (
                            typed.binding_artifact_ref.descriptor_digest
                        ),
                        "source_world_model_artifact": (
                            typed.source_world_model_artifact_ref.descriptor_digest
                        ),
                    },
                    commit_provenance={
                        "identity_projection_fingerprint": (
                            projection_fingerprint
                        ),
                        "identity_commit_run_id": typed.run_id,
                        "identity_commit_branch_id": typed.branch_id,
                    },
                )
            except Exception as exc:
                self._recover_after_commit_failure(
                    graph_snapshot,
                    version=previous_version,
                    snapshot_digest=previous_digest,
                    descriptor_digest=previous_descriptor,
                )
                return aborted(
                    f"identity_commit_failed:{type(exc).__name__}"
                )

            snapshot = self.snapshot_contract().model_copy(update={
                "parent_snapshot_ref": parent_ref,
                "parent_snapshot_digest": parent_digest,
            })
            return IdentityBindingCommitResult(
                status="committed",
                committed=True,
                written=len(prepared),
                projection_fingerprint=projection_fingerprint,
                parent_world_model_snapshot_ref=parent_ref,
                parent_world_model_snapshot_digest=parent_digest,
                world_model_version=self.version,
                world_model_snapshot_ref=self.snapshot_ref,
                world_model_snapshot_digest=self.snapshot_digest,
                internal_cas_descriptor_digest=internal_descriptor,
                world_model_snapshot=snapshot,
            )

    def commit_assertion_transaction(
        self,
        request: Any,
        proposals: tuple[Any, ...],
        decisions: tuple[Any, ...],
    ) -> Any:
        """Apply one Cognition decision group to the current-world projection.

        The request carries only closed references.  Proposal and decision
        values are revalidated at this boundary before they are recorded in
        the assertion graph.  No proposal status is accepted as authority;
        only a matching ``AssertionDecisionArtifact(ACCEPT)`` can project a
        current-world triple.
        """

        from app.contracts.cognition.proposals import (
            AssertionCommitRequest,
            AssertionDecisionArtifact,
            AssertionProposal,
            WorldModelCommitReceipt,
        )

        old_current_digest = self.current_world_digest
        old_snapshot_digest = self.snapshot_digest
        try:
            typed_request = AssertionCommitRequest.model_validate(request)
            typed_proposals = tuple(
                AssertionProposal.model_validate(item) for item in proposals
            )
            typed_decisions = tuple(
                AssertionDecisionArtifact.model_validate(item) for item in decisions
            )
            transaction_fingerprint = "sha256:" + semantic_checksum({
                "request": typed_request,
                "proposals": typed_proposals,
                "decisions": typed_decisions,
            })
        except Exception as exc:
            return WorldModelCommitReceipt(
                status="invalid_request",
                old_current_world_digest=old_current_digest,
                new_current_world_digest=old_current_digest,
                old_world_model_snapshot_digest=old_snapshot_digest,
                new_world_model_snapshot_digest=old_snapshot_digest,
                error_type=f"invalid_transaction:{type(exc).__name__}",
            )

        parent_ref = typed_request.expected_parent_snapshot
        parent_digest = typed_request.expected_current_world_digest

        def receipt(
            status: str,
            *,
            committed: bool = False,
            error_type: str = "",
            snapshot: Any = None,
            accepted: tuple[str, ...] = (),
            ambiguous: tuple[str, ...] = (),
            rejected: tuple[str, ...] = (),
            affected_entities: tuple[str, ...] = (),
            affected_relations: tuple[str, ...] = (),
            affected_representations: tuple[str, ...] = (),
        ) -> Any:
            return WorldModelCommitReceipt(
                status=status,
                committed=committed,
                parent=parent_ref,
                child=(snapshot.snapshot_ref if snapshot is not None else ""),
                accepted_assertion_refs=accepted,
                ambiguous_assertion_refs=ambiguous,
                rejected_assertion_refs=rejected,
                affected_entity_refs=affected_entities,
                affected_relation_refs=affected_relations,
                affected_representation_refs=affected_representations,
                old_current_world_digest=old_current_digest,
                new_current_world_digest=(
                    snapshot.current_world_digest
                    if snapshot is not None
                    else self.current_world_digest
                ),
                old_world_model_snapshot_digest=old_snapshot_digest,
                new_world_model_snapshot_digest=self.snapshot_digest,
                transaction_fingerprint=transaction_fingerprint,
                error_type=error_type,
                world_model_version=self.version,
                world_model_snapshot=snapshot,
            )

        with self._write_lock:
            marker = URIRef(
                f"{PLN_NS}cognition_commit_{_digest(transaction_fingerprint)[:24]}"
            )
            existing = _text(self.assertion_graph.value(
                marker,
                URIRef(f"{PLN_NS}transactionFingerprint"),
            ))
            if existing == transaction_fingerprint:
                current = self.snapshot_contract().model_copy(update={
                    "parent_snapshot_ref": parent_ref,
                    "parent_snapshot_digest": parent_digest,
                })
                return receipt("noop", committed=True, snapshot=current)
            if parent_ref != self.snapshot_ref:
                return receipt("stale_parent", error_type="stale_parent_snapshot")
            if parent_digest != self.current_world_digest:
                return receipt("stale_parent", error_type="stale_current_world_digest")

            proposal_by_ref = {item.proposal_ref: item for item in typed_proposals}
            decision_by_ref = {item.decision_ref: item for item in typed_decisions}
            if len(proposal_by_ref) != len(typed_proposals):
                return receipt("invalid_request", error_type="duplicate_proposal_ref")
            if len(decision_by_ref) != len(typed_decisions):
                return receipt("invalid_request", error_type="duplicate_decision_ref")
            if set(proposal_by_ref) != set(typed_request.proposal_refs):
                return receipt("invalid_request", error_type="proposal_refs_not_closed")
            if set(decision_by_ref) != set(typed_request.decision_refs):
                return receipt("invalid_request", error_type="decision_refs_not_closed")
            if len(proposal_by_ref) != len(decision_by_ref):
                return receipt("invalid_request", error_type="proposal_decision_cardinality")

            decision_by_proposal: dict[str, Any] = {}
            for decision in typed_decisions:
                if decision.proposal_ref not in proposal_by_ref:
                    return receipt("invalid_request", error_type="foreign_decision_proposal")
                if decision.proposal_ref in decision_by_proposal:
                    return receipt("invalid_request", error_type="multiple_decisions_for_proposal")
                decision_by_proposal[decision.proposal_ref] = decision
            if set(decision_by_proposal) != set(proposal_by_ref):
                return receipt("invalid_request", error_type="missing_decision")
            if any(
                proposal.parent_current_world_digest != parent_digest
                for proposal in typed_proposals
            ):
                return receipt("invalid_request", error_type="proposal_parent_digest_mismatch")
            if any(
                decision.parent_current_world_digest != parent_digest
                for decision in typed_decisions
            ):
                return receipt("invalid_request", error_type="decision_parent_digest_mismatch")
            if len({proposal.subject_ref for proposal in typed_proposals}) > 1:
                return receipt("invalid_request", error_type="commit_group_must_have_one_subject")

            prepared: list[tuple[Any, Any, Any, Any, Any]] = []
            for proposal in typed_proposals:
                if not self.find_entities(entity_ref=proposal.subject_ref, limit=1):
                    return receipt("invalid_request", error_type="foreign_proposal_subject")
                if proposal.object_ref and not self.find_entities(
                    entity_ref=proposal.object_ref,
                    limit=1,
                ):
                    return receipt("invalid_request", error_type="foreign_proposal_object")
                assertion_ref = "assertion:" + _digest(proposal.proposal_ref)[:32]
                assertion_node = URIRef(assertion_ref)
                if (assertion_node, RDF.type, PLN.SemanticAssertion) in self.assertion_graph:
                    return receipt("invalid_request", error_type="proposal_already_committed")
                predicate = proposal.predicate.strip()
                predicate_node = URIRef(
                    predicate
                    if predicate.startswith(("http://", "https://", "urn:"))
                    else f"{PLN_NS}{predicate}"
                )
                object_node = (
                    URIRef(proposal.object_ref)
                    if proposal.object_ref
                    else Literal(str(proposal.value))
                )
                for superseded_ref in proposal.supersedes:
                    old_nodes = tuple(self.assertion_graph.subjects(
                        PLN.assertionRef,
                        Literal(superseded_ref),
                    ))
                    if not old_nodes:
                        return receipt(
                            "invalid_request",
                            error_type="foreign_superseded_assertion",
                        )
                prepared.append((
                    proposal,
                    decision_by_proposal[proposal.proposal_ref],
                    assertion_node,
                    predicate_node,
                    object_node,
                ))

            graph_snapshot = self._snapshot_quads()
            previous_version = self.version
            previous_descriptor = self._descriptor_digest
            try:
                transaction_predicate = URIRef(f"{PLN_NS}transactionFingerprint")
                self.assertion_graph.add((marker, RDF.type, PLN.AssertionCommitRequest))
                self.assertion_graph.add((marker, PLN.inWorldModelSession, self.session_node))
                self.assertion_graph.set((marker, transaction_predicate, Literal(transaction_fingerprint)))
                self.assertion_graph.set((marker, PLN.parentWorldModelSnapshotRef, Literal(parent_ref)))
                self.assertion_graph.set((marker, PLN.currentWorldDigest, Literal(parent_digest)))
                for artifact_ref in typed_request.evidence_artifact_refs:
                    self.assertion_graph.add((marker, PLN.evidenceRef, Literal(artifact_ref)))

                accepted: list[str] = []
                ambiguous: list[str] = []
                rejected: list[str] = []
                affected_entities = {proposal.subject_ref for proposal, *_ in prepared}
                affected_relations: set[str] = set()
                affected_representations: set[str] = set()
                for proposal, decision, assertion_node, predicate_node, object_node in prepared:
                    proposal_node = URIRef(f"{PLN_NS}proposal_{_digest(proposal.proposal_ref)[:24]}")
                    decision_node = URIRef(f"{PLN_NS}decision_{_digest(decision.decision_ref)[:24]}")
                    self.assertion_graph.add((proposal_node, RDF.type, PLN.AssertionProposal))
                    self.assertion_graph.set((proposal_node, PLN.proposalRef, Literal(proposal.proposal_ref)))
                    self.assertion_graph.set((proposal_node, PLN.proposalFingerprint, Literal(proposal.proposal_fingerprint)))
                    self.assertion_graph.set((proposal_node, PLN.proposalKind, Literal(proposal.proposal_kind)))
                    self.assertion_graph.set((proposal_node, PLN.subjectRef, Literal(proposal.subject_ref)))
                    self.assertion_graph.set((proposal_node, PLN.predicate, Literal(str(predicate_node))))
                    self.assertion_graph.set((proposal_node, PLN.validTime, Literal(proposal.valid_time)))
                    self.assertion_graph.set((proposal_node, PLN.parentWorldModelSnapshotRef, Literal(parent_ref)))
                    self.assertion_graph.set((proposal_node, PLN.parentWorldModelSnapshotDigest, Literal(parent_digest)))
                    if proposal.object_ref:
                        self.assertion_graph.set((proposal_node, PLN.objectRef, Literal(proposal.object_ref)))
                    elif proposal.value is not None:
                        self.assertion_graph.set((proposal_node, PLN.claimValue, Literal(str(proposal.value))))
                    for predicate, values in (
                        (PLN.sourceRef, proposal.source_refs),
                        (PLN.evidenceRef, proposal.evidence_refs),
                        (PLN.requirementRef, proposal.requirement_refs),
                        (PLN.supersedes, proposal.supersedes),
                    ):
                        for value in values:
                            self.assertion_graph.add((proposal_node, predicate, Literal(value)))
                    for key, value in proposal.authority.items():
                        self.assertion_graph.add((proposal_node, PLN.authority, Literal(f"{key}={value}")))
                    self.assertion_graph.add((decision_node, RDF.type, PLN.AssertionDecisionArtifact))
                    for predicate, value in (
                        (PLN.decisionRef, decision.decision_ref),
                        (PLN.proposalRef, decision.proposal_ref),
                        (PLN.decision, decision.decision),
                        (PLN.reasonCode, decision.reason_code),
                        (PLN.validatorRef, decision.validator_ref),
                        (PLN.policyRef, decision.policy_ref),
                        (PLN.policyVersion, decision.policy_version),
                        (PLN.createdAt, decision.created_at.isoformat()),
                        (PLN.parentWorldModelSnapshotDigest, parent_digest),
                    ):
                        self.assertion_graph.add((decision_node, predicate, Literal(str(value))))
                    assertion_status = {
                        "ACCEPT": "accepted",
                        "AMBIGUOUS": "ambiguous",
                        "REJECT": "rejected",
                    }[decision.decision]
                    self.assertion_graph.add((assertion_node, RDF.type, PLN.SemanticAssertion))
                    for predicate, value in (
                        (PLN.assertionRef, str(assertion_node)),
                        (PLN.proposalRef, proposal.proposal_ref),
                        (PLN.assertionKind, proposal.proposal_kind),
                        (PLN.subjectRef, proposal.subject_ref),
                        (PLN.predicate, str(predicate_node)),
                        (PLN.assertionStatus, assertion_status),
                        (PLN.decisionRef, decision.decision_ref),
                        (PLN.validTime, proposal.valid_time),
                        (PLN.parentWorldModelSnapshotRef, parent_ref),
                        (PLN.parentWorldModelSnapshotDigest, parent_digest),
                    ):
                        if value not in (None, ""):
                            self.assertion_graph.add((assertion_node, predicate, Literal(str(value))))
                    for predicate, values in (
                        (PLN.sourceRef, proposal.source_refs),
                        (PLN.evidenceRef, proposal.evidence_refs),
                        (PLN.requirementRef, proposal.requirement_refs),
                        (PLN.supersedes, proposal.supersedes),
                    ):
                        for value in values:
                            self.assertion_graph.add((assertion_node, predicate, Literal(value)))
                    if proposal.object_ref:
                        self.assertion_graph.add((assertion_node, PLN.objectRef, Literal(proposal.object_ref)))
                    elif proposal.value is not None:
                        self.assertion_graph.add((assertion_node, PLN.claimValue, Literal(str(proposal.value))))

                    if decision.decision == "ACCEPT":
                        accepted.append(str(assertion_node))
                        if proposal.object_ref:
                            affected_relations.add(str(assertion_node))
                        if proposal.proposal_kind == "representation_support":
                            affected_representations.add(proposal.subject_ref)
                        for superseded_ref in proposal.supersedes:
                            for old_node in self.assertion_graph.subjects(
                                PLN.assertionRef,
                                Literal(superseded_ref),
                            ):
                                self._remove_assertion_projection(old_node)
                                self.assertion_graph.set(
                                    (old_node, PLN.assertionStatus, Literal("superseded"))
                                )
                        self.world_graph.add((
                            URIRef(proposal.subject_ref),
                            predicate_node,
                            object_node,
                        ))
                    elif decision.decision == "AMBIGUOUS":
                        ambiguous.append(str(assertion_node))
                    else:
                        rejected.append(str(assertion_node))

                for proposal, decision, _assertion_node, predicate_node, object_node in prepared:
                    if decision.decision != "ACCEPT":
                        continue
                    triple = (URIRef(proposal.subject_ref), predicate_node, object_node)
                    if triple not in self.world_graph:
                        raise ValueError("accepted assertion projection missing")
                    for superseded_ref in proposal.supersedes:
                        for old_node in self.assertion_graph.subjects(
                            PLN.assertionRef,
                            Literal(superseded_ref),
                        ):
                            old_subject = _text(self.assertion_graph.value(old_node, PLN.subjectRef))
                            old_predicate = _text(self.assertion_graph.value(old_node, PLN.predicate))
                            old_object = _text(
                                self.assertion_graph.value(old_node, PLN.objectRef)
                                or self.assertion_graph.value(old_node, PLN.claimValue)
                            )
                            if old_subject and old_predicate and old_object:
                                old_predicate_node = URIRef(old_predicate)
                                old_object_node = URIRef(old_object) if old_object.startswith(("http://", "https://", "urn:")) else Literal(old_object)
                                if (URIRef(old_subject), old_predicate_node, old_object_node) in self.world_graph and (old_predicate_node, old_object_node) != (predicate_node, object_node):
                                    raise ValueError("superseded assertion projection remains")

                self.version += 1
                self._write_version_marker()
                self.snapshot_digest = self._graph_digest()
                self._persist_snapshot(
                    parent_descriptor=previous_descriptor,
                    commit_parents={"cognition_transaction": transaction_fingerprint},
                    commit_provenance={
                        "transaction_fingerprint": transaction_fingerprint,
                        "proposal_count": len(prepared),
                        "accepted_count": len(accepted),
                    },
                )
            except Exception as exc:
                self._recover_after_commit_failure(
                    graph_snapshot,
                    version=previous_version,
                    snapshot_digest=old_snapshot_digest,
                    descriptor_digest=previous_descriptor,
                )
                return receipt("aborted", error_type=f"assertion_commit_failed:{type(exc).__name__}")

            snapshot = self.snapshot_contract().model_copy(update={
                "parent_snapshot_ref": parent_ref,
                "parent_snapshot_digest": parent_digest,
            })
            return receipt(
                "committed",
                committed=True,
                snapshot=snapshot,
                accepted=tuple(accepted),
                ambiguous=tuple(ambiguous),
                rejected=tuple(rejected),
                affected_entities=tuple(sorted(affected_entities)),
                affected_relations=tuple(sorted(affected_relations)),
                affected_representations=tuple(sorted(affected_representations)),
            )

    def _remove_assertion_projection(self, assertion_node: Any) -> None:
        """Remove the current-world triple described by an assertion node."""

        subject_ref = _text(self.assertion_graph.value(assertion_node, PLN.subjectRef))
        predicate_ref = _text(self.assertion_graph.value(assertion_node, PLN.predicate))
        object_ref = _text(
            self.assertion_graph.value(assertion_node, PLN.objectRef)
            or self.assertion_graph.value(assertion_node, PLN.claimValue)
        )
        if not subject_ref or not predicate_ref or not object_ref:
            return
        predicate = URIRef(predicate_ref)
        object_node = (
            URIRef(object_ref)
            if object_ref.startswith(("http://", "https://", "urn:"))
            else Literal(object_ref)
        )
        self.world_graph.remove((URIRef(subject_ref), predicate, object_node))

    def _validate_planned_lineage(self, payload: dict[str, Any]) -> None:
        """Reject foreign DATA/KG references before writing planned graph."""

        snapshot = getattr(self.catalog, "snapshot", self.catalog)
        source_ids = {
            _text(getattr(item, "source_feature_ref", ""))
            for item in (getattr(snapshot, "features", ()) or ())
        }
        representations = {
            _text(getattr(item, "representation_ref", ""))
            for item in (getattr(snapshot, "representations", ()) or ())
        }
        # Derived representations (for example a road centerline assembled
        # from connected source segments) are owned by the World Model graph,
        # while their component geometry/resources remain DATA-owned.
        representations.update(
            _text(self.world_graph.value(item, PLN.representationRef) or "")
            for item in self.world_graph.subjects(RDF.type, PLN.SpatialRepresentation)
        )
        resources = {
            _text(getattr(item, "resource_ref", ""))
            for item in (getattr(snapshot, "representations", ()) or ())
        }
        for key, known in (
            ("representation_refs", representations),
            ("resource_refs", resources),
            ("source_feature_ids", source_ids),
        ):
            foreign = {
                _text(value) for value in (payload.get(key) or []) if _text(value)
            } - known
            if foreign:
                raise ValueError(f"planned feature has foreign {key}: {sorted(foreign)[:3]}")
        entity_refs = {
            _text(value) for value in (payload.get("entity_refs") or []) if _text(value)
        }
        for entity_ref in entity_refs:
            if not self.find_entities(entity_ref=entity_ref, limit=1):
                raise ValueError(f"planned feature has foreign entity_ref: {entity_ref}")

    def _write_planned_feature(self, node: URIRef, payload: dict[str, Any], *, version: int) -> None:
        self.planned_graph.add((node, RDF.type, PLN.PlannedFeature))
        self.planned_graph.add((node, PLN.inWorldModelSession, self.session_node))
        self.planned_graph.add((node, PLN.worldModelVersion, Literal(version)))
        for key in ("feature_id", "target_id", "candidate_id", "geometry_kind", "crs", "generation_operation", "scenario_id", "lineage_id"):
            value = _text(payload.get(key))
            if value:
                self.planned_graph.add((node, URIRef(f"{PLN_NS}{key}"), Literal(value)))
        geometry_wkt = _text(payload.get("geometry_wkt") or payload.get("geometry"))
        if geometry_wkt:
            geometry = URIRef(f"{PLN_NS}planned_geometry_{_digest(str(node))[:24]}")
            self.planned_graph.add((node, GEO.hasGeometry, geometry))
            self.planned_graph.add((geometry, RDF.type, GEO.Geometry))
            self.planned_graph.add((geometry, GEO.asWKT, Literal(geometry_wkt, datatype=GEO.wktLiteral)))
        refs = []
        for key in ("source_refs", "resource_refs", "representation_refs", "entity_refs", "evidence_refs"):
            refs.extend(str(ref) for ref in (payload.get(key) or []) if _text(ref))
        for ref in refs:
            self.planned_graph.add((node, PLN.provenanceRef, Literal(ref)))

    def _write_planned_record(self, node: URIRef, field: str, identity: str, payload: dict[str, Any], *, version: int) -> None:
        self.planned_graph.add((node, RDF.type, PLN.PlannedFeature))
        self.planned_graph.add((node, PLN.inWorldModelSession, self.session_node))
        self.planned_graph.add((node, PLN.worldModelVersion, Literal(version)))
        self.planned_graph.add((node, PLN.planningCollection, Literal(field)))
        self.planned_graph.add((node, PLN.featureId, Literal(identity)))
        geometry_wkt = _text(payload.get("geometry"))
        if geometry_wkt:
            geometry = URIRef(f"{PLN_NS}planned_geometry_{_digest(str(node))[:24]}")
            self.planned_graph.add((node, GEO.hasGeometry, geometry))
            self.planned_graph.add((geometry, RDF.type, GEO.Geometry))
            self.planned_graph.add((geometry, GEO.asWKT, Literal(geometry_wkt, datatype=GEO.wktLiteral)))
        for key, value in sorted(payload.items(), key=lambda item: str(item[0])):
            if key in {"geometry", "feature_id"} or value in (None, "", [], {}, ()):
                continue
            self.planned_graph.add((node, URIRef(f"{PLN_NS}planned_{_text(key)}"), Literal(json.dumps(value, ensure_ascii=False, default=str, sort_keys=True))))


def get_world_model_store(
    session_id: str,
    village_name: str,
    catalog: Any,
    *,
    schema_mapping_snapshot: Any = None,
    schema_mapping_artifact_ref: str = "",
    artifact_root: str = "",
    expected_snapshot_digest: str = "",
) -> WorldModelKGStore:
    """Return the session/snapshot-scoped DATA→KG World Model store."""

    snapshot = getattr(catalog, "snapshot", catalog)
    digest = _text(getattr(snapshot, "digest", "")) or _digest(snapshot)
    mapping_digest = _text(
        getattr(schema_mapping_snapshot, "mapping_fingerprint", "")
        or getattr(schema_mapping_snapshot, "decision_fingerprint", "")
        or getattr(schema_mapping_snapshot, "candidate_digest", "")
    )
    mapping_artifact_ref = _text(schema_mapping_artifact_ref)
    resolved_artifact_root = str(
        Path(str(artifact_root)).resolve()
        if artifact_root
        else ""
    )
    key = (
        _text(session_id),
        digest,
        mapping_digest,
        mapping_artifact_ref,
        resolved_artifact_root,
    )
    with _STORE_LOCK:
        current = _STORES.get(key)
        if current is None or (
            expected_snapshot_digest
            and _text(getattr(current, "snapshot_digest", ""))
            != _text(expected_snapshot_digest)
        ):
            current = WorldModelKGStore(
                session_id,
                village_name,
                catalog,
                schema_mapping_snapshot=schema_mapping_snapshot,
                schema_mapping_artifact_ref=mapping_artifact_ref,
                artifact_root=resolved_artifact_root,
            )
            _STORES[key] = current
        return current


def clear_world_model_stores() -> None:
    with _STORE_LOCK:
        _STORES.clear()


__all__ = [
    "WORLD_MODEL_CODE_VERSION",
    "WORLD_MODEL_DIGEST_ALGORITHM",
    "WORLD_MODEL_PROJECTION_VERSION",
    "WORLD_MODEL_SCHEMA_VERSION",
    "WorldModelKGStore",
    "get_world_model_store",
    "clear_world_model_stores",
]
