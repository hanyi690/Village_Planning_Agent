/**
 * Planning Store - Zustand + Immer State Management
 *
 * This is the single source of truth for planning state.
 * Replaces Context + useReducer from PlanningProvider.
 *
 * Features:
 * - Immer middleware for mutable-style updates
 * - Granular selectors for optimal re-render performance
 * - SSE event handling with batch optimization
 */

import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import type {
  Message,
  DimensionProgressItem,
  DimensionStatus,
  Checkpoint,
  FileMessage,
  LayerCompletedMessage,
  DimensionReportMessage,
  KnowledgeSource,
} from "../types";
import type {
  GisResultMessage,
  ToolStatusMessage,
  GISLayerConfig,
} from "@/types/message/message-types";

import { createErrorMessage } from "../utils";
import { normalizeGisLayers } from "../utils/gis-normalize";
import {
  isSpatialWorkflowPhase,
  isL3HumanReview,
  pausedStageToLayer,
} from "../utils/spatial-phase";
import type { HumanReviewItem, HumanReviewListResponse } from "../api/types";
import {
  loadDeletedSessionIds,
  saveDeletedSessionIds,
} from "@/features/planning/utils/deleted-sessions-storage";

export type LlmHealthStatus =
  | 'offline_template'
  | 'connection_error'
  | 'arrears'
  | 'api_error';

function classifyLlmHealthMessage(message: string): {
  status: LlmHealthStatus;
  text: string;
} | null {
  const text = message.trim();
  if (!text) return null;
  const lower = text.toLowerCase();
  if (
    lower.includes('arrearage')
    || lower.includes('overdue payment')
    || text.includes('欠费')
    || text.includes('账户状态')
  ) {
    return {
      status: 'arrears',
      text: '大模型账户欠费或状态异常，请检查阿里云百炼余额后重启分析。',
    };
  }
  if (text.includes('API Key 无效') || text.includes('401') || lower.includes('invalid_api_key')) {
    return {
      status: 'api_error',
      text: '大模型 API Key 无效或已过期，请更新 .env 中的 OPENAI_API_KEY 后重启后端。',
    };
  }
  if (lower.includes('connection error') || text.includes('连接失败') || text.includes('APIConnectionError')) {
    return {
      status: 'connection_error',
      text: '无法连接大模型服务，请检查网络、并发设置或账户状态后重试。',
    };
  }
  if (text.includes('LLM 不可用') || text.includes('非 LLM 深度分析') || text.includes('本地规划规则')) {
    return {
      status: 'offline_template',
      text: '部分报告由离线模板生成，非真实 LLM 分析。修复模型配置后请新建会话重新分析。',
    };
  }
  return null;
}

function applyLlmHealthFromMessage(state: PlanningState, message: string): void {
  const classified = classifyLlmHealthMessage(message);
  if (!classified || state.llmHealthDismissed) return;
  state.llmHealthStatus = classified.status;
  state.llmHealthMessage = classified.text;
}

function scanReportsForOfflineTemplates(state: PlanningState): void {
  if (state.llmHealthDismissed) return;
  for (const layerKey of ['layer1', 'layer2', 'layer3'] as const) {
    const layerReports = state.reports[layerKey] || {};
    for (const content of Object.values(layerReports)) {
      if (typeof content === 'string' && content.includes('LLM 不可用')) {
        applyLlmHealthFromMessage(state, content);
        return;
      }
    }
  }
}

// Pipeline trace types (mirrors backend trace.py)
export interface ParseTrace {
  source: string;
  llm_model: string;
  llm_prompt: string;
  llm_response: string;
  llm_retry_count: number;
  correction_round: boolean;
  correction_prompt: string;
  correction_response: string;
  anchors: Record<string, unknown>;
  anchor_confidence: string;
  semantic_validation_passed: boolean;
  semantic_violations: string[];
  timing_ms: number;
}

export interface KGTrace {
  built: boolean;
  parcel_count: number;
  triple_count: number;
  constraint_count: number;
  indicator_count: number;
  adjacency_edge_count: number;
  triples_sample: Record<string, unknown>[];
  constraints_detail: Record<string, unknown>;
  timing_ms: number;
}

export interface ConflictTrace {
  metric_conflicts: Record<string, unknown>[];
  constraint_violations: Record<string, unknown>[];
  resolution_applied: Record<string, unknown>[];
  timing_ms: number;
}

export interface MIPTrace {
  mode: string;
  solver_status: string;
  variable_count: number;
  binary_variable_count: number;
  objective_value: number;
  time_limit_seconds: number;
  zone_targets: Record<string, number>;
  zone_actual: Record<string, number>;
  zone_deviations: Record<string, number>;
  kg_slack_values: Record<string, number>;
  adjacency_pairs: number;
  changed_parcels: number;
  changed_pct: number;
  timing_ms: number;
}

export interface ValidationRound {
  round_number: number;
  total_violations: number;
  violations: Record<string, unknown>[];
  adjustments: Record<string, number>;
  damping: number;
  timing_ms: number;
}

export interface ValidationLoopTrace {
  rounds: ValidationRound[];
  final_status: string;
}

export interface PipelineTrace {
  parse?: ParseTrace;
  kg?: KGTrace;
  conflicts?: ConflictTrace;
  mip?: MIPTrace;
  validation?: ValidationLoopTrace;
  total_timing_ms: number;
}
import type { VillageInputData } from "../components/VillageInputForm";
import type {
  VillageInfo,
  VillageSession,
  SessionStatusResponse,
} from "../api";
import {
  getLayerPhase,
  PlanningStatus,
  LayerPhase,
  AgentPhase,
  NAV_KEYS,
  normalizePlanningStatus,
} from "@/features/planning/constants";
import type { NavigationKey } from "@/features/planning/constants";

export type ProcessPanelTab = "messages" | "map" | "history" | "settings";
import {
  createBaseMessage,
  buildLayerReportId,
  buildRevisionReportId,
  buildDimensionProgressKey,
  formatDimensionReportsAsContent,
  calculateReportSummary,
} from "@/features/planning/utils/message-helpers";
import {
  DIMENSION_NAMES,
  getDimensionsByLayer,
  getDimensionLayer,
} from "../config/dimensions";
import {
  getHighestActiveLayer,
  layerHasActivity,
} from "../utils/step-mode-review";

// ============================================
// State Types
// ============================================

type Status = PlanningStatus;

interface Reports {
  layer1: Record<string, string>;
  layer2: Record<string, string>;
  layer3: Record<string, string>;
}

interface CompletedDimensions {
  layer1: string[];
  layer2: string[];
  layer3: string[];
}

interface ToolStatus {
  toolName: string;
  status: "running" | "success" | "error";
  stage?: string;
  progress?: number;
  message?: string;
  summary?: string;
}

// ============================================
// RAG & Cascade Types (New for Demo System)
// ============================================

/**
 * RAG document source for dimension analysis
 */
interface RagDocument {
  title: string;
  snippet: string;
  source?: string;
  score?: number;
  chunk_id?: string;
  matched_query?: string; // 匹配的查询语句
}

/**
 * RAG sources tracked per dimension
 */
interface DimensionRagSource {
  query: string;
  documents: RagDocument[];
}

/**
 * Cascade repair chain visualization
 */
interface CascadeChain {
  trigger: string;
  impacted: string[];
}

// Internal event type for store handling
interface StoreEvent {
  type: string;
  data?: unknown;
}

export interface PlanningState {
  conversationId: string;

  // Session
  sessionId: string | null;
  projectName: string | null;
  // 行政区划和规划期限（从后端恢复）
  villageName?: string;
  province?: string;
  city?: string;
  county?: string;
  township?: string;
  planningPeriod?: string;
  status: Status;
  /** Backend-authoritative active stage used to prevent stale event replay from claiming later layers are done. */
  authoritativeActiveStage: string | null;

  // Agent State (Single Source of Truth)
  phase: string;
  currentWave: number;
  reports: Reports;
  previous_layer: number;
  step_mode: boolean;
  interruptInfo?: {
    layer?: number;
    phase?: string;
    layer_name?: string;
    reason?: string;
  };

  // Derived UI State
  completedDimensions: CompletedDimensions;
  currentLayer: number | null;
  currentPhase: LayerPhase | "修复中";
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  isPaused: boolean;
  pendingReviewLayer: number | null;
  lastPauseLayer: number;

  // SSE Reconnect
  sseResumeTrigger: number;
  lastProcessedSeq: number;

  // Messages
  messages: Message[];

  // Revision draft generated by right-side AI assistant
  revisionDraft: { feedback: string; dimensions: string[] } | null;
  /** Bumped after dimension revision completes to trigger planning-text regen */
  planningTextRegenRequest: { token: number; changedDimensions?: string[] } | null;

  /** Persistent LLM health banner (offline template / API errors) */
  llmHealthStatus: LlmHealthStatus | null;
  llmHealthMessage: string | null;
  llmHealthDismissed: boolean;

  // Progress
  dimensionProgress: Record<string, DimensionProgressItem>;
  executingDimensions: string[];
  layerDimensionCount: Record<number, number>;

  // ============================================
  // NEW: RAG & Cascade Tracking (Demo System)
  // ============================================
  /** RAG sources per dimension key (e.g., "1_resource_endowment") */
  dimensionRagSources: Record<string, DimensionRagSource>;
  /** Current cascade repair chain being displayed */
  cascadeChain: CascadeChain | null;
  /** Dimensions that have completed revision (format: "layer_dimKey", e.g., "1_resource_endowment") */
  revisionCompletedKeys: string[];
  /** Streaming text content per dimension (temporary) */
  streamingContent: Record<string, string>;
  /** Simplified running tool names (replaces full toolStatuses) */
  runningTools: string[];

  // UI State
  viewerVisible: boolean;
  referencedSection?: string;
  viewingFile: FileMessage | null;
  viewMode: "WELCOME_FORM" | "SESSION_ACTIVE";
  villageFormData: VillageInputData | null;
  progressPanelVisible: boolean;
  layerReportVisible: boolean;
  activeReportLayer: number;

  // History
  villages: VillageInfo[];
  /** Client-side tombstones so deleted sessions do not reappear after refresh/sync */
  deletedSessionIds: Record<string, true>;
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  historyLoading: boolean;
  historyError: string | null;
  /** Blocks URL auto-restore while sidebar history navigation is hydrating. */
  pendingHistoricalSessionId: string | null;

  // Checkpoints
  checkpoints: Checkpoint[];
  selectedCheckpoint: string | null;
  loadingContent: boolean;
  deletingSessionId: string | null;

  // Tools (kept for backward compatibility, but runningTools is preferred)
  toolStatuses: Record<string, ToolStatus>;

  // GIS Layers (SSE-driven, no REST API needed)
  gisLayers: Record<string, GISLayerConfig[]>;

  // Pipeline trace (full process recording for parse→layout→validate)
  pipelineTrace: PipelineTrace | null;

  // Three-Panel Layout Navigation State
  selectedNavigationKey: NavigationKey | null;
  isRightPanelExpanded: boolean;
  isLeftNavCollapsed: boolean;

  // ProcessPanel
  processPanelTab: ProcessPanelTab;

  // ============================================
  // NEW: Layer-level RAG Configuration
  // ============================================
  /** Layer-level RAG switch config: { 1: true, 2: false, 3: true } */
  ragLayerConfig: Record<number, boolean>;

