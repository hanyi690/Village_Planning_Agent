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

import { useEffect, useCallback, useMemo, ReactNode, Suspense } from 'react';
import { usePlanningStore } from '../store/planningStore';
import { useSSEConnection, useMessagePersistence, useSessionRestore } from '../hooks';
import { planningApi, dataApi, VillageInfo, VillageSession, ImageData } from '../api';
import { createSystemMessage, createErrorMessage, getErrorMessage } from '@/features/planning/utils';
import { logger } from '@/features/planning/utils/logger';
import { PLANNING_DEFAULTS } from '../config/planning';
import type { PlanningParams } from '../types';

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
  const addMessage = usePlanningStore((s) => s.addMessage);
  const addMessages = usePlanningStore((s) => s.addMessages);
  const setMessages = usePlanningStore((s) => s.setMessages);

  const startPlanning = useCallback(
    async (params: PlanningParams) => {
      const store = usePlanningStore.getState();
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
          villageDataFiles: params.villageDataFiles,
          taskFiles: params.taskFiles,
          constraintFiles: params.constraintFiles,
        });

        if (!response || typeof response.session_id !== 'string') {
          throw new Error('Server response missing session ID');
        }

        store.setSessionId(response.session_id);
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

Session ID: ${response.session_id.slice(0, 8)}...`;

        store.addMessage(createSystemMessage(initMessage));
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Unknown error');
        logger.context.error('Planning failed to start', { error: errorMessage });
        store.setStatus('failed');
        throw error;
      }
    },
    []
  );

  const approve = useCallback(async () => {
    const store = usePlanningStore.getState();
    const sessionId = store.sessionId;
    if (!sessionId) throw new Error('No session ID');
    console.log('[approve] sessionId=%s isPaused=%s status=%s execPaused=%s',
        sessionId, store.isPaused, store.status, store.execution_paused);
    logger.context.info('Approving review', { sessionId });
    try {
      await planningApi.approveReview(sessionId);
      store.setPaused(false);
      store.setPendingReviewLayer(null);
      store.clearProgressState();
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, 'Unknown error');
      logger.context.error('Failed to approve review', { error: errorMessage });
      store.addMessage(createErrorMessage(`批准失败: ${errorMessage}`));
      throw error;
    }
  }, []);

  const reject = useCallback(
    async (feedback: string, dimensions?: string[], images?: ImageData[]) => {
      const store = usePlanningStore.getState();
      const sessionId = store.sessionId;
      if (!sessionId) throw new Error('No session ID');
      if (!feedback.trim()) throw new Error('Feedback is required');
      logger.context.info('Rejecting review', {
        sessionId,
        feedback: feedback.slice(0, 50),
        hasImages: (images?.length ?? 0) > 0,
      });
      try {
        await planningApi.rejectReview(sessionId, feedback, dimensions, images);
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
    []
  );

  const rollback = useCallback(
    async (checkpointId: string) => {
      const store = usePlanningStore.getState();
      const sessionId = store.sessionId;
      if (!sessionId) throw new Error('No session ID');
      await planningApi.rollbackCheckpoint(sessionId, checkpointId);
      store.setSelectedCheckpoint(checkpointId);

      // Sync state after rollback
      const statusData = await planningApi.getStatus(sessionId);
      store.syncBackendState(statusData);

      store.addMessage(
        createSystemMessage(`Rolled back to checkpoint ${checkpointId.slice(0, 8)}...`)
      );
    },
    []
  );

  const loadVillagesHistory = useCallback(async () => {
    const state = usePlanningStore.getState();
    state.setHistoryLoading(true);
    state.setHistoryError(null);
    try {
      const projects = await dataApi.listVillages();
      const villages: VillageInfo[] = await Promise.all(
        projects.map(async (p) => {
          const sessions = await dataApi.getVillageSessions(p.name);
          return {
            name: p.name,
            display_name: p.display_name,
            session_count: p.session_count,
            sessions: sessions.map((s) => ({
              session_id: s.session_id,
              timestamp: s.created_at,
              checkpoint_count: 0,
              has_final_report: s.completed_at !== null,
            })),
          };
        })
      );
      state.setVillages(villages);
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, 'Failed to load history');
      state.setHistoryError(errorMessage);
      state.setVillages([]);
    } finally {
      state.setHistoryLoading(false);
    }
  }, []);

  const selectVillage = useCallback(
    (village: VillageInfo) => {
      usePlanningStore.getState().setSelectedVillage(village);
    },
    []
  );

  const selectSession = useCallback(
    (session: VillageSession) => {
      usePlanningStore.getState().setSelectedSession(session);
    },
    []
  );

  const loadHistoricalSession = useCallback(
    async (villageName: string, sessionId: string) => {
      const store = usePlanningStore.getState();
      store.clearMessages();
      store.setCheckpoints([]);
      store.setSelectedCheckpoint(null);
      store.setProjectName(villageName);
      store.setSessionId(sessionId);
      store.setStatus('completed');

      try {
        const response = await planningApi.getCheckpoints(sessionId);
        store.setCheckpoints(
          response.checkpoints.map((cp) => ({
            checkpoint_id: cp.checkpoint_id,
            description: cp.phase || '',
            timestamp: '',
            layer: cp.layer,
          }))
        );

        const statusData = await planningApi.getStatus(sessionId);
        store.syncBackendState(statusData);

        // Load layer reports for completed layers
        const completedDimensions = statusData.completed_dimensions;
        if (completedDimensions) {
          const layers = [1, 2, 3] as const;
          for (const layer of layers) {
            const dims = completedDimensions[`layer${layer}`];
            if (dims && dims.length > 0) {
              try {
                const reportsData = await planningApi.getLayerReports(sessionId, layer);
                if (reportsData.reports && Object.keys(reportsData.reports).length > 0) {
                  store.setReports({ [`layer${layer}`]: reportsData.reports });
                }
              } catch (error) {
                console.warn(`Failed to load layer ${layer} reports:`, error);
              }
            }
          }
        }
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Failed to load session');
        store.setHistoryError(errorMessage);
      }
    },
    []
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
        usePlanningStore.getState().setHistoryError(errorMessage);
        return false;
      }
    },
    [loadVillagesHistory]
  );

  const showViewer = useCallback(() => {
    usePlanningStore.getState().setViewerVisible(true);
  }, []);

  const hideViewer = useCallback(() => {
    usePlanningStore.getState().setViewerVisible(false);
  }, []);

  const showFileViewer = useCallback(
    (file: Parameters<ReturnType<typeof usePlanningStore.getState>['setViewingFile']>[0]) => {
      const store = usePlanningStore.getState();
      store.setViewingFile(file);
      store.setViewerVisible(true);
    },
    []
  );

  const hideFileViewer = useCallback(() => {
    const store = usePlanningStore.getState();
    store.setViewingFile(null);
    store.setViewerVisible(false);
  }, []);

  const resetConversation = useCallback(() => {
    usePlanningStore.getState().resetConversation();
  }, []);

  const sendChatMessage = useCallback(
    async (message: string) => {
      const sessionId = usePlanningStore.getState().sessionId;
      if (!sessionId) throw new Error('No session ID');
      return planningApi.sendChatMessage(sessionId, message);
    },
    []
  );

  return useMemo(
    () => ({
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
      addMessage,
      addMessages,
      setMessages,
    }),
    [
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
      addMessage,
      addMessages,
      setMessages,
    ]
  );
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
  const sessionId = usePlanningStore((state) => state.sessionId);
  const isPaused = usePlanningStore((state) => state.isPaused);
  const sseResumeTrigger = usePlanningStore((state) => state.sseResumeTrigger);
  const initConversation = usePlanningStore((state) => state.initConversation);
  const setCheckpoints = usePlanningStore((state) => state.setCheckpoints);

  // Initialize store with conversationId
  useEffect(() => {
    initConversation(conversationId);
  }, [conversationId, initConversation]);

  // SSE connection with reconnect trigger
  useSSEConnection({ sessionId, resumeTrigger: sseResumeTrigger });

  // Message persistence
  useMessagePersistence();

  // Checkpoint sync when paused
  useEffect(() => {
    if (isPaused && sessionId) {
      planningApi
        .getStatus(sessionId)
        .then((statusData) => {
          if (statusData.checkpoints) {
            setCheckpoints(statusData.checkpoints);
          }
        })
        .catch((err) => {
          console.error('[PlanningProvider] Failed to sync checkpoints:', err);
        });
    }
  }, [isPaused, sessionId, setCheckpoints]);

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

export { usePlanningStore } from '../store/planningStore';
export type { PlanningState } from '../store/planningStore';
