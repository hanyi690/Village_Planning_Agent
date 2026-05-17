// ============================================
// API Types - 统一类型定义
// ============================================

// Import from existing message-types to avoid duplication
import type { EmbeddedImage } from '@/types/message/message-types';

export { EmbeddedImage };

/**
 * 统一 API 响应格式
 * 提供一致的错误处理和类型安全
 */
export interface APIResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
  request_id?: string;
}

export interface ApiError {
  message?: string;
  detail?: string;
}

// ============================================
// Backend Image Types (snake_case)
// ============================================

/**
 * Backend embedded image (snake_case)
 */
export interface BackendEmbeddedImage {
  image_base64: string;
  image_format: string;
  thumbnail_base64: string;
  image_width: number;
  image_height: number;
}

// ============================================
// Multimodal Image Types
// ============================================

/**
 * Image source type for multimodal messages
 */
export type ImageSourceType = 'upload' | 'embedded';

/**
 * Image data for multimodal API requests
 */
export interface ImageData {
  image_base64: string;
  image_format: string;
  source_type: ImageSourceType;
  source_filename?: string;
  width?: number;
  height?: number;
}

/**
 * Backend image data (snake_case)
 */
export interface BackendImageData {
  image_base64: string;
  image_format: string;
  source_type: ImageSourceType;
  source_filename?: string;
  width?: number;
  height?: number;
}

// ============================================
// Village & Session Types
// ============================================

export interface VillageInfo {
  name: string;
  display_name: string;
  session_count: number;
  sessions: VillageSession[];
}

export interface VillageSession {
  session_id: string;
  timestamp: string;
  checkpoint_count: number;
  has_final_report: boolean;
}

export interface Checkpoint {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
}

export interface LayerContent {
  content: string;
  layer: string;
  session?: string;
  timestamp?: string;
  checkpoint_id?: string;
}

// ============================================
// SSE Types
// ============================================

/**
 * SSE Event type union for better type safety
 */
export type PlanningSSEEventType =
  // Tool Events (NEW System)
  | 'tool_started'
  | 'tool_status'
  // Tool Events (Legacy - kept for compatibility)
  | 'tool_call'
  | 'tool_progress'
  | 'tool_result'
  // Layer & Dimension Events
  | 'layer_started'
  | 'layer_completed'
  | 'dimension_start'
  | 'dimension_complete'
  | 'dimension_error'
  | 'dimension_delta'
  | 'dimension_revised'
  | 'dimension_reset'
  | 'dimension_reset_complete'
  // Progress Events
  | 'progress'
  | 'checkpoint_saved'
  | 'pause'
  | 'resumed'
  | 'completed'
  | 'complete'
  | 'error'
  // Streaming Events
  | 'text_chunk'
  | 'content_delta'
  | 'ai_response_delta'
  | 'ai_response_complete'
  | 'thinking_start'
  | 'thinking'
  | 'thinking_end'
  | 'stream_paused'
  // Review Events
  | 'review_request'
  // RAG & Cascade Events (Demo System)
  | 'rag_query'
  | 'rag_result'
  | 'gis_result'
  | 'cascade_impact'
  | 'cascade_complete'
  // State Events
  | 'state_sync'
  | 'layer_paused'
  | 'connected';

/**
 * SSE Event 数据基础类型
 * 使用具体类型替代 unknown 索引签名
 */
export interface PlanningSSEDataBase {
  progress?: number;
  current_layer?: number;
  layer_number?: number;
  layer_name?: string;
  message?: string;
  result?: SSEEventResult;
  error?: string;
  review_id?: string;
  title?: string;
  content?: string;
  status?: string;
  chunk?: string;
  message_id?: string;
  state?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
  delta?: string;
  accumulated?: string;
  dimension?: string;
  timestamp?: number;
  // 维度相关字段
  dimension_key?: string;
  dimension_name?: string;
  layer?: number;
  has_data?: boolean;
  dimension_count?: number;
  total_chars?: number;
  full_content?: string;
  dimension_reports?: Record<string, string>;
  // RAG 相关字段
  query?: string;
  total_results?: number;
  documents?: Array<{
    title?: string;
    snippet?: string;
    source?: string;
    score?: number;
  }>;
}

/**
 * SSE Event result 类型定义
 */
export interface SSEEventResult {
  status?: string;
  message?: string;
  data?: unknown;
  [key: string]: unknown;
}

export interface PlanningSSEEvent {
  type: PlanningSSEEventType;
  session_id?: string;
  data: PlanningSSEDataBase;
}

// ============================================
// Request/Response Types
// ============================================

export interface StartPlanningRequest {
  project_name: string;
  village_data: string;
  village_name?: string;
  task_description?: string;
  constraints?: string;
  enable_review?: boolean;
  step_mode?: boolean;
  need_human_review?: boolean;
  stream_mode?: boolean;
  input_mode?: 'file' | 'text';
  images?: ImageData[];
  villageDataFiles?: File[];
  taskFiles?: File[];
  constraintFiles?: File[];
}