  // GIS state
  gisGenerating: boolean;
  isFullMapOpen: boolean;
  gisTriggerPending: boolean;
  villageCenter?: [number, number];

  // ============================================
  // Delivery & Artifact (v1 authoritative projections)
  // ============================================
  /** Delivery projection: available, delivery_status, statutory_complete, snapshot_checksum */
  delivery: {
    available: boolean;
    delivery_status: 'complete' | 'partial' | 'diagnostic_only' | 'no_planning_output' | null;
    statutory_complete: boolean;
    snapshot_checksum: string;
    deferral_summary: Record<string, unknown>;
    diagnostic_summary: Record<string, unknown>;
    deliverables: Array<Record<string, unknown>>;
    downloads: string[];
  } | null;
  /** True when a resync_required event was received and full REST recovery is needed. */
  resyncRequired: boolean;
  /** Human review state from /human-review (event_id is the optimistic lock). */
  humanReview: {
    event_id: string | null;
    paused_stage: string;
    items: HumanReviewItem[];
  } | null;
}

// ============================================
// Helper Functions
// ============================================

/**
 * Phase to Layer mapping
 *
 * 与后端 _phase_to_layer 函数对应，但前端 completed 返回 3（显示最终层级报告）
 *
 * Note: 前端不支持详细版 phase（如 layer1_analyzing），因为前端接收的 SSE 事件
 * 只包含简化版 phase。详细版 phase 仅用于后端内部状态管理。
 */
function phaseToLayer(phase: string): number | null {
  const mapping: Record<string, number> = {
    [AgentPhase.INIT]: 0,
    [AgentPhase.LAYER1]: 1,
    [AgentPhase.LAYER2]: 2,
    [AgentPhase.LAYER3]: 3,
    [AgentPhase.COMPLETED]: 3, // 前端显示最终层级报告
  };
  return mapping[phase] ?? null;
}

function deriveCompletedDimensions(
  reports: Reports,
  existing: CompletedDimensions,
  dimensionProgress: Record<string, DimensionProgressItem>,
): CompletedDimensions {
  const layerKeys = ['layer1', 'layer2', 'layer3'] as const;
  const result: CompletedDimensions = { layer1: [], layer2: [], layer3: [] };

  for (const layerKey of layerKeys) {
    const layerNum = Number(layerKey.replace('layer', ''));
    const dims = new Set<string>(existing[layerKey] || []);

    for (const [dimKey, content] of Object.entries(reports[layerKey] || {})) {
      if (typeof content === 'string' && content.trim().length > 0) {
        dims.add(dimKey);
      }
    }

    for (const progress of Object.values(dimensionProgress)) {
      if (
        progress.layer === layerNum
        && progress.status === 'completed'
        && progress.dimensionKey
      ) {
        dims.add(progress.dimensionKey);
      }
    }

    result[layerKey] = Array.from(dims);
  }

  return result;
}

function shallowEqualCompletedDimensions(
  incoming: CompletedDimensions,
  current: CompletedDimensions,
): boolean {
  const layers = ["layer1", "layer2", "layer3"] as const;
  for (const layer of layers) {
    const a = incoming[layer] || [];
    const b = current[layer] || [];
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return false;
    }
  }
  return true;
}

// ============================================
// Initial State
// ============================================

function createInitialState(conversationId: string): PlanningState {
  return {
    conversationId,
    sessionId: null,
    projectName: null,
    // Explicit undefined so Object.assign clears leftover session context.
    villageName: undefined,
    province: undefined,
    city: undefined,
    county: undefined,
    township: undefined,
    planningPeriod: undefined,
    status: "idle",
    authoritativeActiveStage: null,

    // Agent State
    phase: "init",
    currentWave: 1,
    reports: { layer1: {}, layer2: {}, layer3: {} },
    previous_layer: 0,
    step_mode: false,
    interruptInfo: undefined,

    // Derived UI State
    completedDimensions: { layer1: [], layer2: [], layer3: [] },
    currentLayer: null,
    currentPhase: "idle",
    completedLayers: { 1: false, 2: false, 3: false },
    isPaused: false,
    pendingReviewLayer: null,
    lastPauseLayer: 0,
    sseResumeTrigger: 0,
    lastProcessedSeq: 0,

    // Messages
    messages: [],
    revisionDraft: null,
    planningTextRegenRequest: null,
    llmHealthStatus: null,
    llmHealthMessage: null,
    llmHealthDismissed: false,

    // Progress
    dimensionProgress: {},
    executingDimensions: [],
    layerDimensionCount: {},
    runningTools: [],

    // NEW: RAG & Cascade Tracking
    dimensionRagSources: {},
    cascadeChain: null,
    revisionCompletedKeys: [],
    streamingContent: {},

    // UI State
    viewerVisible: false,
    referencedSection: undefined,
    viewingFile: null,
    viewMode: "WELCOME_FORM",
    villageFormData: null,
    progressPanelVisible: false,
    layerReportVisible: false,
    activeReportLayer: 1,

    // History
    villages: [],
    deletedSessionIds: loadDeletedSessionIds(),
    selectedVillage: null,
    selectedSession: null,
    historyLoading: false,
    historyError: null,
    pendingHistoricalSessionId: null,

    // Checkpoints
    checkpoints: [],
    selectedCheckpoint: null,
    loadingContent: false,
    deletingSessionId: null,

    // Tools
    toolStatuses: {},
    // GIS Layers (SSE-driven)
    gisLayers: {},
    pipelineTrace: null,

    // Three-Panel Layout
    selectedNavigationKey: null,
    isRightPanelExpanded: true,
    isLeftNavCollapsed: false,

    // ProcessPanel
    processPanelTab: "messages",

    // Layer-level RAG config (default: all enabled)
    ragLayerConfig: { 1: true, 2: false, 3: true },

    // GIS state
    gisGenerating: false,
    isFullMapOpen: false,
    gisTriggerPending: false,
    villageCenter: undefined,

    // Delivery & Artifact
    delivery: null,
    resyncRequired: false,
    humanReview: null,
  };
}

function applySessionReset(state: PlanningState): void {
  // Intentionally do NOT preserve step_mode: a prior paused session would
  // otherwise force the next run into review pauses and look like "reports missing".
  const preserved = {
    villages: state.villages,
    deletedSessionIds: state.deletedSessionIds,
    historyLoading: state.historyLoading,
    historyError: state.historyError,
    pendingHistoricalSessionId: state.pendingHistoricalSessionId,
    ragLayerConfig: state.ragLayerConfig,
    conversationId: state.conversationId,
  };
  const next = createInitialState(state.conversationId);
  // Drop any leftover keys Object.assign would not clear (dynamic / optional fields).
  for (const key of Object.keys(state) as Array<keyof PlanningState>) {
    if (!(key in next) && !(key in preserved)) {
      delete (state as unknown as Record<string, unknown>)[key as string];
    }
  }
  Object.assign(state, next, preserved);
}

function filterDeletedHistory(
  villages: VillageInfo[],
  deletedSessionIds: Record<string, true>,
): VillageInfo[] {
  return villages
    .map((village) => {
      const sessions = village.sessions.filter((session) => !deletedSessionIds[session.session_id]);
      if (sessions.length === village.sessions.length) return village;
      return {
        ...village,
        sessions,
        session_count: sessions.length,
      };
    })
    .filter((village) => village.sessions.length > 0);
}

// ============================================
// Store Actions Interface
// ============================================

export interface PlanningActions {
  // Core setters
  setSessionId: (sessionId: string | null) => void;
  setProjectName: (projectName: string | null) => void;
  setStatus: (status: Status) => void;
  setPhase: (phase: string) => void;

  // Messages
  addMessage: (message: Message) => void;
  addMessages: (messages: Message[]) => void;
  setMessages: (messages: Message[]) => void;
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;
  setRevisionDraft: (draft: { feedback: string; dimensions: string[] } | null) => void;
  clearRevisionDraft: () => void;
  requestPlanningTextRegen: (changedDimensions?: string[]) => void;
  clearPlanningTextRegenRequest: () => void;
  dismissLlmHealthBanner: () => void;
  scanOfflineReports: () => void;

  // Progress
  updateDimensionProgress: (
    key: string,
    updates: Partial<DimensionProgressItem>,
  ) => void;
  setDimensionStreaming: (
    layer: number,
    dimensionKey: string,
    dimensionName: string,
  ) => void;
  setDimensionCompleted: (
    layer: number,
    dimensionKey: string,
    wordCount: number,
  ) => void;
  clearDimensionProgress: () => void;
  setDimensionProgressBatch: (
    updates: Record<string, DimensionProgressItem>,
  ) => void;

  // Layer & Reports
  setLayerCompleted: (layer: number, completed: boolean) => void;
  setReports: (reports: Partial<Reports>) => void;
  setCompletedDimensions: (completedDimensions: CompletedDimensions) => void;
  clearDimensionReport: (layer: number, dimensionKey: string) => void;

  // Backend sync
  syncBackendState: (
    backendData: Partial<SessionStatusResponse> & { version?: number },
  ) => void;
  hydrateFromStateSync: (data: Record<string, unknown>) => void;

  // ============================================
  // NEW: RAG & Cascade Actions
  // ============================================
  setRagQuery: (dimKey: string, query: string) => void;
  setRagDocuments: (dimKey: string, documents: RagDocument[]) => void;
  clearRagSources: (dimKey: string) => void;
  clearAllRagSources: () => void;
  showCascadeChain: (trigger: string, impacted: string[]) => void;
  clearCascadeChain: () => void;
  setStreamingContent: (dimKey: string, content: string) => void;
  clearStreamingContent: (dimKey: string) => void;

  // ============================================
  // NEW: Simplified Tool Tracking
  // ============================================
  addRunningTool: (toolName: string) => void;
  removeRunningTool: (toolName: string) => void;

  // UI State
  setViewerVisible: (visible: boolean) => void;
  setViewingFile: (file: FileMessage | null) => void;
  setPaused: (paused: boolean) => void;
  setPendingReviewLayer: (layer: number | null) => void;
  setVillageFormData: (data: VillageInputData | null) => void;
  setProgressPanelVisible: (visible: boolean) => void;
  setStepMode: (stepMode: boolean) => void;

  // History
  setVillages: (villages: VillageInfo[]) => void;
  removeSessionFromHistory: (sessionId: string) => void;
  clearVillagesHistory: () => void;
  markSessionsDeleted: (sessionIds: string[]) => void;
  unmarkSessionDeleted: (sessionId: string) => void;
  addSessionToHistory: (entry: { projectName: string; villageName: string; sessionId: string }) => void;
  setSelectedVillage: (village: VillageInfo | null) => void;
  setSelectedSession: (session: VillageSession | null) => void;
  setHistoryLoading: (loading: boolean) => void;
  setHistoryError: (error: string | null) => void;
  setPendingHistoricalSessionId: (sessionId: string | null) => void;

  // Checkpoints
  setCheckpoints: (checkpoints: Checkpoint[]) => void;
  setSelectedCheckpoint: (checkpointId: string | null) => void;

  // Tools (legacy, prefer addRunningTool/removeRunningTool)
  setToolStatus: (toolName: string, status: ToolStatus) => void;
  clearToolStatus: (toolName: string) => void;

