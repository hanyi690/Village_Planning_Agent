/**
 * useSessionRestore Hook
 *
 * Restores a planning session only when `sessionId` is present in the URL.
 * Fresh visits start blank; historical sessions are loaded explicitly from
 * the sidebar history list or by sharing a URL with ?sessionId=...
 */

import { useEffect, useCallback, useRef } from 'react';
import { usePlanningStore } from '../store/planningStore';
import { logger } from '@/features/planning/utils/logger';
import { hydrateSessionSnapshot } from '@/features/planning/utils/session-hydrate';
import { getSessionIdFromUrl, setSessionIdInUrl, clearSessionIdFromUrl } from '@/features/planning/utils/session-url';

interface UseSessionRestoreOptions {
  enabled?: boolean;
}

export function useSessionRestore({ enabled = true }: UseSessionRestoreOptions = {}) {
  const sessionId = usePlanningStore((state) => state.sessionId);
  const setSessionId = usePlanningStore((state) => state.setSessionId);
  const resetConversation = usePlanningStore((state) => state.resetConversation);

  const restoringRef = useRef(false);
  const restoredSessionIdRef = useRef<string | null>(null);

  const restoreSession = useCallback(async (targetSessionId: string) => {
    if (restoringRef.current) return;

    if (usePlanningStore.getState().deletedSessionIds[targetSessionId]) {
      clearSessionIdFromUrl();
      return;
    }

    const currentSessionId = usePlanningStore.getState().sessionId;
    if (currentSessionId === targetSessionId) {
      restoredSessionIdRef.current = targetSessionId;
      return;
    }

    // Store already has a different active session (e.g. user just started planning).
    // Trust the store and sync the URL instead of overwriting it.
    if (currentSessionId && currentSessionId !== targetSessionId) {
      setSessionIdInUrl(currentSessionId);
      restoredSessionIdRef.current = currentSessionId;
      return;
    }

    restoringRef.current = true;
    logger.context.info('Starting session restoration', { sessionId: targetSessionId });

    try {
      if (usePlanningStore.getState().pendingHistoricalSessionId) {
        return;
      }

      // Isolate any HMR / leftover state, hydrate fully, then connect SSE.
      usePlanningStore.getState().resetSessionState();
      const { statusData } = await hydrateSessionSnapshot(targetSessionId, {
        loadCheckpoints: true,
      });
      setSessionId(targetSessionId);
      restoredSessionIdRef.current = targetSessionId;
      setSessionIdInUrl(targetSessionId);
      logger.context.info('Session restoration completed', {
        sessionId: targetSessionId,
        status: statusData.status,
        phase: statusData.phase,
      });
    } catch (error) {
      logger.context.error('Session restoration failed', { error, sessionId: targetSessionId });
      const activeSessionId = usePlanningStore.getState().sessionId;
      if (activeSessionId && activeSessionId !== targetSessionId) {
        clearSessionIdFromUrl();
        return;
      }
      usePlanningStore.getState().markSessionsDeleted([targetSessionId]);
      clearSessionIdFromUrl();
      resetConversation();
    } finally {
      restoringRef.current = false;
    }
  }, [setSessionId, resetConversation]);

  useEffect(() => {
    if (!enabled) return;

    const pendingHistorical = usePlanningStore.getState().pendingHistoricalSessionId;
    if (pendingHistorical) return;

    // Always read the live URL; Next.js searchParams can lag behind replaceState.
    const urlSessionId = getSessionIdFromUrl();
    if (!urlSessionId || restoringRef.current) return;

    if (sessionId === urlSessionId) {
      restoredSessionIdRef.current = urlSessionId;
      return;
    }

    // Only auto-restore when the store has no active session.
    if (sessionId) return;

    if (restoredSessionIdRef.current === urlSessionId) return;

    void restoreSession(urlSessionId);
  }, [enabled, sessionId, restoreSession]);

  useEffect(() => {
    if (!sessionId) {
      restoredSessionIdRef.current = null;
    }
  }, [sessionId]);

  useEffect(() => {
    if (!enabled || !sessionId) return;
    if (sessionId === restoredSessionIdRef.current) return;
    setSessionIdInUrl(sessionId);
    restoredSessionIdRef.current = sessionId;
  }, [enabled, sessionId]);

  return {
    isRestoring: restoringRef.current,
    sessionIdFromUrl: getSessionIdFromUrl(),
    restoreSession,
  };
}

export default useSessionRestore;
