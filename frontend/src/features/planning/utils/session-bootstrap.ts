import { planningApi } from '../api/planning-api';
import { DIMENSIONS_BY_LAYER } from '../config/dimensions';
import { NAV_KEYS } from '../constants';
import { usePlanningStore } from '../store/planningStore';
import { normalizePlanningStatus } from '../constants';

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
  const lastSeq = store.lastProcessedSeq;

  const [statusData, syncResult] = await Promise.all([
    planningApi.getStatus(sessionId),
    planningApi.syncEvents(sessionId, lastSeq),
  ]);

  store.syncBackendState(statusData);

  const terminal =
    normalizePlanningStatus(statusData.status) === 'completed' ||
    normalizePlanningStatus(statusData.status) === 'failed' ||
    statusData.delivery_status != null;

  // History / URL hydrate sets lastProcessedSeq to the tip before connecting.
  // Do not re-apply the full event stream (would wipe restored messages / status).
  const alreadyHydrated = lastSeq > 0;
  if (!alreadyHydrated && !terminal) {
    for (const event of syncResult.events) {
      store.handleSSEEvent({ type: event.type, data: event.data });
    }
  } else if (typeof syncResult.last_seq === 'number') {
    store.setLastProcessedSeq(syncResult.last_seq);
  }

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
