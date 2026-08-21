import { planningApi } from '@/features/planning/api/planning-api';

type MockEventHandler = (event: MessageEvent) => void;

class MockEventSource {
  static readonly CLOSED = 2;

  readyState = 1;
  onerror: ((event: Event) => void) | null = null;
  onopen: (() => void) | null = null;
  private readonly listeners = new Map<string, MockEventHandler[]>();

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const handlers = this.listeners.get(type) || [];
    handlers.push(listener as MockEventHandler);
    this.listeners.set(type, handlers);
  }

  close(): void {
    this.readyState = MockEventSource.CLOSED;
  }

  dispatch(type: string, data: unknown): void {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    for (const listener of this.listeners.get(type) || []) {
      listener(event);
    }
  }
}

describe('planning text placeholder API', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    global.EventSource = MockEventSource as unknown as typeof EventSource;
  });

  it('returns an empty document projection without a network request', async () => {
    await expect(planningApi.getPlanningText('session-1')).resolves.toBeNull();

    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('returns an empty version list without a network request', async () => {
    await expect(planningApi.getPlanningTextVersions('session-1')).resolves.toEqual({
      session_id: 'session-1',
      versions: [],
      total: 0,
    });

    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('returns a successful empty generation response', async () => {
    await expect(
      planningApi.generatePlanningText('session-1', { trigger_reason: 'manual' }),
    ).resolves.toMatchObject({
      session_id: 'session-1',
      markdown_content: '',
      article_count: 0,
      status: 'empty',
      trigger_reason: 'manual',
    });

    expect(global.fetch).not.toHaveBeenCalled();
  });
});

describe('persisted planning history API', () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: '1.0',
        projects: [
          {
            name: '金田村规划',
            display_name: '金田村',
            session_count: 1,
            sessions: [
              {
                session_id: 'session-1',
                timestamp: '2026-08-19T12:00:00',
                checkpoint_count: 0,
                has_final_report: true,
              },
            ],
          },
        ],
      }),
    });
  });

  it('loads persisted projects from the stable v1 endpoint', async () => {
    await expect(planningApi.listProjects()).resolves.toEqual([
      expect.objectContaining({
        name: '金田村规划',
        sessions: [expect.objectContaining({ session_id: 'session-1' })],
      }),
    ]);

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/projects'),
      expect.objectContaining({ method: 'GET' }),
    );
  });
});

describe('local v1 SSE projection', () => {
  it('maps progress source events and preserves resync control payloads', () => {
    const events: Array<{ type: string; data: Record<string, unknown> }> = [];
    const stream = planningApi.createStream('session-1', (event) => {
      events.push({ type: event.type, data: event.data as Record<string, unknown> });
    });
    const mockStream = stream as unknown as MockEventSource;

    mockStream.dispatch('progress', {
      schema_version: '1.0',
      event_id: 'session-1:12',
      seq: 12,
      session_id: 'session-1',
      type: 'progress',
      data: {
        type: 'dimension_complete',
        layer: 1,
        dimension_key: 'population',
        full_content: '',
      },
    });
    mockStream.dispatch('resync_required', {
      schema_version: '1.0',
      after: 12,
    });

    expect(events[0]).toMatchObject({
      type: 'dimension_complete',
      data: {
        seq: 12,
        layer: 1,
        dimension_key: 'population',
        full_content: '',
      },
    });
    expect(events[1]).toEqual({
      type: 'resync_required',
      data: {
        schema_version: '1.0',
        after: 12,
      },
    });

    stream.close();
  });
});
