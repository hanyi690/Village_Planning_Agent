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
} from '../types';
import type { GISLayerConfig } from '@/types/message/message-types';
import type { VillageInputData } from '../components/VillageInputForm';
import type {
  VillageInfo,
  VillageSession,
  SessionStatusResponse,
} from '../api';
import {
  getLayerPhase,
  PlanningStatus,
  LayerPhase,
} from '@/features/planning/constants';
import type { NavigationKey } from '@/features/planning/constants';
import type { HumanReviewItem } from '../api/types';
import { planningApi } from '../api/planning-api';
import { buildDimensionProgressKey } from '@/features/planning/utils/message-helpers';
import { handleSSEEventInStore } from './handlers/sseHandlers';
import { deriveUIStateInStore, type Reports } from './handlers/derivedState';
import { createHistoryActions } from './handlers/historyActions';
import {
  createGisActions,
  type StoreSet,
} from './handlers/gisActions';

export type ProcessPanelTab = 'messages' | 'map' | 'history' | 'settings';

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

// ============================================
// State Types
// ============================================

type Status = PlanningStatus;

interface CompletedDimensions {
  layer1: string[];
  layer2: string[];
  layer3: string[];
}

export interface HumanInterruptInfo {
  event_id?: string;
  channel?: 'step_mode' | 'post_l3_review' | string;
  reason?: 'human_review_required' | string;
  layer?: number;
  phase?: string;
  layer_name?: string;
  paused_stage?: string;
  items?: HumanReviewItem[];
  error_feedback?: Record<string, string>;
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

interface RagDocument {
  title: string;
  snippet: string;
  source?: string;
  score?: number;
  chunk_id?: string;
  matched_query?: string;
}

interface DimensionRagSource {
  query: string;
  documents: RagDocument[];
}

interface CascadeChain {
  trigger: string;
  impacted: string[];
}

// Internal event type for store handling
export interface StoreEvent {
  type: string;
  data?: unknown;
}

export interface PlanningState {
  conversationId: string;

  sessionId: string | null;
  projectName: string | null;
  villageName?: string;
  province?: string;
  city?: string;
  county?: string;
  township?: string;
  planningPeriod?: string;
  status: Status;

  phase: string;
  currentWave: number;
  reports: Reports;
  previous_layer: number;
  step_mode: boolean;
  interruptInfo?: HumanInterruptInfo;

  completedDimensions: CompletedDimensions;
  currentLayer: number | null;
  currentPhase: LayerPhase | '修复中';
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  isPaused: boolean;
  pendingReviewLayer: number | null;
  lastPauseLayer: number;

  humanReviewEventId: string | null;
  pausedStage: string | null;
  humanReviewItems: HumanReviewItem[];
  humanReviewError: string | null;
  isResolvingReview: boolean;

  sseResumeTrigger: number;
  lastProcessedSeq: number;

  messages: Message[];

  dimensionProgress: Record<string, DimensionProgressItem>;
  executingDimensions: string[];
  layerDimensionCount: Record<number, number>;

  dimensionRagSources: Record<string, DimensionRagSource>;
  cascadeChain: CascadeChain | null;
  revisionCompletedKeys: string[];
  streamingContent: Record<string, string>;
  runningTools: string[];

  viewerVisible: boolean;
  referencedSection?: string;
  viewingFile: FileMessage | null;
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  villageFormData: VillageInputData | null;
  progressPanelVisible: boolean;
  layerReportVisible: boolean;
  activeReportLayer: number;

  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  historyLoading: boolean;
  historyError: string | null;

  checkpoints: Checkpoint[];
  selectedCheckpoint: string | null;
  loadingContent: boolean;
  deletingSessionId: string | null;

  toolStatuses: Record<string, ToolStatus>;

  gisLayers: Record<string, GISLayerConfig[]>;

  pipelineTrace: PipelineTrace | null;

  selectedNavigationKey: NavigationKey | null;
  isRightPanelExpanded: boolean;
  isLeftNavCollapsed: boolean;

  processPanelTab: ProcessPanelTab;

  ragLayerConfig: Record<number, boolean>;

  gisGenerating: boolean;
  isFullMapOpen: boolean;
  gisTriggerPending: boolean;
  villageCenter?: [number, number];
  uploadedGisDataTypes: string[];
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

