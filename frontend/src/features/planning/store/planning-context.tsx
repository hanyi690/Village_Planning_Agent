'use client';

/**
 * PlanningProvider - Simplified State Management
 *
 * Uses Zustand + Immer for state management.
 * SSE connection and message persistence are handled by dedicated hooks.
 *
 * This provider is now a thin wrapper that:
 * 1. Initializes the store with conversationId
 * 2. Manages SSE connection lifecycle
 * 3. Handles message persistence
 * 4. Provides high-level actions for planning workflow
 */

import { useEffect, useCallback, ReactNode, Suspense } from 'react';
import { usePlanningStore } from '@/stores/planningStore';
import { useSSEConnection, useMessagePersistence, useSessionRestore } from '@/hooks/planning';
import { planningApi, dataApi, VillageInfo, VillageSession, ImageData } from '@/lib/api';
import { createSystemMessage, createErrorMessage, getErrorMessage } from '@/lib/utils';
import { transformBackendMessages } from '@/lib/utils/message-transform';
import { logger } from '@/lib/logger';
import { PLANNING_DEFAULTS } from '@/config/planning';
import type { PlanningParams } from '@/types';

// ============================================
// Provider Props
// ============================================

interface PlanningProviderProps {
  children: ReactNode;
  conversationId: string;
}

// ============================================
// Planning Actions Hook
// ============================================

export function usePlanningActions() {
  const store = usePlanningStore();

  const startPlanning = useCallback(
    async (params: PlanningParams) => {
      logger.context.info('Starting planning', { projectName: params.projectName });

      try {
        store.setStatus('collecting');
        store.setProjectName(params.projectName);
        store.setStepMode(params.stepMode ?? PLANNING_DEFAULTS.stepMode);

        const response = await planningApi.startPlanning({
          project_name: params.projectName,
          village_data: params.villageData,
          village_name: params.villageName || params.projectName,
          task_description: params.taskDescription || PLANNING_DEFAULTS.defaultTask,
          constraints: params.constraints || PLANNING_DEFAULTS.defaultConstraints,
          enable_review: params.enableReview ?? PLANNING_DEFAULTS.enableReview,
          step_mode: params.stepMode ?? PLANNING_DEFAULTS.stepMode,
          stream_mode: PLANNING_DEFAULTS.streamMode,
          images: params.images,
        });

        if (!response || typeof response.task_id !== 'string') {
          throw new Error('Server response missing task ID');
        }

        store.setTaskId(response.task_id);
        store.setStatus('planning');

        // Build initialization message with planning context
        const villageName = params.villageName || params.projectName;
        const taskDesc = params.taskDescription || PLANNING_DEFAULTS.defaultTask;
        const constraintsText = params.constraints || PLANNING_DEFAULTS.defaultConstraints;

        // Truncate long content (preserve line breaks, relaxed limit for file content)
        const truncate = (text: string, maxLen: number = 500): string => {
          if (text.length <= maxLen) return text;
          const breakPoint = text.lastIndexOf('\n', maxLen);
          if (breakPoint > maxLen * 0.7) return text.slice(0, breakPoint) + '...';
          return text.slice(0, maxLen) + '...';
        };

        const initMessage = `规划任务已启动

村庄: ${villageName}
任务: ${truncate(taskDesc)}
约束: ${truncate(constraintsText)}

Task ID: ${response.task_id.slice(0, 8)}...`;

        store.addMessage(createSystemMessage(initMessage));
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Unknown error');
        logger.context.error('Planning failed to start', { error: errorMessage });
        store.setStatus('failed');
        throw error;
      }
    },
    [store]
  );

  const approve = useCallback(async () => {
    if (!store.taskId) throw new Error('No task ID');
    logger.context.info('Approving review', { taskId: store.taskId });
    try {
      await planningApi.approveReview(store.taskId);
      store.setPaused(false);
      store.setPendingReviewLayer(null);
      store.clearProgressState();
      store.triggerSseReconnect();
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, 'Unknown error');
      logger.context.error('Failed to approve review', { error: errorMessage });
      store.addMessage(createErrorMessage(`批准失败: ${errorMessage}`));
      throw error;
    }
  }, [store]);

  const reject = useCallback(
    async (feedback: string, dimensions?: string[], images?: ImageData[]) => {
      if (!store.taskId) throw new Error('No task ID');
      if (!feedback.trim()) throw new Error('Feedback is required');
      logger.context.info('Rejecting review', {
        taskId: store.taskId,
        feedback: feedback.slice(0, 50),
        hasImages: (images?.length ?? 0) > 0,
      });
      try {
        await planningApi.rejectReview(store.taskId, feedback, dimensions, images);
        store.setPaused(false);

        // Use clearRevisionProgress to preserve other completed dimensions
        if (dimensions && dimensions.length > 0) {
          store.clearRevisionProgress(store.currentLayer || 1, dimensions);
        } else {
          // When no dimensions specified (full reject), clear all progress
          store.clearProgressState();
        }

        store.triggerSseReconnect();
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Unknown error');
        logger.context.error('Failed to reject review', { error: errorMessage });

        throw error;
      }
    },
    [store]
  );

  const rollback = useCallback(
    async (checkpointId: string) => {
      if (!store.taskId) throw new Error('No task ID');
      await planningApi.rollbackCheckpoint(store.taskId, checkpointId);
      store.setSelectedCheckpoint(checkpointId);

      // Sync state after rollback
      const statusData = await planningApi.getStatus(store.taskId);
      store.syncBackendState(statusData);

      store.addMessage(
        createSystemMessage(`Rolled back to checkpoint ${checkpointId.slice(0, 8)}...`)
      );
    },
    [store]
  );

  const loadVillagesHistory = useCallback(async () => {
    store.setHistoryLoading(true);
    store.setHistoryError(null);
    try {
      const data = await dataApi.listVillages();
      store.setVillages(data);
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, 'Failed to load history');
      store.setHistoryError(errorMessage);
      store.setVillages([]);
    } finally {
      store.setHistoryLoading(false);
    }
  }, [store]);

  const selectVillage = useCallback(
    (village: VillageInfo) => {
      store.setSelectedVillage(village);
    },
    [store]
  );

  const selectSession = useCallback(
    (session: VillageSession) => {
      store.setSelectedSession(session);
    },
    [store]
  );

  const loadHistoricalSession = useCallback(
    async (villageName: string, sessionId: string) => {
      store.clearMessages();
      store.setCheckpoints([]);
      store.setSelectedCheckpoint(null);
      store.setProjectName(villageName);
      store.setTaskId(sessionId);
      store.setStatus('completed');

      try {
        const response = await dataApi.getCheckpoints(villageName, sessionId);
        store.setCheckpoints(response.checkpoints);

        const statusData = await planningApi.getStatus(sessionId);
        store.syncBackendState(statusData);

        // Load historical messages
        try {
          const messagesResponse = await planningApi.getMessages(sessionId);
          if (messagesResponse.success && messagesResponse.messages.length > 0) {
            const transformedMessages = transformBackendMessages(messagesResponse.messages);
            store.setMessages(transformedMessages);
          }
        } catch (msgError) {
          console.error('[PlanningProvider] Failed to load messages:', msgError);
        }
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Failed to load session');
        store.setHistoryError(errorMessage);
      }
    },
    [store]
  );

  const deleteSession = useCallback(
    async (sessionId: string, _villageName: string): Promise<boolean> => {
      try {
        await planningApi.deleteSession(sessionId);
        // Reload villages history
        await loadVillagesHistory();
        return true;
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Failed to delete session');
        store.setHistoryError(errorMessage);
        return false;
      }
    },
    [store, loadVillagesHistory]
  );

  const showViewer = useCallback(() => {
    store.setViewerVisible(true);
  }, [store]);

  const hideViewer = useCallback(() => {
    store.setViewerVisible(false);
  }, [store]);

  const showFileViewer = useCallback(
    (file: Parameters<typeof store.setViewingFile>[0]) => {
      store.setViewingFile(file as Parameters<typeof store.setViewingFile>[0]);
      store.setViewerVisible(true);
    },
    [store]
  );

  const hideFileViewer = useCallback(() => {
    store.setViewingFile(null);
    store.setViewerVisible(false);
  }, [store]);

  const resetConversation = useCallback(() => {
    store.resetConversation();
  }, [store]);

  const sendChatMessage = useCallback(
    async (message: string) => {
      if (!store.taskId) throw new Error('No task ID');
      return planningApi.sendChatMessage(store.taskId, message);
    },
    [store]
  );

  return {
    startPlanning,
    approve,
    reject,
    rollback,
    loadVillagesHistory,
    selectVillage,
    selectSession,
    loadHistoricalSession,
    deleteSession,
    showViewer,
    hideViewer,
    showFileViewer,
    hideFileViewer,
    resetConversation,
    sendChatMessage,
    addMessage: store.addMessage,
    addMessages: store.addMessages,
    setMessages: store.setMessages,
  };
}