  // SSE Event handling
  handleSSEEvent: (event: StoreEvent) => void;

  // SSE Reconnect trigger
  triggerSseReconnect: () => void;

  // Clear progress state (for approve/reject transitions)
  clearProgressState: () => void;

  // GIS layer management
  addGisLayersFromUpload: (configs: Array<Record<string, unknown>>) => void;

  // Clear only revision dimensions progress (preserve other completed dimensions)
  clearRevisionProgress: (layer: number, dimensionsToRevise: string[]) => void;

  // Navigation
  setSelectedNavigationKey: (key: NavigationKey | null) => void;
  setRightPanelExpanded: (expanded: boolean) => void;
  setLeftNavCollapsed: (collapsed: boolean) => void;

  // ProcessPanel
  setProcessPanelTab: (tab: ProcessPanelTab) => void;

  // GIS
  setFullMapOpen: (open: boolean) => void;

  // ============================================
  // NEW: Layer-level RAG Configuration
  // ============================================
  setRagLayerConfig: (config: Record<number, boolean>) => void;
  toggleLayerRag: (layer: number) => void;

  // Reset
  resetSessionState: () => void;
  resetConversation: () => void;
  initConversation: (conversationId: string) => void;

  /** Advance SSE dedupe cursor without processing events (history hydrate). */
  setLastProcessedSeq: (seq: number) => void;

  // ============================================
  // Delivery & Artifact (v1)
  // ============================================
  setDelivery: (delivery: PlanningState['delivery']) => void;
  clearDelivery: () => void;
  setResyncRequired: (required: boolean) => void;
  setHumanReview: (review: PlanningState['humanReview']) => void;
  clearHumanReview: () => void;
  refreshHumanReview: (sessionId?: string) => Promise<void>;

  /** Apply authoritative /map-layers layers into the map snapshot. */
  applyMapLayers: (layers: GISLayerConfig[], snapshotChecksum?: string) => void;
}

function restoreGisLayersFromStatus(
  state: PlanningState,
  configs: unknown,
): boolean {
  const layers = normalizeGisLayers(configs);
  if (layers.length === 0) return false;

  // Replace prior generated/status snapshots while retaining explicit user uploads.
  // This keeps reconnects idempotent and avoids drawing the same polygons twice.
  for (const key of Object.keys(state.gisLayers)) {
    if (
      key.startsWith("status_") ||
      key.startsWith("result_") ||
      key.endsWith("_spatial_layout")
    ) {
      delete state.gisLayers[key];
    }
  }
  state.gisLayers.status_spatial_layout = layers;
  state.gisGenerating = false;
  state.gisTriggerPending = false;
  state.isRightPanelExpanded = true;
  state.processPanelTab = "map";
  return true;
}

// ============================================
// SSE Event Handler
// ============================================

function applyHumanReviewResponse(
  state: PlanningState,
  review: HumanReviewListResponse,
): void {
  if (!review.event_id && review.pending_items.length === 0) {
    // Clear an old optimistic lock when the backend reports no active review.
    // Keeping it causes the next decision to target a stale checkpoint.
    state.humanReview = null;
    state.pendingReviewLayer = null;
    return;
  }
  const pausedStage =
    review.paused_stage
    || review.interrupt_info?.paused_stage
    || review.pending_items[0]?.stage
    || '';
  state.humanReview = {
    event_id: review.event_id ?? null,
    paused_stage: pausedStage,
    items: review.pending_items,
  };
  const layer = pausedStageToLayer(pausedStage);
  if (layer) {
    state.pendingReviewLayer = layer;
    state.lastPauseLayer = layer;
  }
  state.isPaused = true;
  if (state.status !== 'revising' && state.status !== 'failed') {
    state.status = 'paused';
  }
}

function applyHumanReviewEventPayload(
  state: PlanningState,
  data: Record<string, unknown>,
): void {
  const items = Array.isArray(data.items)
    ? (data.items as unknown as HumanReviewItem[])
    : [];
  const eventId = typeof data.event_id === 'string' ? data.event_id : null;
  const pausedStage = typeof data.paused_stage === 'string' ? data.paused_stage : '';
  if (!eventId && items.length === 0) {
    return;
  }
  state.humanReview = {
    event_id: eventId,
    paused_stage: pausedStage,
    items,
  };
  const layer = pausedStageToLayer(pausedStage);
  if (layer) {
    state.pendingReviewLayer = layer;
    state.lastPauseLayer = layer;
  }
  state.isPaused = true;
  if (state.status !== 'revising' && state.status !== 'failed') {
    state.status = 'paused';
  }
}

