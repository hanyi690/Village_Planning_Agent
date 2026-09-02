"""Explicit Evidence-to-Cognition round identity contract."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.base import StrictContractModel


CognitionRoundStatus = Literal["open", "frozen", "committed", "stopped"]
_PROPOSAL_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")


def requirement_set_digest(requirements: Iterable[object]) -> str:
    """Return the stable business digest for one ordered requirement set."""

    payload = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in requirements
    ]
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CognitionRound(StrictContractModel):
    """Immutable parent pin for one Evidence/Cognition evaluation round."""

    round_id: str = Field(min_length=1)
    round_number: int = Field(ge=0)
    wm_epoch: str = Field(min_length=1)
    parent_world_model_snapshot_ref: str = Field(min_length=1)
    parent_world_model_snapshot_digest: str = Field(min_length=1)
    requirement_set_digest: str = Field(min_length=1)
    max_rounds: int = Field(default=8, ge=1)
    previous_proposal_fingerprint: str = ""
    proposal_fingerprint: str = ""
    status: CognitionRoundStatus = "open"

    @model_validator(mode="after")
    def _validate_round_state(self) -> "CognitionRound":
        if self.round_number >= self.max_rounds:
            raise ValueError("round_number must be below max_rounds")
        if self.status != "open" and not self.proposal_fingerprint:
            raise ValueError("closed cognition round requires proposal_fingerprint")
        if self.proposal_fingerprint and not _PROPOSAL_FINGERPRINT.fullmatch(
            self.proposal_fingerprint
        ):
            raise ValueError("proposal_fingerprint must use sha256 prefix")
        if (
            self.previous_proposal_fingerprint
            and not _PROPOSAL_FINGERPRINT.fullmatch(self.previous_proposal_fingerprint)
        ):
            raise ValueError("previous_proposal_fingerprint must use sha256 prefix")
        return self

    def freeze(self, proposal_fingerprint: str) -> "CognitionRound":
        """Return the same round with its immutable proposal output bound."""

        if not _PROPOSAL_FINGERPRINT.fullmatch(proposal_fingerprint):
            raise ValueError("proposal_fingerprint must use sha256 prefix")
        if self.status != "open":
            if self.proposal_fingerprint == proposal_fingerprint:
                return self
            raise ValueError("CognitionRound is already frozen")
        return self.model_copy(update={
            "proposal_fingerprint": proposal_fingerprint,
            "status": "frozen",
        })


__all__ = ["CognitionRound", "CognitionRoundStatus", "requirement_set_digest"]
