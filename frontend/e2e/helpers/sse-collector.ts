/**
 * SSE event collector for E2E tests.
 * Connects to the backend SSE stream and collects all events for verification.
 */

import { BACKEND_URL } from '../fixtures/village-data';

export interface SSEDimensionEvent {
  type: string;
  layer: number;
  dimension_key: string;
  delta?: string;
  timestamp?: string;
}

export interface SSEEvent {
  type: string;
  data: unknown;
  timestamp: number;
}

export class SSECollector {
  private events: SSEEvent[] = [];
  private eventSource: EventSource | null = null;
  private baseUrl: string;
  private abortController: AbortController | null = null;

  constructor(baseUrl: string = BACKEND_URL) {
    this.baseUrl = baseUrl;
  }

  /** Connect to SSE stream for a session. */
  connect(sessionId: string): void {
    const url = `${this.baseUrl}/api/sessions/${sessionId}/stream`;

    // Use fetch with streaming for Node.js compatibility (EventSource not in Node)
    this.abortController = new AbortController();

    fetch(url, { signal: this.abortController.signal })
      .then(async (response) => {
        if (!response.ok || !response.body) {
          throw new Error(`SSE connection failed: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const parsed = JSON.parse(line.slice(6));
                this.events.push({
                  type: parsed.type || 'unknown',
                  data: parsed,
                  timestamp: Date.now(),
                });
              } catch {
                // Non-JSON SSE data, skip
              }
            }
          }
        }
      })
      .catch((err) => {
        // Expected when aborted
        if ((err as Error).name !== 'AbortError') {
          console.warn(`[SSECollector] Connection error: ${(err as Error).message}`);
        }
      });
  }

  /** Disconnect from SSE stream. */
  disconnect(): void {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
  }

  /** Get all collected events. */
  getEvents(): SSEEvent[] {
    return [...this.events];
  }

  /** Get events of a specific type. */
  getEventsByType(type: string): SSEEvent[] {
    return this.events.filter((e) => e.type === type);
  }

  /** Wait for an event matching predicate. */
  async waitForEvent(
    predicate: (event: SSEEvent) => boolean,
    timeoutMs: number = 30000,
  ): Promise<SSEEvent> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const match = this.events.find(predicate);
      if (match) return match;
      await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error(`Timeout waiting for SSE event after ${timeoutMs}ms`);
  }

  /** Wait for a specific event type to appear. */
  async waitForEventType(type: string, timeoutMs: number = 30000): Promise<SSEEvent> {
    return this.waitForEvent((e) => e.type === type, timeoutMs);
  }

  /** Check that event sequence contains expected types in order. */
  hasEventSequence(expectedTypes: string[]): boolean {
    let eventIdx = 0;
    for (const event of this.events) {
      if (event.type === expectedTypes[eventIdx]) {
        eventIdx++;
        if (eventIdx >= expectedTypes.length) return true;
      }
    }
    return false;
  }

  /** Clear collected events. */
  clear(): void {
    this.events = [];
  }

  /** Wait for a GIS-related event (gis_result or gis_layer_update). */
  async waitForGisEvent(timeoutMs: number = 60000): Promise<SSEEvent> {
    return this.waitForEvent(
      (e) => e.type === 'gis_result' || e.type === 'gis_layer_update',
      timeoutMs,
    );
  }

  /** Get all GIS events (gis_result + gis_layer_update). */
  getGisEvents(): SSEEvent[] {
    return this.events.filter((e) => e.type === 'gis_result' || e.type === 'gis_layer_update');
  }

  /** Get pipeline trace from tool_started events. */
  getPipelineTrace(): { tool: string; timestamp: number }[] {
    return this.events
      .filter((e) => e.type === 'tool_started' && (e.data as any)?.tool_name)
      .map((e) => ({ tool: (e.data as any).tool_name, timestamp: e.timestamp }));
  }
}
