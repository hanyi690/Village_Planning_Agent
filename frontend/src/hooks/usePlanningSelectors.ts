/**
 * Planning Context Selector Hooks
 *
 * Performance optimization: Provides granular selectors to subscribe to
 * specific state slices instead of the entire state object.
 *
 * Usage:
 * ```tsx
 * // Bad - subscribes to entire state, re-renders on any change
 * const { state } = usePlanningContext();
 * const messages = state.messages;
 *
 * // Good - only re-renders when messages change
 * const messages = useMessages();
 * ```
 */

import { useMemo } from 'react';
import { usePlanningContext, PlanningState } from '@/providers/PlanningProvider';
import type { Message, DimensionProgressItem, Checkpoint } from '@/types';
import type { VillageInfo, VillageSession } from '@/lib/api';

// ============================================
// Core State Selectors
// ============================================

/**
 * Select messages array - only re-renders when messages change
 */
export function useMessages(): Message[] {
  const { state } = usePlanningContext();
  return state.messages;
}

/**
 * Select status - only re-renders when status changes
 */
export function useStatus(): PlanningState['status'] {
  const { state } = usePlanningContext();
  return state.status;
}

/**
 * Select taskId - only re-renders when taskId changes
 */
export function useTaskId(): string | null {
  const { state } = usePlanningContext();
  return state.taskId;
}

/**
 * Select projectName - only re-renders when projectName changes
 */
export function useProjectName(): string | null {
  const { state } = usePlanningContext();
  return state.projectName;
}

/**
 * Select currentLayer - only re-renders when currentLayer changes
 */
export function useCurrentLayer(): number | null {
  const { state } = usePlanningContext();
  return state.currentLayer;
}

/**
 * Select currentPhase - only re-renders when currentPhase changes
 */
export function useCurrentPhase(): PlanningState['currentPhase'] {
  const { state } = usePlanningContext();
  return state.currentPhase;
}

/**
 * Select isPaused - only re-renders when isPaused changes
 */
export function useIsPaused(): boolean {
  const { state } = usePlanningContext();
  return state.isPaused;
}

/**
 * Select pendingReviewLayer - only re-renders when pendingReviewLayer changes
 */
export function usePendingReviewLayer(): number | null {
  const { state } = usePlanningContext();
  return state.pendingReviewLayer;
}

// ============================================
// Dimension Progress Selectors
// ============================================

/**
 * Select all dimension progress - use sparingly, prefer useDimensionProgress
 */
export function useDimensionProgressAll(): Record<string, DimensionProgressItem> {
  const { state } = usePlanningContext();
  return state.dimensionProgress;
}

/**
 * Select specific dimension progress by key
 * Only re-renders when that specific dimension's progress changes
 */
export function useDimensionProgress(key: string): DimensionProgressItem | undefined {
  const { state } = usePlanningContext();
  return state.dimensionProgress[key];
}

/**
 * Select executing dimensions array
 */
export function useExecutingDimensions(): string[] {
  const { state } = usePlanningContext();
  return state.executingDimensions;
}

/**
 * Check if a specific dimension is executing
 */
export function useIsDimensionExecuting(key: string): boolean {
  const { state } = usePlanningContext();
  return state.executingDimensions.includes(key);
}

// ============================================
// Completed Dimensions Selectors
// ============================================

/**
 * Select completed layers status
 */
export function useCompletedLayers(): { 1: boolean; 2: boolean; 3: boolean } {
  const { state } = usePlanningContext();
  return state.completedLayers;
}

/**
 * Check if a specific layer is completed
 */
export function useIsLayerCompleted(layer: 1 | 2 | 3): boolean {
  const { state } = usePlanningContext();
  return state.completedLayers[layer];
}

// ============================================
// Reports Selectors
// ============================================

/**
 * Select all reports - use sparingly
 */
export function useReports(): PlanningState['reports'] {
  const { state } = usePlanningContext();
  return state.reports;
}

/**
 * Select reports for a specific layer
 */
