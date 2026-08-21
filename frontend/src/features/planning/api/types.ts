// ============================================
// API Types - 统一类型定义
// ============================================

// Import from existing message-types to avoid duplication
import type { EmbeddedImage, GeoJsonFeatureCollection } from '@/types/message/message-types';

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

export interface PersistedHistoryResponse {
  schema_version: '1.0';
  projects: VillageInfo[];
}

/** Catalog-backed current GIS context. Planned layers never use this DTO. */
export interface CurrentSourceLayer {
  source_name: string;
  source_layer_type: string;
  layer_type: string;
  layer_name: string;
  display_role: string;
  data_authority: 'authoritative_current';
  requirement: 'baseline' | 'mandatory' | 'conditional' | 'reference';
  crs: string;
  feature_count: number;
  geojson: GeoJsonFeatureCollection;
  metadata: Record<string, unknown>;
}

export interface CurrentSourceRaster {
  source_name: string;
  layer_name: string;
  layer_type: 'dem' | 'dom';
  format: string;
  crs: string;
  available: boolean;
  resolution: number | null;
  width: number | null;
  height: number | null;
  bands: number | null;
  dtype: string;
  bounds: Record<string, number>;
  source_ref: string;
  reason: string;
}

export interface CurrentSourceLayerCollection {
  schema_version: '1.0';
  village_name: string;
  source: 'data_catalog';
  center: number[] | null;
  layers: CurrentSourceLayer[];
  rasters: CurrentSourceRaster[];
  diagnostics: string[];
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
 * 只包含后端已实现的事件类型
 */
export type PlanningSSEEventType =
  // Connection Events
  | 'connected'
  | 'heartbeat'
  | 'error'
  // Layer Events
  | 'layer_started'
  | 'layer_completed'
  | 'layer_paused'
  | 'execution_resumed'
  // Dimension Events
  | 'dimension_start'
  | 'dimension_complete'
  | 'dimension_delta'
  // Progress Events
  | 'resync_required'
  | 'checkpoint_saved'
  | 'pause'
  | 'resumed'
  | 'completed'
  | 'revision_completed'
  // Tool Events (NEW System)
  | 'tool_started'
  | 'tool_status'
  // Tool Events (Legacy - kept for compatibility)
  | 'tool_call'
  | 'tool_progress'
  | 'tool_result'
  // AI Response Events
  | 'ai_response_delta'
  | 'ai_response_complete'
  // GIS & RAG Events
  | 'gis_result'
  | 'gis_layer_update'
  | 'rag_result'
  // Cascade Events
  | 'cascade_impact'
  | 'cascade_complete'
  // Settings Events
  | 'rag_config_updated'
  | 'step_mode_updated'
  // HITL Events
  | 'human_review_paused';

/**
 * 后端未实现的SSE事件类型 - 保留用于向后兼容或未来实现
 * @deprecated 这些事件类型后端尚未实现，请勿在生产代码中使用
 */
export type DeprecatedSSEEventType =
  // Dimension Events (未实现)
  | 'dimension_error'
  | 'dimension_revised'
  // Progress Events (未实现)
  | 'progress'
  // Streaming Events (未实现)
  | 'text_chunk'
  | 'content_delta'
  | 'thinking_start'
  | 'thinking'
  | 'thinking_end'
  // Review Events (未实现)
  | 'review_request'
  // RAG & Cascade Events (未实现)
  | 'rag_query'
  // State Events (未实现)
  | 'state_sync'
  // Legacy (未实现)
  | 'complete';

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
  // 维度相关字段 (snake_case - 通用维度事件)
  dimension_key?: string;
  dimension_name?: string;
  // 维度相关字段 (camelCase - GIS 事件，后端 Pydantic schema 输出)
  dimensionKey?: string;
  dimensionName?: string;
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
    matched_query?: string;
    chunk_id?: string;
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
  province?: string;
  city?: string;
  county?: string;
  township?: string;
  planning_period?: string;
  task_description?: string;
  constraints?: string;
  enable_review?: boolean;
  step_mode?: boolean;
  need_human_review?: boolean;
  stream_mode?: boolean;
  input_mode?: 'file' | 'text';
  // RAG Configuration
  rag_enabled?: boolean;       // 是否启用RAG检索
  rag_layer_config?: string;   // RAG层级配置 (JSON string)
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

/**
 * Side-chat transcript item restored from a backend status payload.
 */
export interface ChatHistoryMessage {
  id: string;
  type: 'text';
  role: 'user' | 'assistant';
  source: 'chat';
  content: string;
  timestamp: string;
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
  // v1 SessionProjection fields (authoritative)
  delivery_status?: 'complete' | 'partial' | 'diagnostic_only' | 'no_planning_output' | null;
  statutory_complete?: boolean;
  human_review_pending?: boolean;
  last_event_seq?: number;
  active_stage?: string;
  // 遗留/可选字段：后端 v1 /state 不再下发，仅当旧兼容数据存在时使用（Phase 2 下线）
  gis_generation_id?: string;
  gis_generation_status?: string;
  gis_generation_error?: string;
  gis_layout_configs?: Array<Record<string, unknown>>;
  chat_history?: ChatHistoryMessage[];
  // Note: reports 不再从后端同步，前端通过 SSE 或 API 获取
  completed_dimensions: {
    layer1: string[];
    layer2: string[];
    layer3: string[];
  };
  previous_layer: number;
  step_mode: boolean;
  interrupt_info?: {
    event_id?: string;
    channel?: 'step_mode' | 'post_l3_review' | string;
    layer?: number;
    phase?: string;
    layer_name?: string;
    reason?: string;
    paused_stage?: string;
    items?: HumanReviewItem[];
    error_feedback?: Record<string, string>;
  };

