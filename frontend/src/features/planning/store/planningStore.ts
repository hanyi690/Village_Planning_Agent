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

import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import type {
  Message,
  DimensionProgressItem,
  DimensionStatus,
  Checkpoint,
  FileMessage,
  LayerCompletedMessage,
  DimensionReportMessage,
  KnowledgeSource,
} from '../types';
import type { GisResultMessage, ToolStatusMessage, GISLayerConfig } from '@/types/message/message-types';
import type { VillageInputData } from '../components/VillageInputForm';
import type { VillageInfo, VillageSession, SessionStatusResponse } from '../api';
import { getLayerPhase, PlanningStatus, LayerPhase, AgentPhase, NAV_KEYS } from '@/features/planning/constants';
import type { NavigationKey } from '@/features/planning/constants';

export type ProcessPanelTab = 'messages' | 'map' | 'history' | 'settings';
import {
  createBaseMessage,
  buildLayerReportId,
  buildRevisionReportId,
  buildDimensionProgressKey,
  formatDimensionReportsAsContent,
  calculateReportSummary,
} from '@/features/planning/utils/message-helpers';
import { DIMENSION_NAMES, getDimensionsByLayer } from '../config/dimensions';

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

interface LayerProgressSnapshot {
  completedAt: string;
  dimensionCount: number;
  completedCount: number;
  totalWordCount: number;
  dimensionDetails: DimensionProgressItem[];
}

interface ToolStatus {
  toolName: string;
  status: 'running' | 'success' | 'error';
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
  matched_query?: string;  // 匹配的查询语句
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

  // Agent State (Single Source of Truth)
  phase: string;
  currentWave: number;
  reports: Reports;
  pause_after_step: boolean;
  previous_layer: number;
  step_mode: boolean;
  execution_paused: boolean;

  // Derived UI State
  completedDimensions: CompletedDimensions;
  currentLayer: number | null;
  currentPhase: LayerPhase | '修复中';
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  isPaused: boolean;
  pendingReviewLayer: number | null;

  // SSE Reconnect
  sseResumeTrigger: number;
  lastProcessedSeq: number;

  // Messages
  messages: Message[];

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
  /** Version count per dimension (incremented on revision) */
  dimensionVersions: Record<string, number>;
  /** Streaming text content per dimension (temporary) */
  streamingContent: Record<string, string>;
  /** Dimensions currently being reset (cascade repair) */
  resettingDimensions: string[];
  /** Simplified running tool names (replaces full toolStatuses) */
  runningTools: string[];

  // UI State
  viewerVisible: boolean;
  referencedSection?: string;
  viewingFile: FileMessage | null;
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  villageFormData: VillageInputData | null;
  progressPanelVisible: boolean;
  layerReportVisible: boolean;
  activeReportLayer: number;

  // History
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  historyLoading: boolean;
  historyError: string | null;

  // Checkpoints
  checkpoints: Checkpoint[];
  selectedCheckpoint: string | null;
  loadingContent: boolean;
  deletingSessionId: string | null;

  // Tools (kept for backward compatibility, but runningTools is preferred)
  toolStatuses: Record<string, ToolStatus>;

  // GIS Layers (SSE-driven, no REST API needed)
  gisLayers: Record<string, GISLayerConfig[]>;

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

function deriveCompletedDimensions(reports: Reports): CompletedDimensions {
  return {
    layer1: Object.keys(reports.layer1 || {}),
    layer2: Object.keys(reports.layer2 || {}),
    layer3: Object.keys(reports.layer3 || {}),
  };
}

function shallowEqualCompletedDimensions(
  incoming: CompletedDimensions,
  current: CompletedDimensions
): boolean {
  const layers = ['layer1', 'layer2', 'layer3'] as const;
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
    status: 'idle',

    // Agent State
    phase: 'init',
    currentWave: 1,
    reports: { layer1: {}, layer2: {}, layer3: {} },
    pause_after_step: false,
    previous_layer: 0,
    step_mode: false,
    execution_paused: false,

    // Derived UI State
    completedDimensions: { layer1: [], layer2: [], layer3: [] },
    currentLayer: null,
    currentPhase: 'idle',
    completedLayers: { 1: false, 2: false, 3: false },
    isPaused: false,
    pendingReviewLayer: null,
    sseResumeTrigger: 0,
    lastProcessedSeq: 0,

    // Messages
    messages: [],

    // Progress
    dimensionProgress: {},
    executingDimensions: [],
    layerDimensionCount: {},
    runningTools: [],
    resettingDimensions: [],

    // NEW: RAG & Cascade Tracking
    dimensionRagSources: {},
    cascadeChain: null,
    dimensionVersions: {},
    streamingContent: {},

    // UI State
    viewerVisible: false,
    referencedSection: undefined,
    viewingFile: null,
    viewMode: 'WELCOME_FORM',
    villageFormData: null,
    progressPanelVisible: false,
    layerReportVisible: false,
    activeReportLayer: 1,

    // History
    villages: [],
    selectedVillage: null,
    selectedSession: null,
    historyLoading: false,
    historyError: null,

    // Checkpoints
    checkpoints: [],
    selectedCheckpoint: null,
    loadingContent: false,
    deletingSessionId: null,

    // Tools
    toolStatuses: {},
    // GIS Layers (SSE-driven)
    gisLayers: {},

    // Three-Panel Layout
    selectedNavigationKey: null,
    isRightPanelExpanded: true,
    isLeftNavCollapsed: false,

    // ProcessPanel
    processPanelTab: 'messages',

    // Layer-level RAG config (default: all enabled)
    ragLayerConfig: { 1: true, 2: true, 3: true },
  };
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

