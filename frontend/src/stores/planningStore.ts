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
} from '@/types';
import type { GisResultMessage, ToolStatusMessage } from '@/types/message/message-types';
import type { VillageInputData } from '@/components/VillageInputForm';
import type { VillageInfo, VillageSession, SessionStatusResponse } from '@/lib/api';
import { getLayerPhase, PlanningStatus, LayerPhase, AgentPhase } from '@/lib/constants';
import {
  createBaseMessage,
  buildLayerReportId,
  buildRevisionReportId,
  buildDimensionProgressKey,
  formatDimensionReportsAsContent,
  calculateReportSummary,
} from '@/lib/utils/message-helpers';
import { DIMENSION_NAMES } from '@/config/dimensions';

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
  status: 'running' | 'success' | 'error';
  stage?: string;
  progress?: number;
  message?: string;
  summary?: string;
}

// Internal event type for store handling
interface StoreEvent {
  type: string;
  data?: unknown;
}

export interface PlanningState {
  conversationId: string;

  // Session
  taskId: string | null;
  projectName: string | null;
  status: Status;

  // Agent State (Single Source of Truth)
  phase: string;
  currentWave: number;
  reports: Reports;
  pause_after_step: boolean;
  previous_layer: number;
  step_mode: boolean;

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

  // Tools
  toolStatuses: Record<string, ToolStatus>;
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

function shallowEqualReports(incoming: Reports | undefined, current: Reports): boolean {
  if (!incoming) return true;
  const layers = ['layer1', 'layer2', 'layer3'] as const;
  for (const layer of layers) {
    const a = incoming[layer] || {};
    const b = current[layer] || {};
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) return false;
    for (const key of keysA) {
      if (a[key] !== b[key]) return false;
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
    taskId: null,
    projectName: null,
    status: 'idle',

    // Agent State
    phase: 'init',
    currentWave: 1,
    reports: { layer1: {}, layer2: {}, layer3: {} },
    pause_after_step: false,
    previous_layer: 0,
    step_mode: false,

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
  };
}

// ============================================
// Store Actions Interface
// ============================================

export interface PlanningActions {
  // Core setters
  setTaskId: (taskId: string | null) => void;
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

  // Layer & Reports
  setLayerCompleted: (layer: number, completed: boolean) => void;
  setReports: (reports: Partial<Reports>) => void;
  setCompletedDimensions: (completedDimensions: CompletedDimensions) => void;

  // Backend sync
  syncBackendState: (backendData: Partial<SessionStatusResponse> & { version?: number }) => void;

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

  // Tools
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
      if (connData.task_id && !state.taskId) {
        state.taskId = connData.task_id;
      }
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

      // 兜底：如果 currentLayer 未设置，从事件中获取
      if (state.currentLayer === null) {
        state.currentLayer = layer;
        state.currentPhase = getLayerPhase(layer);
      }

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
        layer?: number;
        is_revision?: boolean;
        knowledge_sources?: KnowledgeSource[];
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || '';
      const key = buildDimensionProgressKey(layer, dimensionKey);

      // Update dimensionProgress
      state.dimensionProgress[key] = {
        dimensionKey,
        dimensionName: dimData.dimension_name || '',
        layer,
        status: 'completed' as DimensionStatus,
        wordCount: (dimData.full_content || '').length,
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
          msg.content = dimData.full_content || '';
          msg.wordCount = (dimData.full_content || '').length;
          msg.streamingState = 'completed';
        }
        // Update reports state for revision as well
        const layerKey = `layer${layer}` as keyof Reports;
        state.reports[layerKey][dimensionKey] = dimData.full_content || '';
        break;
      }

      // Update reports
      const layerKey = `layer${layer}` as keyof Reports;
      state.reports[layerKey][dimensionKey] = dimData.full_content || '';

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
        layerMsg.dimensionReports[dimensionKey] = dimData.full_content || '';

        // Update fullReportContent and summary using utility functions
        layerMsg.fullReportContent = formatDimensionReportsAsContent(layerMsg.dimensionReports);
        const summary = calculateReportSummary(layerMsg.dimensionReports);
        layerMsg.summary.word_count = summary.word_count;
        layerMsg.summary.dimension_count = summary.dimension_count;

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

      // 直接使用事件中的 layer 更新 currentLayer（避免 phase 映射失败）
      state.currentLayer = layer;
      state.currentPhase = getLayerPhase(layer);

