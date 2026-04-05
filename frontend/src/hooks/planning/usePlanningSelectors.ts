/**
 * Planning Context Selector Hooks
 *
 * Performance optimization: Provides granular selectors to subscribe to
 * specific state slices instead of the entire state object.
 *
 * Usage:
 * ```tsx
 * // Bad - subscribes to entire state, re-renders on any change
 * const state = usePlanningStore();
 * const messages = state.messages;
 *
 * // Good - only re-renders when messages change
 * const messages = useMessages();
 * ```
 */

import { useMemo } from 'react';
import { usePlanningStore, type PlanningState } from '@/stores/planningStore';
import type { Message, DimensionProgressItem, Checkpoint } from '@/types';
import type { VillageInfo, VillageSession } from '@/lib/api';

// ============================================
// Core State Selectors
// ============================================

/**
 * Select messages array - only re-renders when messages change
 */
export function useMessages(): Message[] {
  return usePlanningStore((state) => state.messages);
}

/**
 * Select status - only re-renders when status changes
 */
export function useStatus(): PlanningState['status'] {
  return usePlanningStore((state) => state.status);
}

/**
 * Select taskId - only re-renders when taskId changes
 */
export function useTaskId(): string | null {
  return usePlanningStore((state) => state.taskId);
}

/**
 * Select projectName - only re-renders when projectName changes
 */
export function useProjectName(): string | null {
  return usePlanningStore((state) => state.projectName);
}

/**
 * Select currentLayer - only re-renders when currentLayer changes
 */
export function useCurrentLayer(): number | null {
  return usePlanningStore((state) => state.currentLayer);
}

/**
 * Select currentPhase - only re-renders when currentPhase changes
 */
export function useCurrentPhase(): PlanningState['currentPhase'] {
  return usePlanningStore((state) => state.currentPhase);
}

/**
 * Select isPaused - only re-renders when isPaused changes
 */
export function useIsPaused(): boolean {
  return usePlanningStore((state) => state.isPaused);
}

/**
 * Select pendingReviewLayer - only re-renders when pendingReviewLayer changes
 */
export function usePendingReviewLayer(): number | null {
  return usePlanningStore((state) => state.pendingReviewLayer);
}

// ============================================
// Dimension Progress Selectors
// ============================================

/**
 * Select all dimension progress - use sparingly, prefer useDimensionProgress
 */
export function useDimensionProgressAll(): Record<string, DimensionProgressItem> {
  return usePlanningStore((state) => state.dimensionProgress);
}

/**
 * Select specific dimension progress by key
 * Only re-renders when that specific dimension's progress changes
 */
export function useDimensionProgress(key: string): DimensionProgressItem | undefined {
  return usePlanningStore((state) => state.dimensionProgress[key]);
}

/**
 * Select executing dimensions array
 */
export function useExecutingDimensions(): string[] {
  return usePlanningStore((state) => state.executingDimensions);
}

/**
 * Check if a specific dimension is executing
 */
export function useIsDimensionExecuting(key: string): boolean {
  return usePlanningStore((state) => state.executingDimensions.includes(key));
}

// ============================================
// Completed Dimensions Selectors
// ============================================

/**
 * Select completed layers status
 */
export function useCompletedLayers(): { 1: boolean; 2: boolean; 3: boolean } {
  return usePlanningStore((state) => state.completedLayers);
}

/**
 * Check if a specific layer is completed
 */
export function useIsLayerCompleted(layer: 1 | 2 | 3): boolean {
  return usePlanningStore((state) => state.completedLayers[layer]);
}

// ============================================
// Reports Selectors
// ============================================

/**
 * Select all reports - use sparingly
 */
export function useReports(): PlanningState['reports'] {
  return usePlanningStore((state) => state.reports);
}

/**
 * Select reports for a specific layer
 */
export function useLayerReports(layer: 1 | 2 | 3): Record<string, string> {
  return usePlanningStore((state) => {
    const layerKey = `layer${layer}` as const;
    return state.reports[layerKey];
  });
}

// ============================================
// Tool Status Selectors
// ============================================

/**
 * Select all tool statuses
 */
export function useToolStatuses(): PlanningState['toolStatuses'] {
  return usePlanningStore((state) => state.toolStatuses);
}

/**
 * Select specific tool status
 */
export function useToolStatus(toolName: string): PlanningState['toolStatuses'][string] | undefined {
  return usePlanningStore((state) => state.toolStatuses[toolName]);
}

/**
 * Get count of running tools
 */
export function useRunningToolsCount(): number {
  const toolStatuses = usePlanningStore((state) => state.toolStatuses);
  return useMemo(() => {
    return Object.values(toolStatuses).filter((t) => t?.status === 'running').length;
  }, [toolStatuses]);
}

// ============================================
// History Selectors
// ============================================

/**
 * Select villages list
 */
export function useVillages(): VillageInfo[] {
  return usePlanningStore((state) => state.villages);
}

