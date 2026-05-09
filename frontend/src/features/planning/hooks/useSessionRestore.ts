/**
 * useSessionRestore Hook
 *
 * Handles session restoration from URL sessionId parameter.
 * When page refreshes with sessionId in URL, automatically:
 * 1. Sets sessionId in store
 * 2. Fetches and syncs backend state
 * 3. Loads historical messages
 * 4. Updates URL with sessionId
 */

import { useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { usePlanningStore } from '../store/planningStore';
import { planningApi } from '../api';
import { logger } from '@/features/planning/utils/logger';

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

  // Update URL with sessionId (without triggering navigation)
  const updateUrlWithSessionId = useCallback((newSessionId: string) => {
    const currentUrl = new URL(window.location.href);
    const currentSessionIdInUrl = currentUrl.searchParams.get('sessionId');

    if (currentSessionIdInUrl !== newSessionId) {
      currentUrl.searchParams.set('sessionId', newSessionId);
      window.history.replaceState({}, '', currentUrl.toString());
      logger.context.info('URL updated with sessionId', { sessionId: newSessionId });
    }
  }, []);

  // Restore session from backend
  const restoreSession = useCallback(async (targetSessionId: string) => {
    // Skip if already restoring
    if (restoringRef.current) {
      return;
    }

    // Check if store already has correct sessionId
    const currentSessionId = usePlanningStore.getState().sessionId;
    if (currentSessionId === targetSessionId) {
      restoredSessionIdRef.current = targetSessionId;
      return;
    }

    restoringRef.current = true;
    logger.context.info('Starting session restoration', { sessionId: targetSessionId });

    try {
      // 1. Set sessionId first
      setSessionId(targetSessionId);

      // 2. Fetch session status
      const statusData = await planningApi.getStatus(targetSessionId);

      // 3. Sync backend state
      syncBackendState(statusData);

      // 4. Set project name if available (from village_name field if exists)
      // Note: SessionStatusResponse doesn't include project_name directly
      // Project name is typically derived from village history selection
      // During refresh restore, we skip this and rely on backend state

      // 5. Set status based on backend status
      const backendStatus = statusData.status;
      if (backendStatus === 'completed' || backendStatus === 'paused') {
        setStatus(backendStatus);
      } else if (backendStatus === 'planning' || backendStatus === 'running') {
        setStatus('planning');
      }

      // 6. Clear existing messages
      setMessages([]);

      // 7. Mark as restored
      restoredSessionIdRef.current = targetSessionId;
      logger.context.info('Session restoration completed', {
        sessionId: targetSessionId,
        status: statusData.status,
        phase: statusData.phase,
      });
    } catch (error) {
      logger.context.error('Session restoration failed', { error, sessionId: targetSessionId });
      // Clear invalid sessionId from URL
      const url = new URL(window.location.href);
      url.searchParams.delete('sessionId');
      window.history.replaceState({}, '', url.toString());
      resetConversation();
    } finally {
      restoringRef.current = false;
    }
  }, [setSessionId, syncBackendState, setStatus, setMessages, resetConversation]);

  // On mount: check if sessionId in URL and restore
  useEffect(() => {
    if (!enabled) return;

    // Clear resetProtection when sessionIdFromUrl becomes null (URL cleared)
    if (!sessionIdFromUrl) {
      resetProtectionRef.current = false;
    }

    // Only restore if:
    // 1. sessionId in URL
    // 2. Store has no sessionId (fresh page load)
    // 3. Not already restoring
    // 4. Not protected by reset (prevents restore after clicking "New Task")
    if (sessionIdFromUrl && !sessionId && !restoringRef.current && !resetProtectionRef.current) {
      restoreSession(sessionIdFromUrl);
    }

    // StrictMode cleanup: reset ref so remount can restore
    return () => {
      restoringRef.current = false;
    };
  }, [enabled, sessionIdFromUrl, sessionId, restoreSession]);

  // When sessionId changes in store, update URL
  useEffect(() => {
    if (!enabled || !sessionId) return;

    // Don't update URL if this is the sessionId we just restored
    if (sessionId === restoredSessionIdRef.current) return;

    updateUrlWithSessionId(sessionId);
  }, [enabled, sessionId, updateUrlWithSessionId]);

  // Detect reset: when sessionId becomes null and status becomes 'idle'
  // Set resetProtection to prevent session restore from re-triggering
  useEffect(() => {
    if (!enabled) return;

    // When store is reset to idle state, activate protection
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