      // 仅更新 completedDimensions 和 completedLayers
      const newCompletedDimensions = deriveCompletedDimensions(state.reports);
      if (!shallowEqualCompletedDimensions(newCompletedDimensions, state.completedDimensions)) {
        state.completedDimensions = newCompletedDimensions;
      }
      state.completedLayers = {
        1: state.completedDimensions.layer1.length > 0,
        2: state.completedDimensions.layer2.length > 0,
        3: state.completedDimensions.layer3.length > 0,
      };
      break;
    }

    case 'layer_started': {
      const layerData = data as {
        layer?: number;
        layer_number?: number;
        dimension_count?: number;
      };
      const layerNum = layerData.layer || layerData.layer_number || 1;
      state.currentLayer = layerNum;
      state.currentPhase = getLayerPhase(layerNum);

      // Store dimension_count for progress panel display (with change detection)
      if (
        layerData.dimension_count &&
        state.layerDimensionCount[layerNum] !== layerData.dimension_count
      ) {
        state.layerDimensionCount[layerNum] = layerData.dimension_count;
      }

      // Reset dimensionProgress and executingDimensions for new layer
      // Note: This only resets progress tracking, not the actual message content
      state.dimensionProgress = {};
      state.executingDimensions = [];

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
      break;
    }

    case 'layer_completed': {
      const layerData = data as {
        layer?: number;
        phase?: string;
        dimension_reports?: Record<string, string>;
        pause_after_step?: boolean;
        previous_layer?: number;
        task_id?: string;
      };

      if (layerData.task_id && !state.taskId) {
        state.taskId = layerData.task_id;
      }

      const layerNum = layerData.layer || 1;
      const layerKey = `layer${layerNum}` as keyof Reports;

      if (layerData.dimension_reports && Object.keys(layerData.dimension_reports).length > 0) {
        Object.assign(state.reports[layerKey], layerData.dimension_reports);
      }

      state.phase = layerData.phase || state.phase;
      state.pause_after_step = layerData.pause_after_step ?? state.pause_after_step;
      state.previous_layer = layerData.previous_layer ?? state.previous_layer;

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
        const summary = calculateReportSummary(layerMsg.dimensionReports);
        layerMsg.summary.word_count = summary.word_count;
        layerMsg.summary.dimension_count = summary.dimension_count;
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

      // Use layer from event to update currentLayer
      // When paused, show the just completed layer; when continuing, show new phase
      if (layerData.pause_after_step && layerData.previous_layer) {
        state.currentLayer = layerData.previous_layer;
        state.currentPhase = getLayerPhase(layerData.previous_layer);
      } else {
        state.currentLayer = layerNum;
        state.currentPhase = getLayerPhase(layerNum);
      }

      // 仅更新 completedDimensions 和 completedLayers
      const newCompletedDimensions = deriveCompletedDimensions(state.reports);
      if (!shallowEqualCompletedDimensions(newCompletedDimensions, state.completedDimensions)) {
        state.completedDimensions = newCompletedDimensions;
      }
      state.completedLayers = {
        1: state.completedDimensions.layer1.length > 0,
        2: state.completedDimensions.layer2.length > 0,
        3: state.completedDimensions.layer3.length > 0,
      };

      // 暂停状态设置
      state.isPaused = state.pause_after_step === true;
      state.pendingReviewLayer =
        state.isPaused && state.previous_layer > 0 ? state.previous_layer : null;
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

      if (pauseData.task_id && !state.taskId) {
        state.taskId = pauseData.task_id;
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
  }
}

function deriveUIStateInStore(state: PlanningState): void {
  const currentLayer = phaseToLayer(state.phase);

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
  state.isPaused = state.pause_after_step === true;
  state.pendingReviewLayer =
    state.isPaused && state.previous_layer > 0 ? state.previous_layer : null;

  state.currentLayer = currentLayer;
  state.currentPhase = currentLayer ? getLayerPhase(currentLayer) : 'idle';
}

// ============================================
// Create Store
// ============================================

export const usePlanningStore = create<PlanningState & PlanningActions>()(
  immer((set, _get) => ({
    // Initial state
    ...createInitialState('default'),

    // Core setters
    setTaskId: (taskId) =>
      set((state) => {
        state.taskId = taskId;
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
        const hasPreviousLayerChange = backendData.previous_layer !== state.previous_layer;
        const hasReportsChange = !shallowEqualReports(backendData.reports, state.reports);

        if (
          !hasStatusChange &&
          !hasPhaseChange &&
          !hasPauseChange &&
          !hasPreviousLayerChange &&
          !hasReportsChange
        ) {
          return;
        }

        // 使用后端 status 或从 phase 派生
        if (backendData.status) {
          state.status = backendData.status as Status;
        }
        if (backendData.phase) state.phase = backendData.phase;
        if (backendData.reports) state.reports = backendData.reports;
        state.pause_after_step = backendData.pause_after_step === true;
        if (backendData.previous_layer) state.previous_layer = backendData.previous_layer;
        state.step_mode = backendData.step_mode ?? state.step_mode;
        if (backendData.last_checkpoint_id)
          state.selectedCheckpoint = backendData.last_checkpoint_id;

        deriveUIStateInStore(state);
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

    // Reset
    resetConversation: () =>
      set((state) => {
        const newState = createInitialState(state.conversationId);
        newState.villages = state.villages;
        Object.assign(state, newState);
      }),

    initConversation: (conversationId) =>
      set((state) => {
        // Prevent re-initialization if conversationId matches and taskId exists
        // This protects against StrictMode double-mount clearing restored taskId
        if (state.conversationId === conversationId && state.taskId) {
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
