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

import { useEffect, useCallback, ReactNode, useState } from 'react';
import { usePlanningStore, type PlanningState } from '@/stores/planningStore';
import { useSSEConnection, useMessagePersistence, useSessionRestore } from '@/hooks/planning';
import {
  planningApi,
  dataApi,
  VillageInfo,
  VillageSession,
} from '@/lib/api';
import { createSystemMessage, getErrorMessage } from '@/lib/utils';
import { logger } from '@/lib/logger';
import { PLANNING_DEFAULTS } from '@/config/planning';
import type { PlanningParams, Checkpoint, Message } from '@/types';
import type { VillageInputData } from '@/components/VillageInputForm';

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

  const startPlanning = useCallback(async (params: PlanningParams) => {
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
      });

      if (!response || typeof response.task_id !== 'string') {
        throw new Error('Server response missing task ID');
      }

      store.setTaskId(response.task_id);
      store.setStatus('planning');
      store.addMessage(
        createSystemMessage(`Planning started. Task ID: ${response.task_id.slice(0, 8)}...`)
      );
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, 'Unknown error');
      logger.context.error('Planning failed to start', { error: errorMessage });
      store.setStatus('failed');
      throw error;
    }
  }, [store]);

  const approve = useCallback(async () => {
    if (!store.taskId) throw new Error('No task ID');
    await planningApi.approveReview(store.taskId);
    store.setPaused(false);
    store.setPendingReviewLayer(null);
  }, [store]);

  const reject = useCallback(async (feedback: string, dimensions?: string[]) => {
    if (!store.taskId) throw new Error('No task ID');
    await planningApi.rejectReview(store.taskId, feedback, dimensions);
    store.setPaused(false);
  }, [store]);

  const rollback = useCallback(async (checkpointId: string) => {
    if (!store.taskId) throw new Error('No task ID');
    await planningApi.rollbackCheckpoint(store.taskId, checkpointId);
    store.setSelectedCheckpoint(checkpointId);

    // Sync state after rollback
    const statusData = await planningApi.getStatus(store.taskId);
    store.syncBackendState(statusData);

    store.addMessage(
      createSystemMessage(`Rolled back to checkpoint ${checkpointId.slice(0, 8)}...`)
    );
  }, [store]);

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

  const selectVillage = useCallback((village: VillageInfo) => {
    store.setSelectedVillage(village);
  }, [store]);

  const selectSession = useCallback((session: VillageSession) => {
    store.setSelectedSession(session);
  }, [store]);

  const loadHistoricalSession = useCallback(async (villageName: string, sessionId: string) => {
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
  }, [store]);

  const deleteSession = useCallback(async (sessionId: string, villageName: string): Promise<boolean> => {
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
  }, [store, loadVillagesHistory]);

  const showViewer = useCallback(() => {
    store.setViewerVisible(true);
  }, [store]);

  const hideViewer = useCallback(() => {
    store.setViewerVisible(false);
  }, [store]);

  const showFileViewer = useCallback((file: Parameters<typeof store.setViewingFile>[0]) => {
    store.setViewingFile(file as Parameters<typeof store.setViewingFile>[0]);
    store.setViewerVisible(true);
  }, [store]);

  const hideFileViewer = useCallback(() => {
    store.setViewingFile(null);
    store.setViewerVisible(false);
  }, [store]);

  const resetConversation = useCallback(() => {
    store.resetConversation();
  }, [store]);

  const sendChatMessage = useCallback(async (message: string) => {
    if (!store.taskId) throw new Error('No task ID');
    return planningApi.sendChatMessage(store.taskId, message);
  }, [store]);

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
    setMessages: store.setMessages,
  };
}