export function useLayerReports(layer: 1 | 2 | 3): Record<string, string> {
  const { state } = usePlanningContext();
  const layerKey = `layer${layer}` as const;
  return state.reports[layerKey];
}

// ============================================
// Tool Status Selectors
// ============================================

/**
 * Select all tool statuses
 */
export function useToolStatuses(): PlanningState['toolStatuses'] {
  const { state } = usePlanningContext();
  return state.toolStatuses;
}

/**
 * Select specific tool status
 */
export function useToolStatus(toolName: string): PlanningState['toolStatuses'][string] | undefined {
  const { state } = usePlanningContext();
  return state.toolStatuses[toolName];
}

/**
 * Get count of running tools
 */
export function useRunningToolsCount(): number {
  const { state } = usePlanningContext();
  return useMemo(() => {
    return Object.values(state.toolStatuses).filter(t => t?.status === 'running').length;
  }, [state.toolStatuses]);
}

// ============================================
// History Selectors
// ============================================

/**
 * Select villages list
 */
export function useVillages(): VillageInfo[] {
  const { state } = usePlanningContext();
  return state.villages;
}

/**
 * Select selected village
 */
export function useSelectedVillage(): VillageInfo | null {
  const { state } = usePlanningContext();
  return state.selectedVillage;
}

/**
 * Select selected session
 */
export function useSelectedSession(): VillageSession | null {
  const { state } = usePlanningContext();
  return state.selectedSession;
}

/**
 * Select history loading state
 */
export function useHistoryLoading(): boolean {
  const { state } = usePlanningContext();
  return state.historyLoading;
}

// ============================================
// Checkpoint Selectors
// ============================================

/**
 * Select checkpoints list
 */
export function useCheckpoints(): Checkpoint[] {
  const { state } = usePlanningContext();
  return state.checkpoints;
}

/**
 * Select selected checkpoint ID
 */
export function useSelectedCheckpointId(): string | null {
  const { state } = usePlanningContext();
  return state.selectedCheckpoint;
}

// ============================================
// UI State Selectors
// ============================================

/**
 * Select view mode
 */
export function useViewMode(): PlanningState['viewMode'] {
  const { state } = usePlanningContext();
  return state.viewMode;
}

/**
 * Select progress panel visibility
 */
export function useProgressPanelVisible(): boolean {
  const { state } = usePlanningContext();
  return state.progressPanelVisible;
}

/**
 * Select layer report visibility
 */
export function useLayerReportVisible(): boolean {
  const { state } = usePlanningContext();
  return state.layerReportVisible;
}

/**
 * Select active report layer
 */
export function useActiveReportLayer(): number {
  const { state } = usePlanningContext();
  return state.activeReportLayer;
}

// ============================================
// Compound Selectors (use sparingly)
// ============================================

/**
 * Select planning status info for display
 * Returns status, isPaused, currentPhase, currentLayer
 */
export function usePlanningStatusInfo() {
  const { state } = usePlanningContext();
  return useMemo(() => ({
    status: state.status,
    isPaused: state.isPaused,
    currentPhase: state.currentPhase,
    currentLayer: state.currentLayer,
  }), [state.status, state.isPaused, state.currentPhase, state.currentLayer]);
}

/**
 * Select progress summary for current layer
 */
export function useProgressSummary(layer: number | null) {
  const { state } = usePlanningContext();
  return useMemo(() => {
    if (!layer) return { completed: 0, total: 0, executing: 0 };

    const layerKey = `layer${layer}` as 'layer1' | 'layer2' | 'layer3';
    const completed = state.completedDimensions[layerKey]?.length || 0;
    const executing = state.executingDimensions.filter(k => k.startsWith(`${layer}_`)).length;

    return { completed, executing };
  }, [layer, state.completedDimensions, state.executingDimensions]);
}

// Export all selectors
export {
  usePlanningContext,
  usePlanningContextOptional,
} from '@/providers/PlanningProvider';