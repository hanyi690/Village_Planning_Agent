'use client';

/**
 * Unified Planning Context
 * 统一规划上下文 - 对话状态、UI状态和内容管理
 */

import { createContext, useContext, useState, useCallback, ReactNode, useMemo, useEffect, useRef } from 'react';
import { Message, PlanningParams, Checkpoint } from '@/types';
import { VillageInputData } from '@/components/VillageInputForm';
import { planningApi, dataApi, VillageInfo, VillageSession } from '@/lib/api';
import { createBaseMessage, createSystemMessage, createErrorMessage } from '@/lib/utils';
import { logger } from '@/lib/logger';
import { LAYER_ID_MAP } from '@/lib/constants';
import { PLANNING_DEFAULTS } from '@/config/planning';

type Status = 'idle' | 'collecting' | 'planning' | 'paused' | 'reviewing' | 'revising' | 'completed' | 'failed';

/**
 * Unified view state modes
 * - WELCOME_FORM: Show village input form for new planning
 * - SESSION_ACTIVE: Show chat interface and reports
 */
export type ViewMode = 'WELCOME_FORM' | 'SESSION_ACTIVE';

export interface ReportSyncState {
  lastUpdated: number;
  currentLayer: number | null;
  isStreaming: boolean;
}

export interface LayerContent {
  layerId: string;
  content: string;
  timestamp: string;
  checkpointId: string;
}

interface UnifiedPlanningContextType {
  // Conversation state
  conversationId: string;
  messages: Message[];
  taskId: string | null;
  projectName: string | null;
  status: Status;
  viewerVisible: boolean;
  referencedSection?: string;
  viewMode: ViewMode;

  // Form data
  villageFormData: VillageInputData | null;

  // History state
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  historyLoading: boolean;
  historyError: string | null;

  // Review state (简化版 - 直接从后端同步)
  isPaused: boolean;           // 暂停状态: status === 'paused'
  pendingReviewLayer: number | null;  // 待审查层级: previous_layer

  // 层级完成状态
  completedLayers: {
    1: boolean;
    2: boolean;
    3: boolean;
  };

  // 同步后端状态的 action
  syncBackendState: (backendData: any) => void;

  // Checkpoints
  checkpoints: Checkpoint[];
  currentLayer: number | null;

  // Content data
  selectedCheckpoint: string | null;
  loadingContent: boolean;

  // Report sync state (NEW)
  reportSyncState: ReportSyncState;
  triggerReportUpdate: (layer: number, content: string) => void;

  // Layer report state
  layerReportVisible: boolean;
  setLayerReportVisible: (visible: boolean) => void;
  activeReportLayer: number;
  setActiveReportLayer: (layer: number) => void;

  // Conversation actions
  addMessage: (message: Message) => void;
  setMessages: (messages: Message[] | ((prev: Message[]) => Message[])) => void;
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;
  setTaskId: (taskId: string | null) => void;
  setProjectName: (name: string | null) => void;
  setStatus: (status: Status) => void;

  // Form actions
  setVillageFormData: (data: VillageInputData | null) => void;

  // Checkpoint actions
  setCheckpoints: (checkpoints: Checkpoint[]) => void;
  setCurrentLayer: (layer: number | null) => void;

  // Content actions
  loadLayerContent: (layerId: string) => Promise<void>;
  loadCheckpoints: () => Promise<void>;
  setSelectedCheckpoint: (checkpointId: string | null) => void;
  rollbackToCheckpoint: (checkpointId: string) => Promise<void>;

  // Legacy compatibility
  showViewer: () => void;
  hideViewer: () => void;
  toggleViewer: () => void;
  highlightSection: (section: string) => void;
  clearHighlight: () => void;
  startPlanning: (params: PlanningParams) => Promise<void>;
  resetConversation: () => void;

  // History actions
  loadVillagesHistory: () => Promise<void>;
  selectVillage: (village: VillageInfo) => void;
  selectSession: (session: VillageSession) => void;
  loadHistoricalSession: (villageName: string, sessionId: string) => Promise<void>;
  loadHistoricalReports: (villageName: string, sessionId: string) => Promise<void>;
}