    phase: 'init',
    currentWave: 1,
    reports: { layer1: {}, layer2: {}, layer3: {} },
    previous_layer: 0,
    step_mode: true,
    interruptInfo: undefined,

    completedDimensions: { layer1: [], layer2: [], layer3: [] },
    currentLayer: null,
    currentPhase: 'idle',
    completedLayers: { 1: false, 2: false, 3: false },
    isPaused: false,
    pendingReviewLayer: null,
    lastPauseLayer: 0,
    humanReviewEventId: null,
    pausedStage: null,
    humanReviewItems: [],
    humanReviewError: null,
    isResolvingReview: false,
    sseResumeTrigger: 0,
    lastProcessedSeq: 0,

    messages: [],

    dimensionProgress: {},
    executingDimensions: [],
    layerDimensionCount: {},
    runningTools: [],

    dimensionRagSources: {},
    cascadeChain: null,
    revisionCompletedKeys: [],
    streamingContent: {},

    viewerVisible: false,
    referencedSection: undefined,
    viewingFile: null,
    viewMode: 'WELCOME_FORM',
    villageFormData: null,
    progressPanelVisible: false,
    layerReportVisible: false,
    activeReportLayer: 1,

    villages: [],
    selectedVillage: null,
    selectedSession: null,
    historyLoading: false,
    historyError: null,

    checkpoints: [],
    selectedCheckpoint: null,
    loadingContent: false,
    deletingSessionId: null,

    toolStatuses: {},
    gisLayers: {},
    pipelineTrace: null,

    selectedNavigationKey: null,
    isRightPanelExpanded: true,
    isLeftNavCollapsed: false,

    processPanelTab: 'messages',

    ragLayerConfig: { 1: true, 2: false, 3: true },

    gisGenerating: false,
    isFullMapOpen: false,
    gisTriggerPending: false,
    villageCenter: undefined,
    uploadedGisDataTypes: [],
  };
}

// ============================================
// Store Actions Interface
// ============================================

export interface PlanningActions {
  setSessionId: (sessionId: string | null) => void;
  setProjectName: (projectName: string | null) => void;
  setStatus: (status: Status) => void;
  setPhase: (phase: string) => void;

  addMessage: (message: Message) => void;
  addMessages: (messages: Message[]) => void;
  setMessages: (messages: Message[]) => void;
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;

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

  setLayerCompleted: (layer: number, completed: boolean) => void;
  setReports: (reports: Partial<Reports>) => void;
  setCompletedDimensions: (completedDimensions: CompletedDimensions) => void;
  clearDimensionReport: (layer: number, dimensionKey: string) => void;

  syncBackendState: (
    backendData: Partial<SessionStatusResponse> & { version?: number },
  ) => void;
  hydrateFromStateSync: (data: Record<string, unknown>) => void;

  setRagQuery: (dimKey: string, query: string) => void;
  setRagDocuments: (dimKey: string, documents: RagDocument[]) => void;
  clearRagSources: (dimKey: string) => void;
  clearAllRagSources: () => void;
  showCascadeChain: (trigger: string, impacted: string[]) => void;
  clearCascadeChain: () => void;
  setStreamingContent: (dimKey: string, content: string) => void;
  clearStreamingContent: (dimKey: string) => void;

  addRunningTool: (toolName: string) => void;
  removeRunningTool: (toolName: string) => void;

  setViewerVisible: (visible: boolean) => void;
  setViewingFile: (file: FileMessage | null) => void;
  setPaused: (paused: boolean) => void;
  setPendingReviewLayer: (layer: number | null) => void;
  setVillageFormData: (data: VillageInputData | null) => void;
  setProgressPanelVisible: (visible: boolean) => void;
  setStepMode: (stepMode: boolean) => void;

  setVillages: (villages: VillageInfo[]) => void;
  setSelectedVillage: (village: VillageInfo | null) => void;
  setSelectedSession: (session: VillageSession | null) => void;
  setHistoryLoading: (loading: boolean) => void;
  setHistoryError: (error: string | null) => void;

  setCheckpoints: (checkpoints: Checkpoint[]) => void;
  setSelectedCheckpoint: (checkpointId: string | null) => void;

