/**
 * Planning Feature Types
 *
 * Unified type definitions for the planning feature.
 * Combines message types, SSE event types, and state types.
 */

// Message Types
export type {
  BaseMessage,
  MessageRole,
  KnowledgeReference,
  Checkpoint,
  RevisionItem,
  DimensionProgressItem,
  DimensionStatus,
  ActionButton,
  SSEEventResult,
  SSEEvent,
  ConversationState,
  PlanningParams,
  Message,
  EmbeddedImage,
  KnowledgeSource,
  ImageAttachment,
  TextMessage,
  FileMessage,
  ProgressMessage,
  DimensionReportMessage,
  LayerCompletedMessage,
  ToolStatusMessage,
  GisResultMessage,
} from './messages';

// GIS Types
export type {
  GISAnalysisData,
  GISData,
  GISLayerConfig,
  GeoJsonFeature,
  GeoJsonFeatureCollection,
  ToolExecutionStatus,
} from './messages';

// SSE Event Types (new)
export type { GisLayerUpdateEvent, SSEEventType } from './events';

// Re-export guards and helpers
export {
  isTextMessage,
  isFileMessage,
  isProgressMessage,
  isDimensionReportMessage,
  isLayerCompletedMessage,
  isToolStatusMessage,
  isGisResultMessage,
  getMessageType,
} from './guards';

export {
  createBaseMessage,
  buildLayerReportId,
  buildRevisionReportId,
  buildDimensionProgressKey,
  formatDimensionReportsAsContent,
  calculateReportSummary,
} from './helpers';