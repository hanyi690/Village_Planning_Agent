"""Append-only event repository for replayable public run events."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError

from app.database.engine import get_async_session
from app.database.models import RunEvent


class EventRepository:
    """Own durable `(session_id, seq)` event identity.

    The online connection hub may keep queues in memory, but it must not own
    event history or sequence numbers.  A short SQLite write transaction
    reserves the next sequence so a process restart cannot reset the cursor.
    """

    @staticmethod
    async def append(session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        session_key = str(session_id or "").strip()
        if not session_key:
            raise ValueError("session_id is required")
        payload = dict(event)
        payload.pop("seq", None)
        payload["session_id"] = session_key
        event_type = str(payload.get("type") or "unknown")

        for attempt in range(4):
            try:
                async with get_async_session() as session:
                    await session.execute(text("BEGIN IMMEDIATE"))
                    result = await session.execute(
                        select(func.coalesce(func.max(RunEvent.seq), 0)).where(
                            RunEvent.session_id == session_key
                        )
                    )
                    seq = int(result.scalar_one() or 0) + 1
                    row = RunEvent(
                        session_id=session_key,
                        seq=seq,
                        event_type=event_type,
                        payload=payload,
                    )
                    session.add(row)
                    await session.commit()
                break
            except OperationalError:
                if attempt == 3:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))

        return {**payload, "seq": seq}

    @staticmethod
    async def list_after(session_id: str, after: int = 0) -> list[dict[str, Any]]:
        async with get_async_session() as session:
            result = await session.execute(
                select(RunEvent)
                .where(
                    RunEvent.session_id == str(session_id),
                    RunEvent.seq > int(after),
                )
                .order_by(RunEvent.seq)
            )
            rows = result.scalars().all()
        return EventRepository._serialize_rows(rows)

    @staticmethod
    async def sync_window(session_id: str, after: int = 0) -> tuple[list[dict[str, Any]], int]:
        session_key = str(session_id)
        after_seq = int(after)
        async with get_async_session() as session:
            async with session.begin():
                result = await session.execute(
                    select(RunEvent)
                    .where(
                        RunEvent.session_id == session_key,
                        RunEvent.seq > after_seq,
                    )
                    .order_by(RunEvent.seq)
                )
                rows = result.scalars().all()
                last_seq_result = await session.execute(
                    select(func.coalesce(func.max(RunEvent.seq), 0)).where(
                        RunEvent.session_id == session_key
                    )
                )
                last_seq = int(last_seq_result.scalar_one() or 0)
        return EventRepository._serialize_rows(rows), last_seq

    @staticmethod
    async def last_seq(session_id: str) -> int:
        async with get_async_session() as session:
            result = await session.execute(
                select(func.coalesce(func.max(RunEvent.seq), 0)).where(
                    RunEvent.session_id == str(session_id)
                )
            )
            return int(result.scalar_one() or 0)

    @staticmethod
    async def latest(session_id: str) -> dict[str, Any] | None:
        """Return only the newest durable event for a public status projection."""
        async with get_async_session() as session:
            result = await session.execute(
                select(RunEvent)
                .where(RunEvent.session_id == str(session_id))
                .order_by(RunEvent.seq.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
        if row is None:
            return None
        return {**dict(row.payload or {}), "seq": row.seq, "session_id": row.session_id}

    @staticmethod
    async def recent(session_id: str, limit: int = 512) -> list[dict[str, Any]]:
        """Return a bounded ordered tail for race-safe stage projection."""

        bounded_limit = max(1, min(int(limit), 2048))
        async with get_async_session() as session:
            result = await session.execute(
                select(RunEvent)
                .where(RunEvent.session_id == str(session_id))
                .order_by(RunEvent.seq.desc())
                .limit(bounded_limit)
            )
            rows = list(result.scalars().all())
        rows.reverse()
        return EventRepository._serialize_rows(rows)

    @staticmethod
    async def clear(session_id: str) -> None:
        async with get_async_session() as session:
            await session.execute(delete(RunEvent).where(RunEvent.session_id == str(session_id)))
            await session.commit()

    @staticmethod
    def _serialize_rows(rows: list[RunEvent]) -> list[dict[str, Any]]:
        return [
            {**dict(row.payload or {}), "seq": row.seq, "session_id": row.session_id}
            for row in rows
        ]


__all__ = ["EventRepository"]
