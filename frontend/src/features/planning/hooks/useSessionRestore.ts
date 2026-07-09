/**
 * useSessionRestore Hook
 *
 * Handles session restoration from URL sessionId parameter.
 * When page refreshes with sessionId in URL, automatically:
 * 1. Sets sessionId in store
 * 2. Fetches and syncs backend state
 * 3. Loads historical reports via shared loader
 * 4. Updates URL with sessionId
 */

import { useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { usePlanningStore } from '../store/planningStore';
import { planningApi } from '../api';
import { logger } from '@/features/planning/utils/logger';
import { loadSessionReports, applySessionReportsToStore } from '@/features/planning/utils/session-report-loader';
import type { LayerCompletedMessage, Message } from '../types/messages';
import { buildLayerReportId, calculateReportSummary } from '@/features/planning/utils/message-helpers';

interface UseSessionRestoreOptions {
  enabled?: boolean;
}

export function useSessionRestore({ enabled = true }: UseSessionRestoreOptions = {}) {
  const searchParams = useSearchParams();

  const sessionIdFromUrl = searchParams.get('sessionId');
  const sessionId = usePlanningStore((state) => state.sessionId);
  const status = usePlanningStore((state) => state.status);
  const setSessionId = usePlanningStore((state) => state.setSessionId);
  const setMessages = usePlanningStore((state) => state.setMessages);
  const syncBackendState = usePlanningStore((state) => state.syncBackendState);
  const setStatus = usePlanningStore((state) => state.setStatus);
  const resetConversation = usePlanningStore((state) => state.resetConversation);

  const restoringRef = useRef(false);
  const restoredSessionIdRef = useRef<string | null>(null);
  const resetProtectionRef = useRef(false);

  const updateUrlWithSessionId = useCallback((newSessionId: string) => {
    const currentUrl = new URL(window.location.href);
    const currentSessionIdInUrl = currentUrl.searchParams.get('sessionId');

    if (currentSessionIdInUrl !== newSessionId) {
      currentUrl.searchParams.set('sessionId', newSessionId);
      window.history.replaceState({}, '', currentUrl.toString());
      logger.context.info('URL updated with sessionId', { sessionId: newSessionId });
    }
  }, []);

  const restoreSession = useCallback(async (targetSessionId: string) => {
    if (restoringRef.current) return;

    const currentSessionId = usePlanningStore.getState().sessionId;
    if (currentSessionId === targetSessionId) {
      restoredSessionIdRef.current = targetSessionId;
      return;
    }

    restoringRef.current = true;
    logger.context.info('Starting session restoration', { sessionId: targetSessionId });

    try {
      setSessionId(targetSessionId);

      // Fetch status (reports will be loaded in parallel via loadSessionReports)
      const statusData = await planningApi.getStatus(targetSessionId);
      syncBackendState(statusData);

      const backendStatus = statusData.status;
      if (backendStatus === 'completed' || backendStatus === 'paused') {
        setStatus(backendStatus);
      } else if (backendStatus === 'planning' || backendStatus === 'running') {
        setStatus('planning');
      }

      // Load all layer reports in parallel via shared utility
      const completedDimensions = statusData.completed_dimensions;
      const restoredMessages: Message[] = [];

      if (completedDimensions) {
        const { allReports, allProgress, allRagSources } =
          await loadSessionReports(targetSessionId, completedDimensions);
        applySessionReportsToStore(allReports, allProgress, allRagSources);

        // Build LayerCompletedMessage for each layer with reports
        for (const [layerKey, reportsContent] of Object.entries(allReports)) {
          if (Object.keys(reportsContent).length === 0) continue;
          const layer = parseInt(layerKey.replace('layer', ''), 10);
          const summary = calculateReportSummary(reportsContent);

          const layerMsg: LayerCompletedMessage = {
            id: buildLayerReportId(layer),
            type: 'layer_completed',
            layer,
            content: '',
            summary,
            fullReportContent: '',
            dimensionReports: reportsContent,
            dimensionKnowledgeSources: {},
            actions: [],
            timestamp: new Date(),
            role: 'assistant',
          };
          restoredMessages.push(layerMsg);
        }
      }

      setMessages(restoredMessages.length > 0 ? restoredMessages : []);

      restoredSessionIdRef.current = targetSessionId;
      logger.context.info('Session restoration completed', {
        sessionId: targetSessionId,
        status: statusData.status,
        phase: statusData.phase,
      });
    } catch (error) {
      logger.context.error('Session restoration failed', { error, sessionId: targetSessionId });
      const url = new URL(window.location.href);
      url.searchParams.delete('sessionId');
      window.history.replaceState({}, '', url.toString());
      resetConversation();
    } finally {
      restoringRef.current = false;
    }
  }, [setSessionId, syncBackendState, setStatus, setMessages, resetConversation]);

  useEffect(() => {
    if (!enabled) return;

    if (!sessionIdFromUrl) {
      resetProtectionRef.current = false;
    }

    if (sessionIdFromUrl && !sessionId && !restoringRef.current && !resetProtectionRef.current) {
      restoreSession(sessionIdFromUrl);
    }

    return () => {
      restoringRef.current = false;
    };
  }, [enabled, sessionIdFromUrl, sessionId, restoreSession]);

  useEffect(() => {
    if (!enabled || !sessionId) return;
    if (sessionId === restoredSessionIdRef.current) return;
    updateUrlWithSessionId(sessionId);
  }, [enabled, sessionId, updateUrlWithSessionId]);

  useEffect(() => {
    if (!enabled) return;
    if (sessionId === null && status === 'idle') {
      resetProtectionRef.current = true;
      logger.context.info('Reset protection activated');
    }
  }, [enabled, sessionId, status]);

  return {
    isRestoring: restoringRef.current,
    sessionIdFromUrl,
    restoreSession,
    updateUrlWithSessionId,
  };
}

export default useSessionRestore;
