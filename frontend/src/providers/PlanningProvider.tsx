'use client';

/**
 * PlanningProvider - Unified State Management
 *
 * This is the single source of truth for planning state.
 * Replaces 7 Context files and TaskController with a single useReducer-based solution.
 *
 * Features:
 * - Single reducer for all state updates
 * - Integrated SSE connection management
 * - New UnifiedPlanningState schema (phase, reports, completed_dimensions)
 */

import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useEffect,
  useRef,
  ReactNode,
} from 'react';
import { Message, DimensionProgressItem, DimensionStatus, PlanningParams, Checkpoint, FileMessage, DimensionReportMessage } from '@/types';
import { VillageInputData } from '@/components/VillageInputForm';
import { planningApi, dataApi, VillageInfo, VillageSession, SessionStatusResponse } from '@/lib/api';
import { createSystemMessage, createErrorMessage, getErrorMessage } from '@/lib/utils';
import { logger } from '@/lib/logger';
import { getLayerPhase, LayerPhase, PlanningStatus } from '@/lib/constants';
import { PLANNING_DEFAULTS } from '@/config/planning';

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

interface PlanningState {
  // Session
  conversationId: string;
  taskId: string | null;
  projectName: string | null;
  status: Status;

  // NEW Schema
  phase: string;
  currentWave: number;
  reports: Reports;
  completedDimensions: CompletedDimensions;

  // Messages
  messages: Message[];

  // Progress (optimized: use Record/Array instead of Map/Set for stable references)
  dimensionProgress: Record<string, DimensionProgressItem>;
  executingDimensions: string[];
  currentPhase: LayerPhase | '修复中';

  // UI State
  viewerVisible: boolean;
  referencedSection?: string;
  viewingFile: FileMessage | null;
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  villageFormData: VillageInputData | null;
  isPaused: boolean;
  pendingReviewLayer: number | null;
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  progressPanelVisible: boolean;
  layerReportVisible: boolean;
  activeReportLayer: number;
  currentLayer: number | null;

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

  // Tools (optimized: use Record instead of Map)
  toolStatuses: Record<string, ToolStatus>;

  // Report Sync
  reportSyncState: {
    lastUpdated: number;
    currentLayer: number | null;
    isStreaming: boolean;
  };
}

// ============================================
// Action Types
// ============================================

type PlanningAction =
  | { type: 'SET_TASK_ID'; taskId: string | null }
  | { type: 'SET_PROJECT_NAME'; projectName: string | null }
  | { type: 'SET_STATUS'; status: Status }
  | { type: 'SET_PHASE'; phase: string }
  | { type: 'ADD_MESSAGE'; message: Message }
  | { type: 'SET_MESSAGES'; messages: Message[] }
  | { type: 'UPDATE_LAST_MESSAGE'; updates: Partial<Message> }
  | { type: 'CLEAR_MESSAGES' }
  | { type: 'UPDATE_DIMENSION_PROGRESS'; key: string; updates: Partial<DimensionProgressItem> }
  | { type: 'SET_DIMENSION_STREAMING'; layer: number; dimensionKey: string; dimensionName: string }
  | { type: 'SET_DIMENSION_COMPLETED'; layer: number; dimensionKey: string; wordCount: number }
  | { type: 'CLEAR_DIMENSION_PROGRESS' }
  | { type: 'SET_LAYER_COMPLETED'; layer: number; completed: boolean }
  | { type: 'SET_REPORTS'; reports: Partial<Reports> }
  | { type: 'SET_COMPLETED_DIMENSIONS'; completedDimensions: CompletedDimensions }
  | { type: 'SYNC_BACKEND_STATE'; backendData: Partial<SessionStatusResponse> & { version?: number } }
  | { type: 'SET_VIEWER_VISIBLE'; visible: boolean }
  | { type: 'SET_VIEWING_FILE'; file: FileMessage | null }
  | { type: 'SET_PAUSED'; paused: boolean }
  | { type: 'SET_PENDING_REVIEW_LAYER'; layer: number | null }
  | { type: 'SET_VILLAGE_FORM_DATA'; data: VillageInputData | null }
  | { type: 'SET_VILLAGES'; villages: VillageInfo[] }
  | { type: 'SET_SELECTED_VILLAGE'; village: VillageInfo | null }
  | { type: 'SET_SELECTED_SESSION'; session: VillageSession | null }
  | { type: 'SET_HISTORY_LOADING'; loading: boolean }
  | { type: 'SET_HISTORY_ERROR'; error: string | null }
  | { type: 'SET_CHECKPOINTS'; checkpoints: Checkpoint[] }
  | { type: 'SET_SELECTED_CHECKPOINT'; checkpointId: string | null }
  | { type: 'SET_TOOL_STATUS'; toolName: string; status: ToolStatus }
  | { type: 'CLEAR_TOOL_STATUS'; toolName: string }
  | { type: 'RESET_CONVERSATION' }
  | { type: 'SSE_EVENT'; event: SSEEvent };

