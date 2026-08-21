import { planningApi } from '../api/planning-api';
import { usePlanningStore } from '../store/planningStore';
import type { PlanningSSEEvent } from '../api/types';

export interface EventSyncResult {
  applied: number;
  last_seq: number;
  resync_required: boolean;
}

/**
 * Replay durable SSE events after `fromSeq` and merge into the planning store.
 * Dedup is handled by seq tracking inside handleSSEEvent.
 */
export function applySyncedEvents(events: PlanningSSEEvent[]): number {
  const store = usePlanningStore.getState();
  let applied = 0;
  for (const event of events) {
    const before = store.lastProcessedSeq;
    store.handleSSEEvent({ type: event.type, data: event.data });
    const after = usePlanningStore.getState().lastProcessedSeq;
    if (after > before) {
      applied += 1;
    }
  }
  return applied;
}

/**
 * Catch up missed workflow events from /events/sync.
 * Safe to call periodically while a session is running.
 */
export async function syncMissedPlanningEvents(
  sessionId: string,
): Promise<EventSyncResult> {
  const store = usePlanningStore.getState();
  const fromSeq = store.lastProcessedSeq;
  const syncResult = await planningApi.syncEvents(sessionId, fromSeq);

  if (syncResult.resync_required) {
    store.setResyncRequired(true);
    return {
      applied: 0,
      last_seq: syncResult.last_seq,
      resync_required: true,
    };
  }

  const applied = applySyncedEvents(syncResult.events);

  if (
    typeof syncResult.last_seq === 'number' &&
    syncResult.last_seq > usePlanningStore.getState().lastProcessedSeq
  ) {
    usePlanningStore.getState().setLastProcessedSeq(syncResult.last_seq);
  }

  if (applied > 0) {
    console.log(
      `[event-sync] Applied ${applied} missed event(s) for ${sessionId} (from seq ${fromSeq})`,
    );
  }

  return {
    applied,
    last_seq: syncResult.last_seq,
    resync_required: false,
  };
}

/**
 * Compare server tip seq with client cursor; sync when the client is behind.
 */
export async function syncIfEventSeqBehind(
  sessionId: string,
  serverLastSeq?: number,
): Promise<EventSyncResult | null> {
  const serverSeq = serverLastSeq ?? 0;
  const clientSeq = usePlanningStore.getState().lastProcessedSeq;
  if (serverSeq <= clientSeq) {
    return null;
  }
  return syncMissedPlanningEvents(sessionId);
}