function handleSSEEventInStore(state: PlanningState, event: StoreEvent): void {
  const eventType = event.type;
  const data = (event.data as Record<string, unknown>) || {};

  // Sequence number check for deduplication
  // Skip events that have already been processed or are out of order
  const seq = (data.seq as number) || 0;
  if (seq > 0) {
    if (seq <= state.lastProcessedSeq) {
      // Skip duplicate or old event
      return;
    }
    state.lastProcessedSeq = seq;
  }

  switch (eventType) {
    case "connected": {
      // Never downgrade a restored/terminal session back to "planning".
      if (
        state.status !== "completed" &&
        state.status !== "failed" &&
        state.status !== "paused"
      ) {
        state.status = "planning";
      }
      const connData = data as { task_id?: string };
      if (connData.task_id && !state.sessionId) {
        state.sessionId = connData.task_id;
      }
      break;
    }

    case "completed": {
      state.status = "completed";
      break;
    }

    case "delivery_ready": {
      // Delivery projection is available; the UI should pull /delivery and
      // /map-layers. We do not interpret the payload here — the authoritative
      // data is read from REST so reconnects stay consistent.
      state.status = "completed";
      break;
    }

    case "resync_required": {
      // Local event window is discontinuous. Do NOT apply stale events;
      // full REST recovery (/state → /events/sync) is required.
      state.resyncRequired = true;
      break;
    }

    case "human_review":
    case "human_review_paused": {
      state.status = "paused";
      state.isPaused = true;
      applyHumanReviewEventPayload(state, data);
      break;
    }

    case "error": {
      const errData = data as { message?: string; error?: string; detail?: string };
      const message = errData.message || errData.error || errData.detail || "后端任务失败，请查看后端窗口日志。";
      applyLlmHealthFromMessage(state, message);
      state.messages.push(createErrorMessage(message));
      state.gisGenerating = false;
      state.gisTriggerPending = false;
      state.status = state.previous_layer > 0 || state.lastPauseLayer > 0 ? "paused" : "failed";
      deriveUIStateInStore(state);
      break;
    }

    case "dimension_error": {
      const errData = data as {
        dimension_key?: string;
        dimension_name?: string;
        error?: string;
        error_type?: string;
        layer?: number;
      };
      const layer = errData.layer || 1;
      const key = `${layer}_${errData.dimension_key || ""}`;

      state.dimensionProgress[key] = {
        dimensionKey: errData.dimension_key || "",
        dimensionName: errData.dimension_name || "",
        layer,
        status: "failed" as DimensionStatus,
        wordCount: 0,
        error: errData.error || "Unknown error",
      };
      applyLlmHealthFromMessage(state, errData.error || "");

      state.executingDimensions = state.executingDimensions.filter(
        (k) => k !== key,
      );
      if (errData.dimension_key === "spatial_layout") {
        state.gisGenerating = false;
        state.gisTriggerPending = false;
      }
      break;
    }

    case "dimension_start": {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        layer?: number;
        is_revision?: boolean;
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || "";
      const key = buildDimensionProgressKey(layer, dimensionKey);

      // Track executing dimension (no longer create standalone message)
      if (!state.executingDimensions.includes(key)) {
        state.executingDimensions.push(key);
      }

      // Initialize dimensionProgress for progress tracking
      state.dimensionProgress[key] = {
        dimensionKey,
        dimensionName: dimData.dimension_name || "",
        layer,
        status: "streaming" as DimensionStatus,
        wordCount: 0,
        isRevision: dimData.is_revision || false,
      };

      // If this is a revision, clear old report content and prepare for new analysis
      if (dimData.is_revision && dimensionKey) {
        // Clear old report so UI shows empty/refreshing state
        const layerKey = `layer${layer}` as keyof Reports;
        state.reports[layerKey][dimensionKey] = "";
        // Clear streaming content from previous runs
        delete state.streamingContent[key];

        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const existingMessage = state.messages.find(
          (m) => m.id === revisionReportId && m.type === "dimension_report",
        );
        if (!existingMessage) {
          const baseMsg = createBaseMessage("assistant");
          const newMessage: DimensionReportMessage = {
            ...baseMsg,
            id: revisionReportId,
            type: "dimension_report",
            layer: layer,
            dimensionKey,
            dimensionName: dimData.dimension_name || "",
            content: "",
            streamingState: "streaming",
            wordCount: 0,
            isRevision: true,
          };
          state.messages.push(newMessage);
        }
      }
      break;
    }

    case "dimension_delta": {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        delta?: string;
        accumulated?: string;
        layer?: number;
        is_revision?: boolean;
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || "";
      const key = buildDimensionProgressKey(layer, dimensionKey);

      // If this is a revision, update the standalone revision_report message
      // Then also fall through to normal path for reports/layerMsg updates
      if (dimData.is_revision && dimensionKey && dimData.accumulated) {
        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const msgIdx = state.messages.findIndex(
          (m) => m.id === revisionReportId && m.type === "dimension_report",
        );
        if (msgIdx >= 0) {
          const msg = state.messages[msgIdx] as DimensionReportMessage;
          msg.content = dimData.accumulated;
          msg.wordCount = dimData.accumulated.length;
        }
        // Also update dimensionProgress
        const existing = state.dimensionProgress[key];
        if (existing) {
          existing.wordCount = dimData.accumulated.length;
        }
      }

      // 1. Update reports state
      const layerKey = `layer${layer}` as keyof Reports;
      if (dimensionKey && dimData.accumulated) {
        state.reports[layerKey][dimensionKey] = dimData.accumulated;
      }

      // 2. Update layer_report message's dimensionReports for real-time display
      const layerReportId = buildLayerReportId(layer);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === "layer_completed",
      );

      if (layerMsgIdx >= 0 && dimensionKey && dimData.accumulated) {
        const layerMsg = state.messages[layerMsgIdx] as LayerCompletedMessage;
        // Initialize dimensionReports if undefined
        if (!layerMsg.dimensionReports) {
          layerMsg.dimensionReports = {};
        }
        // Only update the current dimension content (lightweight update)
        // Skip expensive fullReportContent and summary calculation - defer to dimension_complete
        layerMsg.dimensionReports[dimensionKey] = dimData.accumulated;
      }

      // 3. Update dimensionProgress (auto-initialize if missing)
      if (dimData.accumulated) {
        const existing = state.dimensionProgress[key];
        if (existing) {
          existing.wordCount = dimData.accumulated.length;
        } else {
          // Auto-initialize for SSE reconnect resilience
          state.dimensionProgress[key] = {
            dimensionKey,
            dimensionName: dimData.dimension_name || dimensionKey,
            layer,
            status: "streaming" as DimensionStatus,
            wordCount: dimData.accumulated.length,
          };
          if (!state.executingDimensions.includes(key)) {
            state.executingDimensions.push(key);
          }
        }
      }
      break;
    }

    case "dimension_complete": {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        full_content?: string;
        word_count?: number;
        layer?: number;
        is_revision?: boolean;
        offline_fallback?: boolean;
        knowledge_sources?: KnowledgeSource[];
        structured_summary?: {
          dimension_key?: string;
          layer?: number;
          word_count?: number;
          key_points?: string[];
          text_summary?: string;
          metrics?: Record<string, unknown>;
        };
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || "";
      const key = buildDimensionProgressKey(layer, dimensionKey);

      // 获取内容：优先使用 full_content，否则保留已有累积内容（dimension_delta）
      const lk = `layer${layer}` as keyof Reports;
      const existingContent = state.reports[lk]?.[dimensionKey] || "";
      const content = dimData.full_content || existingContent;

      // Update dimensionProgress
      state.dimensionProgress[key] = {
        dimensionKey,
        dimensionName: dimData.dimension_name || "",
        layer,
        status: "completed" as DimensionStatus,
        wordCount: dimData.word_count || content.length,
        completedAt: new Date().toISOString(),
        isRevision: dimData.is_revision || false,
      };

      // Remove from executing
      state.executingDimensions = state.executingDimensions.filter(
        (k) => k !== key,
      );

      // If this is a revision, complete the standalone revision_report message
      // Then also fall through to normal path for layer_completed message updates
      if (dimData.is_revision && dimensionKey) {
        // Track revision completion for cascade panel
        const revKey = `${layer}_${dimensionKey}`;
        if (!state.revisionCompletedKeys.includes(revKey)) {
          state.revisionCompletedKeys.push(revKey);
        }
        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const msgIdx = state.messages.findIndex(
          (m) => m.id === revisionReportId && m.type === "dimension_report",
        );
        if (msgIdx >= 0) {
          const msg = state.messages[msgIdx] as DimensionReportMessage;
          msg.content = content;
          msg.wordCount = content.length;
          msg.streamingState = "completed";
        }
      }

      // Update reports
      const layerKey = `layer${layer}` as keyof Reports;
      state.reports[layerKey][dimensionKey] = content;
      if (dimData.offline_fallback || content.includes('LLM 不可用')) {
        applyLlmHealthFromMessage(state, content);
      }

      // Update layer_report message (no longer create standalone dimension_report)
      const layerReportId = buildLayerReportId(layer);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === "layer_completed",
      );

      if (layerMsgIdx >= 0) {
        const layerMsg = state.messages[layerMsgIdx] as LayerCompletedMessage;
        // Initialize dimensionReports if undefined
        if (!layerMsg.dimensionReports) {
          layerMsg.dimensionReports = {};
        }
        layerMsg.dimensionReports[dimensionKey] = content;

        // Update fullReportContent and summary using utility functions
        layerMsg.fullReportContent = formatDimensionReportsAsContent(
          layerMsg.dimensionReports,
        );
        const summary = calculateReportSummary(
          layerMsg.dimensionReports,
          layerMsg.dimensionSummaries,
        );
        layerMsg.summary.word_count = summary.word_count;
        layerMsg.summary.dimension_count = summary.dimension_count;

        // Extract key_points from structured_summary and store in dimensionSummaries
        if (dimData.structured_summary?.key_points?.length) {
          if (!layerMsg.dimensionSummaries) {
            layerMsg.dimensionSummaries = {};
          }
          // Ensure dimension_key is set, fallback to current dimensionKey
          const summary = {
            ...dimData.structured_summary,
            dimension_key:
              dimData.structured_summary.dimension_key || dimensionKey,
          };
          layerMsg.dimensionSummaries[dimensionKey] = summary;
          // Merge key_points into layer summary
          layerMsg.summary.key_points = Object.values(
            layerMsg.dimensionSummaries,
          )
            .flatMap((s) => s.key_points || [])
            .slice(0, 10);
        }

        // GIS data is now sent via independent gis_result events after review
        // Remove gis_data handling from dimension_complete

        // Store knowledge_sources to layer_completed message
        if (dimData.knowledge_sources && dimData.knowledge_sources.length > 0) {
          if (!layerMsg.dimensionKnowledgeSources) {
            layerMsg.dimensionKnowledgeSources = {};
          }
          layerMsg.dimensionKnowledgeSources[dimensionKey] =
            dimData.knowledge_sources;
        }
      }

      // Ensure phase is correct (dimension_complete may arrive before layer_started)
      const expectedPhase = `layer${layer}`;
      if (state.phase !== expectedPhase) {
        state.phase = expectedPhase;
      }

      // Derive UI state from phase (currentLayer, currentPhase, completedLayers, etc.)
      deriveUIStateInStore(state);

      // 检测当前层是否所有维度已完成，自动触发暂停状态
      const completedCountForLayer =
        state.completedDimensions[layerKey]?.length || 0;
      const expectedCount =
        state.layerDimensionCount[layer] || getDimensionsByLayer(layer).length;

      if (
        state.step_mode &&
        completedCountForLayer >= expectedCount &&
        expectedCount > 0 &&
        state.status !== "paused"
      ) {
        const phaseLayer = phaseToLayer(state.phase) ?? layer;
        const highestActive = getHighestActiveLayer(
          state.reports,
          state.dimensionProgress,
          state.executingDimensions || [],
          phaseLayer,
        );
        // Ignore stale dimension_complete for a layer we've already advanced past.
        if (layer >= phaseLayer && layer >= highestActive) {
          state.previous_layer = layer;
          state.status = "paused";
          deriveUIStateInStore(state);
        }
      }
      break;
    }

    case "layer_started": {
      const layerData = data as {
        layer?: number;
        layer_number?: number;
        dimension_count?: number;
      };
      const layerNum = layerData.layer || layerData.layer_number || 1;

      // Core: Update phase first, then derive UI state from it
      state.phase = `layer${layerNum}`;
      state.status = "planning";
      state.interruptInfo = undefined;

      // Store dimension_count for progress panel display (with change detection)
      if (
        layerData.dimension_count &&
        state.layerDimensionCount[layerNum] !== layerData.dimension_count
      ) {
        state.layerDimensionCount[layerNum] = layerData.dimension_count;
      }

      // Reset dimensionProgress and executingDimensions for current layer only
      // Preserve other layers' progress so LayerNav can display all dimensions
      state.dimensionProgress = Object.fromEntries(
        Object.entries(state.dimensionProgress).filter(
          ([key]) => !key.startsWith(`${layerNum}_`),
        ),
      );
      state.executingDimensions = state.executingDimensions.filter(
        (k) => !k.startsWith(`${layerNum}_`),
      );

      // Create layer_report message framework for real-time streaming
      // Key: Do NOT overwrite existing message - protect content from history restore or SSE reconnect
      const layerReportId = buildLayerReportId(layerNum);
      const existingMessage = state.messages.find(
        (m) => m.id === layerReportId && m.type === "layer_completed",
      );

      if (!existingMessage) {
        // Only create new message framework if it doesn't exist
        const baseMsg = createBaseMessage("assistant");
        const newMessage: LayerCompletedMessage = {
          ...baseMsg,
          id: layerReportId,
          type: "layer_completed",
          layer: layerNum,
          content: "",
          summary: {
            word_count: 0,
            key_points: [],
            dimension_count: 0,
          },
          fullReportContent: "",
          dimensionReports: {},
          actions: [],
        };
        state.messages.push(newMessage);
      }
      // If message exists (history restore or SSE reconnect), preserve its content unchanged

      // Jump to overview when a new layer starts, but keep an explicit dim
      // selection already pointing at this layer (e.g. startPlanning preselect).
      const navKey = state.selectedNavigationKey;
      const dimLayerMatch = typeof navKey === 'string'
        ? navKey.match(/^dim:(\d+)_/)
        : null;
      const alreadyOnThisLayer = dimLayerMatch
        && Number(dimLayerMatch[1]) === layerNum;
      if (!alreadyOnThisLayer && navKey !== NAV_KEYS.OVERVIEW) {
        state.selectedNavigationKey = NAV_KEYS.OVERVIEW;
      }

      // Derive UI state from phase (currentLayer, currentPhase, completedLayers, etc.)
      deriveUIStateInStore(state);
      break;
    }

    case "layer_completed": {
      const layerData = data as {
        layer?: number;
        phase?: string;
        dimension_reports?: Record<string, string>;
        dimension_knowledge_sources?: Record<string, KnowledgeSource[]>;
        previous_layer?: number;
        task_id?: string;
      };

      if (layerData.task_id && !state.sessionId) {
        state.sessionId = layerData.task_id;
      }

      const layerNum = layerData.layer || 1;
      const layerKey = `layer${layerNum}` as keyof Reports;

      if (
        layerData.dimension_reports &&
        Object.keys(layerData.dimension_reports).length > 0
      ) {
        Object.assign(state.reports[layerKey], layerData.dimension_reports);
      }

      state.phase = layerData.phase || state.phase;
      state.previous_layer = layerData.previous_layer ?? state.previous_layer;
      state.status = "paused";

      if (
        state.step_mode &&
        state.selectedNavigationKey !== NAV_KEYS.OVERVIEW
      ) {
        state.selectedNavigationKey = NAV_KEYS.OVERVIEW;
      }

      // Finalize layer_report message (merge any remaining dimension_reports from SSE)
      const layerReportId = buildLayerReportId(layerNum);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === "layer_completed",
      );

      if (layerMsgIdx >= 0 && layerData.dimension_reports) {
        const layerMsg = state.messages[layerMsgIdx] as LayerCompletedMessage;
        // Initialize dimensionReports if undefined
        if (!layerMsg.dimensionReports) {
          layerMsg.dimensionReports = {};
        }
        Object.assign(layerMsg.dimensionReports, layerData.dimension_reports);

        // Update fullReportContent and summary using utility functions
        layerMsg.fullReportContent = formatDimensionReportsAsContent(
          layerMsg.dimensionReports,
        );
        const summary = calculateReportSummary(
          layerMsg.dimensionReports,
          layerMsg.dimensionSummaries,
        );
        layerMsg.summary.word_count = summary.word_count;
        layerMsg.summary.dimension_count = summary.dimension_count;
        if (summary.key_points.length > 0) {
          layerMsg.summary.key_points = summary.key_points;
        }

        // Update knowledge sources if provided
        if (layerData.dimension_knowledge_sources) {
          layerMsg.dimensionKnowledgeSources =
            layerMsg.dimensionKnowledgeSources ?? {};
          Object.assign(
            layerMsg.dimensionKnowledgeSources,
            layerData.dimension_knowledge_sources,
          );
        }
      }

      // Force mark all dimensions in current layer as completed
      // This ensures dimensionProgress is correct even if some dimension_complete events were missed
      if (layerData.dimension_reports) {
        for (const dimKey of Object.keys(layerData.dimension_reports)) {
          const progressKey = buildDimensionProgressKey(layerNum, dimKey);
          state.dimensionProgress[progressKey] = {
            dimensionKey: dimKey,
            dimensionName: DIMENSION_NAMES[dimKey] || dimKey,
            layer: layerNum,
            status: "completed" as DimensionStatus,
            wordCount: (layerData.dimension_reports[dimKey] || "").length,
            completedAt: new Date().toISOString(),
          };
        }
        // Clear executing dimensions for this layer
        state.executingDimensions = state.executingDimensions.filter(
          (k) => !k.startsWith(`${layerNum}_`),
        );
      }

      // Derive UI state from phase and pause state (currentLayer, currentPhase, etc.)
      deriveUIStateInStore(state);
      break;
    }

    case "layer_paused": {
      const pauseData = data as {
        layer?: number;
        phase?: string;
        layer_name?: string;
      };
      state.interruptInfo = pauseData;
      state.status = "paused";
      deriveUIStateInStore(state);
      break;
    }

    case "execution_resumed": {
      state.interruptInfo = undefined;
      state.status = "planning";
      deriveUIStateInStore(state);
      break;
    }

    case "tool_call": {
      const toolData = data as {
        tool_name?: string;
        tool_display_name?: string;
        description?: string;
        estimated_time?: number;
        stage?: string;
      };
      const toolName = toolData.tool_name || "";
      if (!toolName) return;

      state.toolStatuses[toolName] = {
        toolName,
        status: "running",
        stage: toolData.stage,
        message: toolData.description,
      };

      // Auto-switch to messages tab and expand right panel
      state.processPanelTab = "messages";
      state.isRightPanelExpanded = true;
      break;
    }

    case "tool_progress": {
      const toolData = data as {
        tool_name?: string;
        stage?: string;
        progress?: number;
        message?: string;
      };
      const toolName = toolData.tool_name || "";
      if (!toolName) return;

      const existing = state.toolStatuses[toolName];
      if (!existing) return;

      existing.stage = toolData.stage || existing.stage;
      existing.progress = toolData.progress;
      existing.message = toolData.message;
      break;
    }

    case "tool_result": {
      const toolData = data as {
        tool_name?: string;
        status?: string;
        summary?: string;
      };
      const toolName = toolData.tool_name || "";
      if (!toolName) return;

      const existing = state.toolStatuses[toolName];
      if (!existing) return;

      existing.status = toolData.status === "error" ? "error" : "success";
      existing.summary = toolData.summary;
      break;
    }

    // ============================================
    // New Unified Tool Events (tool_started, tool_status)
    // ============================================

    case "tool_started": {
      const toolData = data as {
        tool_name?: string;
        tool_display_name?: string;
        description?: string;
        estimated_time?: number;
        status?: string;
        started_at?: string;
      };
      const toolName = toolData.tool_name || "";
      if (!toolName) return;

      const baseMsg = createBaseMessage("assistant");
      const newMessage: ToolStatusMessage = {
        ...baseMsg,
        id: `tool_${toolName}_${Date.now()}`,
        type: "tool_status",
        toolName,
        toolDisplayName: toolData.tool_display_name || toolName,
        description: toolData.description || "",
        status: "running",
        estimatedTime: toolData.estimated_time,
        startedAt: toolData.started_at,
      };
      state.messages.push(newMessage);

      state.toolStatuses[toolName] = {
        toolName,
        status: "running",
        message: toolData.description,
      };
      break;
    }

    case "tool_status": {
      const toolData = data as {
        tool_name?: string;
        status?: string;
        progress?: number;
        stage?: string;
        stage_message?: string;
        summary?: string;
        error?: string;
        completed_at?: string;
      };
      const toolName = toolData.tool_name || "";
      if (!toolName) return;

      const msgIdx = state.messages.findIndex(
        (m) =>
          m.type === "tool_status" &&
          (m as ToolStatusMessage).toolName === toolName,
      );

      if (msgIdx >= 0) {
        const msg = state.messages[msgIdx] as ToolStatusMessage;
        msg.status =
          (toolData.status as ToolStatusMessage["status"]) || msg.status;
        if (toolData.progress !== undefined) msg.progress = toolData.progress;
        if (toolData.stage) msg.stage = toolData.stage;
        if (toolData.stage_message) msg.stageMessage = toolData.stage_message;
        if (toolData.summary) msg.summary = toolData.summary;
        if (toolData.error) msg.error = toolData.error;
        if (toolData.completed_at) msg.completedAt = toolData.completed_at;
      }

      const existing = state.toolStatuses[toolName];
      if (existing) {
        existing.status =
          toolData.status === "error"
            ? "error"
            : toolData.status === "success"
              ? "success"
              : "running";
        if (toolData.progress !== undefined)
          existing.progress = toolData.progress;
        if (toolData.stage) existing.stage = toolData.stage;
        if (toolData.stage_message) existing.message = toolData.stage_message;
        if (toolData.summary) existing.summary = toolData.summary;
      }
      break;
    }

    // ============================================
    // GIS Result Event
    // ============================================

    case "gis_result": {
      const gisData = data as {
        dimensionKey?: string;
        dimensionName?: string;
        summary?: string;
        layers?: unknown[];
        mapOptions?: { center?: [number, number]; zoom?: number };
        analysisData?: {
          overallScore?: number;
          suitabilityLevel?: string;
          sensitivityClass?: string;
          recommendations?: string[];
        };
        pipeline_trace?: PipelineTrace;
      };
      const dimensionKey = gisData.dimensionKey || "";
      if (!dimensionKey) return;

      const baseMsg = createBaseMessage("assistant");
      const newMessage: GisResultMessage = {
        ...baseMsg,
        id: `gis_${dimensionKey}_${Date.now()}`,
        type: "gis_result",
        dimensionKey,
        dimensionName: gisData.dimensionName || dimensionKey,
        summary: gisData.summary || "",
        layers: normalizeGisLayers(gisData.layers),
        mapOptions:
          gisData.mapOptions?.center && gisData.mapOptions?.zoom
            ? {
                center: gisData.mapOptions.center,
                zoom: gisData.mapOptions.zoom,
              }
            : undefined,
        analysisData: gisData.analysisData,
      };
      state.messages.push(newMessage);

      // Store pipeline_trace if present
      if (gisData.pipeline_trace) {
        state.pipelineTrace = gisData.pipeline_trace;
      }

      let hasRenderableGisLayers = false;

      // Bridge: also populate gisLayers for Map tab
      if (gisData.layers && Array.isArray(gisData.layers)) {
        const layerConfigs = normalizeGisLayers(gisData.layers);
        if (layerConfigs.length > 0) {
          // Replace the incremental/previous result for this dimension. Keeping
          // both would render identical polygons twice and leave stale fallback
          // geometry underneath a regenerated plan.
          for (const key of Object.keys(state.gisLayers)) {
            if (key === `result_${dimensionKey}` || key.endsWith(`_${dimensionKey}`)) {
              delete state.gisLayers[key];
            }
          }
          state.gisLayers[`result_${dimensionKey}`] = layerConfigs;
          hasRenderableGisLayers = true;
        } else {
          state.messages.push(createErrorMessage("GIS 已返回图层信息，但没有可渲染的 GeoJSON 几何数据。请重新生成或上传边界/用地数据。"));
        }
      }

      // The final spatial result belongs to the dedicated map workspace.
      if (hasRenderableGisLayers) {
        state.isRightPanelExpanded = true;
        state.processPanelTab = 'map';
      }
      state.gisGenerating = false;
      state.gisTriggerPending = false;
      break;
    }

    case "ai_response_complete": {
      const aiData = data as {
        content?: string;
        source?: string;
        channel?: string;
      };

      // Planning-generation responses are workflow artifacts, not chat turns.
      // The current chat endpoint returns its reply directly.  Only an SSE
      // event explicitly marked as conversational may enter the transcript.
      if (
        !aiData.content?.trim() ||
        (aiData.source !== "chat" && aiData.channel !== "conversation")
      ) {
        break;
      }

      const aiMessage = {
        id: `ai_${Date.now()}`,
        timestamp: new Date(),
        role: "assistant" as const,
        type: "text" as const,
        content: aiData.content,
      };
      state.messages.push(aiMessage);
      break;
    }

    case "pause": {
      const pauseData = data as {
        current_layer?: number;
        checkpoint_id?: string;
        previous_layer?: number;
        message?: string;
        task_id?: string;
      };

      if (pauseData.task_id && !state.sessionId) {
        state.sessionId = pauseData.task_id;
      }

      state.previous_layer =
        pauseData.current_layer ||
        pauseData.previous_layer ||
        state.previous_layer;
      state.lastPauseLayer = pauseData.current_layer || pauseData.previous_layer || state.lastPauseLayer;
      state.status = "paused";

      if (
        state.step_mode &&
        state.selectedNavigationKey !== NAV_KEYS.OVERVIEW
      ) {
        state.selectedNavigationKey = NAV_KEYS.OVERVIEW;
      }

      // Note: checkpoint_saved event (sent before pause) already creates the checkpoint
      // This is a fallback in case checkpoint_saved was missed
      const layer = pauseData.current_layer || pauseData.previous_layer || 0;
      if (pauseData.checkpoint_id && layer > 0) {
        const existingCp = state.checkpoints.find((cp) => cp.layer === layer);
        if (!existingCp) {
          state.checkpoints.push({
            checkpoint_id: pauseData.checkpoint_id,
            layer: layer,
            timestamp: new Date().toISOString(),
            description: `Layer ${layer} checkpoint`,
            type: "key",
            phase: state.phase,
          });
        }
      }

      deriveUIStateInStore(state);
      break;
    }

    case "resumed": {
      state.interruptInfo = undefined;
      state.previous_layer = 0;
      state.status = "planning";
      deriveUIStateInStore(state);
      break;
    }

    case "revision_completed": {
      const revData = data as {
        layer?: number;
        revised_dimensions?: string[];
        previous_layer?: number;
      };

      state.previous_layer = revData.previous_layer || revData.layer || 0;
      state.status = "paused";

      deriveUIStateInStore(state);
      break;
    }

    case "checkpoint_saved": {
      const cpData = data as {
        checkpoint_id?: string;
        layer?: number;
        checkpoint_type?: string;
        phase?: string;
        description?: string;
        is_revision?: boolean;
        revised_dimensions?: string[];
      };

      const layer = cpData.layer || 0;
      const cpType: "key" | "regular" =
        cpData.checkpoint_type === "key" ? "key" : "regular";

      const existingIndex = state.checkpoints.findIndex(
        (cp) => cp.layer === layer,
      );
      const newCheckpoint = {
        checkpoint_id: cpData.checkpoint_id || "",
        layer: layer,
        timestamp: new Date().toISOString(),
        description: cpData.description || `Checkpoint at layer ${layer}`,
        type: cpType,
        phase: cpData.phase,
        isRevision: cpData.is_revision || false,
        revisedDimensions: cpData.revised_dimensions,
      };

      if (existingIndex >= 0) {
        state.checkpoints[existingIndex] = {
          ...state.checkpoints[existingIndex],
          ...newCheckpoint,
        };
      } else if (cpData.checkpoint_id && layer > 0) {
        state.checkpoints.push(newCheckpoint);
      }
      break;
    }
    // ============================================
    // NEW: RAG Events for Demo System
    // ============================================
    case "rag_query": {
      const ragData = data as {
        dimension_key?: string;
        query?: string;
        layer?: number;
      };
      const dimKey = ragData.dimension_key || "";
      if (dimKey && ragData.query) {
        const fullKey = `${ragData.layer || 1}_${dimKey}`;
        state.dimensionRagSources[fullKey] = {
          query: ragData.query,
          documents: state.dimensionRagSources[fullKey]?.documents || [],
        };
      }
      break;
    }
    case "rag_result": {
      const ragData = data as {
        dimension_key?: string;
        query?: string;
        query_generation_method?: string;
        retrieval_latency_ms?: number;
        total_results?: number;
        documents?: Array<{
          title?: string;
          snippet?: string;
          source?: string;
          score?: number;
          matched_query?: string;
          query?: string;
          chunk_id?: string;
        }>;
        layer?: number;
      };
      const dimKey = ragData.dimension_key || "";
      if (dimKey) {
        const fullKey = `${ragData.layer || 1}_${dimKey}`;
        const documents = (ragData.documents || []).map((doc) => ({
          title: doc.title || doc.source || "未知",
          snippet: doc.snippet || "",
          source: doc.source,
          score: doc.score,
          chunk_id: doc.chunk_id,
          matched_query: doc.matched_query || doc.query || "",
        }));
        state.dimensionRagSources[fullKey] = {
          query: ragData.query || "",
          documents,
        };
      }
      break;
    }
    // ============================================
    // NEW: Cascade Events for Demo System
    // ============================================
    case "cascade_impact": {
      const cascadeData = data as {
        trigger_dim?: string;
        impacted_dimensions?: string[];
      };
      if (cascadeData.trigger_dim && cascadeData.impacted_dimensions) {
        state.cascadeChain = {
          trigger: cascadeData.trigger_dim,
          impacted: cascadeData.impacted_dimensions,
        };
        state.revisionCompletedKeys = [];
      }
      break;
    }
    case "cascade_complete": {
      const ccData = data as { revised_dimensions?: string[] };
      state.cascadeChain = null;
      state.revisionCompletedKeys = [];
      // Restore status from 'revising' to 'paused' so reports display correctly
      if (state.status === "revising") {
        state.status = "paused";
      }
      // Auto-navigate to first revised dimension report
      if (ccData.revised_dimensions && ccData.revised_dimensions.length > 0) {
        const firstDim = ccData.revised_dimensions[0];
        const dimLayer = getDimensionLayer(firstDim);
        if (dimLayer) {
          state.selectedNavigationKey = NAV_KEYS.dim(`${dimLayer}_${firstDim}`);
        }
        state.planningTextRegenRequest = {
          token: Date.now(),
          changedDimensions: ccData.revised_dimensions,
        };
      }
      deriveUIStateInStore(state);
      break;
    }
    // ============================================
    // NEW: State Sync Event (for reconnect)
    // ============================================
    case "state_sync": {
      const syncData = data as Record<string, unknown>;
      // Hydrate state from backend sync
      if (syncData.phase) state.phase = syncData.phase as string;
      if (syncData.current_wave)
        state.currentWave = syncData.current_wave as number;
      // Note: reports 不再从后端同步，前端通过 SSE dimension_delta/dimension_complete 累积
      // 或通过 getLayerReports API 按需获取
      if (syncData.completed_dimensions) {
        const completedData = syncData.completed_dimensions as Record<
          string,
          string[]
        >;
        if (completedData.layer1)
          state.completedDimensions.layer1 = completedData.layer1;
        if (completedData.layer2)
          state.completedDimensions.layer2 = completedData.layer2;
        if (completedData.layer3)
          state.completedDimensions.layer3 = completedData.layer3;
      }
      if (syncData.interrupt_info !== undefined)
        state.interruptInfo = syncData.interrupt_info as PlanningState['interruptInfo'];
      if (syncData.previous_layer !== undefined)
        state.previous_layer = syncData.previous_layer as number;
      if (syncData.gis_layout_configs) {
        restoreGisLayersFromStatus(state, syncData.gis_layout_configs);
      }
      deriveUIStateInStore(state);
      break;
    }
    case "gis_layer_update": {
      const gisUpdateData = data as {
        layer?: number;
        dimensionKey?: string;
        layers?: unknown[];
      };
      // Auto-activate map tab on first GIS data arrival. Must check BEFORE writing.
      const hadNoGisData = Object.keys(state.gisLayers).length === 0;
      const key = `${gisUpdateData.layer}_${gisUpdateData.dimensionKey}`;
      if (gisUpdateData.layers) {
        const normalizedLayers = normalizeGisLayers(gisUpdateData.layers);
        if (normalizedLayers.length > 0) {
          state.gisLayers[key] = normalizedLayers;
        }
      }
      if (hadNoGisData) {
        state.isRightPanelExpanded = true;
        state.processPanelTab = 'map';
      }
      if (!state.gisGenerating) state.gisGenerating = true;
      state.gisTriggerPending = false;
      break;
    }

    case "rag_config_updated": {
      const ragData = data as {
        rag_layer_config?: Record<number, boolean>;
      };
      if (ragData.rag_layer_config) {
        state.ragLayerConfig = ragData.rag_layer_config;
      }
      break;
    }

    case "step_mode_updated": {
      const stepData = data as {
        step_mode?: boolean;
      };
      if (stepData.step_mode !== undefined) {
        state.step_mode = stepData.step_mode;
      }
      break;
    }
  }
}

