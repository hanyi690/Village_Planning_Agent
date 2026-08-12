/**
 * Planning Feature Hooks
 *
 * React hooks for planning state management, SSE connection,
 * and message handling.
 */

// SSE Connection
export { useSSEConnection } from "./useSSE";

// Selectors
export {
  useMessages,
  useStatus,
  useSessionId,
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
  // NEW: RAG & Cascade Selectors
  useDimensionRagSources,
  useAllRagSources,
  useCascadeChain,
  useRevisionCompletedKeys,
  useStreamingContent,
  useRunningTools,
  useIsToolRunning,
  // GIS
  useGisLayers,
  useHasGisLayers,
  useGisLayersByType,
} from "./useSelectors";

// Handlers
export { usePlanningHandlers } from "./useHandlers";

// Streaming
export { useStreamingText, useStreamingAccumulator } from "./useStreaming";

// Approval
export { useApprovalActions } from "./useApprovalActions";

// Delivery & map-layers (v1 authoritative projection sync)
export { useDeliverySync } from "./useDelivery";

// Persistence & Session
export { useMessagePersistence } from "./usePersistence";
export { useSessionRestore } from "./useSessionRestore";

// Analysis progress
export { useActiveAnalysisFocus } from "./useActiveAnalysisFocus";
export type { ActiveAnalysisFocus, AnalysisFocusPhase } from "./useActiveAnalysisFocus";
export { usePlanningBootstrapStage } from "./usePlanningBootstrapStage";
export type { PlanningBootstrapStage, PlanningBootstrapStep } from "./usePlanningBootstrapStage";
export { useAnalysisCompletion } from "./useAnalysisCompletion";
