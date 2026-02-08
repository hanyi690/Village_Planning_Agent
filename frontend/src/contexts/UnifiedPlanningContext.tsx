'use client';

/**
 * Unified Planning Context
 * 统一规划上下文 - 对话状态、UI状态和内容管理
 */

import React, { createContext, useContext, useState, useCallback, ReactNode, useEffect, useMemo } from 'react';
import { Message, PlanningParams, Checkpoint, ReviewInteractionMessage } from '@/types';
import { VillageInputData } from '@/components/VillageInputForm';
import { planningApi, dataApi, VillageInfo, VillageSession } from '@/lib/api';
import { createBaseMessage, createSystemMessage, createErrorMessage } from '@/lib/utils';
import { LAYER_ID_MAP } from '@/lib/constants';

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

  // Review state
  reviewPending: boolean;
  /** @deprecated Use ReviewInteractionMessage in chat flow instead */
  showReviewPanel: boolean;
  /** Track current pending review message for input box interaction */
  pendingReviewMessage: ReviewInteractionMessage | null;
  setPendingReviewMessage: (message: ReviewInteractionMessage | null) => void;

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
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;
  setTaskId: (taskId: string | null) => void;
  setProjectName: (name: string | null) => void;
  setStatus: (status: Status) => void;

  // Form actions
  setVillageFormData: (data: VillageInputData | null) => void;

  // Review actions
  setReviewPending: (pending: boolean) => void;
  /** @deprecated Use ReviewInteractionMessage in chat flow instead */
  setShowReviewPanel: (show: boolean) => void;

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
  const [status, setStatus] = useState<Status>('idle');
  const [viewerVisible, setViewerVisible] = useState(false);
  const [referencedSection, setReferencedSection] = useState<string | undefined>();

  // Form state
  const [villageFormData, setVillageFormData] = useState<VillageInputData | null>(null);

  // Review state
  const [reviewPending, setReviewPending] = useState(false);
  const [showReviewPanel, setShowReviewPanel] = useState(false);
  const [pendingReviewMessage, setPendingReviewMessage] = useState<ReviewInteractionMessage | null>(null);

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

  // NEW: Report sync state
  const [reportSyncState, setReportSyncState] = useState<ReportSyncState>({
    lastUpdated: 0,
    currentLayer: null,
    isStreaming: false,
  });

  // Computed view mode - single source of truth for UI state
  const viewMode: ViewMode = useMemo(() => {
    // Has active task ID? Show session
    if (taskId && taskId !== 'new') {
      return 'SESSION_ACTIVE';
    }

    // Not idle? Show session (planning in progress)
    if (status !== 'idle') {
      return 'SESSION_ACTIVE';
    }

    // Otherwise show welcome form
    return 'WELCOME_FORM';
  }, [taskId, status]);

  // Conversation actions
  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => {
      // Check if this message duplicates the last one
      const lastMessage = prev[prev.length - 1];

      if (lastMessage) {
        // Check if timestamps are very close (within 100ms)
        const isTimeClose =
          Math.abs(
            new Date(message.timestamp).getTime() -
            new Date(lastMessage.timestamp).getTime()
          ) < 100;

        // Check if content is identical (only for messages with content property)
        let isContentSame = false;
        if ('content' in lastMessage && 'content' in message) {
          isContentSame = lastMessage.content === message.content;
        }

        // If both content and time are the same, treat as duplicate message
        if (isContentSame && isTimeClose) {
          console.log('[UnifiedPlanningContext] Skipping duplicate message:', message.type);
          return prev; // Don't add duplicate message
        }
      }

      return [...prev, message];
    });
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

  // Viewer actions
  const showViewer = useCallback(() => {
    setViewerVisible(true);
  }, []);

  const hideViewer = useCallback(() => {
    setViewerVisible(false);
  }, []);

  const toggleViewer = useCallback(() => {
    setViewerVisible((prev) => !prev);
  }, []);

  const highlightSection = useCallback((section: string) => {
    setReferencedSection(section);
    setViewerVisible(true);
  }, []);

  const clearHighlight = useCallback(() => {
    setReferencedSection(undefined);
  }, []);

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
    try {
      setStatus('collecting');
      setProjectName(params.projectName);

      // Call backend API to start planning
      const response = await planningApi.startPlanning({
        project_name: params.projectName,
        village_data: params.villageData,
        task_description: params.taskDescription || '制定村庄总体规划方案',
        constraints: params.constraints || '无特殊约束',
        enable_review: params.enableReview ?? true,
        step_mode: params.stepMode ?? true,
      });

      setTaskId(response.task_id);
      setStatus('planning');

      addMessage(createSystemMessage(`🚀 规划任务已创建，任务ID: ${response.task_id.slice(0, 8)}...`));
    } catch (error: any) {
      console.error('[UnifiedPlanningContext] Failed to start planning:', error);
      setStatus('failed');

      addMessage(createErrorMessage(`启动规划失败: ${error.message || '未知错误'}`));

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
    setReviewPending(false);
    setShowReviewPanel(false);
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
    } catch (error: any) {
      console.error('[UnifiedPlanningContext] Failed to load villages history:', error);
      setHistoryError(error.message || '加载历史记录失败');
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

    // Layer mapping configuration
    const layers = [
      { id: 'layer_1_analysis', number: 1, name: '现状分析' },
      { id: 'layer_2_concept', number: 2, name: '规划思路' },
      { id: 'layer_3_detailed', number: 3, name: '详细规划' },
    ];

    try {
      // Load each layer sequentially
      for (const layer of layers) {
        try {
          console.log('[UnifiedPlanningContext] Loading layer:', layer.id);

          // Fetch layer content from backend API
          const data = await dataApi.getLayerContent(
            villageName,
            layer.id,
            sessionId,  // Pass session ID to load historical data
            'markdown'
          );

          console.log('[UnifiedPlanningContext] Loaded layer:', layer.number,
                      'content length:', data.content?.length || 0);

          // Skip if no content
          if (!data.content || data.content.length === 0) {
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
            content: `## ${layer.name}（历史会话）\n\n${data.content.substring(0, 200)}...`,
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

          // Add message to chat
          addMessage(layerMessage);

        } catch (error) {
          // Handle missing layers gracefully - don't fail entire operation
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
      // Clear current state
      clearMessages();
      setCheckpoints([]);
      setSelectedCheckpoint(null);

      // 重置报告同步状态（重要：防止旧会话状态残留）
      setReportSyncState({
        lastUpdated: 0,
        currentLayer: null,
        isStreaming: false,
      });

      // Set new session info
      setProjectName(villageName);
      setTaskId(sessionId);
      setStatus('completed'); // Fixed: Use 'completed' for historical sessions to prevent form from showing

      // Load checkpoints for this session
      await loadCheckpoints();

      // Add system message
      addMessage(createSystemMessage(`📂 已加载历史会话: ${villageName} (${sessionId.slice(0, 8)}...)`));

      // NEW: Load and display all three layer reports
      await loadHistoricalReports(villageName, sessionId);

      console.log('[UnifiedPlanningContext] Loaded historical session with reports:', sessionId);
    } catch (error: any) {
      console.error('[UnifiedPlanningContext] Failed to load historical session:', error);
      addMessage(createSystemMessage(`❌ 加载历史会话失败: ${error.message}`));
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
    reviewPending,
    setReviewPending,
    showReviewPanel,
    setShowReviewPanel,
    pendingReviewMessage,
    setPendingReviewMessage,
    checkpoints,
    setCheckpoints,
    currentLayer,
    setCurrentLayer,
    selectedCheckpoint,
    loadingContent,
    layerReportVisible,
    setLayerReportVisible,
    activeReportLayer,
    setActiveReportLayer,
    reportSyncState,
    triggerReportUpdate,

    // History state
    villages,
    selectedVillage,
    selectedSession,
    historyLoading,
    historyError,

    // Actions
    addMessage,
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