export interface StartPlanningResponse {
  session_id: string;
  stream_url: string;
  status: string;
}

/** @deprecated 使用 FeedbackRequest 替代 */
export interface ReviewActionRequest {
  action: 'approve' | 'reject' | 'rollback';
  feedback?: string;
  dimensions?: string[];
  checkpoint_id?: string;
  review_id?: string;
  images?: ImageData[];
}

export interface FeedbackRequest {
  feedback?: string;
  dimensions?: string[];
  message?: string;
  approve?: boolean;
  images?: ImageData[];
}

export interface SessionStatusResponse {
  session_id: string;
  status: string;
  created_at: string;
  execution_error: string | null;
  version?: number;

  // Agent State (Single Source of Truth)
  phase: string;
  current_wave: number;
  // Note: reports 不再从后端同步，前端通过 SSE 或 API 获取
  completed_dimensions: {
    layer1: string[];
    layer2: string[];
    layer3: string[];
  };
  pause_after_step: boolean;
  previous_layer: number;
  step_mode: boolean;
  execution_paused: boolean;

  // Other metadata
  current_layer: number;
  progress: number | null;
  last_checkpoint_id: string;
  execution_complete: boolean;
  checkpoints?: Checkpoint[];

  // Messages
  messages?: Array<{
    type: string;
    content: string;
    role: string;
  }>;
  revision_history?: Array<{
    dimension: string;
    layer: number;
    old_content: string;
    new_content: string;
    feedback: string;
    timestamp: string;
  }>;
  ui_messages?: UIMessage[];
}

/**
 * UI 消息类型（用于持久化存储）
 */
export interface UIMessage {
  id: number;
  session_id: string;
  message_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  message_type: string;
  message_metadata?: Record<string, unknown>;
  created_at?: string;
  timestamp: string;
}

/**
 * 维度报告响应类型
 */
export interface DimensionReportResponse {
  session_id: string;
  dimension_key: string;
  layer: number;
  content: string;
}

/**
 * 知识来源项类型
 */
export interface KnowledgeSourceItem {
  title: string;
  snippet: string;
  source?: string;
  score?: number;
  matched_query?: string;
}

/**
 * RAG 检索切片（后端 RetrievedChunk 格式）
 */
export interface RetrievedChunk {
  chunk_id: string;
  content_preview: string;
  source: string;
  score: number;
  dimension_tags: string[];
}

/**
 * RAG 检索日志（后端 RAGRetrievalLog 格式）
 */
export interface RAGRetrievalLog {
  dimension_key: string;
  query: string;
  query_generation_method: string;
  retrieved_chunks: RetrievedChunk[];
  total_results: number;
  retrieval_latency_ms: number;
  context_length: number;
  context_truncated: boolean;
  rag_enabled: boolean;
  skip_reason: string;
}

/**
 * 层级报告响应类型
 */
export interface LayerReportsResponse {
  layer: number;
  reports: Record<string, {
    content: string;
    knowledge_sources?: RAGRetrievalLog | KnowledgeSourceItem[];
  }>;
  report_content: string;
  project_name: string;
  completed: boolean;
  stats: {
    dimension_count: number;
    total_chars: number;
  };
}

export interface FileUploadResponse {
  content: string;
  encoding: string;
  size: number;
  fileType?: 'document' | 'image';
  imageBase64?: string;
  imageFormat?: string;
  thumbnailBase64?: string;
  imageWidth?: number;
  imageHeight?: number;
  embeddedImages?: EmbeddedImage[];
}

/**
 * Backend raw response type (snake_case) for file upload
 * Used internally for type-safe conversion
 */
export interface BackendFileUploadResponse {
  content: string;
  encoding: string;
  size: number;
  file_type?: 'document' | 'image';
  image_base64?: string;
  image_format?: string;
  thumbnail_base64?: string;
  image_width?: number;
  image_height?: number;
  embedded_images?: BackendEmbeddedImage[];
}

// ============================================
// Review Types
// ============================================

/**
 * ReviewData 类型 - 用于 ReviewDrawer
 */
export interface ReviewData {
  current_layer: number;
  content: string;
  summary: {
    word_count: number;
    dimension_count?: number;
  };
  available_dimensions: string[];
  checkpoints: Checkpoint[];
}

// ============================================
// Report Comparison Types
// ============================================

/**
 * 维度版本历史项
 */
export interface DimensionVersion {
  version: number;
  layer: number;
  created_at: string;
  reason: string | null;
}

/**
 * 跨会话报告响应
 */
export interface CrossSessionReport {
  project_name: string;
  session_id: string;
  dimension_key: string;
  layer: number;
  content: string;
  version?: number;
  created_at?: string;
  knowledge_sources?: KnowledgeSourceItem[];
}

/**
 * 对比会话信息
 */
export interface CompareSession {
  id: string;
  name: string;
  timestamp: string;
  isCompleted: boolean;
}