// Helper to transform backend messages
function transformBackendMessages(messages: unknown[]): Message[] {
  return messages.map((msg: unknown) => {
    const m = msg as Record<string, unknown>;
    const baseMsg = {
      id: (m.message_id as string) || `db-${m.id}`,
      timestamp: new Date((m.created_at as string) || Date.now()),
      role: (m.role || 'assistant') as 'user' | 'assistant' | 'system',
      created_at: m.created_at as string | undefined,
    };

    const msgMeta = (m.message_metadata || m.metadata || {}) as Record<string, unknown>;

    switch (m.message_type) {
      case 'dimension_report':
        return {
          ...baseMsg,
          type: 'dimension_report' as const,
          layer: (msgMeta.layer as number) || 1,
          dimensionKey: (msgMeta.dimensionKey as string) || '',
          dimensionName: (msgMeta.dimensionName as string) || '',
          content: (m.content as string) || '',
          streamingState: (msgMeta.streamingState as 'streaming' | 'completed' | 'error') || 'completed',
          wordCount: (msgMeta.wordCount as number) || ((m.content as string)?.length || 0),
          previousContent: msgMeta.previousContent as string | undefined,
          revisionVersion: msgMeta.revisionVersion as number | undefined,
          isRevision: msgMeta.isRevision as boolean | undefined,
        };

      case 'layer_completed':
        return {
          ...baseMsg,
          type: 'layer_completed' as const,
          layer: (msgMeta.layer as number) || 1,
          content: (m.content as string) || '',
          summary: (msgMeta.summary as { word_count: number; key_points: string[] }) || { word_count: 0, key_points: [] },
          fullReportContent: msgMeta.fullReportContent as string | undefined,
          dimensionReports: msgMeta.dimensionReports as Record<string, string> | undefined,
          actions: [],
        };

      case 'file':
        return {
          ...baseMsg,
          type: 'file' as const,
          filename: (msgMeta.filename as string) || '',
          fileContent: (msgMeta.fileContent as string) || '',
          fileSize: msgMeta.fileSize as number | undefined,
          encoding: msgMeta.encoding as string | undefined,
        };

      case 'progress':
        return {
          ...baseMsg,
          type: 'progress' as const,
          content: (m.content as string) || '',
          progress: (msgMeta.progress as number) || 0,
          currentLayer: msgMeta.currentLayer as string | undefined,
          taskId: msgMeta.taskId as string | undefined,
        };

      case 'tool_call':
        return {
          ...baseMsg,
          type: 'tool_call' as const,
          toolName: (msgMeta.toolName as string) || '',
          toolDisplayName: (msgMeta.toolDisplayName as string) || '',
          description: (msgMeta.description as string) || '',
          estimatedTime: msgMeta.estimatedTime as number | undefined,
          stage: msgMeta.stage as string | undefined,
        };

      case 'tool_progress':
        return {
          ...baseMsg,
          type: 'tool_progress' as const,
          toolName: (msgMeta.toolName as string) || '',
          stage: (msgMeta.stage as string) || '',
          progress: (msgMeta.progress as number) || 0,
          message: (msgMeta.message as string) || '',
        };

      case 'tool_result':
        return {
          ...baseMsg,
          type: 'tool_result' as const,
          toolName: (msgMeta.toolName as string) || '',
          status: (msgMeta.status as 'success' | 'error') || 'success',
          summary: (msgMeta.summary as string) || '',
          displayHints: msgMeta.displayHints as { primary_view?: 'text' | 'table' | 'map' | 'chart' | 'json'; priority_fields?: string[] } | undefined,
          dataPreview: msgMeta.dataPreview as string | undefined,
          stages: msgMeta.stages as { name: string; status: 'pending' | 'running' | 'success' | 'error'; progress: number; message: string }[] | undefined,
        };

      default:
        return {
          ...baseMsg,
          type: 'text' as const,
          content: (m.content as string) || '',
        };
    }
  });
}

// ============================================
// Provider Component
// ============================================

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

  // Session restore from URL taskId
  useSessionRestore();

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

  return <>{children}</>;
}

// ============================================
// Exports
// ============================================

export { usePlanningStore } from '@/stores/planningStore';
export type { PlanningState } from '@/stores/planningStore';