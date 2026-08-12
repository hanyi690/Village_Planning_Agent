import { planningApi } from '../api/planning-api';
import { DIMENSIONS_BY_LAYER } from '../config/dimensions';
import { NAV_KEYS } from '../constants';
import { usePlanningStore } from '../store/planningStore';
import { loadSessionReports, applySessionReportsToStore } from './session-report-loader';
import { normalizePlanningStatus } from '../constants';

/**
 * Hydrate client state after a new session starts or SSE connects late.
 * Replays cached SSE events so layer/dimension progress is not lost —
 * unless history hydrate already advanced lastProcessedSeq (skip replay).
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
    statusData.execution_complete === true;

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

  const completed = statusData.completed_dimensions;
  const reportsEmpty =
    Object.keys(store.reports.layer1).length === 0 &&
    Object.keys(store.reports.layer2).length === 0 &&
    Object.keys(store.reports.layer3).length === 0;
  if (completed && reportsEmpty && Object.values(completed).some((items) => items.length > 0)) {
    const loaded = await loadSessionReports(sessionId, completed);
    applySessionReportsToStore(loaded.allReports, loaded.allProgress, loaded.allRagSources);
  }

  if (Array.isArray(statusData.gis_layout_configs) && statusData.gis_layout_configs.length > 0) {
    const hasGis = Object.keys(usePlanningStore.getState().gisLayers).length > 0;
    if (!hasGis) {
      store.hydrateFromStateSync({
        gis_layout_configs: statusData.gis_layout_configs,
      });
    }
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