const UnifiedPlanningContext = createContext<UnifiedPlanningContextType | undefined>(undefined);

interface UnifiedPlanningProviderProps {
  children: ReactNode;
  conversationId: string;
}

export function UnifiedPlanningProvider({
  children,
  conversationId,
}: UnifiedPlanningProviderProps) {
  // Conversation state
  const [messages, setMessages] = useState<Message[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string | null>(null);
  const [status, setStatusState] = useState<Status>('idle');
  const [viewerVisible, setViewerVisible] = useState(false);
  const [referencedSection, setReferencedSection] = useState<string | undefined>();

  // Form state
  const [villageFormData, setVillageFormData] = useState<VillageInputData | null>(null);

  // 审查状态 (直接从后端同步)
  const [isPaused, setIsPaused] = useState(false);
  const [pendingReviewLayer, setPendingReviewLayer] = useState<number | null>(null);

  // 层级完成状态
  const [completedLayers, setCompletedLayers] = useState({
    1: false,
    2: false,
    3: false,
  });

  // 用于跟踪之前的状态，避免不必要的更新
  const previousBackendStateRef = useRef<any>(null);

  // History state
  const [villages, setVillages] = useState<VillageInfo[]>([]);
  const [selectedVillage, setSelectedVillage] = useState<VillageInfo | null>(null);
  const [selectedSession, setSelectedSessionState] = useState<VillageSession | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Checkpoint state
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [currentLayer, setCurrentLayer] = useState<number | null>(null);

  // Content state
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);

  // Layer report state
  const [layerReportVisible, setLayerReportVisible] = useState(false);
  const [activeReportLayer, setActiveReportLayer] = useState(1);

  // Report sync state
  const [reportSyncState, setReportSyncState] = useState<ReportSyncState>({
    lastUpdated: 0,
    currentLayer: null,
    isStreaming: false,
  });

  // Computed view mode - single source of truth for UI state
  const viewMode: ViewMode = useMemo(() => {
    if (taskId && taskId !== 'new') {
      return 'SESSION_ACTIVE';
    }
    if (status !== 'idle') {
      return 'SESSION_ACTIVE';
    }
    return 'WELCOME_FORM';
  }, [taskId, status]);

  // Conversation actions
  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  // Custom setStatus (no side effects - side effects moved to useEffect below)
  const setStatus = useCallback((newStatus: Status) => {
    setStatusState(newStatus);
  }, []);

  const updateLastMessage = useCallback((updates: Partial<Message>) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const lastMessage = prev[prev.length - 1];
      return [...prev.slice(0, -1), { ...lastMessage, ...updates } as Message];
    });
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  // 同步后端状态到 Context
  const syncBackendState = useCallback((backendData: any) => {
    // 比较关键字段，避免不必要的更新
    const previousState = previousBackendStateRef.current;
    const hasStateChanged = !previousState ||
      previousState.status !== backendData.status ||
      previousState.previous_layer !== backendData.previous_layer ||
      previousState.layer_1_completed !== backendData.layer_1_completed ||
      previousState.layer_2_completed !== backendData.layer_2_completed ||
      previousState.layer_3_completed !== backendData.layer_3_completed;

    if (!hasStateChanged) {
      console.log('[UnifiedPlanningContext] State unchanged, skipping update');
      return;
    }

    console.log('[UnifiedPlanningContext] Syncing backend state (changed):', {
      status: backendData.status,
      previous_layer: backendData.previous_layer,
      layer_1_completed: backendData.layer_1_completed,
      layer_2_completed: backendData.layer_2_completed,
      layer_3_completed: backendData.layer_3_completed,
      current_layer: backendData.current_layer,
    });

    setStatusState(backendData.status || 'idle');
    
    // 暂停状态判断: status === 'paused'
    const isPausedValue = backendData.status === 'paused';
    setIsPaused(isPausedValue);
    console.log('[UnifiedPlanningContext] Set isPaused:', isPausedValue);
    
    // 待审查层级: previous_layer
    const previousLayerValue = backendData.previous_layer;
    setPendingReviewLayer(previousLayerValue && previousLayerValue > 0 ? previousLayerValue : null);
    console.log('[UnifiedPlanningContext] Set pendingReviewLayer:', previousLayerValue);

    // 同步层级完成状态
    const completedLayersData = {
      1: backendData.layer_1_completed || false,
      2: backendData.layer_2_completed || false,
      3: backendData.layer_3_completed || false,
    };
    setCompletedLayers(completedLayersData);

    // 同步其他状态
    if (backendData.last_checkpoint_id) {
      setSelectedCheckpoint(backendData.last_checkpoint_id);
    }

    if (backendData.execution_error) {
      console.error('[UnifiedPlanningContext] Backend error:', backendData.execution_error);
    }

    // 更新之前的状态引用
    previousBackendStateRef.current = {
      status: backendData.status,
      previous_layer: backendData.previous_layer,
      layer_1_completed: backendData.layer_1_completed,
      layer_2_completed: backendData.layer_2_completed,
      layer_3_completed: backendData.layer_3_completed,
    };
  }, []);

  // Viewer actions
  const showViewer = useCallback(() => setViewerVisible(true), []);
  const hideViewer = useCallback(() => setViewerVisible(false), []);
  const toggleViewer = useCallback(() => setViewerVisible(prev => !prev), []);
  const highlightSection = useCallback((section: string) => {
    setReferencedSection(section);
    setViewerVisible(true);
  }, []);
  const clearHighlight = useCallback(() => setReferencedSection(undefined), []);

  // Content actions
  const loadLayerContent = useCallback(async (layerId: string) => {
    if (!taskId || !projectName) {
      console.warn('[UnifiedPlanningContext] Cannot load content: missing taskId or projectName');
      return;
    }

    try {
      setLoadingContent(true);

      // Load from API with session parameter
      const data = await dataApi.getLayerContent(
        projectName,
        layerId,
        taskId,  // Pass session ID to locate correct directory
        'markdown'
      );

      // Content is loaded but not stored in context anymore
      // Components should fetch content directly when needed
    } catch (error) {
      console.error('[UnifiedPlanningContext] Failed to load layer content:', error);
      throw error;
    } finally {
      setLoadingContent(false);
    }
  }, [taskId, projectName]);

  const loadCheckpoints = useCallback(async () => {
    if (!projectName) {
      console.warn('[UnifiedPlanningContext] Cannot load checkpoints: missing projectName');
      return;
    }

    try {
      // Pass taskId as session parameter to load checkpoints for specific session
      const response = await dataApi.getCheckpoints(projectName, taskId || undefined);
      setCheckpoints(response.checkpoints);
    } catch (error) {
      console.error('[UnifiedPlanningContext] Failed to load checkpoints:', error);
      throw error;
    }
  }, [projectName, taskId]);

  const rollbackToCheckpoint = useCallback(async (checkpointId: string) => {
    if (!taskId) {
      console.warn('[UnifiedPlanningContext] Cannot rollback: missing taskId');
      return;
    }

    try {
      await planningApi.rollbackCheckpoint(taskId, checkpointId);
      setSelectedCheckpoint(checkpointId);

      // Reload checkpoints and content
      await loadCheckpoints();

      // Clear cached content to force reload
      // TODO: setLayerContents was not defined, need to fix this properly
      // setLayerContents({});

      addMessage(createSystemMessage(`✅ 已回退到检查点 ${checkpointId.slice(0, 8)}...`));
    } catch (error) {
      console.error('[UnifiedPlanningContext] Failed to rollback:', error);
      throw error;
    }
  }, [taskId, loadCheckpoints, addMessage]);

  // Planning actions
  const startPlanning = useCallback(async (params: PlanningParams) => {
    logger.context.info('开始规划流程', { projectName: params.projectName });

    try {
      setStatus('collecting');
      setProjectName(params.projectName);
      logger.context.info('设置状态为 collecting');

      const response = await planningApi.startPlanning({
        project_name: params.projectName,
        village_data: params.villageData,
        task_description: params.taskDescription || PLANNING_DEFAULTS.defaultTask,
        constraints: params.constraints || PLANNING_DEFAULTS.defaultConstraints,
        enable_review: params.enableReview ?? PLANNING_DEFAULTS.enableReview,
        step_mode: params.stepMode ?? PLANNING_DEFAULTS.stepMode,
        stream_mode: PLANNING_DEFAULTS.streamMode,
      });

      // 强制检查 task_id 存在
      if (!response || typeof response.task_id !== 'string') {
        throw new Error('服务器响应缺少任务ID，可能已达请求频率上限');
      }

      setTaskId(response.task_id);
      setStatus('planning');

      logger.context.info('API 调用成功', { taskId: response.task_id });
      addMessage(createSystemMessage(`🚀 规划任务已创建，任务ID: ${response.task_id.slice(0, 8)}...`));
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      logger.context.error('规划流程失败', { error: errorMessage });
      console.error('[UnifiedPlanningContext] Failed to start planning:', error);
      setStatus('failed');
      addMessage(createErrorMessage(`启动规划失败: ${errorMessage}`));
      throw error;
    }
  }, [addMessage]);

  // Trigger report update (同步更新聊天流)
  const triggerReportUpdate = useCallback((layer: number, content: string) => {
    const layerId = LAYER_ID_MAP[layer];
    if (!layerId) return;

    setReportSyncState({
      lastUpdated: Date.now(),
      currentLayer: layer,
      isStreaming: false,
    });
  }, []);

  const resetConversation = useCallback(() => {
    setMessages([]);
    setTaskId(null);
    setProjectName(null);
    setStatus('idle');
    setViewerVisible(false);
    setReferencedSection(undefined);
    setVillageFormData(null);
    setIsPaused(false);
    setPendingReviewLayer(null);
    setCheckpoints([]);
    setCurrentLayer(null);
    setSelectedCheckpoint(null);
    setReportSyncState({
      lastUpdated: 0,
      currentLayer: null,
      isStreaming: false,
    });
    // Don't reset history state when resetting conversation
  }, []);

  // History actions
  const loadVillagesHistory = useCallback(async () => {
    try {
      setHistoryLoading(true);
      setHistoryError(null);
      const data = await dataApi.listVillages();
      setVillages(data);
      console.log('[UnifiedPlanningContext] Loaded villages history:', data.length, 'villages');
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '加载历史记录失败';
      console.error('[UnifiedPlanningContext] Failed to load villages history:', error);
      setHistoryError(errorMessage);
      setVillages([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const selectVillage = useCallback((village: VillageInfo) => {
    setSelectedVillage(village);
    setSelectedSessionState(null);
    console.log('[UnifiedPlanningContext] Selected village:', village.display_name);
  }, []);

  const selectSession = useCallback((session: VillageSession) => {
    setSelectedSessionState(session);
    console.log('[UnifiedPlanningContext] Selected session:', session.session_id);
  }, []);

  // Load historical session reports into chat
  const loadHistoricalReports = useCallback(async (villageName: string, sessionId: string) => {
    if (!villageName || !sessionId) {
      console.warn('[UnifiedPlanningContext] Missing village or session ID for loading reports');
      return;
    }

    console.log('[UnifiedPlanningContext] Loading historical reports for:', villageName, sessionId);

    const layers = [
      { id: 'layer_1_analysis', number: 1, name: '现状分析' },
      { id: 'layer_2_concept', number: 2, name: '规划思路' },
      { id: 'layer_3_detailed', number: 3, name: '详细规划' },
    ] as const;

    try {
      for (const layer of layers) {
        try {
          console.log('[UnifiedPlanningContext] Loading layer:', layer.id);

          const data = await dataApi.getLayerContent(villageName, layer.id, sessionId, 'markdown');

          console.log('[UnifiedPlanningContext] Loaded layer:', layer.number,
                      'content length:', data.content?.length || 0);

          if (!data.content?.length) {
            console.warn('[UnifiedPlanningContext] Layer has no content:', layer.id);
            continue;
          }

          // Create layer completed message
          const layerMessage: Message = {
            id: `msg-historical-layer-${layer.number}-${Date.now()}`,
            timestamp: data.timestamp ? new Date(data.timestamp) : new Date(),
            role: 'assistant',
            type: 'layer_completed',
            layer: layer.number,
            content: `## ${layer.name}(历史会话)\n\n${data.content.substring(0, 200)}...`,
            summary: {
              word_count: data.content.length,
              key_points: [`已加载 ${layer.name}`],
              dimension_count: 0,
              dimension_names: [],
            },
            fullReportContent: data.content,
            dimensionReports: undefined,
            actions: [
              { id: 'view', label: '查看详情', action: 'view', variant: 'primary' },
            ],
          };

          addMessage(layerMessage);
        } catch (error) {
          console.error(`[UnifiedPlanningContext] Failed to load ${layer.id}:`, error);
          // Continue to next layer instead of throwing
        }
      }

      console.log('[UnifiedPlanningContext] Historical reports loaded successfully');
    } catch (error) {
      console.error('[UnifiedPlanningContext] Failed to load historical reports:', error);
      addMessage(createErrorMessage('加载历史报告失败'));
    }
  }, [addMessage]);

  const loadHistoricalSession = useCallback(async (villageName: string, sessionId: string) => {
    try {
      clearMessages();
      setCheckpoints([]);
      setSelectedCheckpoint(null);

      // Reset report sync state
      setReportSyncState({
        lastUpdated: 0,
        currentLayer: null,
        isStreaming: false,
      });

      // Set new session info
      setProjectName(villageName);
      setTaskId(sessionId);
      setStatus('completed');

      await loadCheckpoints();
      addMessage(createSystemMessage(`📂 已加载历史会话: ${villageName} (${sessionId.slice(0, 8)}...)`));
      await loadHistoricalReports(villageName, sessionId);

      console.log('[UnifiedPlanningContext] Loaded historical session with reports:', sessionId);
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      console.error('[UnifiedPlanningContext] Failed to load historical session:', error);
      addMessage(createSystemMessage(`❌ 加载历史会话失败: ${errorMessage}`));
    }
  }, [clearMessages, loadCheckpoints, addMessage, loadHistoricalReports]);

  // Context value
  const value: UnifiedPlanningContextType = {
    // State
    conversationId,
    messages,
    taskId,
    projectName,
    status,
    viewerVisible,
    referencedSection,
    viewMode,
    villageFormData,
    setVillageFormData,
    checkpoints,
    setCheckpoints,
    selectedCheckpoint,
    loadingContent,
    layerReportVisible,
    setLayerReportVisible,
    activeReportLayer,
    setActiveReportLayer,
    reportSyncState,
    triggerReportUpdate,

    // 审查状态
    isPaused,
    pendingReviewLayer,

    // 层级完成状态
    completedLayers,

    // 同步后端状态
    syncBackendState,

    // Checkpoints
    currentLayer,
    setCurrentLayer,

    // History state
    villages,
    selectedVillage,
    selectedSession,
    historyLoading,
    historyError,

    // Actions
    addMessage,
    setMessages,
    updateLastMessage,
    clearMessages,
    setTaskId,
    setProjectName,
    setStatus,
    loadLayerContent,
    loadCheckpoints,
    setSelectedCheckpoint,
    rollbackToCheckpoint,
    showViewer,
    hideViewer,
    toggleViewer,
    highlightSection,
    clearHighlight,
    startPlanning,
    resetConversation,

    // History actions
    loadVillagesHistory,
    selectVillage,
    selectSession,
    loadHistoricalSession,
    loadHistoricalReports,
  };

  return (
    <UnifiedPlanningContext.Provider value={value}>
      {children}
    </UnifiedPlanningContext.Provider>
  );
}

// Hooks
export function useUnifiedPlanningContext(): UnifiedPlanningContextType {
  const context = useContext(UnifiedPlanningContext);
  if (!context) {
    throw new Error('useUnifiedPlanningContext must be used within a UnifiedPlanningProvider');
  }
  return context;
}

export function useUnifiedPlanningContextOptional(): UnifiedPlanningContextType | undefined {
  return useContext(UnifiedPlanningContext);
}

// Migration helper for backward compatibility
export function useConversationContext() {
  return useUnifiedPlanningContext();
}
