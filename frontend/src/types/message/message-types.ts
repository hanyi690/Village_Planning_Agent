/**
 * Specific Message Type Definitions
 * 特定消息类型定义
 *
 * This file contains all specific message type implementations that extend BaseMessage.
 * Each type represents a different kind of message in the conversational UI.
 */

import type { BaseMessage, ActionButton, KnowledgeReference } from './index';

// ============================================================================
// Core Message Types (实际使用的5种类型)
// ============================================================================

/**
 * Text Message - Standard text content with optional streaming and knowledge references
 */
export interface TextMessage extends BaseMessage {
  type: 'text';
  content: string;
  // Streaming support
  streamingState?: 'idle' | 'streaming' | 'paused' | 'completed';
  streamingContent?: string; // 当前已显示的内容
  // RAG知识引用
  knowledgeReferences?: KnowledgeReference[];
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
  // ✅ 修复相关字段：用于显示修复前后对比
  previousContent?: string; // 修复前的原始内容
  revisionVersion?: number; // 版本号
  isRevision?: boolean; // 是否是修复后的报告
}

/**
 * Layer Completed Message - Shown when a planning layer is completed
 */
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
}

// ============================================================================
// Tool Execution Messages (工具执行相关消息类型)
// ============================================================================

/**
 * Tool Execution Status - 工具执行状态类型
 */
export type ToolExecutionStatus = 'pending' | 'running' | 'success' | 'error';

/**
 * Tool Stage - 工具执行阶段
 */
export interface ToolStage {
  name: string;
  status: ToolExecutionStatus;
  progress: number;
  message: string;
}

/**
 * Tool Display Hints - 前端渲染提示
 */
export interface ToolDisplayHints {
  primary_view?: 'text' | 'table' | 'map' | 'chart' | 'json';
  priority_fields?: string[];
}

/**
 * Tool Call Message - 工具调用开始
 */
export interface ToolCallMessage extends BaseMessage {
  type: 'tool_call';
  toolName: string;
  toolDisplayName: string;
  description: string;
  estimatedTime?: number;
  stage?: string;
}

/**
 * Tool Progress Message - 工具执行进度
 */
export interface ToolProgressMessage extends BaseMessage {
  type: 'tool_progress';
  toolName: string;
  stage: string;
  progress: number;
  message: string;
}

/**
 * Tool Result Message - 工具执行结果
 */
export interface ToolResultMessage extends BaseMessage {
  type: 'tool_result';
  toolName: string;
  status: 'success' | 'error';
  summary: string;
  displayHints?: ToolDisplayHints;
  dataPreview?: string;
  stages?: ToolStage[];
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
  layerType: 'function_zone' | 'facility_point' | 'development_axis' | 'sensitivity_zone' | 'isochrone';
  layerName: string;
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
