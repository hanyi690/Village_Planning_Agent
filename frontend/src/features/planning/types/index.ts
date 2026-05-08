/**
 * Planning Feature Types
 *
 * Unified type definitions for the planning feature.
 * Combines message types, SSE event types, and state types.
 */

// Base Types (from base.ts)
export type {
  BaseMessage,
  MessageRole,
  KnowledgeReference,
  Checkpoint,
  RevisionItem,
  DimensionProgressItem,
  DimensionStatus,
  ActionButton,
  PlanningParams,
} from './base';

// Message Types (from messages.ts)
export type {
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
  Message,
  SSEEvent,
  SSEEventResult,
  GISAnalysisData,
  GISData,
  GISLayerConfig,
  GeoJsonFeature,
  GeoJsonFeatureCollection,
  ToolExecutionStatus,
} from './messages';

// SSE Event Types (from events.ts)
export type { GisLayerUpdateEvent, SSEEventType } from './events';

// Re-export guards (from guards.ts)
export {
  isUserMessage,
  isTextMessage,
  isFileMessage,
  isProgressMessage,
  isDimensionReportMessage,
  isLayerCompletedMessage,
  isToolStatusMessage,
  isGisResultMessage,
} from './guards';

// Note: createBaseMessage, buildLayerReportId, etc. are in @/lib/utils/message-helpers.ts
// Import directly from there if needed