  rag_enabled?: boolean;
  rag_layer_config?: Record<number, boolean>;

  // Other metadata
  current_layer: number;
  progress: number | null;
  last_checkpoint_id: string;
  execution_complete: boolean;
  checkpoints?: Checkpoint[];

  // 项目上下文（用于页面刷新后恢复）
  project_name?: string;
  village_name?: string;
  province?: string;
  city?: string;
  county?: string;
  township?: string;
  planning_period?: string;

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
  dimension_key: string;
  report_id: string;
  summary: string;
  generated_at: string;
  revision_trigger: string | null;
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

// ============================================
// Export Types
// ============================================

// ============================================
// Planning Text Types
// ============================================

/**
 * Planning text document
 */
export interface PlanningTextDocument {
  id: number;
  session_id: string;
  version: number;
  document_id: string;
  markdown_content: string;
  json_content?: Record<string, unknown>;
  article_count: number;
  generated_at: string;
  generation_duration_seconds?: number;
  status: 'pending' | 'generating' | 'completed' | 'failed';
  error_message?: string;
  trigger_reason?: 'initial' | 'dimension_change' | 'manual';
  changed_dimensions?: string[];
}

/**
 * Planning text version metadata
 */
export interface PlanningTextVersion {
  id: number;
  version: number;
  document_id: string;
  article_count: number;
  generated_at: string;
  generation_duration_seconds?: number;
  status: string;
  trigger_reason?: string;
  changed_dimensions?: string[];
}

/**
 * Planning text version list response
 */
export interface PlanningTextVersionList {
  session_id: string;
  versions: PlanningTextVersion[];
  total: number;
}

/**
 * Generate planning text request
 */
export interface GeneratePlanningTextRequest {
  trigger_reason?: 'initial' | 'dimension_change' | 'manual';
  changed_dimensions?: string[];
  use_llm?: boolean;
}

/**
 * Generate planning text response
 */
export interface GeneratePlanningTextResponse {
  session_id: string;
  version: number;
  document_id: string;
  markdown_content: string;
  article_count: number;
  generated_at: string;
  generation_duration_seconds: number;
  status: string;
  trigger_reason: string;
}

// ============================================
// Settings API Types
// ============================================

export interface RagConfigRequest {
  rag_enabled?: boolean;
  rag_layer_config?: Record<number, boolean>;
}

export interface RagConfigResponse {
  session_id: string;
  rag_enabled: boolean;
  rag_layer_config: Record<number, boolean>;
}

export interface StepModeRequest {
  step_mode: boolean;
}

export interface StepModeResponse {
  session_id: string;
  step_mode: boolean;
}

// ============================================
// Geocode Types
// ============================================

export interface GeocodeResponse {
  location: string;
  center: [number, number] | null;
  strategy: string | null;
  boundary_geojson?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface GisDataUploadResponse {
  file_id: number;
  filename: string;
  data_type: string | null;
  feature_count: number;
  parse_status: string;
}

// ============================================
// Artifact (typed pipeline artifacts) Types
// ============================================

export type ArtifactType =
  | 'L1Snapshot'
  | 'L2Strategy'
  | 'PlanningProgram'
  | 'IntentCompilationResult'
  | 'GroundingResult'
  | 'SiteSelectionDecision'
  | 'ExecutionPlan'
  | 'ParcelChangeSet'
  | 'PlannedState'
  | 'ValidationReport'
  | 'ReconciliationReport'
  | 'DeliveryManifest';

export interface ArtifactRef {
  context_version: string;
  artifact_id: string;
  module: string;
  run_id: string;
  artifact_type: string;
  revision: string;
}

export interface ArtifactListResponse {
  session_id: string;
  artifacts: ArtifactRef[];
  count: number;
}

export interface ArtifactResponse {
  session_id: string;
  artifact_type: string;
  revision: string;
  artifact_ref: ArtifactRef;
  payload: Record<string, unknown>;
  manifest: Record<string, unknown>;
}

export interface ArtifactRefResponse {
  session_id: string;
  artifact_type: string;
  revision: string;
  artifact_ref: ArtifactRef;
  manifest: Record<string, unknown>;
}

// ============================================
// Render Layers Types
// ============================================

export interface RenderLayer {
  layerType: string;
  layerName: string;
  data: {
    type: 'FeatureCollection';
    features: Array<{ type: 'Feature'; geometry: unknown; properties: Record<string, unknown> }>;
  };
}

export interface RenderLayersResponse {
  session_id: string;
  layers: RenderLayer[];
  snapshot_checksum?: string;
  delivery_status?: 'complete' | 'partial' | 'diagnostic_only' | 'no_planning_output' | null;
}

export interface PositioningTraceStep {
  id?: number | string;
  session_id?: string;
  stage: string;
  step_name?: string;
  dimension_key?: string;
  layer?: number;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  artifacts?: Array<Record<string, unknown>>;
  diagnostics?: Record<string, unknown>;
  timestamp?: string;
}

export interface PositioningTraceResponse {
  session_id: string;
  stages: string[];
  stage_coverage: Record<string, boolean>;
  complete: boolean;
  by_dimension: Record<string, PositioningTraceStep[]>;
  reports: PositioningTraceStep[];
}

export interface PlanningDependencyNode {
  key: string;
  name: string;
  layer: 1 | 2 | 3;
  wave: number;
  depends_on: string[];
}

export interface PlanningDependencyEdge {
  source: string;
  target: string;
  kind: 'same_layer' | 'layer' | 'phase';
}

export interface PlanningDependencyGraphResponse {
  schema_version: string;
  source: string;
  dimensions: PlanningDependencyNode[];
  edges: PlanningDependencyEdge[];
}

// Unified Evidence Query contracts are generated from the backend OpenAPI.
export type {
  EvidenceFeatureRef,
  EvidenceQueryRequest,
  EvidenceQueryResponse,
} from './v1-types';

// ============================================
// Delivery Projection Types (v1)
// ============================================
// 权威来源：docs/contracts/openapi-v1.json（openapi-typescript 生成），
// 手写副本已删除，避免与后端契约漂移。

export type DeliveryStatus = 'complete' | 'partial' | 'diagnostic_only';

export type { DeliveryProjection } from './v1-types';

// ============================================
// Human Review (HITL) Types
// ============================================

export interface HumanReviewItem {
  request_id: string;
  stage: string;
  request_type: string;
  context?: Record<string, unknown>;
}

export interface HumanReviewListResponse {
  session_id: string;
  post_l3_status: string;
  paused_stage?: string;
  event_id?: string;
  interrupt_info?: {
    event_id?: string;
    channel?: string;
    reason?: string;
    paused_stage?: string;
  } | null;
  pending_items: HumanReviewItem[];
  count: number;
}

export interface HumanReviewResolveRequest {
  decisions: Record<string, unknown>;
  event_id?: string;
}

export interface HumanReviewResolveResponse {
  session_id: string;
  resolved: boolean;
  result: Record<string, unknown>;
}