// ============================================
// SSE Event Types
// ============================================

interface SSEEvent {
  type: string;
  data?: unknown;
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

    // NEW Schema
    phase: 'init',
    currentWave: 1,
    reports: { layer1: {}, layer2: {}, layer3: {} },
    completedDimensions: { layer1: [], layer2: [], layer3: [] },

    // Messages
    messages: [],

    // Progress (optimized)
    dimensionProgress: {},
    executingDimensions: [],
    currentPhase: 'idle',

    // UI State
    viewerVisible: false,
    referencedSection: undefined,
    viewingFile: null,
    viewMode: 'WELCOME_FORM',
    villageFormData: null,
    isPaused: false,
    pendingReviewLayer: null,
    completedLayers: { 1: false, 2: false, 3: false },
    progressPanelVisible: false,
    layerReportVisible: false,
    activeReportLayer: 1,
    currentLayer: null,

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

    // Tools (optimized)
    toolStatuses: {},

    // Report Sync
    reportSyncState: {
      lastUpdated: 0,
      currentLayer: null,
      isStreaming: false,
    },
  };
}

// ============================================
// Reducer
// ============================================

function planningReducer(state: PlanningState, action: PlanningAction): PlanningState {
  switch (action.type) {
    case 'SET_TASK_ID':
      return { ...state, taskId: action.taskId };

    case 'SET_PROJECT_NAME':
      return { ...state, projectName: action.projectName };

    case 'SET_STATUS':
      return { ...state, status: action.status };

    case 'SET_PHASE':
      return { ...state, phase: action.phase };

    case 'ADD_MESSAGE':
      return { ...state, messages: [...state.messages, action.message] };

    case 'SET_MESSAGES':
      return { ...state, messages: action.messages };

    case 'UPDATE_LAST_MESSAGE': {
      if (state.messages.length === 0) return state;
      const lastMessage = state.messages[state.messages.length - 1];
      return {
        ...state,
        messages: [...state.messages.slice(0, -1), { ...lastMessage, ...action.updates } as Message],
      };
    }

    case 'CLEAR_MESSAGES':
      return { ...state, messages: [] };

    case 'UPDATE_DIMENSION_PROGRESS': {
      const existing = state.dimensionProgress[action.key];
      if (existing) {
        // Optimized: use spread operator for Record, only update if value changed
        const newItem = { ...existing, ...action.updates };
        // Skip update if wordCount hasn't meaningfully changed (threshold: 50 chars)
        if (action.updates.wordCount !== undefined && existing.wordCount !== undefined) {
          if (Math.abs(existing.wordCount - (action.updates.wordCount || 0)) < 50) {
            return state; // Skip update for small changes
          }
        }
        return {
          ...state,
          dimensionProgress: {
            ...state.dimensionProgress,
            [action.key]: newItem,
          },
        };
      } else {
        return {
          ...state,
          dimensionProgress: {
            ...state.dimensionProgress,
            [action.key]: {
              dimensionKey: action.updates.dimensionKey || '',
              dimensionName: action.updates.dimensionName || '',
              layer: action.updates.layer || 0,
              status: action.updates.status || 'pending',
              wordCount: action.updates.wordCount || 0,
              ...action.updates,
            },
          },
        };
      }
    }

    case 'SET_DIMENSION_STREAMING': {
      const key = `${action.layer}_${action.dimensionKey}`;
      // Optimized: use spread for Record, check before adding to array
      const currentExecuting = state.executingDimensions;
      const alreadyExecuting = currentExecuting.includes(key);

      return {
        ...state,
        dimensionProgress: {
          ...state.dimensionProgress,
          [key]: {
            dimensionKey: action.dimensionKey,
            dimensionName: action.dimensionName,
            layer: action.layer,
            status: 'streaming' as DimensionStatus,
            wordCount: 0,
            startedAt: new Date().toISOString(),
          },
        },
        executingDimensions: alreadyExecuting
          ? currentExecuting
          : [...currentExecuting, key],
        currentPhase: getLayerPhase(action.layer),
      };
    }

    case 'SET_DIMENSION_COMPLETED': {
      const key = `${action.layer}_${action.dimensionKey}`;
      const existing = state.dimensionProgress[key];
      if (!existing) return state;

      // Optimized: use spread for Record, filter for array
      return {
        ...state,
        dimensionProgress: {
          ...state.dimensionProgress,
          [key]: {
            ...existing,
            status: 'completed' as DimensionStatus,
            wordCount: action.wordCount,
            completedAt: new Date().toISOString(),
          },
        },
        executingDimensions: state.executingDimensions.filter(k => k !== key),
      };
    }

    case 'CLEAR_DIMENSION_PROGRESS':
      return {
        ...state,
        dimensionProgress: {},
        executingDimensions: [],
        currentPhase: 'idle',
      };

    case 'SET_LAYER_COMPLETED':
      return {
        ...state,
        completedLayers: {
          ...state.completedLayers,
          [action.layer]: action.completed,
        },
      };

    case 'SET_REPORTS':
      return {
        ...state,
        reports: { ...state.reports, ...action.reports },
      };

    case 'SET_COMPLETED_DIMENSIONS':
      return { ...state, completedDimensions: action.completedDimensions };

    case 'SYNC_BACKEND_STATE': {
      const { backendData } = action;
      const newStatus = (backendData.status || 'idle') as Status;
      const isPausedValue = backendData.status === 'paused';
      const previousLayerValue = backendData.previous_layer;
      const pendingReviewLayer = previousLayerValue && previousLayerValue > 0 ? previousLayerValue : null;

      // Sync completed layers
      const newCompletedLayers = { ...state.completedLayers };
      if (backendData.layer_1_completed !== undefined) newCompletedLayers[1] = backendData.layer_1_completed;
      if (backendData.layer_2_completed !== undefined) newCompletedLayers[2] = backendData.layer_2_completed;
      if (backendData.layer_3_completed !== undefined) newCompletedLayers[3] = backendData.layer_3_completed;

      // Sync phase
      let newPhase = state.phase;
      let newCurrentLayer = state.currentLayer;
      if (backendData.phase) {
        newPhase = backendData.phase;
      }
      if (backendData.current_layer !== undefined) {
        newCurrentLayer = backendData.current_layer;
      }

      return {
        ...state,
        status: newStatus,
        isPaused: isPausedValue,
        pendingReviewLayer,
        completedLayers: newCompletedLayers,
        phase: newPhase,
        currentLayer: newCurrentLayer,
        selectedCheckpoint: backendData.last_checkpoint_id || state.selectedCheckpoint,
      };
    }

    case 'SET_VIEWER_VISIBLE':
      return { ...state, viewerVisible: action.visible };

    case 'SET_VIEWING_FILE':
      return { ...state, viewingFile: action.file };

    case 'SET_PAUSED':
      return { ...state, isPaused: action.paused };

    case 'SET_PENDING_REVIEW_LAYER':
      return { ...state, pendingReviewLayer: action.layer };

    case 'SET_VILLAGE_FORM_DATA':
      return { ...state, villageFormData: action.data };

    case 'SET_VILLAGES':
      return { ...state, villages: action.villages };

    case 'SET_SELECTED_VILLAGE':
      return { ...state, selectedVillage: action.village, selectedSession: null };

    case 'SET_SELECTED_SESSION':
      return { ...state, selectedSession: action.session };

    case 'SET_HISTORY_LOADING':
      return { ...state, historyLoading: action.loading };

    case 'SET_HISTORY_ERROR':
      return { ...state, historyError: action.error };

    case 'SET_CHECKPOINTS':
      return { ...state, checkpoints: action.checkpoints };

    case 'SET_SELECTED_CHECKPOINT':
      return { ...state, selectedCheckpoint: action.checkpointId };

    case 'SET_TOOL_STATUS': {
      // Optimized: use spread for Record
      return {
        ...state,
        toolStatuses: {
          ...state.toolStatuses,
          [action.toolName]: action.status,
        },
      };
    }

    case 'CLEAR_TOOL_STATUS': {
      // Optimized: use Object.fromEntries to remove key
      const rest = Object.fromEntries(
        Object.entries(state.toolStatuses).filter(([key]) => key !== action.toolName)
      );
      return { ...state, toolStatuses: rest };
    }

    case 'RESET_CONVERSATION':
      return {
        ...createInitialState(state.conversationId),
        villages: state.villages,
      };

    case 'SSE_EVENT':
      return handleSSEEvent(state, action.event);

    default:
      return state;
  }
}

