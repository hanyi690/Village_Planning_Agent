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
  setIsPaused: (paused: boolean) => void;  // 🔧 新增：用于 SSE pause 事件更新
  setPendingReviewLayer: (layer: number | null) => void;  // 🔧 新增：用于 SSE pause 事件更新

  // 层级完成状态
  completedLayers: {
    1: boolean;
    2: boolean;
    3: boolean;
  };

  // 同步后端状态的 action
  syncBackendState: (backendData: any) => void;

  // ✅ SSE 驱动的层级完成状态更新
  setUILayerCompleted: (layer: number, completed: boolean) => void;

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
  syncMessageToBackend: (message: Message) => void;  // 🔧 新增：同步消息到后端
  setMessages: (messages: Message[] | ((prev: Message[]) => Message[])) => void;
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;
  setTaskId: (taskId: string | null) => void;
  setProjectName: (name: string | null) => void;
  setStatus: (status: Status) => void;

  // Form actions
  setVillageFormData: (data: VillageInputData | null) => void;

  // Checkpoint actions
  setCheckpoints: (checkpoints: Checkpoint[] | ((prev: Checkpoint[]) => Checkpoint[])) => void;
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
  deleteSession: (sessionId: string, villageName: string) => Promise<boolean>;
  deletingSessionId: string | null;
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

  // 层级完成状态（单一状态源）
  // SSE 事件驱动更新，REST 轮询用于断线重连恢复
  const [completedLayers, setCompletedLayers] = useState({
    1: false,
    2: false,
    3: false,
  });

  // 用于跟踪之前的状态，避免不必要的更新
  const previousBackendStateRef = useRef<any>(null);

  // 用于跟踪是否正在加载历史消息（避免重复存储）
  const isLoadingHistoryRef = useRef(false);

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

    // 异步存储消息到后端（跳过历史消息加载期间和延迟存储的消息）
    // 🔧 跳过有 _pendingStorage 标记的消息（等待完整数据后再存储）
    const pendingStorage = (message as any)._pendingStorage;
    if (!isLoadingHistoryRef.current && taskId && !pendingStorage) {
      // 异步存储，不阻塞 UI
      // ✅ 传递消息 ID 用于 upsert
      planningApi.createMessage(taskId, {
        id: message.id,  // 前端消息 ID（用于 upsert）
        role: message.role,
        content: message.type === 'text' ? message.content :
                 message.type === 'file' ? `[文件] ${message.filename}` :
                 message.type === 'progress' ? message.content :
                 message.type === 'dimension_report' ? message.content :
                 message.type === 'layer_completed' ? message.content : '',
        message_type: message.type,
        metadata: message.type !== 'text' ? { ...message } as unknown as Record<string, unknown> : undefined,
      }).catch((error) => {
        console.warn('[UnifiedPlanningContext] Failed to store message:', error);
      });
    }
  }, [taskId]);

  // 🔧 新增：同步单条消息到后端（用于消息更新后的持久化）
  const syncMessageToBackend = useCallback((message: Message) => {
    if (!isLoadingHistoryRef.current && taskId) {
      // ✅ 传递消息 ID 用于 upsert
      planningApi.createMessage(taskId, {
        id: message.id,  // 前端消息 ID（用于 upsert）
        role: message.role,
        content: message.type === 'text' ? message.content :
                 message.type === 'file' ? `[文件] ${message.filename}` :
                 message.type === 'progress' ? message.content :
                 message.type === 'dimension_report' ? message.content :
                 message.type === 'layer_completed' ? message.content : '',
        message_type: message.type,
        metadata: message.type !== 'text' ? { ...message } as unknown as Record<string, unknown> : undefined,
      }).catch((error) => {
        console.warn('[UnifiedPlanningContext] Failed to sync message to backend:', error);
      });
    }
  }, [taskId]);

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

    // ✅ 精简：单一状态源，直接更新 completedLayers
    // SSE 事件驱动实时更新，REST 轮询用于断线重连恢复
    const backendCompletedData = {
      1: backendData.layer_1_completed || false,
      2: backendData.layer_2_completed || false,
      3: backendData.layer_3_completed || false,
    };

    const currentStatus = backendData.status;
    if (currentStatus === 'idle' || currentStatus === 'completed' || currentStatus === 'failed' || currentStatus === 'paused') {
      // 会话结束、暂停或初始状态时，同步 REST 状态
      setCompletedLayers(backendCompletedData);
      console.log('[UnifiedPlanningContext] Sync state from REST:', backendCompletedData);
    }
    // 运行中的状态由 SSE 的 layer_completed 事件驱动

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

  // ✅ SSE 驱动的层级完成状态更新
  // 此函数由 handleLayerCompleted 回调调用
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
      
      // 🔧 新增：将 taskId 设置前添加的消息存储到数据库
      // 这些消息（如文件上传、"已设置规划任务"等）在 taskId 为空时未被存储
      setMessages(prev => {
        for (const msg of prev) {
          // 跳过延迟存储的消息（等待完整数据）
          if ((msg as any)._pendingStorage) continue;
          
          // ✅ 传递消息 ID 用于 upsert
          planningApi.createMessage(response.task_id, {
            id: msg.id,  // 前端消息 ID
            role: msg.role,
            content: msg.type === 'text' ? msg.content :
                     msg.type === 'file' ? `[文件] ${msg.filename}` :
                     msg.type === 'progress' ? msg.content :
                     msg.type === 'dimension_report' ? msg.content :
                     msg.type === 'layer_completed' ? msg.content : '',
            message_type: msg.type,
            metadata: msg.type !== 'text' ? { ...msg } as unknown as Record<string, unknown> : undefined,
          }).catch(err => console.warn('[UnifiedPlanningContext] Failed to store message:', err));
        }
        return prev;  // 不修改消息列表
      });
      
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

    // 设置标志，避免历史消息重复存储
    isLoadingHistoryRef.current = true;

    try {
      const statusData = await planningApi.getStatus(sessionId);
      
      // ✅ 简化：使用 ui_messages 恢复消息历史
      // 数据库已通过 upsert 确保消息唯一性，无需前端去重
      if (statusData.ui_messages && statusData.ui_messages.length > 0) {
        console.log('[UnifiedPlanningContext] Loading UI messages:', statusData.ui_messages.length, 'messages');
        
        // 按 timestamp 排序后直接恢复
        const sortedMessages = [...statusData.ui_messages].sort((a, b) => {
          const timeA = new Date(a.timestamp || 0).getTime();
          const timeB = new Date(b.timestamp || 0).getTime();
          return timeA - timeB;
        });
        
        for (const msg of sortedMessages) {
          // 跳过空消息
          if (!msg.content && !msg.message_metadata) continue;
          
          // ✅ 使用数据库中的 message_id（前端原始 ID）恢复消息
          const messageId = msg.message_id || `msg-history-${msg.id}`;
          
          // 根据 message_type 和 message_metadata 恢复原始消息结构
          if (msg.message_type && msg.message_type !== 'text' && msg.message_metadata) {
            // 从 metadata 恢复完整消息（文件、维度报告等）
            const restoredMessage = {
              ...msg.message_metadata,
              id: messageId,  // ✅ 使用原始前端消息 ID
              timestamp: new Date(msg.timestamp || Date.now()),
            } as Message;
            addMessage(restoredMessage);
          } else {
            // 普通文本消息
            addMessage({
              id: messageId,  // ✅ 使用原始前端消息 ID
              timestamp: new Date(msg.timestamp || Date.now()),
              role: msg.role as 'user' | 'assistant' | 'system',
              type: 'text',
              content: msg.content,
            });
          }
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
              id: `revision-feedback-${revision.timestamp}-${revision.dimension}`,
              timestamp: new Date(revision.timestamp),
              role: 'user',
              type: 'text',
              content: `修改意见（${dimensionName}）：${revision.feedback}`,
            });
          }
          
          // 添加修复结果消息
          addMessage({
            id: `revision-result-${revision.timestamp}-${revision.dimension}`,
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

      console.log('[UnifiedPlanningContext] Historical reports loaded successfully');
    } catch (error) {
      console.error('[UnifiedPlanningContext] Failed to load historical reports:', error);
      addMessage(createErrorMessage('加载历史报告失败'));
    } finally {
      // 重置标志，允许后续消息存储
      isLoadingHistoryRef.current = false;
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

  // Delete session
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  const deleteSession = useCallback(async (sessionId: string, villageName: string): Promise<boolean> => {
    try {
      setDeletingSessionId(sessionId);
      console.log('[UnifiedPlanningContext] Deleting session:', sessionId);

      await planningApi.deleteSession(sessionId);

      // 刷新历史列表
      await loadVillagesHistory();

      // 如果删除的是当前会话，重置状态
      if (taskId === sessionId) {
        clearMessages();
        setTaskId(null);
        setProjectName(null);
        setStatus('idle');
        addMessage(createSystemMessage(`🗑️ 已删除会话: ${sessionId.slice(0, 8)}...`));
      }

      console.log('[UnifiedPlanningContext] Session deleted successfully:', sessionId);
      return true;
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      console.error('[UnifiedPlanningContext] Failed to delete session:', error);
      addMessage(createErrorMessage(`删除会话失败: ${errorMessage}`));
      return false;
    } finally {
      setDeletingSessionId(null);
    }
  }, [taskId, clearMessages, addMessage, loadVillagesHistory]);

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
    setIsPaused,  // 🔧 新增：用于 SSE pause 事件更新
    setPendingReviewLayer,  // 🔧 新增：用于 SSE pause 事件更新

    // 层级完成状态
    completedLayers,

    // 同步后端状态
    syncBackendState,

    // ✅ SSE 驱动的层级完成状态更新
    setUILayerCompleted,

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
    syncMessageToBackend,  // 🔧 新增：同步消息到后端
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
    deleteSession,
    deletingSessionId,
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