/**
 * Select selected village
 */
export function useSelectedVillage(): VillageInfo | null {
  return usePlanningStore((state) => state.selectedVillage);
}

/**
 * Select selected session
 */
export function useSelectedSession(): VillageSession | null {
  return usePlanningStore((state) => state.selectedSession);
}

/**
 * Select history loading state
 */
export function useHistoryLoading(): boolean {
  return usePlanningStore((state) => state.historyLoading);
}

// ============================================
// Checkpoint Selectors
// ============================================

/**
 * Select checkpoints list
 */
export function useCheckpoints(): Checkpoint[] {
  return usePlanningStore((state) => state.checkpoints);
}

/**
 * Select selected checkpoint ID
 */
export function useSelectedCheckpointId(): string | null {
  return usePlanningStore((state) => state.selectedCheckpoint);
}

// ============================================
// UI State Selectors
// ============================================

/**
 * Select view mode
 */
export function useViewMode(): PlanningState['viewMode'] {
  return usePlanningStore((state) => state.viewMode);
}

/**
 * Select progress panel visibility
 */
export function useProgressPanelVisible(): boolean {
  return usePlanningStore((state) => state.progressPanelVisible);
}

/**
 * Select layer report visibility
 */
export function useLayerReportVisible(): boolean {
  return usePlanningStore((state) => state.layerReportVisible);
}

/**
 * Select active report layer
 */
export function useActiveReportLayer(): number {
  return usePlanningStore((state) => state.activeReportLayer);
}

// ============================================
// Compound Selectors (use sparingly)
// ============================================

/**
 * Select planning status info for display
 * Returns status, isPaused, currentPhase, currentLayer
 */
export function usePlanningStatusInfo() {
  const status = usePlanningStore((state) => state.status);
  const isPaused = usePlanningStore((state) => state.isPaused);
  const currentPhase = usePlanningStore((state) => state.currentPhase);
  const currentLayer = usePlanningStore((state) => state.currentLayer);

  return useMemo(
    () => ({
      status,
      isPaused,
      currentPhase,
      currentLayer,
    }),
    [status, isPaused, currentPhase, currentLayer]
  );
}

/**
 * Select progress summary for current layer
 */
export function useProgressSummary(layer: number | null) {
  const completedDimensions = usePlanningStore((state) => state.completedDimensions);
  const executingDimensions = usePlanningStore((state) => state.executingDimensions);

  return useMemo(() => {
    if (!layer) return { completed: 0, total: 0, executing: 0 };

    const layerKey = `layer${layer}` as 'layer1' | 'layer2' | 'layer3';
    const completed = completedDimensions[layerKey]?.length || 0;
    const executing = executingDimensions.filter((k) => k.startsWith(`${layer}_`)).length;

    return { completed, executing };
  }, [layer, completedDimensions, executingDimensions]);
}

// ============================================
// Store Access (for backwards compatibility)
// ============================================

/**
 * Get the full store state (use sparingly, prefer specific selectors)
 */
export function usePlanningState(): PlanningState {
  return usePlanningStore();
}

/**
 * Get store actions
 */
export function usePlanningActions() {
  return usePlanningStore((state) => ({
    setTaskId: state.setTaskId,
    setProjectName: state.setProjectName,
    setStatus: state.setStatus,
    setPhase: state.setPhase,
    addMessage: state.addMessage,
    setMessages: state.setMessages,
    updateLastMessage: state.updateLastMessage,
    clearMessages: state.clearMessages,
    updateDimensionProgress: state.updateDimensionProgress,
    setDimensionStreaming: state.setDimensionStreaming,
    setDimensionCompleted: state.setDimensionCompleted,
    clearDimensionProgress: state.clearDimensionProgress,
    setLayerCompleted: state.setLayerCompleted,
    setReports: state.setReports,
    setCompletedDimensions: state.setCompletedDimensions,
    syncBackendState: state.syncBackendState,
    setViewerVisible: state.setViewerVisible,
    setViewingFile: state.setViewingFile,
    setPaused: state.setPaused,
    setPendingReviewLayer: state.setPendingReviewLayer,
    setVillageFormData: state.setVillageFormData,
    setProgressPanelVisible: state.setProgressPanelVisible,
    setStepMode: state.setStepMode,
    setVillages: state.setVillages,
    setSelectedVillage: state.setSelectedVillage,
    setSelectedSession: state.setSelectedSession,
    setHistoryLoading: state.setHistoryLoading,
    setHistoryError: state.setHistoryError,
    setCheckpoints: state.setCheckpoints,
    setSelectedCheckpoint: state.setSelectedCheckpoint,
    setToolStatus: state.setToolStatus,
    clearToolStatus: state.clearToolStatus,
    handleSSEEvent: state.handleSSEEvent,
    resetConversation: state.resetConversation,
    initConversation: state.initConversation,
  }));
}