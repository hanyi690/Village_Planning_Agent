/**
 * Shared historical / URL session hydration.
 *
 * v1 alignment: restores state ONLY from the real backend full-process outputs:
 *   - /state (SessionProjection) for status / delivery / review flags;
 *   - durable SSE events via /events/sync replay (dimension/layer reports and
 *     progress are rebuilt from the workflow's own event stream);
 *   - /delivery + /map-layers fetched by useDeliverySync once delivery_status
 *     is exposed (authoritative spatial snapshot).
 * The legacy /layer/reports, /checkpoints and chat_history endpoints were
 * removed from the backend and are no longer consulted.
 */

import { planningApi } from '../api';
import { usePlanningStore } from '../store/planningStore';
import type { SessionStatusResponse } from '../api/types';
import { normalizePlanningStatus } from '../constants';

function resolveUiStatus(backendStatus: string | undefined): void {
  const store = usePlanningStore.getState();
  const normalized = normalizePlanningStatus(backendStatus);
  if (
    normalized === 'completed' ||
    normalized === 'paused' ||
    normalized === 'failed' ||
    normalized === 'planning' ||
    normalized === 'revising' ||
    normalized === 'collecting' ||
    normalized === 'reviewing'
  ) {
    store.setStatus(normalized);
  } else if (backendStatus === 'running' || backendStatus === 'pending') {
    store.setStatus('planning');
  } else {
    store.setStatus('idle');
  }
}

export interface HydrateSessionOptions {
  /** Kept for API compatibility; checkpoints are no longer fetched from the backend. */
  loadCheckpoints?: boolean;
}

export interface HydrateSessionResult {
  statusData: SessionStatusResponse;
  lastSeq: number;
}

/**
 * Fully hydrate store from a backend session WITHOUT setting sessionId.
 * Caller should set sessionId after this returns so SSE connects with
 * lastProcessedSeq already advanced past historical events.
 */
export async function hydrateSessionSnapshot(
  sessionId: string,
  _options: HydrateSessionOptions = {},
): Promise<HydrateSessionResult> {
  const store = usePlanningStore.getState();

  const [statusData, syncResult] = await Promise.all([
    planningApi.getStatus(sessionId),
    planningApi.syncEvents(sessionId, 0),
  ]);

  // Advance seq before any SSE connection so bootstrap/reconnect skip replay.
  const lastSeq = typeof syncResult.last_seq === 'number' ? syncResult.last_seq : 0;
  store.setLastProcessedSeq(lastSeq);

  store.syncBackendState(statusData);
  if (statusData.step_mode !== undefined) {
    store.setStepMode(statusData.step_mode);
  }
  resolveUiStatus(statusData.status);

  // v1: rebuild dimension/layer reports and progress by replaying the durable
  // SSE event stream (the real workflow outputs). No legacy report endpoints.
  if (Array.isArray(syncResult.events) && syncResult.events.length > 0) {
    for (const event of syncResult.events) {
      store.handleSSEEvent({ type: event.type, data: event.data });
    }
  }

  // Authoritative delivery + map-layers are fetched by useDeliverySync as soon
  // as /state exposes delivery_status (terminal or delivery_ready).

  store.scanOfflineReports();

  return { statusData, lastSeq };
}