  // Progress
  updateDimensionProgress: (key: string, updates: Partial<DimensionProgressItem>) => void;
  setDimensionStreaming: (layer: number, dimensionKey: string, dimensionName: string) => void;
  setDimensionCompleted: (layer: number, dimensionKey: string, wordCount: number) => void;
  clearDimensionProgress: () => void;
  setDimensionProgressBatch: (updates: Record<string, DimensionProgressItem>) => void;

  // Layer & Reports
  setLayerCompleted: (layer: number, completed: boolean) => void;
  setReports: (reports: Partial<Reports>) => void;
  setCompletedDimensions: (completedDimensions: CompletedDimensions) => void;

  // Backend sync
  syncBackendState: (backendData: Partial<SessionStatusResponse> & { version?: number }) => void;
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
  incrementDimensionVersion: (dimKey: string) => void;
  setStreamingContent: (dimKey: string, content: string) => void;
  clearStreamingContent: (dimKey: string) => void;
  markDimensionResetting: (dimKey: string) => void;
  finishDimensionResetting: (dimKey: string) => void;

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
  setSelectedVillage: (village: VillageInfo | null) => void;
  setSelectedSession: (session: VillageSession | null) => void;
  setHistoryLoading: (loading: boolean) => void;
  setHistoryError: (error: string | null) => void;

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

  // Clear only revision dimensions progress (preserve other completed dimensions)
  clearRevisionProgress: (layer: number, dimensionsToRevise: string[]) => void;

  // Navigation
  setSelectedNavigationKey: (key: NavigationKey | null) => void;
  setRightPanelExpanded: (expanded: boolean) => void;
  setLeftNavCollapsed: (collapsed: boolean) => void;

  // ProcessPanel
  setProcessPanelTab: (tab: ProcessPanelTab) => void;

  // ============================================
  // NEW: Layer-level RAG Configuration
  // ============================================
  setRagLayerConfig: (config: Record<number, boolean>) => void;
  toggleLayerRag: (layer: number) => void;

  // Reset
  resetConversation: () => void;
  initConversation: (conversationId: string) => void;
}