function inferAwaitingReviewLayer(state: PlanningState): number | null {
  if (!state.step_mode) return null;
  if (state.status === "revising" || state.status === "completed" || state.status === "failed") return null;
  // After approve the UI briefly shows planning while the backend resumes; do not
  // re-infer L1/L2 pause until an explicit interrupt or dimension_complete pause.
  if (state.status === "planning") return null;

  const hasBackendInterrupt =
    Boolean(state.humanReview?.event_id) ||
    Boolean(state.interruptInfo?.layer);
  const locallyPausedForReview =
    state.status === "paused"
    && (state.previous_layer > 0 || state.lastPauseLayer > 0);
  if (!hasBackendInterrupt && !locallyPausedForReview) return null;

  const executingDimensions = state.executingDimensions || [];
  if (executingDimensions.length > 0) return null;

  const phaseLayer = phaseToLayer(state.phase);
  const highestActive = getHighestActiveLayer(
    state.reports,
    state.dimensionProgress,
    executingDimensions,
    phaseLayer,
  );

  for (let layer = 3; layer >= 1; layer--) {
    if (!state.completedLayers[layer as 1 | 2 | 3]) continue;

    // Already working in a higher layer — do not re-prompt for L1/L2 review.
    if (layer < highestActive) continue;

    const nextLayer = layer + 1;
    if (nextLayer <= 3) {
      const nextStarted =
        nextLayer <= highestActive
        || layerHasActivity(nextLayer as 1 | 2 | 3, state.reports, state.dimensionProgress);
      if (nextStarted) continue;
    }

    return layer;
  }

  return null;
}

