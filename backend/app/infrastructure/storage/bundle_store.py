"""
Bundle Store - versioned persistence for session-level VillageBundle snapshots.

Stores full JSON snapshots (original input documents + spatial features +
embedded L1/L2/L3 reports) in the ``planning_bundles`` table. Versioned per
layer completion / manual trigger.

This is the future unified data source: ``get_layer_reports_from_bundle``
provides the read path that will eventually replace ``dimension_reports``.
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
        """Serialize a VillageBundle to a JSON string."""
        return json.dumps(to_bundle_dict(bundle), ensure_ascii=False)

    @staticmethod
    def deserialize(bundle_json: str) -> VillageBundle:
        """Rebuild a VillageBundle from a JSON string."""
        return from_bundle_dict(json.loads(bundle_json))

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

    async def get_layer_reports_from_bundle(
        self,
        session_id: str,
        layer: Optional[int] = None,
        version: Optional[int] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """Read layer reports from the latest (or given) snapshot.

        Future replacement for ``dimension_reports`` reads: layer -> dim_key ->
        {report_id, content, summary, version, generated_at}.

        Args:
            session_id: Session identifier.
            layer: If set, return only this layer's reports.
            version: Snapshot version; defaults to latest.

        Returns:
            {layer: {dim_key: report_record}} (filtered to ``layer`` if given).
        """
        bundle = await self.load_bundle(session_id, version=version)
        if bundle is None:
            return {}
        layer_reports = bundle.layer_reports or {}
        if layer is not None:
            return {layer: layer_reports.get(layer, {})}
        return layer_reports


__all__ = ["BundleStore"]
