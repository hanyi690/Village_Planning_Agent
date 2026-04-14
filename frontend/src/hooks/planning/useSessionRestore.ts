/**
 * useSessionRestore Hook
 *
 * Handles session restoration from URL taskId parameter.
 * When page refreshes with taskId in URL, automatically:
 * 1. Sets taskId in store
 * 2. Fetches and syncs backend state
 * 3. Loads historical messages
 * 4. Updates URL with taskId
 */

import { useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { usePlanningStore } from '@/stores/planningStore';
import { planningApi } from '@/lib/api';
import { logger } from '@/lib/logger';
import { transformBackendMessages } from '@/lib/utils/message-transform';

interface UseSessionRestoreOptions {
  enabled?: boolean;
}

export function useSessionRestore({ enabled = true }: UseSessionRestoreOptions = {}) {
  const searchParams = useSearchParams();

  const taskIdFromUrl = searchParams.get('taskId');
  const taskId = usePlanningStore((state) => state.taskId);
  const status = usePlanningStore((state) => state.status);
  const setTaskId = usePlanningStore((state) => state.setTaskId);
  const setMessages = usePlanningStore((state) => state.setMessages);
  const syncBackendState = usePlanningStore((state) => state.syncBackendState);
  const setStatus = usePlanningStore((state) => state.setStatus);
  const resetConversation = usePlanningStore((state) => state.resetConversation);

  const restoringRef = useRef(false);
  const restoredTaskIdRef = useRef<string | null>(null);
  const resetProtectionRef = useRef(false);

  // Update URL with taskId (without triggering navigation)
  const updateUrlWithTaskId = useCallback((newTaskId: string) => {
    const currentUrl = new URL(window.location.href);
    const currentTaskIdInUrl = currentUrl.searchParams.get('taskId');

    if (currentTaskIdInUrl !== newTaskId) {
      currentUrl.searchParams.set('taskId', newTaskId);
      window.history.replaceState({}, '', currentUrl.toString());
      logger.context.info('URL updated with taskId', { taskId: newTaskId });
    }
  }, []);

  // Restore session from backend
  const restoreSession = useCallback(async (targetTaskId: string) => {
    // Skip if already restoring
    if (restoringRef.current) {
      return;
    }

    // Check if store already has correct taskId
    const currentTaskId = usePlanningStore.getState().taskId;
    if (currentTaskId === targetTaskId) {
      restoredTaskIdRef.current = targetTaskId;
      return;
    }

    restoringRef.current = true;
    logger.context.info('Starting session restoration', { taskId: targetTaskId });

    try {
      // 1. Set taskId first
      setTaskId(targetTaskId);

      // 2. Fetch session status
      const statusData = await planningApi.getStatus(targetTaskId);

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

      // 6. Clear existing messages before loading history (avoid SSE queue conflict)
      setMessages([]);

      // 7. Load historical messages
      const messagesResponse = await planningApi.getMessages(targetTaskId);
      if (messagesResponse.success && messagesResponse.messages.length > 0) {
        const transformedMessages = transformBackendMessages(messagesResponse.messages);
        // Sort by created_at to ensure correct order
        const sortedMessages = transformedMessages.sort((a, b) => {
          const timeA = a.created_at ? new Date(a.created_at).getTime() : 0;
          const timeB = b.created_at ? new Date(b.created_at).getTime() : 0;
          return timeA - timeB;
        });
        setMessages(sortedMessages);
        logger.context.info('Messages restored', { count: sortedMessages.length });
      }

      // 8. Mark as restored
      restoredTaskIdRef.current = targetTaskId;
      logger.context.info('Session restoration completed', {
        taskId: targetTaskId,
        status: statusData.status,
        phase: statusData.phase,
      });
    } catch (error) {
      logger.context.error('Session restoration failed', { error, taskId: targetTaskId });
      // Clear invalid taskId from URL
      const url = new URL(window.location.href);
      url.searchParams.delete('taskId');
      window.history.replaceState({}, '', url.toString());
      resetConversation();
    } finally {
      restoringRef.current = false;
    }
  }, [setTaskId, syncBackendState, setStatus, setMessages, resetConversation]);

  // On mount: check if taskId in URL and restore
  useEffect(() => {
    if (!enabled) return;

    // Clear resetProtection when taskIdFromUrl becomes null (URL cleared)
    if (!taskIdFromUrl) {
      resetProtectionRef.current = false;
    }

    // Only restore if:
    // 1. taskId in URL
    // 2. Store has no taskId (fresh page load)
    // 3. Not already restoring
    // 4. Not protected by reset (prevents restore after clicking "New Task")
    if (taskIdFromUrl && !taskId && !restoringRef.current && !resetProtectionRef.current) {
      restoreSession(taskIdFromUrl);
    }

    // StrictMode cleanup: reset ref so remount can restore
    return () => {
      restoringRef.current = false;
    };
  }, [enabled, taskIdFromUrl, taskId, restoreSession]);

  // When taskId changes in store, update URL
  useEffect(() => {
    if (!enabled || !taskId) return;

    // Don't update URL if this is the taskId we just restored
    if (taskId === restoredTaskIdRef.current) return;

    updateUrlWithTaskId(taskId);
  }, [enabled, taskId, updateUrlWithTaskId]);

  // Detect reset: when taskId becomes null and status becomes 'idle'
  // Set resetProtection to prevent session restore from re-triggering
  useEffect(() => {
    if (!enabled) return;

    // When store is reset to idle state, activate protection
    if (taskId === null && status === 'idle') {
      resetProtectionRef.current = true;
      logger.context.info('Reset protection activated');
    }
  }, [enabled, taskId, status]);

  return {
    isRestoring: restoringRef.current,
    taskIdFromUrl,
    restoreSession,
    updateUrlWithTaskId,
  };
}

export default useSessionRestore;