import { planningApi } from '../api/planning-api';
import { DIMENSIONS_BY_LAYER } from '../config/dimensions';
import { NAV_KEYS } from '../constants';
import { usePlanningStore } from '../store/planningStore';
import { normalizePlanningStatus } from '../constants';
import { applySyncedEvents } from './event-sync';

/**
 * Hydrate client state after a new session starts or SSE connects late.
 *
 * v1 alignment: restores from /state (SessionProjection) + durable SSE event
 * replay; the authoritative /delivery + /map-layers are fetched by
 * useDeliverySync. No legacy endpoints (/layer/reports, /checkpoints,
 * /projects) are consulted.
 */
export async function bootstrapPlanningSession(sessionId: string): Promise<void> {
  const store = usePlanningStore.getState();

  const [statusData, syncResult] = await Promise.all([
    planningApi.getStatus(sessionId),
    planningApi.syncEvents(sessionId, store.lastProcessedSeq),
  ]);

  store.syncBackendState(statusData);

  const terminal =
    normalizePlanningStatus(statusData.status) === 'completed' ||
    normalizePlanningStatus(statusData.status) === 'failed' ||
    statusData.delivery_status != null;

  // Always catch up durable events the live SSE stream may have missed.
  if (!terminal && syncResult.events.length > 0) {
    applySyncedEvents(syncResult.events);
  } else if (typeof syncResult.last_seq === 'number') {
    store.setLastProcessedSeq(syncResult.last_seq);
  }

  // The REST projection wins over replayed optimistic events.
  store.syncBackendState(statusData);

  const firstLayer = statusData.phase?.startsWith('layer')
    ? Number.parseInt(statusData.phase.replace('layer', ''), 10)
    : 1;
  const layer = Number.isFinite(firstLayer) && firstLayer >= 1 && firstLayer <= 3
    ? firstLayer
    : 1;
  const firstDim = DIMENSIONS_BY_LAYER[layer]?.[0];
  const navKey = store.selectedNavigationKey;
  if (firstDim && (!navKey || navKey === 'overview' || !navKey.startsWith('dim:'))) {
    store.setSelectedNavigationKey(NAV_KEYS.dim(`${layer}_${firstDim}`));
  }
}
