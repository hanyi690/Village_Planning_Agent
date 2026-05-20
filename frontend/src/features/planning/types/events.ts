/**
 * SSE Event Types
 *
 * Server-Sent Events type definitions for planning workflow.
 * Includes new GIS layer update events.
 */

// SSE Event Types
export type SSEEventType =
  | 'dimension_start'
  | 'dimension_delta'
  | 'dimension_complete'
  | 'layer_started'
  | 'layer_completed'
  | 'tool_call'
  | 'tool_progress'
  | 'tool_result'
  | 'gis_layer_update'  // NEW: GIS layer update event
  | 'progress'
  | 'status'
  | 'error'
  | 'message'
  | 'checkpoint'
  | 'review_request';

/**
 * GIS Layer Update Event
 *
 * Sent when GIS analysis produces new layer data.
 * Frontend should directly update map without REST API call.
 */
export interface GisLayerUpdateEvent {
  type: 'gis_layer_update';
  layer: number;           // Planning layer (1, 2, 3)
  dimension_key: string;   // Dimension identifier
  dimension_name: string;  // Human-readable name
  layers: import('./messages').GISLayerConfig[];
  mapOptions?: {
    center: [number, number];
    zoom: number;
  };
  analysisData?: import('./messages').GISAnalysisData;
}

/**
 * All SSE Event Data Types
 */
export type SSEEventData =
  | GisLayerUpdateEvent
  | DimensionStartData
  | DimensionDeltaData
  | DimensionCompleteData
  | LayerStartedData
  | LayerCompletedData
  | ToolCallData
  | ToolProgressData
  | ToolResultData
  | ProgressData
  | StatusData
  | ErrorData
  | MessageData
  | CheckpointData
  | ReviewRequestData;

// Event data interfaces
export interface DimensionStartData {
  layer: number;
  dimension_key: string;
  dimension_name: string;
}

export interface DimensionDeltaData {
  layer: number;
  dimension_key: string;
  chunk: string;
  accumulated: string;
  word_count: number;
}

export interface DimensionCompleteData {
  layer: number;
  dimension_key: string;
  dimension_name: string;
  content: string;
  word_count: number;
  gis_data?: import('./messages').GISData;
  knowledge_sources?: import('./messages').KnowledgeSource[];
  structured_summary?: DimensionStructuredSummary;
}

export interface DimensionStructuredSummary {
  dimension_key: string;
  layer: number;
  word_count: number;
  key_points: string[];
  text_summary: string;
  metrics: Record<string, unknown>;
}

export interface LayerStartedData {
  layer: number;
  phase: string;
}

export interface LayerCompletedData {
  layer: number;
  content: string;
  summary: {
    word_count: number;
    key_points: string[];
    dimension_count?: number;
    dimension_names?: string[];
  };
  dimension_reports?: Record<string, string>;
  dimension_gis_data?: Record<string, import('./messages').GISData>;
}

export interface ToolCallData {
  tool_name: string;
  tool_display_name: string;
  description: string;
}

export interface ToolProgressData {
  tool_name: string;
  progress: number;
  stage?: string;
  stage_message?: string;
}

export interface ToolResultData {
  tool_name: string;
  status: 'success' | 'error';
  summary?: string;
  error?: string;
}

export interface ProgressData {
  progress: number;
  current_layer?: number;
  message?: string;
}

export interface StatusData {
  status: string;
  phase?: string;
  layer?: number;
}

export interface ErrorData {
  error: string;
  code?: string;
  details?: unknown;
}

export interface MessageData {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface CheckpointData {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
  type?: 'key' | 'regular';
}

export interface ReviewRequestData {
  layer: number;
  content: string;
  dimensions: string[];
}