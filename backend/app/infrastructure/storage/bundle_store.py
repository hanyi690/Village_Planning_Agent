"""
Bundle Store - versioned persistence for session-level VillageBundle snapshots.

Stores versioned retrieval projections (spatial features, input references and
evidence/report manifests) in ``planning_bundles``. Long report bodies are
owned by the report store and are never duplicated in a bundle snapshot.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from app.database.operations import (
    create_planning_bundle_async,
    get_planning_bundle_async,
    list_planning_bundle_versions_async,
)
from app.data.model.canonical import VillageBundle, from_bundle_dict, to_bundle_dict
from app.data.model.snapshot import SessionDataSnapshot
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


class BundleStore:
    """
    Versioned storage of session VillageBundle snapshots (database-backed).
    """

    _instance: Optional["BundleStore"] = None

    def __init__(self):
        logger.info("[BundleStore] Initialized with database backend")

    @classmethod
    def get_instance(cls) -> "BundleStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── helpers ───────────────────────────────────────────────

    @staticmethod
    def serialize(bundle: VillageBundle) -> str:
        """Serialize a VillageBundle and its source manifest to JSON.

        The bundle payload remains self-contained.  ``_source_snapshot`` is a
        compact manifest (IDs, source URIs and content/geometry digests), not
        a second copy of the feature payload.  Keeping it in the persisted
        blob makes a restored bundle auditable even when the process-local
        ``SessionDataSnapshot`` has been discarded.
        """
        payload = to_bundle_dict(bundle)
        session_id = str(getattr(getattr(bundle, "metadata", None), "session_id", "") or "")
        snapshot = SessionDataSnapshot.from_canonical_payload(
            payload,
            session_id=session_id,
            village_name=str(getattr(bundle, "village_name", "") or ""),
            source="data_catalog",
        )
        payload["_source_snapshot"] = snapshot.model_dump(mode="json")
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def deserialize(bundle_json: str) -> VillageBundle:
        """Rebuild a VillageBundle and restore its source manifest."""
        payload = json.loads(bundle_json)
        source_snapshot = payload.pop("_source_snapshot", None)
        bundle = from_bundle_dict(payload)
        if source_snapshot:
            restored_snapshot = SessionDataSnapshot.model_validate(source_snapshot)
            object.__setattr__(bundle, "source_snapshot", restored_snapshot)
        return bundle

    @staticmethod
    def _sha256(bundle_json: str) -> str:
        return hashlib.sha256(bundle_json.encode("utf-8")).hexdigest()

    # ── writes ────────────────────────────────────────────────

    async def save(
        self,
        session_id: str,
        bundle: VillageBundle,
        version: Optional[int] = None,
        trigger_reason: Optional[str] = None,
    ) -> int:
        """Persist a bundle snapshot, returning the stored version number.

        Args:
            session_id: Session identifier.
            bundle: Session-level VillageBundle to snapshot.
            version: Explicit version. If None, auto-increments from the
                latest stored version for the session.
            trigger_reason: Optional reason ("layer1" | "layer2" | "layer3" |
                "final" | "manual") recorded on the snapshot.
        """
        bundle_json = self.serialize(bundle)
        sha256 = self._sha256(bundle_json)

        bundle_ref = None
        try:
            from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository
            from app.infrastructure.paths import run_tmp_root
            descriptor = ContentAddressedArtifactRepository(run_tmp_root()).put_bytes(
                bundle_json.encode("utf-8"),
                schema_id="VillageBundle",
                schema_version="3",
                producer_stage="session_bundle",
                run_id=session_id,
                branch_id="main",
            )
            bundle_ref = json.dumps(descriptor.model_dump(mode="json"))
        except Exception as exc:
            logger.warning(
                "[BundleStore] CAS blob persist failed for %s; falling back to DB blob: %s",
                session_id, exc,
            )

        if version is None:
            latest = await get_planning_bundle_async(session_id)
            version = (latest.get("version", 0) if latest else 0) + 1

        await create_planning_bundle_async({
            "session_id": session_id,
            "version": version,
            "bundle_json": bundle_json,
            "sha256": sha256,
            "bundle_ref": bundle_ref,
            "trigger_reason": trigger_reason,
        })
        logger.info(
            "[BundleStore] Saved snapshot v%s for session %s (sha256=%s...)",
            version, session_id, sha256[:8],
        )
        return version

    # ── reads ─────────────────────────────────────────────────

    async def get_latest(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest snapshot record (with bundle_json)."""
        return await get_planning_bundle_async(session_id)

    async def get_version(self, session_id: str, version: int) -> Optional[Dict[str, Any]]:
        """Get a specific snapshot record (with bundle_json)."""
        return await get_planning_bundle_async(session_id, version=version)

    async def list_versions(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """List snapshot metadata (without bundle_json)."""
        return await list_planning_bundle_versions_async(session_id, limit=limit)

    async def load_bundle(
        self,
        session_id: str,
        version: Optional[int] = None,
    ) -> Optional[VillageBundle]:
        """Load and deserialize a snapshot into a VillageBundle.

        Args:
            session_id: Session identifier.
            version: Version number; defaults to the latest snapshot.

        Returns:
            Deserialized VillageBundle or None if no snapshot exists.
        """
        record = await get_planning_bundle_async(session_id, version=version) if version is not None \
            else await get_planning_bundle_async(session_id)
        if not record:
            return None

        bundle_ref = record.get("bundle_ref")
        if bundle_ref:
            from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
            from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository
            from app.infrastructure.paths import run_tmp_root
            descriptor = ArtifactDescriptor.model_validate(json.loads(bundle_ref))
            bundle_json = ContentAddressedArtifactRepository(run_tmp_root()).get_bytes(descriptor).decode("utf-8")
        else:
            bundle_json = record.get("bundle_json")

        if not bundle_json:
            return None
        if self._sha256(bundle_json) != record.get("sha256"):
            raise ValueError(
                f"[BundleStore] Bundle checksum mismatch for session {session_id} "
                f"version {record.get('version')}"
            )
        return self.deserialize(bundle_json)

__all__ = ["BundleStore"]
