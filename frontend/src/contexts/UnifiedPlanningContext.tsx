'use client';

/**
 * Unified Planning Context
 * 统一规划上下文 - 聚合多个独立 Context 的外观层
 *
 * 重构说明：
 * - 作为 ConversationContext、ProgressContext、HistoryContext、PlanningStateContext、ReportContext、ViewerContext 的聚合层
 * - 保持向后兼容的 API，现有消费者无需修改
 * - 新代码建议使用细粒度 Context hooks 减少重渲染
 *
 * 细粒度 Context hooks:
 * - useConversationContext() - 消息和对话状态（高频更新）
 * - useProgressContext() - 进度和执行状态（高频更新）
 * - useHistoryContext() - 历史记录状态
 * - usePlanningStateContext() - 规划核心状态
 * - useReportContext() - 报告状态
 * - useViewerContext() - 查看器状态
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  ReactNode,
  useMemo,
  useRef,
} from 'react';
import { Message, PlanningParams, Checkpoint, DimensionProgressItem, FileMessage } from '@/types';
import { VillageInputData } from '@/components/VillageInputForm';
import {
  planningApi,
  dataApi,
  VillageInfo,
  VillageSession,
  SessionStatusResponse,
} from '@/lib/api';
import { createSystemMessage, createErrorMessage } from '@/lib/utils';
import { logger } from '@/lib/logger';
import { LAYER_ID_MAP, getLayerPhase, LayerPhase, PlanningStatus } from '@/lib/constants';
import { PLANNING_DEFAULTS } from '@/config/planning';
import { getDimensionsByLayer, DIMENSION_NAMES } from '@/config/dimensions';

// Note: Fine-grained context hooks are available from their respective files:
// - useConversationContext from './ConversationContext'
// - useProgressContext from './ProgressContext'
// - useHistoryContext from './HistoryContext'
// - usePlanningStateContext from './PlanningStateContext'
// - useReportContext from './ReportContext'
// - useViewerContext from './ViewerContext'

// Use PlanningStatus from constants for type consistency
type Status = PlanningStatus;

interface UnifiedPlanningContextType {
  conversationId: string;
  messages: Message[];
  taskId: string | null;
  projectName: string | null;
  status: Status;
  viewerVisible: boolean;
  referencedSection?: string;
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  villageFormData: VillageInputData | null;
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  historyLoading: boolean;
  historyError: string | null;
  isPaused: boolean;
  pendingReviewLayer: number | null;
  setIsPaused: (paused: boolean) => void;
  setPendingReviewLayer: (layer: number | null) => void;
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  progressPanelVisible: boolean;
  setProgressPanelVisible: (visible: boolean) => void;
  dimensionProgress: Map<string, DimensionProgressItem>;
  executingDimensions: Set<string>;
  currentPhase: LayerPhase | '修复中';
  setCurrentLayerAndPhase: (layer: number) => void;
  updateDimensionProgress: (key: string, updates: Partial<DimensionProgressItem>) => void;
  setDimensionStreaming: (layer: number, dimensionKey: string, dimensionName: string) => void;
  setDimensionCompleted: (layer: number, dimensionKey: string, wordCount: number) => void;
  clearDimensionProgress: () => void;
  syncBackendState: (backendData: Partial<SessionStatusResponse> & { version?: number }) => void;
  setUILayerCompleted: (layer: number, completed: boolean) => void;
  checkpoints: Checkpoint[];
  currentLayer: number | null;
  selectedCheckpoint: string | null;
  loadingContent: boolean;
  reportSyncState: { lastUpdated: number; currentLayer: number | null; isStreaming: boolean };
  triggerReportUpdate: (layer: number, content: string) => void;
  layerReportVisible: boolean;
  setLayerReportVisible: (visible: boolean) => void;
  activeReportLayer: number;
  setActiveReportLayer: (layer: number) => void;
  layerReports: {
    analysis_reports: Record<string, string>;
    concept_reports: Record<string, string>;
    detail_reports: Record<string, string>;
    analysis_report_content: string;
    concept_report_content: string;
    detail_report_content: string;
  };
  setLayerReports: (reports: Partial<{
    analysis_reports: Record<string, string>;
    concept_reports: Record<string, string>;
    detail_reports: Record<string, string>;
    analysis_report_content: string;
    concept_report_content: string;
    detail_report_content: string;
  }>) => void;
  addMessage: (message: Message) => void;
  syncMessageToBackend: (message: Message) => void;
  setMessages: (messages: Message[] | ((prev: Message[]) => Message[])) => void;
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;
  setTaskId: (taskId: string | null) => void;
  setProjectName: (name: string | null) => void;
  setStatus: (status: Status) => void;
  setVillageFormData: (data: VillageInputData | null) => void;
  setCheckpoints: (checkpoints: Checkpoint[] | ((prev: Checkpoint[]) => Checkpoint[])) => void;
  setCurrentLayer: (layer: number | null) => void;
  loadLayerContent: (layerId: string) => Promise<void>;
  loadCheckpoints: () => Promise<void>;
  setSelectedCheckpoint: (checkpointId: string | null) => void;
  rollbackToCheckpoint: (checkpointId: string) => Promise<void>;
  showViewer: () => void;
  hideViewer: () => void;
  toggleViewer: () => void;
  highlightSection: (section: string) => void;
  clearHighlight: () => void;
  viewingFile: FileMessage | null;
  showFileViewer: (file: FileMessage) => void;
  hideFileViewer: () => void;
  startPlanning: (params: PlanningParams) => Promise<void>;
  resetConversation: () => void;
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
  const [messages, setMessages] = useState<Message[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string | null>(null);
  const [status, setStatusState] = useState<Status>('idle');
  const [viewerVisible, setViewerVisible] = useState(false);
  const [referencedSection, setReferencedSection] = useState<string | undefined>();
  const [viewingFile, setViewingFile] = useState<FileMessage | null>(null);
  const [villageFormData, setVillageFormData] = useState<VillageInputData | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [pendingReviewLayer, setPendingReviewLayer] = useState<number | null>(null);
  const [completedLayers, setCompletedLayers] = useState({ 1: false, 2: false, 3: false });
  const [progressPanelVisible, setProgressPanelVisible] = useState(false);
  const [dimensionProgress, setDimensionProgress] = useState<Map<string, DimensionProgressItem>>(new Map());
  const [executingDimensions, setExecutingDimensions] = useState<Set<string>>(new Set());
  const [currentPhase, setCurrentPhase] = useState<LayerPhase | '修复中'>('idle');
  const [villages, setVillages] = useState<VillageInfo[]>([]);
  const [selectedVillage, setSelectedVillage] = useState<VillageInfo | null>(null);
  const [selectedSession, setSelectedSessionState] = useState<VillageSession | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [currentLayer, setCurrentLayer] = useState<number | null>(null);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [layerReportVisible, setLayerReportVisible] = useState(false);
  const [activeReportLayer, setActiveReportLayer] = useState(1);
  const [layerReports, setLayerReportsState] = useState<{
    analysis_reports: Record<string, string>;
    concept_reports: Record<string, string>;
    detail_reports: Record<string, string>;
    analysis_report_content: string;
    concept_report_content: string;
    detail_report_content: string;
  }>({
    analysis_reports: {},
    concept_reports: {},
    detail_reports: {},
    analysis_report_content: '',
    concept_report_content: '',
    detail_report_content: '',
  });
  const [reportSyncState, setReportSyncState] = useState<{
    lastUpdated: number;
    currentLayer: number | null;
    isStreaming: boolean;
  }>({
    lastUpdated: 0,
    currentLayer: null,
    isStreaming: false,
  });
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  const previousBackendStateRef = useRef<unknown>(null);
  const localVersionRef = useRef<number>(0);
  const isLoadingHistoryRef = useRef(false);

  const viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE' = useMemo(() => {
    if (taskId && taskId !== 'new') return 'SESSION_ACTIVE';
    if (status !== 'idle') return 'SESSION_ACTIVE';
    return 'WELCOME_FORM';
  }, [taskId, status]);

  const updateDimensionProgress = useCallback(
    (key: string, updates: Partial<DimensionProgressItem>) => {
      setDimensionProgress((prev) => {
        const next = new Map(prev);
        const existing = next.get(key);
        if (existing) {
          next.set(key, { ...existing, ...updates });
        } else {
          next.set(key, {
            dimensionKey: updates.dimensionKey || '',
            dimensionName: updates.dimensionName || '',
            layer: updates.layer || 0,
            status: updates.status || 'pending',
            wordCount: updates.wordCount || 0,
            ...updates,
          });
        }
        return next;
      });
    },
    []
  );

  const setCurrentLayerAndPhase = useCallback((layer: number) => {
    setCurrentLayer(layer);
    setCurrentPhase(getLayerPhase(layer));
  }, []);

  const setDimensionStreaming = useCallback(
    (layer: number, dimensionKey: string, dimensionName: string) => {
      const key = `${layer}_${dimensionKey}`;
      updateDimensionProgress(key, {
        dimensionKey,
        dimensionName,
        layer,
        status: 'streaming',
        startedAt: new Date().toISOString(),
      });
      setExecutingDimensions((prev) => new Set(prev).add(key));
      setCurrentPhase(getLayerPhase(layer));
    },
    [updateDimensionProgress]
  );

  const setDimensionCompleted = useCallback(
    (layer: number, dimensionKey: string, wordCount: number) => {
      const key = `${layer}_${dimensionKey}`;
      updateDimensionProgress(key, {
        status: 'completed',
        wordCount,
        completedAt: new Date().toISOString(),
      });
      setExecutingDimensions((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    },
    [updateDimensionProgress]
  );

  const clearDimensionProgress = useCallback(() => {
    setDimensionProgress(new Map());
    setExecutingDimensions(new Set());
    setCurrentPhase('idle');
  }, []);

  const addMessage = useCallback(
    (message: Message) => {
      setMessages((prev) => [...prev, message]);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const pendingStorage = (message as any)._pendingStorage;
      if (!isLoadingHistoryRef.current && taskId && !pendingStorage) {
        planningApi
          .createMessage(taskId, {
            id: message.id,
            role: message.role,
            content:
              message.type === 'text'
                ? message.content
                : message.type === 'file'
                  ? `[文件] ${message.filename}`
                  : message.type === 'progress'
                    ? message.content
                    : message.type === 'dimension_report'
                      ? message.content
                      : message.type === 'layer_completed'
                        ? message.content
                        : '',
            message_type: message.type,
            metadata:
              message.type !== 'text'
                ? ({ ...message } as unknown as Record<string, unknown>)
                : undefined,
          })
          .catch((error) => {
            console.warn('[UnifiedPlanningContext] Failed to store message:', error);
          });
      }
    },
    [taskId]
  );

  const syncMessageToBackend = useCallback(
    (message: Message) => {
      if (!isLoadingHistoryRef.current && taskId) {
        planningApi
          .createMessage(taskId, {
            id: message.id,
            role: message.role,
            content:
              message.type === 'text'
                ? message.content
                : message.type === 'file'
                  ? `[文件] ${message.filename}`
                  : message.type === 'progress'
                    ? message.content
                    : message.type === 'dimension_report'
                      ? message.content
                      : message.type === 'layer_completed'
                        ? message.content
                        : '',
            message_type: message.type,
            metadata:
              message.type !== 'text'
                ? ({ ...message } as unknown as Record<string, unknown>)
                : undefined,
          })
          .catch((error) => {
            console.warn('[UnifiedPlanningContext] Failed to sync message:', error);
          });
      }
    },
    [taskId]
  );

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

  const syncBackendState = useCallback(
    (backendData: Partial<SessionStatusResponse> & { version?: number }) => {
      const serverVersion = backendData.version ?? 0;
      const localVersion = localVersionRef.current;
      if (serverVersion > 0 && serverVersion <= localVersion) return;
      if (serverVersion > 0) localVersionRef.current = serverVersion;

      const previousState = previousBackendStateRef.current;
      const hasStateChanged =
        !previousState ||
        (previousState as { status: string }).status !== backendData.status ||
        (previousState as { previous_layer: number }).previous_layer !== backendData.previous_layer;
      if (!hasStateChanged) return;

      setStatusState((backendData.status || 'idle') as Status);
      const isPausedValue = backendData.status === 'paused';
      setIsPaused(isPausedValue);
      const previousLayerValue = backendData.previous_layer;
      setPendingReviewLayer(previousLayerValue && previousLayerValue > 0 ? previousLayerValue : null);

      const backendCompletedData = {
        1: backendData.layer_1_completed || false,
        2: backendData.layer_2_completed || false,
        3: backendData.layer_3_completed || false,
      };
      const currentStatus = backendData.status;
      if (currentStatus === 'idle' || currentStatus === 'completed' || currentStatus === 'failed' || currentStatus === 'paused') {
        setCompletedLayers(backendCompletedData);
      }

      if (backendData.last_checkpoint_id) setSelectedCheckpoint(backendData.last_checkpoint_id);

      const currentLayerValue = backendData.current_layer;
      if (currentLayerValue && currentLayerValue >= 1 && currentLayerValue <= 3) {
        setCurrentLayer(currentLayerValue);
        const phaseMap: Record<number, LayerPhase> = { 1: '现状分析', 2: '规划思路', 3: '详细规划' };
        setCurrentPhase(phaseMap[currentLayerValue] || 'idle');
      }

      previousBackendStateRef.current = {
        status: backendData.status,
        previous_layer: backendData.previous_layer,
        layer_1_completed: backendData.layer_1_completed,
        layer_2_completed: backendData.layer_2_completed,
        layer_3_completed: backendData.layer_3_completed,
      };
    },
    []
  );

  const setUILayerCompleted = useCallback((layer: number, completed: boolean) => {
    setCompletedLayers((prev) => {
      if (prev[layer as 1 | 2 | 3] === completed) return prev;
      return { ...prev, [layer]: completed };
    });
  }, []);

  const showViewer = useCallback(() => setViewerVisible(true), []);
  const hideViewer = useCallback(() => setViewerVisible(false), []);
  const toggleViewer = useCallback(() => setViewerVisible((prev) => !prev), []);
  const highlightSection = useCallback((section: string) => {
    setReferencedSection(section);
    setViewerVisible(true);
  }, []);
  const clearHighlight = useCallback(() => setReferencedSection(undefined), []);
  const showFileViewer = useCallback((file: FileMessage) => setViewingFile(file), []);
  const hideFileViewer = useCallback(() => setViewingFile(null), []);

  const loadLayerContent = useCallback(
    async (layerId: string) => {
      if (!taskId || !projectName) {
        console.warn('[UnifiedPlanningContext] Cannot load content: missing taskId or projectName');
        return;
      }
      try {
        setLoadingContent(true);
        await dataApi.getLayerContent(projectName, layerId, taskId, 'markdown');
      } catch (error) {
        console.error('[UnifiedPlanningContext] Failed to load layer content:', error);
        throw error;
      } finally {
        setLoadingContent(false);
      }
    },
    [taskId, projectName]
  );

  const loadCheckpoints = useCallback(async () => {
    if (!projectName) {
      console.warn('[UnifiedPlanningContext] Cannot load checkpoints: missing projectName');
      return;
    }
    try {
      const response = await dataApi.getCheckpoints(projectName, taskId || undefined);
      setCheckpoints(response.checkpoints);
    } catch (error) {
      console.error('[UnifiedPlanningContext] Failed to load checkpoints:', error);
      throw error;
    }
  }, [projectName, taskId]);

  const rollbackToCheckpoint = useCallback(
    async (checkpointId: string) => {
      if (!taskId) {
        console.warn('[UnifiedPlanningContext] Cannot rollback: missing taskId');
        return;
      }
      try {
        await planningApi.rollbackCheckpoint(taskId, checkpointId);
        setSelectedCheckpoint(checkpointId);
        await loadCheckpoints();
        try {
          const backendState = await planningApi.getStatus(taskId);
          syncBackendState(backendState);
        } catch (syncError) {
          console.warn('[UnifiedPlanningContext] Rollback: failed to sync backend state:', syncError);
        }
        addMessage(createSystemMessage(`✅ 已回退到检查点 ${checkpointId.slice(0, 8)}...`));
      } catch (error) {
        console.error('[UnifiedPlanningContext] Failed to rollback:', error);
        throw error;
      }
    },
    [taskId, loadCheckpoints, addMessage, syncBackendState]
  );

  const startPlanning = useCallback(
    async (params: PlanningParams) => {
      logger.context.info('开始规划流程', { projectName: params.projectName });
      try {
        setStatus('collecting');
        setProjectName(params.projectName);
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
          throw new Error('服务器响应缺少任务ID，可能已达请求频率上限');
        }
        setTaskId(response.task_id);
        setStatus('planning');
        setMessages((prev) => {
          for (const msg of prev) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            if ((msg as any)._pendingStorage) continue;
            planningApi
              .createMessage(response.task_id, {
                id: msg.id,
                role: msg.role,
                content: msg.type === 'text' ? msg.content : msg.type === 'file' ? `[文件] ${msg.filename}` : '',
                message_type: msg.type,
                metadata: msg.type !== 'text' ? ({ ...msg } as unknown as Record<string, unknown>) : undefined,
              })
              .catch((err) => console.warn('[UnifiedPlanningContext] Failed to store message:', err));
          }
          return prev;
        });
        addMessage(createSystemMessage(`🚀 规划任务已创建，任务ID: ${response.task_id.slice(0, 8)}...`));
      } catch (error: unknown) {
        const errorMessage = error instanceof Error ? error.message : '未知错误';
        logger.context.error('规划流程失败', { error: errorMessage });
        setStatus('failed');
        addMessage(createErrorMessage(`启动规划失败: ${errorMessage}`));
        throw error;
      }
    },
    [addMessage, setStatus]
  );

  const triggerReportUpdate = useCallback((layer: number, _content: string) => {
    const layerId = LAYER_ID_MAP[layer];
    if (!layerId) return;
    setReportSyncState({ lastUpdated: Date.now(), currentLayer: layer, isStreaming: false });
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
    setReportSyncState({ lastUpdated: 0, currentLayer: null, isStreaming: false });
    clearDimensionProgress();
    setProgressPanelVisible(false);
    setLayerReportsState({
      analysis_reports: {},
      concept_reports: {},
      detail_reports: {},
      analysis_report_content: '',
      concept_report_content: '',
      detail_report_content: '',
    });
  }, [clearDimensionProgress, setStatus]);

  const setLayerReports = useCallback((reports: Partial<typeof layerReports>) => {
    setLayerReportsState((prev) => ({ ...prev, ...reports }));
  }, []);

  const loadVillagesHistory = useCallback(async () => {
    try {
      setHistoryLoading(true);
      setHistoryError(null);
      const data = await dataApi.listVillages();
      setVillages(data);
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
  }, []);

  const selectSession = useCallback((session: VillageSession) => {
    setSelectedSessionState(session);
  }, []);

  const loadHistoricalReports = useCallback(
    async (villageName: string, sessionId: string) => {
      if (!villageName || !sessionId) {
        console.warn('[UnifiedPlanningContext] Missing village or session ID for loading reports');
        return;
      }
      isLoadingHistoryRef.current = true;
      try {
        const statusData = await planningApi.getStatus(sessionId);
        if (statusData.ui_messages && statusData.ui_messages.length > 0) {
          const sortedMessages = [...statusData.ui_messages].sort((a, b) => {
            const timeA = new Date(a.created_at || a.timestamp || 0).getTime();
            const timeB = new Date(b.created_at || b.timestamp || 0).getTime();
            return timeA - timeB;
          });
          const loadedMessageIds = new Set<string>();
          for (const msg of sortedMessages) {
            if (!msg.content && !msg.message_metadata) continue;
            const messageId = msg.message_id || `msg-history-${msg.id}`;
            if (loadedMessageIds.has(messageId)) continue;
            loadedMessageIds.add(messageId);
            if (msg.message_type && msg.message_type !== 'text' && msg.message_metadata) {
              const restoredMessage = {
                ...msg.message_metadata,
                id: messageId,
                timestamp: new Date(msg.timestamp || Date.now()),
                created_at: msg.created_at,
              } as Message;
              addMessage(restoredMessage);
            } else {
              addMessage({
                id: messageId,
                timestamp: new Date(msg.timestamp || Date.now()),
                role: msg.role as 'user' | 'assistant' | 'system',
                type: 'text',
                content: msg.content,
              });
            }
          }
          if (statusData.revision_history && statusData.revision_history.length > 0) {
            for (const revision of statusData.revision_history) {
              const dimensionName = DIMENSION_NAMES[revision.dimension] || revision.dimension;
              const revisionId = `revision-${revision.timestamp}-${revision.dimension}`;
              if (loadedMessageIds.has(revisionId)) continue;
              if (revision.feedback) {
                const feedbackId = `${revisionId}-feedback`;
                if (!loadedMessageIds.has(feedbackId)) {
                  loadedMessageIds.add(feedbackId);
                  addMessage({
                    id: feedbackId,
                    timestamp: new Date(revision.timestamp),
                    role: 'user',
                    type: 'text',
                    content: `🎯 修改意见（${dimensionName}）：${revision.feedback}`,
                  });
                }
              }
              const resultId = `${revisionId}-result`;
              if (!loadedMessageIds.has(resultId)) {
                loadedMessageIds.add(resultId);
                addMessage({
                  id: resultId,
                  timestamp: new Date(revision.timestamp),
                  role: 'assistant',
                  type: 'text',
                  content: `✅ **${dimensionName}** 已按用户反馈完成修改`,
                });
              }
              if (!loadedMessageIds.has(revisionId)) {
                loadedMessageIds.add(revisionId);
                addMessage({
                  id: revisionId,
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
          }
        }
        if (statusData.layer_1_completed) {
          const layer1Dimensions = getDimensionsByLayer(1);
          for (const dimKey of layer1Dimensions) {
            updateDimensionProgress(`1_${dimKey}`, {
              dimensionKey: dimKey,
              dimensionName: DIMENSION_NAMES[dimKey] || dimKey,
              layer: 1,
              status: 'completed',
              wordCount: 0,
            });
          }
        }
        if (statusData.layer_2_completed) {
          const layer2Dimensions = getDimensionsByLayer(2);
          for (const dimKey of layer2Dimensions) {
            updateDimensionProgress(`2_${dimKey}`, {
              dimensionKey: dimKey,
              dimensionName: DIMENSION_NAMES[dimKey] || dimKey,
              layer: 2,
              status: 'completed',
              wordCount: 0,
            });
          }
        }
        if (statusData.layer_3_completed) {
          const layer3Dimensions = getDimensionsByLayer(3);
          for (const dimKey of layer3Dimensions) {
            updateDimensionProgress(`3_${dimKey}`, {
              dimensionKey: dimKey,
              dimensionName: DIMENSION_NAMES[dimKey] || dimKey,
              layer: 3,
              status: 'completed',
              wordCount: 0,
            });
          }
        }
        const currentLayerValue = statusData.current_layer;
        if (currentLayerValue && currentLayerValue >= 1 && currentLayerValue <= 3) {
          setCurrentLayer(currentLayerValue);
          const phaseMap: Record<number, LayerPhase> = { 1: '现状分析', 2: '规划思路', 3: '详细规划' };
          setCurrentPhase(phaseMap[currentLayerValue] || 'idle');
        } else if (statusData.layer_3_completed) {
          setCurrentLayer(3);
          setCurrentPhase('详细规划');
        } else if (statusData.layer_2_completed) {
          setCurrentLayer(3);
          setCurrentPhase('详细规划');
        } else if (statusData.layer_1_completed) {
          setCurrentLayer(2);
          setCurrentPhase('规划思路');
        }
      } catch (error) {
        console.error('[UnifiedPlanningContext] Failed to load historical reports:', error);
        addMessage(createErrorMessage('加载历史报告失败'));
      } finally {
        isLoadingHistoryRef.current = false;
      }
    },
    [addMessage, updateDimensionProgress]
  );

  const loadHistoricalSession = useCallback(
    async (villageName: string, sessionId: string) => {
      try {
        clearMessages();
        setCheckpoints([]);
        setSelectedCheckpoint(null);
        setReportSyncState({ lastUpdated: 0, currentLayer: null, isStreaming: false });
        setProjectName(villageName);
        setTaskId(sessionId);
        setStatus('completed');
        await loadCheckpoints();
        await loadHistoricalReports(villageName, sessionId);
        addMessage(
          createSystemMessage(
            `📂 已加载历史会话: ${villageName} (${sessionId.slice(0, 8)}...)`,
            'info',
            new Date().toISOString()
          )
        );
      } catch (error: unknown) {
        const errorMessage = error instanceof Error ? error.message : '未知错误';
        console.error('[UnifiedPlanningContext] Failed to load historical session:', error);
        addMessage(createSystemMessage(`❌ 加载历史会话失败: ${errorMessage}`, 'error'));
      }
    },
    [clearMessages, loadCheckpoints, addMessage, loadHistoricalReports, setStatus]
  );

  const deleteSession = useCallback(
    async (sessionId: string, _villageName: string): Promise<boolean> => {
      try {
        setDeletingSessionId(sessionId);
        await planningApi.deleteSession(sessionId);
        await loadVillagesHistory();
        if (taskId === sessionId) {
          clearMessages();
          setTaskId(null);
          setProjectName(null);
          setStatus('idle');
          addMessage(createSystemMessage(`🗑️ 已删除会话: ${sessionId.slice(0, 8)}...`));
        }
        return true;
      } catch (error: unknown) {
        const errorMessage = error instanceof Error ? error.message : '未知错误';
        console.error('[UnifiedPlanningContext] Failed to delete session:', error);
        addMessage(createErrorMessage(`删除会话失败: ${errorMessage}`));
        return false;
      } finally {
        setDeletingSessionId(null);
      }
    },
    [taskId, clearMessages, addMessage, loadVillagesHistory, setStatus]
  );

  const value: UnifiedPlanningContextType = {
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
    layerReports,
    setLayerReports,
    reportSyncState,
    triggerReportUpdate,
    isPaused,
    pendingReviewLayer,
    setIsPaused,
    setPendingReviewLayer,
    completedLayers,
    progressPanelVisible,
    setProgressPanelVisible,
    dimensionProgress,
    executingDimensions,
    currentPhase,
    setCurrentLayerAndPhase,
    updateDimensionProgress,
    setDimensionStreaming,
    setDimensionCompleted,
    clearDimensionProgress,
    syncBackendState,
    setUILayerCompleted,
    currentLayer,
    setCurrentLayer,
    villages,
    selectedVillage,
    selectedSession,
    historyLoading,
    historyError,
    addMessage,
    syncMessageToBackend,
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
    viewingFile,
    showFileViewer,
    hideFileViewer,
    startPlanning,
    resetConversation,
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

/**
 * useConversationContext - 向后兼容的 hook
 * 返回完整的 UnifiedPlanningContext，新代码建议直接使用细粒度 hooks
 */
export function useConversationContext() {
  return useUnifiedPlanningContext();
}