function deriveUIStateInStore(state: PlanningState): void {
  // Derive completedDimensions from reports, backend sync, and dimension progress.
  const newCompletedDimensions = deriveCompletedDimensions(
    state.reports,
    state.completedDimensions,
    state.dimensionProgress,
  );

  // Use stable reference if dimensions haven't changed
  if (
    !shallowEqualCompletedDimensions(
      newCompletedDimensions,
      state.completedDimensions,
    )
  ) {
    state.completedDimensions = newCompletedDimensions;
  }

  // Derive completedLayers: a layer is complete only when ALL dimensions are done
  const totalDims = (layer: number) =>
    state.layerDimensionCount[layer] || getDimensionsByLayer(layer).length;
  state.completedLayers = {
    1: state.completedDimensions.layer1.length >= totalDims(1) && totalDims(1) > 0,
    2: state.completedDimensions.layer2.length >= totalDims(2) && totalDims(2) > 0,
    3: state.completedDimensions.layer3.length >= totalDims(3) && totalDims(3) > 0,
  };

  // Durable event replay can contain optimistic/future progress from an old
  // client. The backend /state projection is authoritative for the active
  // stage, so later layers must not appear complete while l1/l2/l3 is active.
  const activeStageMatch = state.authoritativeActiveStage?.match(/^l([1-3])$/i);
  const activeStageLayer = activeStageMatch ? Number(activeStageMatch[1]) : null;
  if (activeStageLayer && state.status !== "completed") {
    for (let layer = activeStageLayer + 1; layer <= 3; layer += 1) {
      state.completedLayers[layer as 1 | 2 | 3] = false;
    }
  }

  // Derive pause state from explicit backend interrupt OR robust local inference.
  // The inference is important when layer_paused/layer_completed SSE is missed or page state is restored:
  // if a layer is complete and the next layer has not started, step mode means the UI must show review controls.
  const explicitPauseLayer =
    state.interruptInfo?.layer ||
    (state.lastPauseLayer > 0 ? state.lastPauseLayer : state.previous_layer);
  const inferredPauseLayer = inferAwaitingReviewLayer(state);

  state.isPaused = state.status === "paused" || inferredPauseLayer !== null;
  if (isL3HumanReview(state.humanReview)) {
    state.isPaused = true;
    state.pendingReviewLayer = 3;
    if (state.status !== "revising" && state.status !== "failed") {
      state.status = "paused";
    }
  }
  state.pendingReviewLayer =
    explicitPauseLayer && state.status === "paused"
      ? explicitPauseLayer
      : inferredPauseLayer;

  if (state.pendingReviewLayer && state.status !== "revising" && state.status !== "failed") {
    state.status = "paused";
  }

  // Derive currentLayer: prefer pendingReviewLayer when paused, else from phase
  const layerFromPhase = phaseToLayer(state.phase);
  state.currentLayer = state.pendingReviewLayer || layerFromPhase;
  state.currentPhase = state.currentLayer
    ? getLayerPhase(state.currentLayer)
    : "idle";
}

// ============================================
// Create Store
// ============================================

