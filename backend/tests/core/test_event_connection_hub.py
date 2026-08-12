from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

import app.infrastructure.events.repository as repository_module
from app.api.v1.routes import stream_events
from app.application.projections.events import public_event
from app.application.queries.run_events import EventStream, RunEventQueryService
from app.infrastructure.events import EventConnectionHub, EventRepository


@pytest.fixture(autouse=True)
def reset_event_connection_hub() -> None:
    EventConnectionHub._subscribers.clear()
    EventConnectionHub._desynced.clear()
    yield
    EventConnectionHub._subscribers.clear()
    EventConnectionHub._desynced.clear()


class _FakeRow:
    def __init__(self, *, payload: dict[str, Any], seq: int, session_id: str) -> None:
        self.payload = payload
        self.seq = seq
        self.session_id = session_id


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value


class _FakeTransaction:
    def __init__(self, session: "_FakeSession") -> None:
        self._session = session

    async def __aenter__(self) -> None:
        self._session.in_transaction = True

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._session.in_transaction = False


class _FakeSession:
    def __init__(self) -> None:
        self.in_transaction = False
        self.execute_count = 0

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    async def execute(self, _statement: Any) -> _FakeResult:
        assert self.in_transaction
        self.execute_count += 1
        if self.execute_count == 1:
            return _FakeResult([
                _FakeRow(
                    payload={'type': 'progress', 'step': 'replay'},
                    seq=2,
                    session_id='session-1',
                )
            ])
        return _FakeResult(3)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


async def _collect_events(source: Any) -> list[Any]:
    events = []
    async for item in source:
        events.append(item)
    return events


@pytest.mark.asyncio
async def test_event_repository_sync_window_reads_one_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    monkeypatch.setattr(
        repository_module,
        'get_async_session',
        lambda: _FakeSessionContext(session),
    )

    events, last_seq = await EventRepository.sync_window('session-1', after=1)

    assert session.execute_count == 2
    assert session.in_transaction is False
    assert events == [{
        'type': 'progress',
        'step': 'replay',
        'seq': 2,
        'session_id': 'session-1',
    }]
    assert last_seq == 3


