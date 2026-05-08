/**
 * Planning Feature Hooks
 *
 * React hooks for planning state management, SSE connection,
 * and message handling.
 */

// SSE Connection
export { useSSEConnection } from './useSSE';

// Selectors
export {
  useMessages,
  useStatus,
  useTaskId,
  useProjectName,
  useCurrentLayer,
  useCurrentPhase,
  useIsPaused,
  usePendingReviewLayer,
  useDimensionProgressAll,
  useDimensionProgress,
  useExecutingDimensions,
  useIsDimensionExecuting,
  useCompletedLayers,
  useIsLayerCompleted,
  useReports,
  useLayerReports,
  useToolStatuses,
  useToolStatus,
  useRunningToolsCount,
  useVillages,
  useSelectedVillage,
  useSelectedSession,
  useHistoryLoading,
  useCheckpoints,
  useSelectedCheckpointId,
  useViewMode,
  useProgressPanelVisible,
  useLayerReportVisible,
  useActiveReportLayer,
  usePlanningStatusInfo,
  useProgressSummary,
  usePlanningState,
  useStoreActions,
} from './useSelectors';

// Handlers
export { usePlanningHandlers } from './useHandlers';

// Streaming
export { useStreamingText, useStreamingAccumulator } from './useStreaming';

// Persistence & Session
export { useMessagePersistence } from './usePersistence';
export { useSessionRestore } from './useSessionRestore';