// ============================================
// SSE Event Handler
// ============================================

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
    case 'connected': {
      state.status = 'planning';
      const connData = data as { task_id?: string };
      if (connData.task_id && !state.sessionId) {
        state.sessionId = connData.task_id;
      }
      break;
    }

    case 'completed': {
      state.status = 'completed';
      break;
    }

    case 'dimension_error': {
      const errData = data as {
        dimension_key?: string;
        dimension_name?: string;
        error?: string;
        error_type?: string;
        layer?: number;
      };
      const layer = errData.layer || 1;
      const key = `${layer}_${errData.dimension_key || ''}`;

      state.dimensionProgress[key] = {
        dimensionKey: errData.dimension_key || '',
        dimensionName: errData.dimension_name || '',
        layer,
        status: 'failed' as DimensionStatus,
        wordCount: 0,
        error: errData.error || 'Unknown error',
      };

      state.executingDimensions = state.executingDimensions.filter((k) => k !== key);
      break;
    }

    case 'dimension_start': {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        layer?: number;
        is_revision?: boolean;
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || '';
      const key = buildDimensionProgressKey(layer, dimensionKey);

      // Track executing dimension (no longer create standalone message)
      state.executingDimensions.push(key);

      // Initialize dimensionProgress for progress tracking
      state.dimensionProgress[key] = {
        dimensionKey,
        dimensionName: dimData.dimension_name || '',
        layer,
        status: 'streaming' as DimensionStatus,
        wordCount: 0,
        isRevision: dimData.is_revision || false,
      };

      // If this is a revision, create a standalone revision_report message
      if (dimData.is_revision && dimensionKey) {
        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const existingMessage = state.messages.find(
          (m) => m.id === revisionReportId && m.type === 'dimension_report'
        );
        if (!existingMessage) {
          const baseMsg = createBaseMessage('assistant');
          const newMessage: DimensionReportMessage = {
            ...baseMsg,
            id: revisionReportId,
            type: 'dimension_report',
            layer: layer,
            dimensionKey,
            dimensionName: dimData.dimension_name || '',
            content: '',
            streamingState: 'streaming',
            wordCount: 0,
            isRevision: true,
          };
          state.messages.push(newMessage);
        }
      }
      break;
    }

    case 'dimension_delta': {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        delta?: string;
        accumulated?: string;
        layer?: number;
        is_revision?: boolean;
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || '';
      const key = buildDimensionProgressKey(layer, dimensionKey);

      // If this is a revision, update the standalone revision_report message
      if (dimData.is_revision && dimensionKey && dimData.accumulated) {
        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const msgIdx = state.messages.findIndex(
          (m) => m.id === revisionReportId && m.type === 'dimension_report'
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
        break;
      }

      // 1. Update reports state
      const layerKey = `layer${layer}` as keyof Reports;
      if (dimensionKey && dimData.accumulated) {
        state.reports[layerKey][dimensionKey] = dimData.accumulated;
      }

      // 2. Update layer_report message's dimensionReports for real-time display
      const layerReportId = buildLayerReportId(layer);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === 'layer_completed'
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
            status: 'streaming' as DimensionStatus,
            wordCount: dimData.accumulated.length,
          };
          if (!state.executingDimensions.includes(key)) {
            state.executingDimensions.push(key);
          }
        }
      }
      break;
    }

    case 'dimension_complete': {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        full_content?: string;
        word_count?: number;
        layer?: number;
        is_revision?: boolean;
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
      const dimensionKey = dimData.dimension_key || '';
      const key = buildDimensionProgressKey(layer, dimensionKey);

      // 获取内容：优先使用 full_content，否则从 reports 状态获取（dimension_delta 已累积）
      const lk = `layer${layer}` as keyof Reports;
      const content = dimData.full_content || state.reports[lk]?.[dimensionKey] || '';

      // Update dimensionProgress
      state.dimensionProgress[key] = {
        dimensionKey,
        dimensionName: dimData.dimension_name || '',
        layer,
        status: 'completed' as DimensionStatus,
        wordCount: dimData.word_count || content.length,
        completedAt: new Date().toISOString(),
        isRevision: dimData.is_revision || false,
      };

      // Remove from executing
      state.executingDimensions = state.executingDimensions.filter((k) => k !== key);

      // If this is a revision, complete the standalone revision_report message
      if (dimData.is_revision && dimensionKey) {
        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const msgIdx = state.messages.findIndex(
          (m) => m.id === revisionReportId && m.type === 'dimension_report'
        );
        if (msgIdx >= 0) {
          const msg = state.messages[msgIdx] as DimensionReportMessage;
          msg.content = content;
          msg.wordCount = content.length;
          msg.streamingState = 'completed';
        }
        // Update reports state for revision as well
        const layerKey = `layer${layer}` as keyof Reports;
        state.reports[layerKey][dimensionKey] = content;
        break;
      }

      // Update reports
      const layerKey = `layer${layer}` as keyof Reports;
      state.reports[layerKey][dimensionKey] = content;

      // Update layer_report message (no longer create standalone dimension_report)
      const layerReportId = buildLayerReportId(layer);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === 'layer_completed'
      );

      if (layerMsgIdx >= 0) {
        const layerMsg = state.messages[layerMsgIdx] as LayerCompletedMessage;
        // Initialize dimensionReports if undefined
        if (!layerMsg.dimensionReports) {
          layerMsg.dimensionReports = {};
        }
        layerMsg.dimensionReports[dimensionKey] = content;

        // Update fullReportContent and summary using utility functions
        layerMsg.fullReportContent = formatDimensionReportsAsContent(layerMsg.dimensionReports);
        const summary = calculateReportSummary(layerMsg.dimensionReports, layerMsg.dimensionSummaries);
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
            dimension_key: dimData.structured_summary.dimension_key || dimensionKey,
          };
          layerMsg.dimensionSummaries[dimensionKey] = summary;
          // Merge key_points into layer summary
          layerMsg.summary.key_points = Object.values(layerMsg.dimensionSummaries)
            .flatMap(s => s.key_points || [])
            .slice(0, 10);
        }

        // GIS data is now sent via independent gis_result events after review
        // Remove gis_data handling from dimension_complete

        // Store knowledge_sources to layer_completed message
        if (dimData.knowledge_sources && dimData.knowledge_sources.length > 0) {
          if (!layerMsg.dimensionKnowledgeSources) {
            layerMsg.dimensionKnowledgeSources = {};
          }
          layerMsg.dimensionKnowledgeSources[dimensionKey] = dimData.knowledge_sources;
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
      const completedCountForLayer = state.completedDimensions[layerKey]?.length || 0;
      const expectedCount =
        state.layerDimensionCount[layer] || getDimensionsByLayer(layer).length;

      if (
        completedCountForLayer >= expectedCount &&
        expectedCount > 0 &&
        !state.pause_after_step &&
        state.status !== 'paused'
      ) {
        state.pause_after_step = true;
        state.previous_layer = layer;
        state.status = 'paused';
        deriveUIStateInStore(state); // 重新派生 isPaused / pendingReviewLayer
      }
      break;
    }

    case 'layer_started': {
      const layerData = data as {
        layer?: number;
        layer_number?: number;
        dimension_count?: number;
      };
      const layerNum = layerData.layer || layerData.layer_number || 1;

      // Core: Update phase first, then derive UI state from it
      state.phase = `layer${layerNum}`;

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
          ([key]) => !key.startsWith(`${layerNum}_`)
        )
      );
      state.executingDimensions = state.executingDimensions.filter(
        (k) => !k.startsWith(`${layerNum}_`)
      );

      // Create layer_report message framework for real-time streaming
      // Key: Do NOT overwrite existing message - protect content from history restore or SSE reconnect
      const layerReportId = buildLayerReportId(layerNum);
      const existingMessage = state.messages.find(
        (m) => m.id === layerReportId && m.type === 'layer_completed'
      );

      if (!existingMessage) {
        // Only create new message framework if it doesn't exist
        const baseMsg = createBaseMessage('assistant');
        const newMessage: LayerCompletedMessage = {
          ...baseMsg,
          id: layerReportId,
          type: 'layer_completed',
          layer: layerNum,
          content: '',
          summary: {
            word_count: 0,
            key_points: [],
            dimension_count: 0,
          },
          fullReportContent: '',
          dimensionReports: {},
          actions: [],
        };
        state.messages.push(newMessage);
      }
      // If message exists (history restore or SSE reconnect), preserve its content unchanged

      // Auto-navigate to overview when new layer starts (guard against no-op)
      if (state.selectedNavigationKey !== NAV_KEYS.OVERVIEW) {
        state.selectedNavigationKey = NAV_KEYS.OVERVIEW;
      }

      // Derive UI state from phase (currentLayer, currentPhase, completedLayers, etc.)
      deriveUIStateInStore(state);
      break;
    }

    case 'layer_completed': {
      const layerData = data as {
        layer?: number;
        phase?: string;
        dimension_reports?: Record<string, string>;
        dimension_knowledge_sources?: Record<string, KnowledgeSource[]>;
        pause_after_step?: boolean;
        previous_layer?: number;
        task_id?: string;
      };

      if (layerData.task_id && !state.sessionId) {
        state.sessionId = layerData.task_id;
      }

      const layerNum = layerData.layer || 1;
      const layerKey = `layer${layerNum}` as keyof Reports;

      if (layerData.dimension_reports && Object.keys(layerData.dimension_reports).length > 0) {
        Object.assign(state.reports[layerKey], layerData.dimension_reports);
      }

      state.phase = layerData.phase || state.phase;
      state.pause_after_step = layerData.pause_after_step ?? state.pause_after_step;
      state.previous_layer = layerData.previous_layer ?? state.previous_layer;
      state.status = 'paused';

      // Finalize layer_report message (merge any remaining dimension_reports from SSE)
      const layerReportId = buildLayerReportId(layerNum);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === 'layer_completed'
      );

      if (layerMsgIdx >= 0 && layerData.dimension_reports) {
        const layerMsg = state.messages[layerMsgIdx] as LayerCompletedMessage;
        // Initialize dimensionReports if undefined
        if (!layerMsg.dimensionReports) {
          layerMsg.dimensionReports = {};
        }
        Object.assign(layerMsg.dimensionReports, layerData.dimension_reports);

        // Update fullReportContent and summary using utility functions
        layerMsg.fullReportContent = formatDimensionReportsAsContent(layerMsg.dimensionReports);
        const summary = calculateReportSummary(layerMsg.dimensionReports, layerMsg.dimensionSummaries);
        layerMsg.summary.word_count = summary.word_count;
        layerMsg.summary.dimension_count = summary.dimension_count;
        if (summary.key_points.length > 0) {
          layerMsg.summary.key_points = summary.key_points;
        }

        // Update knowledge sources if provided
        if (layerData.dimension_knowledge_sources) {
          layerMsg.dimensionKnowledgeSources = layerMsg.dimensionKnowledgeSources ?? {};
          Object.assign(layerMsg.dimensionKnowledgeSources, layerData.dimension_knowledge_sources);
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
            status: 'completed' as DimensionStatus,
            wordCount: (layerData.dimension_reports[dimKey] || '').length,
            completedAt: new Date().toISOString(),
          };
        }
        // Clear executing dimensions for this layer
        state.executingDimensions = state.executingDimensions.filter(
          (k) => !k.startsWith(`${layerNum}_`)
        );
      }

      // Derive UI state from phase and pause state (currentLayer, currentPhase, etc.)
      deriveUIStateInStore(state);
      break;
    }

    case 'layer_paused': {
      state.execution_paused = true;
      state.pause_after_step = true;
      state.status = 'paused';
      deriveUIStateInStore(state);
      break;
    }

    case 'execution_resumed': {
      state.execution_paused = false;
      state.pause_after_step = false;
      state.isPaused = false;
      state.pendingReviewLayer = null;
      state.status = 'planning';
      deriveUIStateInStore(state);
      break;
    }

    case 'tool_call': {
      const toolData = data as {
        tool_name?: string;
        tool_display_name?: string;
        description?: string;
        estimated_time?: number;
        stage?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      state.toolStatuses[toolName] = {
        toolName,
        status: 'running',
        stage: toolData.stage,
        message: toolData.description,
      };

      // Auto-switch to messages tab and expand right panel
      state.processPanelTab = 'messages';
      state.isRightPanelExpanded = true;
      break;
    }

    case 'tool_progress': {
      const toolData = data as {
        tool_name?: string;
        stage?: string;
        progress?: number;
        message?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      const existing = state.toolStatuses[toolName];
      if (!existing) return;

      existing.stage = toolData.stage || existing.stage;
      existing.progress = toolData.progress;
      existing.message = toolData.message;
      break;
    }

    case 'tool_result': {
      const toolData = data as {
        tool_name?: string;
        status?: string;
        summary?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      const existing = state.toolStatuses[toolName];
      if (!existing) return;

      existing.status = toolData.status === 'error' ? 'error' : 'success';
      existing.summary = toolData.summary;
      break;
    }

    // ============================================
    // New Unified Tool Events (tool_started, tool_status)
    // ============================================

    case 'tool_started': {
      const toolData = data as {
        tool_name?: string;
        tool_display_name?: string;
        description?: string;
        estimated_time?: number;
        status?: string;
        started_at?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      const baseMsg = createBaseMessage('assistant');
      const newMessage: ToolStatusMessage = {
        ...baseMsg,
        id: `tool_${toolName}_${Date.now()}`,
        type: 'tool_status',
        toolName,
        toolDisplayName: toolData.tool_display_name || toolName,
        description: toolData.description || '',
        status: 'running',
        estimatedTime: toolData.estimated_time,
        startedAt: toolData.started_at,
      };
      state.messages.push(newMessage);

      state.toolStatuses[toolName] = {
        toolName,
        status: 'running',
        message: toolData.description,
      };
      break;
    }

    case 'tool_status': {
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
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      const msgIdx = state.messages.findIndex(
        (m) => m.type === 'tool_status' && (m as ToolStatusMessage).toolName === toolName
      );

      if (msgIdx >= 0) {
        const msg = state.messages[msgIdx] as ToolStatusMessage;
        msg.status = (toolData.status as ToolStatusMessage['status']) || msg.status;
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
          toolData.status === 'error'
            ? 'error'
            : toolData.status === 'success'
              ? 'success'
              : 'running';
        if (toolData.progress !== undefined) existing.progress = toolData.progress;
        if (toolData.stage) existing.stage = toolData.stage;
        if (toolData.stage_message) existing.message = toolData.stage_message;
        if (toolData.summary) existing.summary = toolData.summary;
      }
      break;
    }

    // ============================================
    // GIS Result Event
    // ============================================

    case 'gis_result': {
      const gisData = data as {
        dimension_key?: string;
        dimension_name?: string;
        summary?: string;
        layers?: unknown[];
        map_options?: { center?: [number, number]; zoom?: number };
        analysis_data?: {
          overall_score?: number;
          suitability_level?: string;
          sensitivity_class?: string;
          recommendations?: string[];
        };
      };
      const dimensionKey = gisData.dimension_key || '';
      if (!dimensionKey) return;

      const baseMsg = createBaseMessage('assistant');
      const newMessage: GisResultMessage = {
        ...baseMsg,
        id: `gis_${dimensionKey}_${Date.now()}`,
        type: 'gis_result',
        dimensionKey,
        dimensionName: gisData.dimension_name || dimensionKey,
        summary: gisData.summary || '',
        layers: (gisData.layers as GisResultMessage['layers']) || [],
        mapOptions:
          gisData.map_options?.center && gisData.map_options?.zoom
            ? { center: gisData.map_options.center, zoom: gisData.map_options.zoom }
            : undefined,
        analysisData: gisData.analysis_data,
      };
      state.messages.push(newMessage);
      break;
    }

    case 'ai_response_complete': {
      const aiData = data as { content?: string };
      const aiMessage = {
        id: `ai_${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant' as const,
        type: 'text' as const,
        content: aiData.content || '',
      };
      state.messages.push(aiMessage);
      break;
    }

    case 'pause': {
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

      state.pause_after_step = true;
      state.previous_layer =
        pauseData.current_layer || pauseData.previous_layer || state.previous_layer;
      state.status = 'paused';

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
            type: 'key',
            phase: state.phase,
          });
        }
      }

      deriveUIStateInStore(state);
      break;
    }

    case 'resumed': {
      state.pause_after_step = false;
      state.previous_layer = 0;
      state.status = 'planning';

      deriveUIStateInStore(state);
      break;
    }

    case 'revision_completed': {
      const revData = data as {
        layer?: number;
        revised_dimensions?: string[];
        previous_layer?: number;
      };

      state.pause_after_step = true;
      state.previous_layer = revData.previous_layer || revData.layer || 0;
      state.status = 'paused';

      deriveUIStateInStore(state);
      break;
    }

    case 'checkpoint_saved': {
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
      const cpType: 'key' | 'regular' = cpData.checkpoint_type === 'key' ? 'key' : 'regular';

      const existingIndex = state.checkpoints.findIndex((cp) => cp.layer === layer);
      const newCheckpoint = {
        checkpoint_id: cpData.checkpoint_id || '',
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
    case 'rag_query': {
      const ragData = data as {
        dimension_key?: string;
        query?: string;
        layer?: number;
      };
      const dimKey = ragData.dimension_key || '';
      if (dimKey && ragData.query) {
        const fullKey = `${ragData.layer || 1}_${dimKey}`;
        state.dimensionRagSources[fullKey] = {
          query: ragData.query,
          documents: state.dimensionRagSources[fullKey]?.documents || [],
        };
      }
      break;
    }
    case 'rag_result': {
      const ragData = data as {
        dimension_key?: string;
        query?: string;
        query_generation_method?: string;
        retrieval_latency_ms?: number;
        total_results?: number;
        documents?: Array<{ title: string; snippet: string; source?: string; score?: number; matched_query?: string }>;
        layer?: number;
      };
      const dimKey = ragData.dimension_key || '';
      if (dimKey) {
        const fullKey = `${ragData.layer || 1}_${dimKey}`;
        state.dimensionRagSources[fullKey] = {
          query: ragData.query || '',
          documents: ragData.documents || [],
        };
      }
      break;
    }
    // ============================================
    // NEW: Cascade Events for Demo System
    // ============================================
    case 'cascade_impact': {
      const cascadeData = data as {
        trigger_dim?: string;
        impacted_dimensions?: string[];
      };
      if (cascadeData.trigger_dim && cascadeData.impacted_dimensions) {
        state.cascadeChain = {
          trigger: cascadeData.trigger_dim,
          impacted: cascadeData.impacted_dimensions,
        };
      }
      break;
    }
    case 'cascade_complete': {
      state.cascadeChain = null;
      break;
    }
    // ============================================
    // NEW: Dimension Reset Events for Demo System
    // ============================================
    case 'dimension_reset': {
      const resetData = data as {
        dimension_key?: string;
        layer?: number;
      };
      const dimKey = resetData.dimension_key || '';
      if (dimKey) {
        const fullKey = `${resetData.layer || 1}_${dimKey}`;
        // Add to resetting dimensions list
        if (!state.resettingDimensions.includes(fullKey)) {
          state.resettingDimensions.push(fullKey);
        }
        // Increment version count
        state.dimensionVersions[fullKey] = (state.dimensionVersions[fullKey] || 0) + 1;
      }
      break;
    }
    case 'dimension_reset_complete': {
      const resetData = data as {
        dimension_key?: string;
        layer?: number;
      };
      const dimKey = resetData.dimension_key || '';
      if (dimKey) {
        const fullKey = `${resetData.layer || 1}_${dimKey}`;
        // Remove from resetting dimensions list
        state.resettingDimensions = state.resettingDimensions.filter((k) => k !== fullKey);
        // Clear streaming content
        delete state.streamingContent[fullKey];
      }
      break;
    }
    // ============================================
    // NEW: State Sync Event (for reconnect)
    // ============================================
    case 'state_sync': {
      const syncData = data as Record<string, unknown>;
      // Hydrate state from backend sync
      if (syncData.phase) state.phase = syncData.phase as string;
      if (syncData.current_wave) state.currentWave = syncData.current_wave as number;
      // Note: reports 不再从后端同步，前端通过 SSE dimension_delta/dimension_complete 累积
      // 或通过 getLayerReports API 按需获取
      if (syncData.completed_dimensions) {
        const completedData = syncData.completed_dimensions as Record<string, string[]>;
        if (completedData.layer1) state.completedDimensions.layer1 = completedData.layer1;
        if (completedData.layer2) state.completedDimensions.layer2 = completedData.layer2;
        if (completedData.layer3) state.completedDimensions.layer3 = completedData.layer3;
      }
      if (syncData.pause_after_step !== undefined) state.pause_after_step = syncData.pause_after_step as boolean;
      if (syncData.previous_layer !== undefined) state.previous_layer = syncData.previous_layer as number;
      deriveUIStateInStore(state);
      break;
    }
    case 'gis_layer_update': {
      const gisUpdateData = data as {
        layer?: number;
        dimension_key?: string;
        layers?: unknown[];
      };
      const key = `${gisUpdateData.layer}_${gisUpdateData.dimension_key}`;
      if (gisUpdateData.layers) {
        state.gisLayers[key] = gisUpdateData.layers as GISLayerConfig[];
      }
      break;
    }

    case 'rag_config_updated': {
      const ragData = data as {
        rag_layer_config?: Record<number, boolean>;
      };
      if (ragData.rag_layer_config) {
        state.ragLayerConfig = ragData.rag_layer_config;
      }
      break;
    }
  }
}

function deriveUIStateInStore(state: PlanningState): void {
  // Derive completedDimensions from reports
  const newCompletedDimensions = deriveCompletedDimensions(state.reports);

  // Use stable reference if dimensions haven't changed
  if (!shallowEqualCompletedDimensions(newCompletedDimensions, state.completedDimensions)) {
    state.completedDimensions = newCompletedDimensions;
  }

  // Derive completedLayers
  state.completedLayers = {
    1: state.completedDimensions.layer1.length > 0,
    2: state.completedDimensions.layer2.length > 0,
    3: state.completedDimensions.layer3.length > 0,
  };

  // Derive pause state
  state.isPaused = state.pause_after_step === true || state.status === 'paused';
  state.pendingReviewLayer =
    state.isPaused && state.previous_layer > 0 ? state.previous_layer : null;

  // Derive currentLayer: prefer pendingReviewLayer when paused, else from phase
  const layerFromPhase = phaseToLayer(state.phase);
  state.currentLayer = state.pendingReviewLayer || layerFromPhase;
  state.currentPhase = state.currentLayer ? getLayerPhase(state.currentLayer) : 'idle';
}

// ============================================
// Create Store
// ============================================

export const usePlanningStore = create<PlanningState & PlanningActions>()(
  immer((set, _get) => ({
    // Initial state
    ...createInitialState('default'),

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
          if (updates.wordCount !== undefined && existing.wordCount !== undefined) {
            if (Math.abs(existing.wordCount - (updates.wordCount || 0)) < 50) {
              return;
            }
          }
          Object.assign(existing, updates);
        } else {
          state.dimensionProgress[key] = {
            dimensionKey: updates.dimensionKey || '',
            dimensionName: updates.dimensionName || '',
            layer: updates.layer || 0,
            status: updates.status || 'pending',
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
          status: 'streaming' as DimensionStatus,
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

        existing.status = 'completed' as DimensionStatus;
        existing.wordCount = wordCount;
        existing.completedAt = new Date().toISOString();

        state.executingDimensions = state.executingDimensions.filter((k) => k !== key);
      }),

    clearDimensionProgress: () =>
      set((state) => {
        state.dimensionProgress = {};
        state.executingDimensions = [];
        state.currentPhase = 'idle';
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
        Object.assign(state.reports, reports);
        deriveUIStateInStore(state);
      }),

    setCompletedDimensions: (completedDimensions) =>
      set((state) => {
        state.completedDimensions = completedDimensions;
      }),

    // Backend sync
    syncBackendState: (backendData) =>
      set((state) => {
        const hasStatusChange = backendData.status !== state.status;
        const hasPhaseChange = backendData.phase !== state.phase;
        const hasPauseChange = backendData.pause_after_step !== state.pause_after_step;
        const hasExecutionPausedChange = backendData.execution_paused !== state.execution_paused;
        const hasPreviousLayerChange = backendData.previous_layer !== state.previous_layer;
        const hasWaveChange = backendData.current_wave !== state.currentWave;

        if (
          !hasStatusChange &&
          !hasPhaseChange &&
          !hasPauseChange &&
          !hasExecutionPausedChange &&
          !hasPreviousLayerChange &&
          !hasWaveChange
        ) {
          return;
        }

        // 使用后端 status 或从 phase 派生
        if (backendData.status) {
          state.status = backendData.status as Status;
        }
        if (backendData.phase) state.phase = backendData.phase;
        if (backendData.current_wave) state.currentWave = backendData.current_wave;
        // Note: reports 不再从后端同步，前端通过 SSE 或 API 获取
        if (backendData.completed_dimensions) {
          const completedData = backendData.completed_dimensions as Record<string, string[]>;
          if (completedData.layer1) state.completedDimensions.layer1 = completedData.layer1;
          if (completedData.layer2) state.completedDimensions.layer2 = completedData.layer2;
          if (completedData.layer3) state.completedDimensions.layer3 = completedData.layer3;
        }
        if (state.isPaused && backendData.pause_after_step === false) {
          state.pause_after_step = true;
        } else {
          state.pause_after_step = backendData.pause_after_step === true;
        }
        if (backendData.previous_layer) state.previous_layer = backendData.previous_layer;
        state.step_mode = backendData.step_mode ?? state.step_mode;
        if (backendData.execution_paused !== undefined)
          state.execution_paused = backendData.execution_paused;
        if (backendData.last_checkpoint_id)
          state.selectedCheckpoint = backendData.last_checkpoint_id;

        // 同步项目上下文（页面刷新后恢复）
        if (backendData.project_name && !state.projectName) {
          state.projectName = backendData.project_name;
        }
        if (backendData.village_name) state.villageName = backendData.village_name;
        if (backendData.province) state.province = backendData.province;
        if (backendData.city) state.city = backendData.city;
        if (backendData.county) state.county = backendData.county;
        if (backendData.township) state.township = backendData.township;
        if (backendData.planning_period) state.planningPeriod = backendData.planning_period;

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
          const reportsData = data.reports as Record<string, Record<string, string>>;
          if (reportsData.layer1) state.reports.layer1 = reportsData.layer1;
          if (reportsData.layer2) state.reports.layer2 = reportsData.layer2;
          if (reportsData.layer3) state.reports.layer3 = reportsData.layer3;
        }
        if (data.pause_after_step !== undefined) {
          state.pause_after_step = data.pause_after_step as boolean;
        }
        if (data.previous_layer !== undefined) {
          state.previous_layer = data.previous_layer as number;
        }
        if (data.step_mode !== undefined) {
          state.step_mode = data.step_mode as boolean;
        }
        if (data.execution_paused !== undefined) {
          state.execution_paused = data.execution_paused as boolean;
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
          query: state.dimensionRagSources[dimKey]?.query || '',
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

    // ============================================
    // NEW: Dimension Version & Streaming Actions
    // ============================================
    incrementDimensionVersion: (dimKey) =>
      set((state) => {
        state.dimensionVersions[dimKey] = (state.dimensionVersions[dimKey] || 0) + 1;
      }),

    setStreamingContent: (dimKey, content) =>
      set((state) => {
        state.streamingContent[dimKey] = content;
      }),

    clearStreamingContent: (dimKey) =>
      set((state) => {
        delete state.streamingContent[dimKey];
      }),

    markDimensionResetting: (dimKey) =>
      set((state) => {
        if (!state.resettingDimensions.includes(dimKey)) {
          state.resettingDimensions.push(dimKey);
        }
      }),

    finishDimensionResetting: (dimKey) =>
      set((state) => {
        state.resettingDimensions = state.resettingDimensions.filter((k) => k !== dimKey);
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
        state.villages = villages;
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
    handleSSEEvent: (event) =>
      set((state) => {
        handleSSEEventInStore(state, event);
      }),

    // SSE Reconnect trigger - increment to trigger reconnect
    triggerSseReconnect: () =>
      set((state) => {
        state.sseResumeTrigger += 1;
      }),

    // Clear progress state (used when approve/reject to wait for new layer)
    clearProgressState: () =>
      set((state) => {
        state.currentLayer = null;
        state.currentPhase = 'idle';
        state.dimensionProgress = {};
        state.executingDimensions = [];
      }),

    // Clear only revision dimensions progress, preserve other completed dimensions
    clearRevisionProgress: (layer, dimensionsToRevise) =>
      set((state) => {
        if (!dimensionsToRevise || dimensionsToRevise.length === 0) {
          // If no dimensions specified, only clear executing state for this layer
          state.executingDimensions = state.executingDimensions.filter(
            (k) => !k.startsWith(`${layer}_`)
          );
          return;
        }

        // Clear progress for specified dimensions only
        for (const dimKey of dimensionsToRevise) {
          const progressKey = buildDimensionProgressKey(layer, dimKey);
          delete state.dimensionProgress[progressKey];
        }

        // Clear executing state for specified dimensions only (preserve other executing)
        const keysToRemove = dimensionsToRevise.map((dim) => buildDimensionProgressKey(layer, dim));
        state.executingDimensions = state.executingDimensions.filter(
          (k) => !keysToRemove.includes(k)
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
    resetConversation: () =>
      set((state) => {
        const newState = createInitialState(state.conversationId);
        newState.villages = state.villages;
        Object.assign(state, newState);
      }),

    initConversation: (conversationId) =>
      set((state) => {
        // Prevent re-initialization if conversationId matches and sessionId exists
        // This protects against StrictMode double-mount clearing restored sessionId
        if (state.conversationId === conversationId && state.sessionId) {
          return;
        }

        const newState = createInitialState(conversationId);
        newState.villages = state.villages;
        Object.assign(state, newState);
      }),
  }))
);

// ============================================
// Selector Hooks (for performance)
// ============================================
