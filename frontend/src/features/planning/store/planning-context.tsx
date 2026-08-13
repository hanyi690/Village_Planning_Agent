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
import { useSSEConnection, useMessagePersistence, useSessionRestore, useDeliverySync } from '../hooks';
import { planningApi, VillageInfo, VillageSession, ImageData } from '../api';
import { createSystemMessage, createErrorMessage, getErrorMessage } from '@/features/planning/utils';
import { hydrateSessionSnapshot } from '@/features/planning/utils/session-hydrate';
import { logger } from '@/features/planning/utils/logger';
import { DIMENSIONS_BY_LAYER } from '../config/dimensions';
import { NAV_KEYS } from '../constants';
import { setSessionIdInUrl, clearSessionIdFromUrl } from '@/features/planning/utils/session-url';
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
        // Each planning run creates a brand-new backend session. Fully reset
        // client state so artifacts from the previous session cannot bleed through.
        store.resetSessionState();
        store.setStatus('collecting');
        store.setProjectName(params.projectName);
        store.setStepMode(params.stepMode ?? PLANNING_DEFAULTS.stepMode);
        clearSessionIdFromUrl();

        const response = await planningApi.startPlanning({
          project_name: params.projectName,
          village_data: params.villageData,
          village_name: params.villageName || params.projectName,
          province: params.province || '',
          city: params.city || '',
          county: params.county || '',
          township: params.township || '',
          planning_period: params.planningPeriod || '',
          task_description: params.taskDescription || PLANNING_DEFAULTS.defaultTask,
          constraints: params.constraints || PLANNING_DEFAULTS.defaultConstraints,
          enable_review: params.enableReview ?? PLANNING_DEFAULTS.enableReview,
          step_mode: store.step_mode,
          stream_mode: PLANNING_DEFAULTS.streamMode,
          rag_enabled: true,
          rag_layer_config: JSON.stringify(store.ragLayerConfig),
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
        setSessionIdInUrl(response.session_id);
        store.addSessionToHistory({
          projectName: params.projectName,
          villageName: params.villageName || params.projectName,
          sessionId: response.session_id,
        });

        // Immediate UI feedback before SSE connects and replays cached events.
        const firstDim = DIMENSIONS_BY_LAYER[1][0];
        if (firstDim) {
          store.setSelectedNavigationKey(NAV_KEYS.dim(`1_${firstDim}`));
        }
        store.handleSSEEvent({
          type: 'layer_started',
          data: {
            layer: 1,
            layer_name: '现状分析',
            dimension_count: DIMENSIONS_BY_LAYER[1].length,
          },
        });

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

        // v1: 后端无 geocode 端点，村庄中心点不再自动请求。
        // 页面刷新后地图中心由 /map-layers 权威快照决定。
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
    console.log('[approve] sessionId=%s isPaused=%s status=%s interruptInfo=%o',
        sessionId, store.isPaused, store.status, store.interruptInfo);
    logger.context.info('Approving review', { sessionId });
    try {
      // v1: resolve with the current event_id optimistic lock.
      const review = store.humanReview
        ?? (await planningApi.getHumanReview(sessionId));
      if (!review.event_id) {
        throw new Error('没有待审核的人工审核项（缺少 event_id）');
      }
      await planningApi.resolveHumanReview(sessionId, review.event_id, { action: 'approve' });
      store.clearHumanReview();
      store.setPaused(false);
      store.setPendingReviewLayer(null);
      store.setStatus('planning');
      // Reconnect SSE so layer_started / dimension events after interrupt resume are not missed.
      store.triggerSseReconnect();
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
        // v1: reject with the current event_id optimistic lock.
        const review = store.humanReview
          ?? (await planningApi.getHumanReview(sessionId));
        if (!review.event_id) {
          throw new Error('没有待审核的人工审核项（缺少 event_id）');
        }
        await planningApi.resolveHumanReview(sessionId, review.event_id, {
          action: 'reject',
          feedback,
        });
        store.clearHumanReview();
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
      // v1: fork a historical checkpoint into a new branch.
      await planningApi.resumeSession(sessionId, {
        mode: 'checkpoint',
        checkpoint_id: checkpointId,
      });
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
    // v1: 后端不再提供 /api/projects 历史列表；只保留本地会话历史
    // （本会话内新建 + localStorage 删除标记）。
    state.setVillages(state.villages);
    state.setHistoryLoading(false);
  }, []);

  const selectVillage = useCallback(
    (village: VillageInfo) => {
      usePlanningStore.getState().setSelectedVillage(village);
    },
    []
  );

  const selectSession = useCallback(
    (session: VillageSession) => {
      const store = usePlanningStore.getState();
      store.setSelectedSession(session);
      store.clearAllRagSources();
    },
    []
  );

  const loadHistoricalSession = useCallback(
    async (villageName: string, sessionId: string) => {
      const store = usePlanningStore.getState();
      // Pin target session before reset so URL auto-restore cannot reload the wrong session.
      store.setPendingHistoricalSessionId(sessionId);
      setSessionIdInUrl(sessionId);
      store.setProjectName(villageName);

      try {
        // Fully isolate from the previous conversation before hydrating.
        store.resetSessionState();
        store.setProjectName(villageName);

        const { statusData } = await hydrateSessionSnapshot(sessionId);
        if (statusData.project_name) {
          store.setProjectName(statusData.project_name);
        } else {
          store.setProjectName(villageName);
        }

        store.setSessionId(sessionId);
        setSessionIdInUrl(sessionId);
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Failed to load session');
        store.addMessage(createErrorMessage(`加载历史会话失败：${errorMessage}`));
      } finally {
        usePlanningStore.getState().setPendingHistoricalSessionId(null);
      }
    },
    []
  );

  const deleteSession = useCallback(
    async (sessionId: string, _villageName: string): Promise<boolean> => {
      const store = usePlanningStore.getState();
      store.markSessionsDeleted([sessionId]);
      store.removeSessionFromHistory(sessionId);
      if (store.sessionId === sessionId) {
        clearSessionIdFromUrl();
      }
      // v1: 后端无 DELETE /sessions 端点，删除仅作用于本地历史。
      return true;
    },
    []
  );

  const clearAllHistory = useCallback(async (
    knownSessionIds?: string[],
  ): Promise<{ success: boolean; clearedActiveSession: boolean }> => {
    const store = usePlanningStore.getState();
    const sessionIds = knownSessionIds ?? store.villages.flatMap((village) =>
      village.sessions.map((session) => session.session_id),
    );
    if (sessionIds.length === 0) {
      return { success: true, clearedActiveSession: false };
    }

    store.markSessionsDeleted(sessionIds);
    const clearedActiveSession = Boolean(
      store.sessionId && sessionIds.includes(store.sessionId),
    );
    if (!knownSessionIds) {
      store.clearVillagesHistory();
    }
    // v1: 后端无删除端点，清空仅作用于本地历史。
    return { success: true, clearedActiveSession };
  }, []);

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
    clearSessionIdFromUrl();
    usePlanningStore.getState().resetConversation();
  }, []);

  const sendChatMessage = useCallback(
    async (
      _message: string,
    ): Promise<{ status: string; reply?: string; draft_feedback?: string; dimensions?: string[] }> => {
      const sessionId = usePlanningStore.getState().sessionId;
      if (!sessionId) throw new Error('No session ID');
      // v1: 后端未提供 chat 端点；本地回显并提示，避免调用已删除的 /feedback。
      return {
        status: 'unsupported',
        reply: '对话功能在 v1 暂不可用（后端未提供 chat 端点）。你可以使用人工审核（批准/驳回）推进流程。',
      };
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
      clearAllHistory,
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
      clearAllHistory,
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

  // Delivery + map-layers authoritative projection sync
  useDeliverySync();

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