@pytest.mark.asyncio
async def test_run_event_query_service_uses_sync_window(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unexpected(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError('legacy split reads should not be used')

    async def _fake_sync_window(session_id: str, after: int = 0) -> tuple[list[dict[str, Any]], int]:
        assert session_id == 'session-1'
        assert after == 1
        return ([{'type': 'progress', 'seq': 2, 'session_id': session_id}], 2)

    monkeypatch.setattr(EventRepository, 'sync_window', staticmethod(_fake_sync_window))
    monkeypatch.setattr(EventRepository, 'list_after', staticmethod(_unexpected))
    monkeypatch.setattr(EventRepository, 'last_seq', staticmethod(_unexpected))

    sync = await RunEventQueryService().sync('session-1', after=1)

    assert sync.events == [{'type': 'progress', 'seq': 2, 'session_id': 'session-1'}]
    assert sync.last_seq == 2
    assert sync.resync_required is False


@pytest.mark.asyncio
async def test_stream_events_dedupes_replay_and_live(monkeypatch: pytest.MonkeyPatch) -> None:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for event in (
        {'type': 'progress', 'seq': 3, 'session_id': 'session-1', 'delta': 'duplicate'},
        {'type': 'progress', 'seq': 4, 'session_id': 'session-1', 'delta': 'live'},
        {'type': 'completed', 'seq': 5, 'session_id': 'session-1', 'delivery_status': 'partial'},
    ):
        queue.put_nowait(event)

    closed: list[tuple[str, asyncio.Queue[dict[str, Any]]]] = []

    async def _fake_open_stream(session_id: str, after: int = 0) -> EventStream:
        assert session_id == 'session-1'
        assert after == 1
        return EventStream(
            queue=queue,
            replay=[
                {'type': 'progress', 'seq': 2, 'session_id': session_id, 'delta': 'replay-2'},
                {'type': 'progress', 'seq': 3, 'session_id': session_id, 'delta': 'replay-3'},
            ],
            last_seq=5,
            resync_required=False,
            needs_resync=lambda: False,
        )

    async def _fake_close_stream(session_id: str, target_queue: asyncio.Queue[dict[str, Any]]) -> None:
        closed.append((session_id, target_queue))

    import app.api.v1.routes as routes_module

    monkeypatch.setattr(routes_module.run_event_queries, 'open_stream', _fake_open_stream)
    monkeypatch.setattr(routes_module.run_event_queries, 'close_stream', _fake_close_stream)

    events = await _collect_events(stream_events('session-1', last_event_id=1))

    assert [event.comment for event in events] == ['connected', None, None, None, None]
    assert [event.id for event in events if event.event] == ['2', '3', '4', '5']
    assert [event.data['seq'] for event in events if isinstance(event.data, dict)] == [2, 3, 4, 5]
    assert events[-1].event == 'completed'
    assert closed == [('session-1', queue)]


@pytest.mark.asyncio
async def test_stream_events_emits_resync_from_confirmed_cursor_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    closed: list[tuple[str, asyncio.Queue[dict[str, Any]]]] = []

    async def _fake_open_stream(session_id: str, after: int = 0) -> EventStream:
        return EventStream(
            queue=queue,
            replay=[
                {'type': 'progress', 'seq': 2, 'session_id': session_id, 'delta': 'replay-2'},
            ],
            last_seq=4,
            resync_required=False,
            needs_resync=lambda: True,
        )

    async def _fake_close_stream(session_id: str, target_queue: asyncio.Queue[dict[str, Any]]) -> None:
        closed.append((session_id, target_queue))

    import app.api.v1.routes as routes_module

    monkeypatch.setattr(routes_module.run_event_queries, 'open_stream', _fake_open_stream)
    monkeypatch.setattr(routes_module.run_event_queries, 'close_stream', _fake_close_stream)

    events = await _collect_events(stream_events('session-1', last_event_id=1))

    assert [event.event for event in events] == [None, 'progress', 'resync_required']
    assert events[-1].id == '2'
    assert events[-1].data == {'schema_version': '1.0', 'after': 2}
    assert closed == [('session-1', queue)]


@pytest.mark.asyncio
async def test_publish_marks_only_overflowed_subscriber_desynced(monkeypatch: pytest.MonkeyPatch) -> None:
    overflow_queue = await EventConnectionHub.subscribe('session-1')
    healthy_queue = await EventConnectionHub.subscribe('session-1')

    while True:
        try:
            overflow_queue.put_nowait({'type': 'buffered', 'seq': 0})
        except asyncio.QueueFull:
            break

    async def _fake_append(session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return {**event, 'session_id': session_id, 'seq': 7}

    monkeypatch.setattr(EventRepository, 'append', staticmethod(_fake_append))

    persisted = await EventConnectionHub.publish('session-1', {'type': 'progress', 'delta': 'live'})

    overflow_contents: list[dict[str, Any]] = []
    while not overflow_queue.empty():
        overflow_contents.append(overflow_queue.get_nowait())

    assert persisted['seq'] == 7
    assert EventConnectionHub.is_desynced('session-1', overflow_queue) is True
    assert EventConnectionHub.is_desynced('session-1', healthy_queue) is False
    assert healthy_queue.get_nowait()['seq'] == 7
    assert all(item.get('seq') != 7 for item in overflow_contents)


def test_public_event_projects_human_review_pause() -> None:
    event = public_event('session-1', {
        'type': 'human_review_paused',
        'seq': 6,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'event_id': 'hr-6',
        'paused_stage': 'validate',
        'items': [{'request_id': 'r1', 'stage': 'validate', 'request_type': 'approve'}],
        'channel': 'post_l3_review',
        'reason': 'human_review_required',
    })

    assert event['type'] == 'human_review'
    assert event['data'] == {
        'schema_version': '1.0',
        'session_id': 'session-1',
        'pending': True,
        'event_id': 'hr-6',
        'paused_stage': 'validate',
        'items': [{'request_id': 'r1', 'stage': 'validate', 'request_type': 'approve'}],
    }
