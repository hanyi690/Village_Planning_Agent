// ============================================
// API Types - 统一类型定义
// ============================================

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
// Embedded Image Types
// ============================================

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
  | 'layer_started'
  | 'dimension_start'
  | 'dimension_error'
  | 'layer_completed'
  | 'checkpoint_saved'
  | 'pause'
  | 'progress'
  | 'completed'
  | 'error'
  | 'resumed'
  | 'dimension_delta'
  | 'dimension_complete'
  | 'dimension_revised'
  | 'complete'
  | 'text_chunk'
  | 'thinking_start'
  | 'thinking'
  | 'thinking_end'
  | 'review_request'
  | 'content_delta'
  | 'stream_paused'
  | 'connected'
  | 'tool_call'
  | 'tool_progress'
  | 'tool_result'
  | 'ai_response_delta'
  | 'ai_response_complete';

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
  layer?: number;
  has_data?: boolean;
  dimension_count?: number;
  total_chars?: number;
  full_content?: string;
  dimension_reports?: Record<string, string>;
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
}

export interface StartPlanningResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface ReviewActionRequest {
  action: 'approve' | 'reject' | 'rollback';
  feedback?: string;
  dimensions?: string[];
  checkpoint_id?: string;
  review_id?: string;
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
  reports: {
    layer1: Record<string, string>;
    layer2: Record<string, string>;
    layer3: Record<string, string>;
  };
  pause_after_step: boolean;
  previous_layer: number;
  step_mode: boolean;

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
 * 层级报告响应类型
 */
export interface LayerReportsResponse {
  layer: number;
  reports: Record<string, string>;
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
// Knowledge Base Types
// ============================================

export interface KnowledgeDocument {
  source: string;
  chunk_count: number;
  doc_type: string;
  // 元数据字段（新增）
  dimension_tags?: string[];
  terrain?: string;
  regions?: string[];
  category?: string;
}

export interface KnowledgeStats {
  total_documents: number;
  total_chunks: number;
  vector_db_path: string;
  source_dir: string;
}

export interface AddDocumentResponse {
  status: string;
  message: string;
  source?: string;
  chunksAdded?: number;
}

/**
 * Backend raw response type (snake_case) for add document
 * Used internally for type-safe conversion
 */
export interface BackendAddDocumentResponse {
  status: string;
  message: string;
  source?: string;
  chunks_added?: number;
}

export interface AddDocumentOptions {
  category?: string;
  doc_type?: string;
  dimension_tags?: string[];
  terrain?: string;
  regions?: string[];
}

export interface SyncResponse {
  status: string;
  message: string;
  addedCount?: number;
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