  setToolStatus: (toolName: string, status: ToolStatus) => void;
  clearToolStatus: (toolName: string) => void;

  handleSSEEvent: (event: StoreEvent) => void;

  fetchHumanReviewItems: (sessionId: string) => Promise<void>;
  resolveHumanReview: (sessionId: string, decisions: Record<string, unknown>) => Promise<void>;

  triggerSseReconnect: () => void;

  clearProgressState: () => void;

  addGisLayersFromUpload: (configs: Array<Record<string, unknown>>) => void;

  clearRevisionProgress: (layer: number, dimensionsToRevise: string[]) => void;

  setSelectedNavigationKey: (key: NavigationKey | null) => void;
  setRightPanelExpanded: (expanded: boolean) => void;
  setLeftNavCollapsed: (collapsed: boolean) => void;

  setProcessPanelTab: (tab: ProcessPanelTab) => void;

  setFullMapOpen: (open: boolean) => void;
  setUploadedGisDataTypes: (types: string[]) => void;

  setRagLayerConfig: (config: Record<number, boolean>) => void;
  toggleLayerRag: (layer: number) => void;

  resetConversation: () => void;
  initConversation: (conversationId: string) => void;
}

// ============================================
// Create Store
// ============================================

export const usePlanningStore = create<PlanningState & PlanningActions>()(
  immer((set, get) => ({
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

        state.executingDimensions = state.executingDimensions.filter(
          (k) => k !== key,
        );
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

    clearDimensionReport: (layer, dimensionKey) =>
      set((state) => {
        const layerKey = `layer${layer}` as 'layer1' | 'layer2' | 'layer3';
        if (state.reports[layerKey]) {
          delete state.reports[layerKey][dimensionKey];
        }
        delete state.streamingContent[`${layer}_${dimensionKey}`];
      }),

    // Backend sync
    syncBackendState: (backendData) =>
      set((state) => {
        const hasStatusChange = backendData.status !== state.status;
        const hasPhaseChange = backendData.phase !== state.phase;
        const hasInterruptInfoChange =
          backendData.interrupt_info !== undefined &&
          JSON.stringify(backendData.interrupt_info) !== JSON.stringify(state.interruptInfo);
        const hasPreviousLayerChange =
          backendData.previous_layer !== state.previous_layer;
        const hasWaveChange = backendData.current_wave !== state.currentWave;
        const hasRagConfigChange =
          backendData.rag_layer_config &&
          (backendData.rag_layer_config[1] !== state.ragLayerConfig[1] ||
            backendData.rag_layer_config[2] !== state.ragLayerConfig[2] ||
            backendData.rag_layer_config[3] !== state.ragLayerConfig[3]);

        if (
          !hasStatusChange &&
          !hasPhaseChange &&
          !hasInterruptInfoChange &&
          !hasPreviousLayerChange &&
          !hasWaveChange &&
          !hasRagConfigChange
        ) {
          return;
        }

        if (backendData.status) {
          state.status = backendData.status as Status;
        }
        if (backendData.phase) state.phase = backendData.phase;
        if (backendData.current_wave)
          state.currentWave = backendData.current_wave;
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
          const interruptInfo = backendData.interrupt_info as PlanningState['interruptInfo'];
          state.interruptInfo = interruptInfo;
          state.humanReviewEventId = interruptInfo?.event_id || null;
          state.pausedStage = interruptInfo?.paused_stage || null;
          state.humanReviewItems = interruptInfo?.items || [];
        }
        if (backendData.previous_layer)
          state.previous_layer = backendData.previous_layer;
        state.step_mode = backendData.step_mode ?? state.step_mode;
        if (hasRagConfigChange) {
          state.ragLayerConfig = {
            ...state.ragLayerConfig,
            ...backendData.rag_layer_config!,
          };
        }
        if (backendData.last_checkpoint_id)
          state.selectedCheckpoint = backendData.last_checkpoint_id;

        if (backendData.project_name && !state.projectName) {
          state.projectName = backendData.project_name;
        }
        if (backendData.village_name)
          state.villageName = backendData.village_name;
        if (backendData.province) state.province = backendData.province;
        if (backendData.city) state.city = backendData.city;
        if (backendData.county) state.county = backendData.county;
        if (backendData.township) state.township = backendData.township;
        if (backendData.planning_period)
          state.planningPeriod = backendData.planning_period;

        deriveUIStateInStore(state);
      }),

    hydrateFromStateSync: (data) =>
      set((state) => {
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
          const interruptInfo = data.interrupt_info as PlanningState['interruptInfo'];
          state.interruptInfo = interruptInfo;
          state.humanReviewEventId = interruptInfo?.event_id || null;
          state.pausedStage = interruptInfo?.paused_stage || null;
          state.humanReviewItems = interruptInfo?.items || [];
        }
        if (data.previous_layer !== undefined) {
          state.previous_layer = data.previous_layer as number;
        }
        if (data.step_mode !== undefined) {
          state.step_mode = data.step_mode as boolean;
        }
        deriveUIStateInStore(state);
      }),

    // RAG Actions
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
    ...createHistoryActions(set as StoreSet),

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

    fetchHumanReviewItems: async (sessionId) => {
      try {
        const response = await planningApi.getHumanReview(sessionId);
        set((state) => {
          state.humanReviewItems = response.pending_items || [];
          state.humanReviewError = null;
          if (response.pending_items.length > 0 && response.post_l3_status === 'paused') {
            state.status = 'paused';
            state.pausedStage = response.pending_items[0]?.stage || null;
            state.humanReviewEventId = response.event_id || state.humanReviewEventId;
            deriveUIStateInStore(state);
          }
        });
      } catch (err) {
        set((state) => {
          state.humanReviewError = err instanceof Error ? err.message : 'Failed to fetch review items';
        });
      }
    },

    resolveHumanReview: async (sessionId, decisions) => {
      set((state) => { state.isResolvingReview = true; state.humanReviewError = null; });
      try {
        const eventId = get().humanReviewEventId;
        if (!eventId) throw new Error('Missing human-review event id');
        await planningApi.resolveHumanReview(sessionId, decisions, eventId);
        set((state) => { state.isResolvingReview = true; });
      } catch (err) {
        set((state) => {
          state.isResolvingReview = false;
          state.humanReviewError = err instanceof Error ? err.message : 'Failed to resolve review';
        });
      }
    },

    triggerSseReconnect: () =>
      set((state) => {
        state.sseResumeTrigger += 1;
      }),

    clearProgressState: () =>
      set((state) => {
        state.currentLayer = null;
        state.currentPhase = 'idle';
        state.dimensionProgress = {};
        state.executingDimensions = [];
      }),

    // GIS actions
    ...createGisActions(set as StoreSet),

    clearRevisionProgress: (layer, dimensionsToRevise) =>
      set((state) => {
        if (!dimensionsToRevise || dimensionsToRevise.length === 0) {
          state.executingDimensions = state.executingDimensions.filter(
            (k) => !k.startsWith(`${layer}_`),
          );
          return;
        }

        for (const dimKey of dimensionsToRevise) {
          const progressKey = buildDimensionProgressKey(layer, dimKey);
          delete state.dimensionProgress[progressKey];
        }

        const keysToRemove = dimensionsToRevise.map((dim) =>
          buildDimensionProgressKey(layer, dim),
        );
        state.executingDimensions = state.executingDimensions.filter(
          (k) => !keysToRemove.includes(k),
        );
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

    setProcessPanelTab: (tab) =>
      set((state) => {
        state.processPanelTab = tab;
      }),

    // Layer-level RAG Configuration
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
        newState.uploadedGisDataTypes = state.uploadedGisDataTypes;
        Object.assign(state, newState);
      }),

    initConversation: (conversationId) =>
      set((state) => {
        if (state.conversationId === conversationId && state.sessionId) {
          return;
        }

        const newState = createInitialState(conversationId);
        newState.villages = state.villages;
        newState.uploadedGisDataTypes = state.uploadedGisDataTypes;
        Object.assign(state, newState);
      }),
  })),
);

// Expose store to window for Playwright E2E tests (dev/test only)
if (typeof window !== 'undefined' && process.env.NODE_ENV !== 'production') {
  (window as any).__PLANNING_STORE__ = usePlanningStore;
}
