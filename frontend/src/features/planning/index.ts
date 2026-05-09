/**
 * Planning Feature
 *
 * Feature-based module for village planning workflow.
 * Includes state management, hooks, components, and API.
 */

// Store
export {
  usePlanningStore,
  PlanningProvider,
  usePlanningActions,
  type PlanningState,
  type PlanningActions,
} from './store';

// Hooks
export {
  useSSEConnection,
  useMessages,
  useStatus,
  useTaskId,
  useProjectName,
  useCurrentLayer,
  useCurrentPhase,
  useIsPaused,
  useDimensionProgressAll,
  useDimensionProgress,
  useExecutingDimensions,
  useCompletedLayers,
  useReports,
  useToolStatuses,
  useRunningToolsCount,
  useVillages,
  useSelectedVillage,
  useSelectedSession,
  useHistoryLoading,
  useCheckpoints,
  useViewMode,
  useProgressSummary,
  usePlanningState,
  useStoreActions,
  usePlanningHandlers,
  useStreamingText,
  useStreamingAccumulator,
  useMessagePersistence,
  useSessionRestore,
  // NEW: RAG & Cascade Selectors
  useDimensionRagSources,
  useAllRagSources,
  useCascadeChain,
  useDimensionVersions,
  useDimensionVersion,
  useStreamingContent,
  useResettingDimensions,
  useIsDimensionResetting,
  useRunningTools,
  useIsToolRunning,
} from './hooks';

// Types
export type {
  Message,
  BaseMessage,
  TextMessage,
  FileMessage,
  ProgressMessage,
  DimensionReportMessage,
  LayerCompletedMessage,
  ToolStatusMessage,
  GisResultMessage,
  Checkpoint,
  DimensionProgressItem,
  DimensionStatus,
  GISLayerConfig,
  GISData,
  PlanningParams,
  SSEEvent,
} from './types';

// Config
export {
  DIMENSION_NAMES,
  DIMENSION_ICONS,
  DIMENSIONS_BY_LAYER,
  getDimensionName,
  getDimensionIcon,
  getDimensionsByLayer,
  PLANNING_DEFAULTS,
  PARAM_MAPPING,
} from './config';

// API
export { planningApi, dataApi, gisApi, fileApi, knowledgeApi } from './api';

// Components (optional - usually imported directly)
// export * from './components';