// ============================================
// SSE Event Handler
// ============================================

function handleSSEEvent(state: PlanningState, event: SSEEvent): PlanningState {
  const eventType = event.type;
  const data = (event.data as Record<string, unknown>) || {};

  switch (eventType) {
    case 'dimension_delta': {
      const dimData = data as {
        dimension_key?: string;
        delta?: string;
        accumulated?: string;
        layer?: number;
      };
      const key = `${dimData.layer || 1}_${dimData.dimension_key || ''}`;
      const existing = state.dimensionProgress[key];
      if (existing) {
        // Optimized: add threshold guard to skip small updates
        const newWordCount = (dimData.accumulated || '').length;
        if (Math.abs(existing.wordCount - newWordCount) < 50) {
          return state; // Skip update for small changes
        }
        return {
          ...state,
          dimensionProgress: {
            ...state.dimensionProgress,
            [key]: { ...existing, wordCount: newWordCount },
          },
        };
      }
      return state;
    }

    case 'dimension_complete': {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        full_content?: string;
        layer?: number;
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || '';
      const key = `${layer}_${dimensionKey}`;

      // Optimized: use Record spread and array filter
      const nextProgress = {
        ...state.dimensionProgress,
        [key]: {
          dimensionKey,
          dimensionName: dimData.dimension_name || '',
          layer,
          status: 'completed' as DimensionStatus,
          wordCount: (dimData.full_content || '').length,
          completedAt: new Date().toISOString(),
        },
      };

      const nextExecuting = state.executingDimensions.filter(k => k !== key);

      // Update reports
      const nextReports = { ...state.reports };
      const layerKey = `layer${layer}` as keyof Reports;
      nextReports[layerKey] = {
        ...nextReports[layerKey],
        [dimensionKey]: dimData.full_content || '',
      };

      // Update completed dimensions
      const nextCompletedDims = { ...state.completedDimensions };
      const dimsList = [...(nextCompletedDims[layerKey] || [])];
      if (!dimsList.includes(dimensionKey)) {
        dimsList.push(dimensionKey);
      }
      nextCompletedDims[layerKey] = dimsList;

      // Create DimensionReportMessage
      const newMessage: DimensionReportMessage = {
        id: `dim_${layer}_${dimensionKey}_${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant',
        type: 'dimension_report',
        layer,
        dimensionKey,
        dimensionName: dimData.dimension_name || '',
        content: dimData.full_content || '',
        streamingState: 'completed',
        wordCount: (dimData.full_content || '').length,
      };

      return {
        ...state,
        dimensionProgress: nextProgress,
        executingDimensions: nextExecuting,
        reports: nextReports,
        completedDimensions: nextCompletedDims,
        messages: [...state.messages, newMessage],
      };
    }

    case 'layer_started': {
      const layerData = data as { layer?: number; layer_number?: number; layer_name?: string };
      const layerNum = layerData.layer || layerData.layer_number || 1;
      return {
        ...state,
        currentLayer: layerNum,
        currentPhase: getLayerPhase(layerNum),
      };
    }

    case 'layer_completed': {
      const layerData = data as {
        layer?: number;
        has_data?: boolean;
        dimension_count?: number;
        dimension_reports?: Record<string, string>;
      };
      const layerNum = layerData.layer || 1;
      const layerKey = `layer${layerNum}` as keyof Reports;

      const newCompletedLayers = { ...state.completedLayers, [layerNum]: true };
      const newReports = { ...state.reports };
      if (layerData.dimension_reports) {
        newReports[layerKey] = {
          ...newReports[layerKey],
          ...layerData.dimension_reports,
        };
      }

      return {
        ...state,
        completedLayers: newCompletedLayers,
        reports: newReports,
      };
    }

    case 'pause': {
      const pauseData = data as { current_layer?: number; checkpoint_id?: string };
      return {
        ...state,
        isPaused: true,
        pendingReviewLayer: pauseData.current_layer || null,
        selectedCheckpoint: pauseData.checkpoint_id || state.selectedCheckpoint,
      };
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
      if (!toolName) return state;
      // Optimized: use Record spread
      return {
        ...state,
        toolStatuses: {
          ...state.toolStatuses,
          [toolName]: {
            toolName,
            status: 'running',
            stage: toolData.stage,
            message: toolData.description,
          },
        },
      };
    }

    case 'tool_progress': {
      const toolData = data as {
        tool_name?: string;
        stage?: string;
        progress?: number;
        message?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return state;
      const existing = state.toolStatuses[toolName];
      if (!existing) return state;
      // Optimized: use Record spread
      return {
        ...state,
        toolStatuses: {
          ...state.toolStatuses,
          [toolName]: {
            ...existing,
            stage: toolData.stage || existing.stage,
            progress: toolData.progress,
            message: toolData.message,
          },
        },
      };
    }

    case 'tool_result': {
      const toolData = data as {
        tool_name?: string;
        status?: string;
        summary?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return state;
      const existing = state.toolStatuses[toolName];
      if (!existing) return state;
      // Optimized: use Record spread
      return {
        ...state,
        toolStatuses: {
          ...state.toolStatuses,
          [toolName]: {
            ...existing,
            status: toolData.status === 'error' ? 'error' : 'success',
            summary: toolData.summary,
          },
        },
      };
    }

    default:
      return state;
  }
}

// ============================================
// Context
// ============================================

interface PlanningContextValue {
  state: PlanningState;
  dispatch: React.Dispatch<PlanningAction>;
  actions: PlanningActions;
}

interface PlanningActions {
  startPlanning: (params: PlanningParams) => Promise<void>;
  approve: () => Promise<void>;
  reject: (feedback: string, dimensions?: string[]) => Promise<void>;
  rollback: (checkpointId: string) => Promise<void>;
  addMessage: (message: Message) => void;
  setMessages: (messages: Message[] | ((prev: Message[]) => Message[])) => void;
  loadVillagesHistory: () => Promise<void>;
  selectVillage: (village: VillageInfo) => void;
  selectSession: (session: VillageSession) => void;
  loadHistoricalSession: (villageName: string, sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string, villageName: string) => Promise<boolean>;
  showViewer: () => void;
  hideViewer: () => void;
  showFileViewer: (file: FileMessage) => void;
  hideFileViewer: () => void;
  resetConversation: () => void;
}

const PlanningContext = createContext<PlanningContextValue | undefined>(undefined);

// ============================================
// Provider
// ============================================

interface PlanningProviderProps {
  children: ReactNode;
  conversationId: string;
}

export type {
  PlanningState,
  PlanningAction,
  PlanningContextValue,
  PlanningActions,
  Reports,
  CompletedDimensions,
  ToolStatus,
  SSEEvent,
};

export function PlanningProvider({ children, conversationId }: PlanningProviderProps) {
  const [state, dispatch] = useReducer(planningReducer, createInitialState(conversationId));

  // SSE connection refs
  const sseConnectionRef = useRef<EventSource | null>(null);
  const prevTaskIdRef = useRef<string | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 5;

  // ============================================
  // SSE Batch Processing (Performance Optimization)
  // ============================================
  const batchQueueRef = useRef<SSEEvent[]>([]);
  const batchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const BATCH_WINDOW = 50; // ms

  // Process batched events - merge dimension_delta events by key
  const processBatch = useCallback(() => {
    const events = batchQueueRef.current;
    batchQueueRef.current = [];

    if (events.length === 0) return;

    // Group events by type
    const dimensionDeltaMap = new Map<string, SSEEvent>();
    const otherEvents: SSEEvent[] = [];

    for (const event of events) {
      if (event.type === 'dimension_delta') {
        const data = event.data as { layer?: number; dimension_key?: string };
        const key = `${data.layer || 1}_${data.dimension_key || ''}`;
        // Keep only the last event for each dimension key
        dimensionDeltaMap.set(key, event);
      } else {
        otherEvents.push(event);
      }
    }

    // Dispatch merged dimension_delta events
    for (const event of dimensionDeltaMap.values()) {
      dispatch({ type: 'SSE_EVENT', event });
    }

    // Dispatch other events
    for (const event of otherEvents) {
      dispatch({ type: 'SSE_EVENT', event });
    }
  }, []);

  // Enqueue event for batch processing
  const enqueueEvent = useCallback((event: SSEEvent) => {
    batchQueueRef.current.push(event);

    if (!batchTimeoutRef.current) {
      batchTimeoutRef.current = setTimeout(() => {
        batchTimeoutRef.current = null;
        processBatch();
      }, BATCH_WINDOW);
    }
  }, [processBatch]);

  // Cleanup batch timeout on unmount
  useEffect(() => {
    return () => {
      if (batchTimeoutRef.current) {
        clearTimeout(batchTimeoutRef.current);
        batchTimeoutRef.current = null;
      }
    };
  }, []);

  // ============================================
  // SSE Connection Management
  // ============================================

  const connectSSE = useCallback((taskId: string) => {
    if (sseConnectionRef.current) {
      sseConnectionRef.current.close();
    }

    console.log('[PlanningProvider] Connecting to SSE for task:', taskId);

    const es = planningApi.createStream(
      taskId,
      (event) => {
        reconnectAttemptsRef.current = 0;
        enqueueEvent(event); // Use batch processing instead of direct dispatch
      },
      (error) => {
        console.error('[PlanningProvider] SSE error:', error);

        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current++;
          const delay = Math.min(1000 * reconnectAttemptsRef.current, 5000);
          console.log(`[PlanningProvider] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`);
          setTimeout(() => {
            if (state.taskId) {
              connectSSE(state.taskId);
            }
          }, delay);
        }
      },
      () => {
        console.log('[PlanningProvider] SSE reconnected, syncing state...');
        if (state.taskId) {
          planningApi.getStatus(state.taskId).then((statusData) => {
            dispatch({ type: 'SYNC_BACKEND_STATE', backendData: statusData });
          });
        }
      }
    );

    sseConnectionRef.current = es;
    return es;
  }, [state.taskId, enqueueEvent]);

  // Connect/disconnect SSE when taskId changes
  useEffect(() => {
    if (!state.taskId) {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
      return;
    }

    if (prevTaskIdRef.current !== state.taskId) {
      prevTaskIdRef.current = state.taskId;
      connectSSE(state.taskId);
    }

    return () => {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
    };
  }, [state.taskId, connectSSE]);

  // ============================================
  // Actions
  // ============================================

  const actions: PlanningActions = {
    startPlanning: useCallback(async (params: PlanningParams) => {
      logger.context.info('Starting planning', { projectName: params.projectName });
      try {
        dispatch({ type: 'SET_STATUS', status: 'collecting' });
        dispatch({ type: 'SET_PROJECT_NAME', projectName: params.projectName });

        const response = await planningApi.startPlanning({
          project_name: params.projectName,
          village_data: params.villageData,
          task_description: params.taskDescription || PLANNING_DEFAULTS.defaultTask,
          constraints: params.constraints || PLANNING_DEFAULTS.defaultConstraints,
          enable_review: params.enableReview ?? PLANNING_DEFAULTS.enableReview,
          step_mode: params.stepMode ?? PLANNING_DEFAULTS.stepMode,
          stream_mode: PLANNING_DEFAULTS.streamMode,
        });

        if (!response || typeof response.task_id !== 'string') {
          throw new Error('Server response missing task ID');
        }

        dispatch({ type: 'SET_TASK_ID', taskId: response.task_id });
        dispatch({ type: 'SET_STATUS', status: 'planning' });
        dispatch({
          type: 'ADD_MESSAGE',
          message: createSystemMessage(`Planning started. Task ID: ${response.task_id.slice(0, 8)}...`),
        });
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Unknown error');
        logger.context.error('Planning failed to start', { error: errorMessage });
        dispatch({ type: 'SET_STATUS', status: 'failed' });
        dispatch({
          type: 'ADD_MESSAGE',
          message: createErrorMessage(`Failed to start planning: ${errorMessage}`),
        });
        throw error;
      }
    }, []),

    approve: useCallback(async () => {
      if (!state.taskId) throw new Error('No task ID');
      await planningApi.approveReview(state.taskId);
      dispatch({ type: 'SET_PAUSED', paused: false });
      dispatch({ type: 'SET_PENDING_REVIEW_LAYER', layer: null });
    }, [state.taskId]),

    reject: useCallback(async (feedback: string, dimensions?: string[]) => {
      if (!state.taskId) throw new Error('No task ID');
      await planningApi.rejectReview(state.taskId, feedback, dimensions);
      dispatch({ type: 'SET_PAUSED', paused: false });
    }, [state.taskId]),

    rollback: useCallback(async (checkpointId: string) => {
      if (!state.taskId) throw new Error('No task ID');
      await planningApi.rollbackCheckpoint(state.taskId, checkpointId);
      dispatch({ type: 'SET_SELECTED_CHECKPOINT', checkpointId });

      // Sync state after rollback
      const statusData = await planningApi.getStatus(state.taskId);
      dispatch({ type: 'SYNC_BACKEND_STATE', backendData: statusData });

      dispatch({
        type: 'ADD_MESSAGE',
        message: createSystemMessage(`Rolled back to checkpoint ${checkpointId.slice(0, 8)}...`),
      });
    }, [state.taskId]),

    addMessage: useCallback((message: Message) => {
      dispatch({ type: 'ADD_MESSAGE', message });
    }, []),

    setMessages: useCallback((messages: Message[] | ((prev: Message[]) => Message[])) => {
      if (typeof messages === 'function') {
        // Need to handle function form
        dispatch({ type: 'SET_MESSAGES', messages: [] }); // Placeholder
      } else {
        dispatch({ type: 'SET_MESSAGES', messages });
      }
    }, []),

    loadVillagesHistory: useCallback(async () => {
      dispatch({ type: 'SET_HISTORY_LOADING', loading: true });
      dispatch({ type: 'SET_HISTORY_ERROR', error: null });
      try {
        const data = await dataApi.listVillages();
        dispatch({ type: 'SET_VILLAGES', villages: data });
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, 'Failed to load history');
        dispatch({ type: 'SET_HISTORY_ERROR', error: errorMessage });
        dispatch({ type: 'SET_VILLAGES', villages: [] });
      } finally {
        dispatch({ type: 'SET_HISTORY_LOADING', loading: false });
      }
    }, []),

    selectVillage: useCallback((village: VillageInfo) => {
      dispatch({ type: 'SET_SELECTED_VILLAGE', village });
    }, []),

    selectSession: useCallback((session: VillageSession) => {
      dispatch({ type: 'SET_SELECTED_SESSION', session });
    }, []),

    loadHistoricalSession: useCallback(async (villageName: string, sessionId: string) => {
      dispatch({ type: 'CLEAR_MESSAGES' });
      dispatch({ type: 'SET_CHECKPOINTS', checkpoints: [] });
      dispatch({ type: 'SET_SELECTED_CHECKPOINT', checkpointId: null });
      dispatch({ type: 'SET_PROJECT_NAME', projectName: villageName });
      dispatch({ type: 'SET_TASK_ID', taskId: sessionId });
      dispatch({ type: 'SET_STATUS', status: 'completed' });

      // Load checkpoints and reports
      try {
        const response = await dataApi.getCheckpoints(villageName, sessionId);
        dispatch({ type: 'SET_CHECKPOINTS', checkpoints: response.checkpoints });

        const statusData = await planningApi.getStatus(sessionId);
        dispatch({ type: 'SYNC_BACKEND_STATE', backendData: statusData });
      } catch (error: unknown) {
        console.error('[PlanningProvider] Failed to load historical session:', error);
      }
    }, []),

    deleteSession: useCallback(async (sessionId: string, _villageName: string): Promise<boolean> => {
      try {
        await planningApi.deleteSession(sessionId);
        dispatch({ type: 'SET_HISTORY_LOADING', loading: true });
        const data = await dataApi.listVillages();
        dispatch({ type: 'SET_VILLAGES', villages: data });
        dispatch({ type: 'SET_HISTORY_LOADING', loading: false });

        if (state.taskId === sessionId) {
          dispatch({ type: 'RESET_CONVERSATION' });
        }
        return true;
      } catch (error: unknown) {
        console.error('[PlanningProvider] Failed to delete session:', error);
        return false;
      }
    }, [state.taskId]),

    showViewer: useCallback(() => {
      dispatch({ type: 'SET_VIEWER_VISIBLE', visible: true });
    }, []),

    hideViewer: useCallback(() => {
      dispatch({ type: 'SET_VIEWER_VISIBLE', visible: false });
    }, []),

    showFileViewer: useCallback((file: FileMessage) => {
      dispatch({ type: 'SET_VIEWING_FILE', file });
    }, []),

    hideFileViewer: useCallback(() => {
      dispatch({ type: 'SET_VIEWING_FILE', file: null });
    }, []),

    resetConversation: useCallback(() => {
      dispatch({ type: 'RESET_CONVERSATION' });
    }, []),
  };

  const value: PlanningContextValue = {
    state,
    dispatch,
    actions,
  };

  return (
    <PlanningContext.Provider value={value}>
      {children}
    </PlanningContext.Provider>
  );
}

// ============================================
// Hook
// ============================================

export function usePlanningContext(): PlanningContextValue {
  const context = useContext(PlanningContext);
  if (!context) {
    throw new Error('usePlanningContext must be used within a PlanningProvider');
  }
  return context;
}

export function usePlanningContextOptional(): PlanningContextValue | undefined {
  return useContext(PlanningContext);
}