// ============================================
// Provider Component
// ============================================

// Session restore wrapper - needs Suspense for useSearchParams
function SessionRestoreWrapper() {
  useSessionRestore();
  return null;
}

export function PlanningProvider({ children, conversationId }: PlanningProviderProps) {
  const taskId = usePlanningStore((state) => state.taskId);
  const isPaused = usePlanningStore((state) => state.isPaused);
  const sseResumeTrigger = usePlanningStore((state) => state.sseResumeTrigger);
  const initConversation = usePlanningStore((state) => state.initConversation);
  const setCheckpoints = usePlanningStore((state) => state.setCheckpoints);

  // Initialize store with conversationId
  useEffect(() => {
    initConversation(conversationId);
  }, [conversationId, initConversation]);

  // SSE connection with reconnect trigger
  useSSEConnection({ taskId, resumeTrigger: sseResumeTrigger });

  // Message persistence
  useMessagePersistence();

  // Checkpoint sync when paused
  useEffect(() => {
    if (isPaused && taskId) {
      planningApi
        .getStatus(taskId)
        .then((statusData) => {
          if (statusData.checkpoints) {
            setCheckpoints(statusData.checkpoints);
          }
        })
        .catch((err) => {
          console.error('[PlanningProvider] Failed to sync checkpoints:', err);
        });
    }
  }, [isPaused, taskId, setCheckpoints]);

  return (
    <>
      {/* Session restore wrapped in Suspense for useSearchParams */}
      <Suspense fallback={null}>
        <SessionRestoreWrapper />
      </Suspense>
      {children}
    </>
  );
}

// ============================================
// Exports
// ============================================

export { usePlanningStore } from '@/stores/planningStore';
export type { PlanningState } from '@/stores/planningStore';
