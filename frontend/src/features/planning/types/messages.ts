/**
 * Specific Message Type Definitions
 * 特定消息类型定义
 *
 * This file contains all specific message type implementations that extend BaseMessage.
 * Each type represents a different kind of message in the conversational UI.
 */

import type { BaseMessage, ActionButton, KnowledgeReference } from './base';

// ============================================================================
// Core Message Types (实际使用的5种类型)
// ============================================================================

/**
 * Embedded image from document
 */
export interface EmbeddedImage {
  imageBase64: string;
  imageFormat: string;
  thumbnailBase64: string;
  imageWidth: number;
  imageHeight: number;
}

/**
 * Knowledge Source - 知识库切片信息
 */
export interface KnowledgeSource {
  source: string;      // 文档来源
  page: number;        // 页码
  doc_type: string;    // 文档类型
  content: string;     // 内容预览
}

/**
 * Text Message - Standard text content with optional streaming, images and knowledge references
 */
export interface TextMessage extends BaseMessage {
  type: 'text';
  content: string;
  // Streaming support
  streamingState?: 'idle' | 'streaming' | 'paused' | 'completed';
  streamingContent?: string;
  // Multimodal images
  images?: ImageAttachment[];
  // RAG knowledge references
  knowledgeReferences?: KnowledgeReference[];
}

/**
 * Image Attachment - Multimodal image for TextMessage
 */
export interface ImageAttachment {
  base64: string;
  format: string;
  width?: number;
  height?: number;
}

/**
 * File Message - File upload/download messages
 */
export interface FileMessage extends BaseMessage {
  type: 'file';
  filename: string;
  fileContent: string;
  fileSize?: number;
  encoding?: string;
  fileType?: 'document' | 'image';
  imageBase64?: string;
  imageFormat?: string;
  thumbnailBase64?: string;
  imageWidth?: number;
  imageHeight?: number;
  embeddedImages?: EmbeddedImage[];
}

/**
 * Progress Message - Task progress updates
 */
export interface ProgressMessage extends BaseMessage {
  type: 'progress';
  content: string;
  progress: number;
  currentLayer?: string;
  taskId?: string;
}

/**
 * GIS Analysis Data - GIS 分析数据
 */
export interface GISAnalysisData {
  overallScore?: number;
  suitabilityLevel?: string;
  sensitivityClass?: string;
  recommendations?: string[];
}

/**
 * GIS Data for Dimension Report - 维度报告的 GIS 数据
 */
export interface GISData {
  layers?: GISLayerConfig[];
  mapOptions?: {
    center: [number, number];
    zoom: number;
  };
  analysisData?: GISAnalysisData;
}

/**
 * Dimension Report Message - Real-time streaming dimension report content
 */
export interface DimensionReportMessage extends BaseMessage {
  type: 'dimension_report';
  layer: number;
  dimensionKey: string;
  dimensionName: string;
  content: string;
  streamingState: 'streaming' | 'completed' | 'error';
  wordCount: number;
  progress?: {
    current: number;
    total: number;
  };
  // 修复相关字段：用于显示修复前后对比
  previousContent?: string;
  revisionVersion?: number;
  isRevision?: boolean;
  // GIS 数据
  gisData?: GISData;
  // 知识库切片
  knowledgeSources?: KnowledgeSource[];
}

/**
 * Layer Completed Message - Shown when a planning layer is completed
 */
export interface DimensionStructuredSummary {
  dimension_key?: string;
  layer?: number;
  word_count?: number;
  key_points?: string[];
  text_summary?: string;
  metrics?: Record<string, unknown>;
}

export interface LayerCompletedMessage extends BaseMessage {
  type: 'layer_completed';
  layer: number;
  content: string;
  summary: {
    word_count: number;
    key_points: string[];
    dimension_count?: number;
    dimension_names?: string[];
  };
  fullReportContent?: string;
  dimensionReports?: Record<string, string>;
  actions: ActionButton[];
  // GIS
  dimensionGisData?: Record<string, GISData>;
  // Knowledge sources
  dimensionKnowledgeSources?: Record<string, KnowledgeSource[]>;
  // Structured summaries
  dimensionSummaries?: Record<string, DimensionStructuredSummary>;
}

// ============================================================================
// Tool Status Message (合并 tool_call/progress/result)
// ============================================================================

/**
 * Tool Execution Status - 工具执行状态类型
 */
export type ToolExecutionStatus = 'pending' | 'running' | 'success' | 'error';

/**
 * Tool Status Message - Unified tool execution status
 */
export interface ToolStatusMessage extends BaseMessage {
  type: 'tool_status';
  toolName: string;
  toolDisplayName: string;
  description: string;
  status: ToolExecutionStatus;
  progress?: number;
  stage?: string;
  stageMessage?: string;
  summary?: string;
  error?: string;
  startedAt?: string;
  completedAt?: string;
  estimatedTime?: number;
}

// ============================================================================
// GIS Result Messages (GIS 分析结果消息类型)
// ============================================================================

/**
 * GeoJSON Feature - 单个地理要素
 */
export interface GeoJsonFeature {
  type: 'Feature';
  geometry: {
    type: 'Point' | 'LineString' | 'Polygon' | 'MultiPoint' | 'MultiLineString' | 'MultiPolygon';
    coordinates: unknown;
  };
  properties?: Record<string, unknown>;
}

/**
 * GeoJSON FeatureCollection - 地理要素集合
 */
export interface GeoJsonFeatureCollection {
  type: 'FeatureCollection';
  features: GeoJsonFeature[];
}

/**
 * GIS Layer Configuration - 图层配置
 */
export interface GISLayerConfig {
  geojson: GeoJsonFeatureCollection;
  layerType: 'boundary' | 'function_zone' | 'facility_point' | 'development_axis' | 'sensitivity_zone' | 'isochrone' | 'infrastructure';
  layerName: string;
  color?: string; // Backend sends color at top level
  style?: {
    fillColor?: string;
    fillOpacity?: number;
    color?: string;
    weight?: number;
  };
}

/**
 * GIS Result Message - GIS 分析结果消息
 */
export interface GisResultMessage extends BaseMessage {
  type: 'gis_result';
  dimensionKey: string;
  dimensionName: string;
  summary: string;
  layers: GISLayerConfig[];
  mapOptions?: {
    center: [number, number];
    zoom: number;
  };
  analysisData?: {
    overallScore?: number;
    suitabilityLevel?: string;
    sensitivityClass?: string;
    recommendations?: string[];
  };
}

// ============================================================================
// Message Union Type
// ============================================================================

/**
 * Message - Union type of all message types
 */
export type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | DimensionReportMessage
  | LayerCompletedMessage
  | ToolStatusMessage
  | GisResultMessage;

// ============================================================================
// SSE Event Types (for helpers)
// ============================================================================

/**
 * SSE Event Result
 */
export interface SSEEventResult {
  status?: string;
  message?: string;
  data?: unknown;
  [key: string]: unknown;
}

/**
 * SSE Event
 */
export interface SSEEvent {
  event_type?: string;
  status?: string;
  progress?: number;
  current_layer?: string;
  message?: string;
  task_id?: string;
  result?: SSEEventResult;
  error?: string;
}