export const usePlanningStore = create<PlanningState & PlanningActions>()(
  immer((set, _get) => ({
    // Initial state
    ...createInitialState("default"),

    // Core setters
    setSessionId: (sessionId) =>
      set((state) => {
        state.sessionId = sessionId;
      }),

    setProjectName: (projectName) =>
      set((state) => {
        state.projectName = projectName;
      }),

    setStatus: (status) =>
      set((state) => {
        state.status = status;
        deriveUIStateInStore(state);
      }),

    setPhase: (phase) =>
      set((state) => {
        state.phase = phase;
      }),

    // Messages
    addMessage: (message) =>
      set((state) => {
        state.messages.push(message);
      }),

    addMessages: (messages) =>
      set((state) => {
        state.messages.push(...messages);
      }),

    setMessages: (messages) =>
      set((state) => {
        state.messages = messages;
      }),

    updateLastMessage: (updates) =>
      set((state) => {
        if (state.messages.length === 0) return;
        const lastMessage = state.messages[state.messages.length - 1];
        Object.assign(lastMessage, updates);
      }),

    setRevisionDraft: (draft) =>
      set((state) => {
        state.revisionDraft = draft;
      }),

    clearRevisionDraft: () =>
      set((state) => {
        state.revisionDraft = null;
      }),

    requestPlanningTextRegen: (changedDimensions) =>
      set((state) => {
        state.planningTextRegenRequest = {
          token: Date.now(),
          changedDimensions,
        };
      }),

    clearPlanningTextRegenRequest: () =>
      set((state) => {
        state.planningTextRegenRequest = null;
      }),

    dismissLlmHealthBanner: () =>
      set((state) => {
        state.llmHealthDismissed = true;
        state.llmHealthStatus = null;
        state.llmHealthMessage = null;
      }),

    scanOfflineReports: () =>
      set((state) => {
        scanReportsForOfflineTemplates(state);
      }),

    clearMessages: () =>
      set((state) => {
        state.messages = [];
      }),

    // Progress
    updateDimensionProgress: (key, updates) =>
      set((state) => {
        const existing = state.dimensionProgress[key];
        if (existing) {
          // Skip update for small wordCount changes
          if (
            updates.wordCount !== undefined &&
            existing.wordCount !== undefined
          ) {
            if (Math.abs(existing.wordCount - (updates.wordCount || 0)) < 50) {
              return;
            }
          }
          Object.assign(existing, updates);
        } else {
          state.dimensionProgress[key] = {
            dimensionKey: updates.dimensionKey || "",
            dimensionName: updates.dimensionName || "",
            layer: updates.layer || 0,
            status: updates.status || "pending",
            wordCount: updates.wordCount || 0,
            ...updates,
          };
        }
      }),

    setDimensionStreaming: (layer, dimensionKey, dimensionName) =>
      set((state) => {
        const key = `${layer}_${dimensionKey}`;
        const currentExecuting = state.executingDimensions;
        const alreadyExecuting = currentExecuting.includes(key);

        state.dimensionProgress[key] = {
          dimensionKey,
          dimensionName,
          layer,
          status: "streaming" as DimensionStatus,
          wordCount: 0,
          startedAt: new Date().toISOString(),
        };

        if (!alreadyExecuting) {
          state.executingDimensions.push(key);
        }
        state.currentPhase = getLayerPhase(layer);
      }),

    setDimensionCompleted: (layer, dimensionKey, wordCount) =>
      set((state) => {
        const key = `${layer}_${dimensionKey}`;
        const existing = state.dimensionProgress[key];
        if (!existing) return;

        existing.status = "completed" as DimensionStatus;
        existing.wordCount = wordCount;
        existing.completedAt = new Date().toISOString();

        state.executingDimensions = state.executingDimensions.filter(
          (k) => k !== key,
        );
      }),

    clearDimensionProgress: () =>
      set((state) => {
        state.dimensionProgress = {};
        state.executingDimensions = [];
        state.currentPhase = "idle";
      }),

    setDimensionProgressBatch: (updates) =>
      set((state) => {
        Object.assign(state.dimensionProgress, updates);
      }),

    // Layer & Reports
    setLayerCompleted: (layer, completed) =>
      set((state) => {
        (state.completedLayers as Record<number, boolean>)[layer] = completed;
      }),

    setReports: (reports) =>
      set((state) => {
        for (const [layerKey, layerReports] of Object.entries(reports)) {
          const key = layerKey as keyof Reports;
          if (!layerReports || typeof layerReports !== 'object') continue;
          if (!state.reports[key]) state.reports[key] = {};
          Object.assign(state.reports[key], layerReports);
        }
        deriveUIStateInStore(state);
      }),

    setCompletedDimensions: (completedDimensions) =>
      set((state) => {
        state.completedDimensions = completedDimensions;
      }),

    clearDimensionReport: (layer, dimensionKey) =>
      set((state) => {
        const layerKey = `layer${layer}` as "layer1" | "layer2" | "layer3";
        if (state.reports[layerKey]) {
          delete state.reports[layerKey][dimensionKey];
        }
        delete state.streamingContent[`${layer}_${dimensionKey}`];
      }),

    // Backend sync
    syncBackendState: (backendData) =>
      set((state) => {
        const hasAuthoritativeStage = backendData.active_stage !== undefined;
        const normalizedStatus = normalizePlanningStatus(backendData.status);
        const hasStatusChange =
          normalizedStatus !== undefined && normalizedStatus !== state.status;
        const hasPhaseChange = backendData.phase !== state.phase;
        const hasInterruptInfoChange =
          backendData.interrupt_info !== undefined &&
          JSON.stringify(backendData.interrupt_info) !== JSON.stringify(state.interruptInfo);
        const hasPreviousLayerChange =
          backendData.previous_layer !== state.previous_layer;
        const hasWaveChange = backendData.current_wave !== state.currentWave;
        const hasStepModeChange =
          backendData.step_mode !== undefined &&
          Boolean(backendData.step_mode) !== state.step_mode;
        const hasRagConfigChange =
          backendData.rag_layer_config &&
          (backendData.rag_layer_config[1] !== state.ragLayerConfig[1] ||
            backendData.rag_layer_config[2] !== state.ragLayerConfig[2] ||
            backendData.rag_layer_config[3] !== state.ragLayerConfig[3]);
        const hasGisLayoutToRestore =
          Array.isArray(backendData.gis_layout_configs) &&
          backendData.gis_layout_configs.length > 0 &&
          Object.keys(state.gisLayers).length === 0;
        const hasProjectContextChange = Boolean(
          (backendData.project_name && backendData.project_name !== state.projectName) ||
          (backendData.village_name && backendData.village_name !== state.villageName) ||
          (backendData.province && backendData.province !== state.province) ||
          (backendData.city && backendData.city !== state.city) ||
          (backendData.county && backendData.county !== state.county) ||
          (backendData.township && backendData.township !== state.township) ||
          (backendData.planning_period &&
            backendData.planning_period !== state.planningPeriod) ||
          (backendData.completed_dimensions &&
            JSON.stringify(backendData.completed_dimensions) !==
              JSON.stringify(state.completedDimensions)),
        );

        if (
          !hasStatusChange &&
          !hasPhaseChange &&
          !hasInterruptInfoChange &&
          !hasPreviousLayerChange &&
          !hasWaveChange &&
          !hasStepModeChange &&
          !hasRagConfigChange &&
          !hasGisLayoutToRestore &&
          !hasProjectContextChange &&
          !hasAuthoritativeStage
        ) {
          return;
        }

        // 使用后端 status（归一化 running/pending → planning）或从 phase 派生
        if (normalizedStatus) {
          state.status = normalizedStatus;
        }
        if (backendData.phase) state.phase = backendData.phase;
        if (backendData.active_stage !== undefined) {
          state.authoritativeActiveStage = backendData.active_stage || null;
        }
        if (backendData.current_wave)
          state.currentWave = backendData.current_wave;

        // v1 SessionProjection fields: authoritative delivery / review flags.
        if (backendData.delivery_status !== undefined) {
          if (!state.delivery) {
            state.delivery = {
              available: false,
              delivery_status: backendData.delivery_status,
              statutory_complete: false,
              snapshot_checksum: '',
              deferral_summary: {},
              diagnostic_summary: {},
              deliverables: [],
              downloads: [],
            };
          }
          const delivery = state.delivery;
          delivery.delivery_status = backendData.delivery_status;
          delivery.available = backendData.delivery_status !== null;
          if (backendData.delivery_status === 'diagnostic_only') {
            state.status = 'failed';
            state.isPaused = false;
            state.pendingReviewLayer = null;
            state.executingDimensions = [];
            state.gisGenerating = false;
            state.gisTriggerPending = false;
            state.delivery = null;
          }
        }
        if (backendData.statutory_complete !== undefined && state.delivery) {
          state.delivery.statutory_complete = backendData.statutory_complete;
        }
        if (backendData.human_review_pending !== undefined) {
          state.isPaused = backendData.human_review_pending;
          if (backendData.human_review_pending && !state.humanReview) {
            state.humanReview = { event_id: null, paused_stage: '', items: [] };
          }
        }
        if (backendData.phase && isSpatialWorkflowPhase(backendData.phase)) {
          // Entering a spatial phase should keep the map tab active, but it
          // must not re-arm the one-shot GIS probe on every status poll.
          state.isRightPanelExpanded = true;
          state.processPanelTab = "map";
        }
        // Note: reports 不再从后端同步，前端通过 SSE 或 API 获取
        if (backendData.completed_dimensions) {
          const completedData = backendData.completed_dimensions as Record<
            string,
            string[]
          >;
          if (completedData.layer1)
            state.completedDimensions.layer1 = completedData.layer1;
          if (completedData.layer2)
            state.completedDimensions.layer2 = completedData.layer2;
          if (completedData.layer3)
            state.completedDimensions.layer3 = completedData.layer3;
        }
        if (backendData.interrupt_info !== undefined) {
          state.interruptInfo = backendData.interrupt_info as PlanningState['interruptInfo'];
        }
        if (backendData.previous_layer)
          state.previous_layer = backendData.previous_layer;
        // step_mode is restored from status above so the toggle matches the
        // running session (and review pauses are not silent).
        if (hasRagConfigChange) {
          state.ragLayerConfig = {
            ...state.ragLayerConfig,
            ...backendData.rag_layer_config!,
          };
        }
        if (backendData.last_checkpoint_id)
          state.selectedCheckpoint = backendData.last_checkpoint_id;

        // Keep the toggle in sync with the live session so UI does not claim
        // continuous mode while the backend is actually paused for review.
        if (backendData.step_mode !== undefined) {
          state.step_mode = Boolean(backendData.step_mode);
        }

        // 同步项目上下文（页面刷新 / 历史恢复）
        if (backendData.project_name) {
          state.projectName = backendData.project_name;
        }
        if (backendData.village_name !== undefined)
          state.villageName = backendData.village_name || undefined;
        if (backendData.province !== undefined)
          state.province = backendData.province || undefined;
        if (backendData.city !== undefined)
          state.city = backendData.city || undefined;
        if (backendData.county !== undefined)
          state.county = backendData.county || undefined;
        if (backendData.township !== undefined)
          state.township = backendData.township || undefined;
        if (backendData.planning_period !== undefined)
          state.planningPeriod = backendData.planning_period || undefined;

        if (hasGisLayoutToRestore) {
          restoreGisLayersFromStatus(state, backendData.gis_layout_configs);
        }

        deriveUIStateInStore(state);
      }),

    // ============================================
    // NEW: hydrateFromStateSync (for SSE reconnect)
    // ============================================
    hydrateFromStateSync: (data) =>
      set((state) => {
        // Hydrate from state_sync SSE event
        if (data.phase) state.phase = data.phase as string;
        if (data.current_wave) state.currentWave = data.current_wave as number;
        if (data.reports) {
          const reportsData = data.reports as Record<
            string,
            Record<string, string>
          >;
          if (reportsData.layer1) state.reports.layer1 = reportsData.layer1;
          if (reportsData.layer2) state.reports.layer2 = reportsData.layer2;
          if (reportsData.layer3) state.reports.layer3 = reportsData.layer3;
        }
        if (data.interrupt_info !== undefined) {
          state.interruptInfo = data.interrupt_info as PlanningState['interruptInfo'];
        }
        if (data.previous_layer !== undefined) {
          state.previous_layer = data.previous_layer as number;
        }
        if (data.step_mode !== undefined) {
          state.step_mode = data.step_mode as boolean;
        }
        if (data.gis_layout_configs) {
          restoreGisLayersFromStatus(state, data.gis_layout_configs);
        }
        deriveUIStateInStore(state);
      }),

    // ============================================
    // RAG Actions
    // ============================================
    setRagQuery: (dimKey, query) =>
      set((state) => {
        state.dimensionRagSources[dimKey] = {
          query,
          documents: state.dimensionRagSources[dimKey]?.documents || [],
        };
      }),

    setRagDocuments: (dimKey, documents) =>
      set((state) => {
        state.dimensionRagSources[dimKey] = {
          query: state.dimensionRagSources[dimKey]?.query || "",
          documents,
        };
      }),

    clearRagSources: (dimKey) =>
      set((state) => {
        delete state.dimensionRagSources[dimKey];
      }),

    clearAllRagSources: () =>
      set((state) => {
        state.dimensionRagSources = {};
      }),

    // ============================================
    // NEW: Cascade Actions
    // ============================================
    showCascadeChain: (trigger, impacted) =>
      set((state) => {
        state.cascadeChain = { trigger, impacted };
      }),

    clearCascadeChain: () =>
      set((state) => {
        state.cascadeChain = null;
      }),

    setStreamingContent: (dimKey, content) =>
      set((state) => {
        state.streamingContent[dimKey] = content;
      }),

    clearStreamingContent: (dimKey) =>
      set((state) => {
        delete state.streamingContent[dimKey];
      }),

    // ============================================
    // NEW: Simplified Tool Actions
    // ============================================
    addRunningTool: (toolName) =>
      set((state) => {
        if (!state.runningTools.includes(toolName)) {
          state.runningTools.push(toolName);
        }
      }),

    removeRunningTool: (toolName) =>
      set((state) => {
        state.runningTools = state.runningTools.filter((t) => t !== toolName);
      }),

    // UI State
    setViewerVisible: (visible) =>
      set((state) => {
        state.viewerVisible = visible;
      }),

    setViewingFile: (file) =>
      set((state) => {
        state.viewingFile = file;
      }),

    setPaused: (paused) =>
      set((state) => {
        state.isPaused = paused;
        if (!paused) {
          state.lastPauseLayer = 0;
        }
        deriveUIStateInStore(state);
      }),

    setPendingReviewLayer: (layer) =>
      set((state) => {
        state.pendingReviewLayer = layer;
      }),

    setVillageFormData: (data) =>
      set((state) => {
        state.villageFormData = data;
      }),

    setProgressPanelVisible: (visible) =>
      set((state) => {
        state.progressPanelVisible = visible;
      }),

    setStepMode: (stepMode) =>
      set((state) => {
        state.step_mode = stepMode;
      }),

    // History
    setVillages: (villages) =>
      set((state) => {
        state.villages = filterDeletedHistory(villages, state.deletedSessionIds);
      }),

    removeSessionFromHistory: (sessionId) =>
      set((state) => {
        state.villages = state.villages
          .map((village) => {
            const sessions = village.sessions.filter((session) => session.session_id !== sessionId);
            if (sessions.length === village.sessions.length) return village;
            return {
              ...village,
              sessions,
              session_count: sessions.length,
            };
          })
          .filter((village) => village.sessions.length > 0);
      }),

    clearVillagesHistory: () =>
      set((state) => {
        state.villages = [];
      }),

    markSessionsDeleted: (sessionIds) =>
      set((state) => {
        for (const sessionId of sessionIds) {
          state.deletedSessionIds[sessionId] = true;
        }
        saveDeletedSessionIds(state.deletedSessionIds);
      }),

    unmarkSessionDeleted: (sessionId) =>
      set((state) => {
        delete state.deletedSessionIds[sessionId];
        saveDeletedSessionIds(state.deletedSessionIds);
      }),

    addSessionToHistory: ({ projectName, villageName, sessionId }) =>
      set((state) => {
        const session = {
          session_id: sessionId,
          timestamp: new Date().toISOString(),
          checkpoint_count: 0,
          has_final_report: false,
        };
        const existing = state.villages.find((village) => village.name === projectName);
        if (existing) {
          existing.sessions = [
            session,
            ...existing.sessions.filter((item) => item.session_id !== sessionId),
          ];
          existing.session_count = existing.sessions.length;
          if (villageName) existing.display_name = villageName;
          return;
        }
        state.villages.unshift({
          name: projectName,
          display_name: villageName || projectName,
          session_count: 1,
          sessions: [session],
        });
      }),

    setSelectedVillage: (village) =>
      set((state) => {
        state.selectedVillage = village;
        state.selectedSession = null;
      }),

    setSelectedSession: (session) =>
      set((state) => {
        state.selectedSession = session;
      }),

    setHistoryLoading: (loading) =>
      set((state) => {
        state.historyLoading = loading;
      }),

    setHistoryError: (error) =>
      set((state) => {
        state.historyError = error;
      }),

    setPendingHistoricalSessionId: (sessionId) =>
      set((state) => {
        state.pendingHistoricalSessionId = sessionId;
      }),

    // Checkpoints
    setCheckpoints: (checkpoints) =>
      set((state) => {
        state.checkpoints = checkpoints;
      }),

    setSelectedCheckpoint: (checkpointId) =>
      set((state) => {
        state.selectedCheckpoint = checkpointId;
      }),

    // Tools
    setToolStatus: (toolName, status) =>
      set((state) => {
        state.toolStatuses[toolName] = status;
      }),

    clearToolStatus: (toolName) =>
      set((state) => {
        delete state.toolStatuses[toolName];
      }),

    // SSE Event handling
    handleSSEEvent: (event) => {
      set((state) => {
        handleSSEEventInStore(state, event);
      });
      if (event.type === "human_review" || event.type === "human_review_paused") {
        const data = (event.data as Record<string, unknown>) || {};
        const hasItems = Array.isArray(data.items) && data.items.length > 0;
        const hasEventId = typeof data.event_id === "string" && data.event_id.length > 0;
        if (hasItems || hasEventId) {
          void _get().refreshHumanReview();
        }
      }
      if (event.type === "layer_paused") {
        void _get().refreshHumanReview();
      }
    },

    // SSE Reconnect trigger - increment to trigger reconnect
    triggerSseReconnect: () =>
      set((state) => {
        state.sseResumeTrigger += 1;
      }),

    // Clear progress state (used when approve/reject to wait for new layer)
    clearProgressState: () =>
      set((state) => {
        state.currentLayer = null;
        state.currentPhase = "idle";
        state.dimensionProgress = {};
        state.executingDimensions = [];
      }),

    addGisLayersFromUpload: (configs) =>
      set((state) => {
        // Status API returns gis_layout_configs as a direct layer array, while
        // older upload responses wrap layers inside { layers: [...] }.
        const directLayers = normalizeGisLayers(configs);
        if (directLayers.length > 0) {
          restoreGisLayersFromStatus(state, directLayers);
          return;
        }
        for (const cfg of configs) {
          const normalizedLayers = normalizeGisLayers(cfg.layers);
          if (normalizedLayers.length === 0) continue;
          const key = `upload_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
          state.gisLayers[key] = normalizedLayers;
        }
      }),

    // Clear only revision dimensions progress, preserve other completed dimensions
    clearRevisionProgress: (layer, dimensionsToRevise) =>
      set((state) => {
        if (!dimensionsToRevise || dimensionsToRevise.length === 0) {
          // If no dimensions specified, only clear executing state for this layer
          state.executingDimensions = state.executingDimensions.filter(
            (k) => !k.startsWith(`${layer}_`),
          );
          return;
        }

        // Clear progress for specified dimensions only
        for (const dimKey of dimensionsToRevise) {
          const progressKey = buildDimensionProgressKey(layer, dimKey);
          delete state.dimensionProgress[progressKey];
        }

        // Clear executing state for specified dimensions only (preserve other executing)
        const keysToRemove = dimensionsToRevise.map((dim) =>
          buildDimensionProgressKey(layer, dim),
        );
        state.executingDimensions = state.executingDimensions.filter(
          (k) => !keysToRemove.includes(k),
        );
        // Preserve currentLayer and currentPhase for UI display
      }),

    // Navigation
    setSelectedNavigationKey: (key) =>
      set((state) => {
        if (state.selectedNavigationKey === key) return;
        state.selectedNavigationKey = key;
      }),

    setRightPanelExpanded: (expanded) =>
      set((state) => {
        state.isRightPanelExpanded = expanded;
      }),

    setLeftNavCollapsed: (collapsed) =>
      set((state) => {
        state.isLeftNavCollapsed = collapsed;
      }),

    // ChatBar & ProcessPanel
    setProcessPanelTab: (tab) =>
      set((state) => {
        state.processPanelTab = tab;
      }),

    // GIS
    setFullMapOpen: (open) =>
      set((state) => {
        state.isFullMapOpen = open;
      }),

    // ============================================
    // Layer-level RAG Configuration
    // ============================================
    setRagLayerConfig: (config) =>
      set((state) => {
        state.ragLayerConfig = config;
      }),

    toggleLayerRag: (layer) =>
      set((state) => {
        state.ragLayerConfig[layer] = !state.ragLayerConfig[layer];
      }),

    // Reset
    resetSessionState: () => set(applySessionReset),

    resetConversation: () => set(applySessionReset),

    setLastProcessedSeq: (seq) =>
      set((state) => {
        if (seq > state.lastProcessedSeq) {
          state.lastProcessedSeq = seq;
        }
      }),

    // ============================================
    // Delivery & Artifact (v1)
    // ============================================
    setDelivery: (delivery) =>
      set((state) => {
        state.delivery = delivery;
      }),
    clearDelivery: () =>
      set((state) => {
        state.delivery = null;
      }),
    setResyncRequired: (required) =>
      set((state) => {
        state.resyncRequired = required;
      }),
    setHumanReview: (review) =>
      set((state) => {
        state.humanReview = review;
      }),
    clearHumanReview: () =>
      set((state) => {
        state.humanReview = null;
      }),
    refreshHumanReview: async (sessionId) => {
      const targetSessionId = sessionId ?? _get().sessionId;
      if (!targetSessionId) return;
      const { planningApi } = await import("../api");
      const review = await planningApi.getHumanReview(targetSessionId);
      set((state) => {
        applyHumanReviewResponse(state, review);
        deriveUIStateInStore(state);
      });
    },

    applyMapLayers: (layers, snapshotChecksum) =>
      set((state) => {
        if (layers.length === 0) return;
        // Replace the authoritative delivery snapshot wholesale keyed by checksum.
        // Do NOT merge with prior SSE deltas; a checksum change means a new snapshot.
        for (const key of Object.keys(state.gisLayers)) {
          if (
            key.startsWith("v1_") ||
            key.startsWith("status_") ||
            key.startsWith("result_") ||
            key.endsWith("_spatial_layout")
          ) {
            delete state.gisLayers[key];
          }
        }
        state.gisLayers[`v1_${snapshotChecksum || Date.now()}`] = layers;
        state.gisGenerating = false;
        state.gisTriggerPending = false;
        state.isRightPanelExpanded = true;
        state.processPanelTab = "map";
      }),

    initConversation: (conversationId) =>
      set((state) => {
        // Prevent re-initialization if conversationId matches and sessionId exists
        // This protects against StrictMode double-mount clearing restored sessionId
        if (state.conversationId === conversationId && state.sessionId) {
          return;
        }

        applySessionReset(state);
        state.conversationId = conversationId;
      }),
  })),
);

declare global {
  interface Window {
    __PLANNING_STORE__?: typeof usePlanningStore;
  }
}

// Expose store to window for Playwright E2E tests (dev/test only)
if (typeof window !== 'undefined' && process.env.NODE_ENV !== 'production') {
  window.__PLANNING_STORE__ = usePlanningStore;
}

// ============================================
// Selector Hooks (for performance)
// ============================================
