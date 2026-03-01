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
import { getDimensionsByLayer, DIMENSION_NAMES } from '@/config/dimensions';

/**
 * 解析 Markdown 报告内容，提取维度数据
 * 用于历史记录加载时构建 dimensionReports
 */
function parseDimensionReports(markdown: string, layerNumber: number): Record<string, string> {
  const dimensionKeys = getDimensionsByLayer(layerNumber);
  const result: Record<string, string> = {};
  
  if (!markdown) return result;
  
  // 匹配 ## 标题格式
  const regex = /##\s+(.+?)\n([\s\S]*?)(?=\n##\s|$)/g;
  let match;
  
  while ((match = regex.exec(markdown)) !== null) {
    const title = match[1].trim();
    const content = match[2].trim();
    
    // 尝试匹配维度键名（标题可能是英文键名或中文名称）
    const key = dimensionKeys.find(k => {
      const chineseName = DIMENSION_NAMES[k];
      return title === k || 
             title.includes(k) || 
             k.includes(title) ||
             title === chineseName ||
             title.includes(chineseName) ||
             chineseName.includes(title);
    });
    
    if (key && content) {
      result[key] = content;
    }
  }
  
  console.log(`[parseDimensionReports] Layer ${layerNumber}: found ${Object.keys(result).length} dimensions`);
  return result;
}

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

  // ✅ 新增：SSE 驱动的层级完成状态更新
  setUILayerCompleted: (layer: number, completed: boolean) => void;
  
  // ✅ 新增：从 REST 状态恢复（用于断线重连）
  restoreFromBackendState: () => void;

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

  // 层级完成状态（双重状态源）
  // backendCompletedLayers: 来自 REST 轮询，用于断线重连恢复
  // completedLayers: 来自 SSE 事件，用于 UI 渲染（单一真实源）
  const [backendCompletedLayers, setBackendCompletedLayers] = useState({
    1: false,
    2: false,
    3: false,
  });

  // SSE 驱动的层级完成状态 - UI 渲染的真实源
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

    // ✅ 重构：更新 REST 状态（用于断线重连恢复）
    const backendCompletedData = {
      1: backendData.layer_1_completed || false,
      2: backendData.layer_2_completed || false,
      3: backendData.layer_3_completed || false,
    };
    setBackendCompletedLayers(backendCompletedData);

    // ✅ 重构：仅当 SSE 未连接时（status === 'idle' 或初始加载），使用 REST 状态恢复
    // 这样可以处理断线重连的情况，同时避免 REST 轮询覆盖 SSE 的实时状态
    const currentStatus = backendData.status;
    if (currentStatus === 'idle' || currentStatus === 'completed' || currentStatus === 'failed') {
      // 会话结束或初始状态，同步 REST 状态到 UI
      setCompletedLayers(backendCompletedData);
      console.log('[UnifiedPlanningContext] Sync REST state to UI (session ended or idle):', backendCompletedData);
    }
    // 注意：运行中的状态由 SSE 的 layer_stream_complete 事件驱动，不在此处更新

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

  // ✅ 新增：SSE 驱动的层级完成状态更新
  // 此函数由 SSE 的 layer_stream_complete 事件调用
  const setUILayerCompleted = useCallback((layer: number, completed: boolean) => {
    setCompletedLayers(prev => {
      if (prev[layer as 1 | 2 | 3] === completed) {
        return prev; // 无变化，避免重渲染
      }
      const newState = { ...prev, [layer]: completed };
      console.log(`[UnifiedPlanningContext] SSE-driven layer ${layer} completed:`, completed);
      return newState;
    });
  }, []);

  // ✅ 新增：从 REST 状态恢复（用于断线重连）
  const restoreFromBackendState = useCallback(() => {
    setCompletedLayers(backendCompletedLayers);
    console.log('[UnifiedPlanningContext] Restored from backend state:', backendCompletedLayers);
  }, [backendCompletedLayers]);

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
      console.log('[UnifiedPlanningContext] Raw data:', JSON.stringify(data, null, 2));
      console.log('[UnifiedPlanningContext] First village sessions:', data[0]?.sessions?.slice(0, 2));
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

    // 【新增】先加载消息历史和修订历史
    try {
      const statusData = await planningApi.getStatus(sessionId);
      
      // 1. 还原消息历史
      if (statusData.messages && statusData.messages.length > 0) {
        console.log('[UnifiedPlanningContext] Loading message history:', statusData.messages.length, 'messages');
        for (const msg of statusData.messages) {
          // 跳过空消息
          if (!msg.content || msg.content.trim().length === 0) continue;
          
          addMessage({
            id: `msg-history-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            timestamp: new Date(),
            role: msg.role as 'user' | 'assistant' | 'system',
            type: 'text',
            content: msg.content,
          });
        }
      }
      
      // 2. 还原修订历史（修复对话流）
      if (statusData.revision_history && statusData.revision_history.length > 0) {
        console.log('[UnifiedPlanningContext] Loading revision history:', statusData.revision_history.length, 'revisions');
        for (const revision of statusData.revision_history) {
          const dimensionName = DIMENSION_NAMES[revision.dimension] || revision.dimension;
          
          // 添加用户反馈消息
          if (revision.feedback) {
            addMessage({
              id: `msg-revision-feedback-${Date.now()}-${Math.random().toString(36).slice(2)}`,
              timestamp: new Date(revision.timestamp),
              role: 'user',
              type: 'text',
              content: `修改意见（${dimensionName}）：${revision.feedback}`,
            });
          }
          
          // 添加修复结果消息
          addMessage({
            id: `msg-revision-result-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            timestamp: new Date(revision.timestamp),
            role: 'assistant',
            type: 'dimension_report',
            layer: revision.layer,
            dimensionKey: revision.dimension,
            dimensionName: dimensionName,
            content: revision.new_content,
            streamingState: 'completed',
            wordCount: revision.new_content?.length || 0,
          });
        }
      }
    } catch (error) {
      console.warn('[UnifiedPlanningContext] Failed to load message history:', error);
      // 继续加载层级报告
    }

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

          // 解析维度数据
          const dimensionReports = parseDimensionReports(data.content, layer.number);
          const dimensionCount = Object.keys(dimensionReports).length;
          const dimensionNames = Object.keys(dimensionReports).map(k => DIMENSION_NAMES[k] || k);

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
              dimension_count: dimensionCount,
              dimension_names: dimensionNames,
            },
            fullReportContent: data.content,
            dimensionReports: dimensionReports,
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

    // ✅ 新增：SSE 驱动的层级完成状态更新
    setUILayerCompleted,
    
    // ✅ 新增：从 REST 状态恢复（用于断线重连）
    restoreFromBackendState,

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
