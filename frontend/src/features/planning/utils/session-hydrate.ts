/**
 * Shared historical / URL session hydration.
 *
 * Restores reports, layer_completed messages, chat, status, and advances
 * lastProcessedSeq so a subsequent SSE bootstrap does not replay the full
 * event stream and wipe the restored UI.
 */

import { planningApi } from '../api';
import { usePlanningStore } from '../store/planningStore';
import type { LayerCompletedMessage, Message } from '../types/messages';
import type { SessionStatusResponse } from '../api/types';
import { buildLayerReportId, calculateReportSummary } from './message-helpers';
import { restoreChatHistoryMessages } from './chat-messages';
import { loadSessionReports, applySessionReportsToStore } from './session-report-loader';
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

function buildLayerCompletedMessages(
  allReports: Record<string, Record<string, string>>,
): LayerCompletedMessage[] {
  const messages: LayerCompletedMessage[] = [];
  for (const [layerKey, reportsContent] of Object.entries(allReports)) {
    if (Object.keys(reportsContent).length === 0) continue;
    const layer = parseInt(layerKey.replace('layer', ''), 10);
    if (!Number.isFinite(layer)) continue;
    messages.push({
      id: buildLayerReportId(layer),
      type: 'layer_completed',
      layer,
      content: '',
      summary: calculateReportSummary(reportsContent),
      fullReportContent: '',
      dimensionReports: reportsContent,
      dimensionKnowledgeSources: {},
      actions: [],
      timestamp: new Date(),
      role: 'assistant',
    });
  }
  return messages;
}

export interface HydrateSessionOptions {
  /** When true, also fetch and store checkpoints. Default true. */
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
  options: HydrateSessionOptions = {},
): Promise<HydrateSessionResult> {
  const { loadCheckpoints = true } = options;
  const store = usePlanningStore.getState();

  const [statusData, syncResult, checkpointsResp] = await Promise.all([
    planningApi.getStatus(sessionId),
    planningApi.syncEvents(sessionId, 0),
    loadCheckpoints
      ? planningApi.getCheckpoints(sessionId).catch(() => null)
      : Promise.resolve(null),
  ]);

  // Advance seq before any SSE connection so bootstrap/reconnect skip replay.
  const lastSeq = typeof syncResult.last_seq === 'number' ? syncResult.last_seq : 0;
  store.setLastProcessedSeq(lastSeq);

  if (checkpointsResp?.checkpoints) {
    store.setCheckpoints(
      checkpointsResp.checkpoints.map((cp) => ({
        checkpoint_id: cp.checkpoint_id,
        description: cp.phase || '',
        timestamp: '',
        layer: cp.layer,
      })),
    );
  }

  store.syncBackendState(statusData);
  if (statusData.step_mode !== undefined) {
    store.setStepMode(statusData.step_mode);
  }
  resolveUiStatus(statusData.status);

  // hydrateFromStateSync always applies GIS layouts (syncBackendState only
  // restores when gisLayers is empty AND something else also changed).
  if (
    Array.isArray(statusData.gis_layout_configs) &&
    statusData.gis_layout_configs.length > 0
  ) {
    store.hydrateFromStateSync({
      gis_layout_configs: statusData.gis_layout_configs,
    });
  }

  const restoredMessages: Message[] = [];
  const completedDimensions = statusData.completed_dimensions ?? {};
  const { allReports, allProgress, allRagSources } = await loadSessionReports(
    sessionId,
    completedDimensions,
  );
  if (Object.keys(allReports).length > 0) {
    applySessionReportsToStore(allReports, allProgress, allRagSources);
    restoredMessages.push(...buildLayerCompletedMessages(allReports));
  }

  const restoredChatMessages = restoreChatHistoryMessages(statusData.chat_history);
  store.setMessages([...restoredMessages, ...restoredChatMessages]);
  store.scanOfflineReports();

  return { statusData, lastSeq };
}
