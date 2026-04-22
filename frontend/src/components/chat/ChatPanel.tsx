'use client';

/**
 * ChatPanel - Unified chat interface integrating messaging and progress display
 * Refactored to use Zustand + Immer for state management
 * Business logic: usePlanningActions (from planning-context), usePlanningHandlers
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import { usePlanningStore, usePlanningActions } from '@/stores';
import { useStreamingRender } from '@/hooks/utils';
import { useThrottleCallback } from '@/hooks/utils';
import { usePlanningHandlers } from '@/hooks/planning';
import type { Message, FileMessage, Checkpoint } from '@/types';
import { planningApi, fileApi } from '@/lib/api';
import {
  createBaseMessage,
  createSystemMessage,
  createErrorMessage,
  getErrorMessage,
} from '@/lib/utils';
import { logger } from '@/lib/logger';
import SegmentedControl from '@/components/ui/SegmentedControl';
import MessageList from './MessageList';
import ReviewPanel from './ReviewPanel';
import ProgressPanel from './ProgressPanel';
import ToolStatusPanel from './ToolStatusPanel';
import DimensionSelector from './DimensionSelector';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faLayerGroup, faMap } from '@fortawesome/free-solid-svg-icons';
import GISUploadSidebar from '@/components/gis/GISUploadSidebar';
import type { UploadResult } from '@/components/gis/DataUpload';
import { getDimensionName, getDimensionsByLayer, DIMENSION_NAMES } from '@/config/dimensions';
import { PLANNING_DEFAULTS } from '@/config/planning';
import {
  LAYER_OPTIONS_ARRAY,
  LAYER_LABEL_MAP,
  LAYER_VALUE_MAP,
  LAYER_IDS,
  getLayerId,
  FILE_ACCEPT,
  isInputDisabled,
  getStatusBadge,
} from '@/lib/constants';

interface ChatPanelProps {
  className?: string;
  onOpenLayerSidebar?: (layer: number) => void;
}

export default function ChatPanel({ className = '', onOpenLayerSidebar }: ChatPanelProps) {
  // Get state from Zustand store
  const messages = usePlanningStore((state) => state.messages);
  const status = usePlanningStore((state) => state.status);
  const taskId = usePlanningStore((state) => state.taskId);
  const villageFormData = usePlanningStore((state) => state.villageFormData);
  const currentLayer = usePlanningStore((state) => state.currentLayer);
  const isPaused = usePlanningStore((state) => state.isPaused);
  const pendingReviewLayer = usePlanningStore((state) => state.pendingReviewLayer);
  const progressPanelVisible = usePlanningStore((state) => state.progressPanelVisible);
  const dimensionProgress = usePlanningStore((state) => state.dimensionProgress);
  const executingDimensions = usePlanningStore((state) => state.executingDimensions);
  const currentPhase = usePlanningStore((state) => state.currentPhase);
  const completedDimensions = usePlanningStore((state) => state.completedDimensions);
  const toolStatusMap = usePlanningStore((state) => state.toolStatuses);
  const checkpoints = usePlanningStore((state) => state.checkpoints);

  // Get actions
  const actions = usePlanningActions();

  const completedLayers = useMemo(
    () => ({
      1: completedDimensions.layer1.length > 0,
      2: completedDimensions.layer2.length > 0,
      3: completedDimensions.layer3.length > 0,
    }),
    [completedDimensions]
  );

  const [inputText, setInputText] = useState('');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [isRollingBack, setIsRollingBack] = useState(false);
  const [uploadedFileContent, setUploadedFileContent] = useState<string | null>(null);
  const [stepMode, setStepMode] = useState<boolean>(PLANNING_DEFAULTS.stepMode);
  const [showGISUploadSidebar, setShowGISUploadSidebar] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Track typing timeout for cleanup
  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // SSE connection state tracking ref
  const sseConnectedRef = useRef(false);

  // Dimension content cache (for streaming render) - optimized: use Record instead of Map
  const [dimensionContents, setDimensionContents] = useState<Record<string, string>>({});

  // Batch render Hook: reduce React re-renders from high-frequency events
  const { addToken, completeDimension, flushBatch } = useStreamingRender(
    (dimensionKey: string, content: string, layer?: number) => {
      // Batch callback: update dimension content cache
      setDimensionContents((prev) => {
        const layerNum = layer !== undefined ? layer : currentLayer || 1;
        const key = `${layerNum}_${dimensionKey}`;
        return { ...prev, [key]: content };
      });
    },
    {
      batchSize: 10,
      batchWindow: 50,
      debounceMs: 30,
    }
  );

  // Throttle setDimensionStreaming - use getState() for stable reference
  const throttledSetDimensionStreaming = useThrottleCallback(
    (layer: number, dimensionKey: string, dimensionName: string) => {
      usePlanningStore.getState().setDimensionStreaming(layer, dimensionKey, dimensionName);
    },
    300
  );

  // Define showViewer before usePlanningHandlers initialization
  const showViewer = useCallback(() => {
    usePlanningStore.getState().setViewerVisible(true);
  }, []);

  // Initialize usePlanningHandlers hook with streaming callbacks
  const planningHandlers = usePlanningHandlers({
    addToken,
    completeDimension,
    flushBatch,
    throttledSetDimensionStreaming,
    showViewer,
  });

  // Rate limit error tracking
  const [rateLimitError, setRateLimitError] = useState<{ projectName: string } | null>(null);

  // Tool status handlers - use getState() for stable references
  const handleToolCall = useCallback(
    (data: {
      toolName: string;
      toolDisplayName: string;
      description: string;
      estimatedTime?: number;
      stage?: string;
    }) => {
      usePlanningStore.getState().setToolStatus(data.toolName, {
        toolName: data.toolName,
        status: 'running',
        stage: data.stage,
        message: data.description,
      });
    },
    []
  );

  const handleToolProgress = useCallback(
    (data: { toolName: string; stage: string; progress: number; message: string }) => {
      const state = usePlanningStore.getState();
      const existing = state.toolStatuses[data.toolName];
      if (existing) {
        state.setToolStatus(data.toolName, {
          ...existing,
          stage: data.stage,
          progress: data.progress,
          message: data.message,
        });
      }
    },
    []
  );

  const handleToolResult = useCallback(
    (data: {
      toolName: string;
      status: 'success' | 'error';
      summary: string;
      displayHints?: {
        primary_view?: 'text' | 'table' | 'map' | 'chart' | 'json';
        priority_fields?: string[];
      };
      dataPreview?: string;
    }) => {
      const state = usePlanningStore.getState();
      const existing = state.toolStatuses[data.toolName];
      if (existing) {
        state.setToolStatus(data.toolName, {
          ...existing,
          status: data.status,
          summary: data.summary,
        });
      }
    },
    []
  );

  // Helper functions for message operations - use getState() for stable references
  const addMessage = useCallback(
    (message: Message) => {
      usePlanningStore.getState().addMessage(message);
    },
    []
  );

  const addMessages = useCallback(
    (messages: Message[]) => {
      usePlanningStore.getState().addMessages(messages);
    },
    []
  );

  const setMessages = useCallback(
    (messagesOrUpdater: Message[] | ((prev: Message[]) => Message[])) => {
      const state = usePlanningStore.getState();
      if (typeof messagesOrUpdater === 'function') {
        const newMessages = messagesOrUpdater(state.messages);
        state.setMessages(newMessages);
      } else {
        state.setMessages(messagesOrUpdater);
      }
    },
    []
  );

  const startPlanning = actions.startPlanning;

  const setProgressPanelVisible = useCallback(
    (visible: boolean) => {
      usePlanningStore.getState().setProgressPanelVisible(visible);
    },
    []
  );

  const setIsPaused = useCallback(
    (paused: boolean) => {
      usePlanningStore.getState().setPaused(paused);
    },
    []
  );

  const setPendingReviewLayer = useCallback(
    (layer: number | null) => {
      usePlanningStore.getState().setPendingReviewLayer(layer);
    },
    []
  );

  const setCheckpoints = useCallback(
    (checkpointsOrUpdater: Checkpoint[] | ((prev: Checkpoint[]) => Checkpoint[])) => {
      const state = usePlanningStore.getState();
      if (typeof checkpointsOrUpdater === 'function') {
        const newCheckpoints = checkpointsOrUpdater(state.checkpoints);
        state.setCheckpoints(newCheckpoints);
      } else {
        state.setCheckpoints(checkpointsOrUpdater);
      }
    },
    []
  );

  const syncBackendState = useCallback(
    (
      backendData: Partial<{
        status: string;
        previous_layer: number;
        current_layer: number;
        layer_1_completed: boolean;
        layer_2_completed: boolean;
        layer_3_completed: boolean;
        last_checkpoint_id: string;
        phase: string;
        version: number;
      }>
    ) => {
      usePlanningStore.getState().syncBackendState(backendData);
    },
    []
  );

  const showFileViewer = useCallback(
    (file: FileMessage) => {
      usePlanningStore.getState().setViewingFile(file);
    },
    []
  );

  // Derive taskState-like object for compatibility
  const taskState = useMemo(
    () => ({
      status: status,
      current_layer: currentLayer ?? undefined,
      previous_layer: undefined as number | undefined,
      layer_1_completed: completedLayers[1],
      layer_2_completed: completedLayers[2],
      layer_3_completed: completedLayers[3],
      pause_after_step: isPaused,
      last_checkpoint_id: usePlanningStore.getState().selectedCheckpoint ?? undefined,
      execution_error: null,
      execution_complete: completedLayers[1] && completedLayers[2] && completedLayers[3],
      progress: null,
    }),
    [
      status,
      currentLayer,
      isPaused,
      completedLayers,
    ]
  );

  // Action shortcuts for review handlers
  const approve = actions.approve;
  const reject = actions.reject;
  const rollback = actions.rollback;

  const handleTextDelta = useCallback(
    (text: string, _layer?: number) => {
      setMessages((prevMessages) => {
        const lastMsg = prevMessages[prevMessages.length - 1];
        if (lastMsg?.type === 'text') {
          return [
            ...prevMessages.slice(0, -1),
            {
              ...lastMsg,
              content: (lastMsg as { content: string }).content + text,
            },
          ];
        }
        return [
          ...prevMessages,
          {
            ...createBaseMessage('assistant'),
            type: 'text',
            content: text,
          } as Message & { layer?: number },
        ];
      });
    },
    [setMessages]
  );

  // 维度级流式回调 - 使用 usePlanningHandlers hook
  const handleDimensionDelta = planningHandlers.handleDimensionDelta;
  const handleDimensionComplete = planningHandlers.handleDimensionComplete;

  // 层级进度回调
  const handleLayerProgress = useCallback((_layer: number, _completed: number, _total: number) => {
    // Layer progress tracking
  }, []);

  // 层级完成回调 - 使用 usePlanningHandlers hook
  const handleLayerCompleted = planningHandlers.handleLayerCompleted;

  // 层级数据恢复 - 使用 usePlanningHandlers hook
  const restoreLayerData = planningHandlers.restoreLayerData;

  // 层级开始回调 - 使用 usePlanningHandlers hook
  const handleLayerStarted = planningHandlers.handleLayerStarted;

  // 获取层级报告的函数引用 - 来自 usePlanningHandlers hook
  const fetchLayerReportsFromBackend = planningHandlers.fetchLayerReportsFromBackend;

  // 暂停回调 - 处理审查暂停状态
  const handlePause = useCallback(
    async (layer: number, checkpointId: string) => {
      // 🔧 修复：更新审查状态，使 ReviewPanel 能够正确显示
      setIsPaused(true);
      setPendingReviewLayer(layer);

      // 🔧 修复：添加新的 checkpoint 到状态，使 CheckpointMarker 能够正确显示
      if (checkpointId && layer > 0) {
        setCheckpoints((prev) => {
          // 避免重复添加同一层的 checkpoint
          if (prev.some((cp) => cp.layer === layer)) {
            return prev;
          }
          return [
            ...prev,
            {
              checkpoint_id: checkpointId,
              layer: layer,
              timestamp: new Date().toISOString(),
              description: `Layer ${layer} checkpoint`,
              type: 'key' as const, // 标记为关键检查点，启用回滚功能
            },
          ];
        });
      }

      // ✅ 兜底机制：从 REST API 获取最新层级数据
      // 当 SSE 的 layer_completed 事件丢失时，确保数据仍能被正确获取
      if (layer > 0) {
        try {
          const backendData = await fetchLayerReportsFromBackend(layer);
          if (backendData && backendData.reports && Object.keys(backendData.reports).length > 0) {
            // 更新 dimensionContents 状态
            setDimensionContents((prev) => {
              const updates: Record<string, string> = {};
              Object.entries(backendData.reports).forEach(([dimKey, content]) => {
                const key = `${layer}_${dimKey}`;
                const existing = prev[key] || '';
                // 只有当 REST API 数据更长时才更新
                if (!existing || content.length > existing.length) {
                  updates[key] = content;
                }
              });
              return Object.keys(updates).length > 0 ? { ...prev, ...updates } : prev;
            });
          }
        } catch (error) {
          console.error(`[ChatPanel] Pause fallback: REST API error for layer ${layer}:`, error);
        }
      }
    },
    [
      setCheckpoints,
      setIsPaused,
      setPendingReviewLayer,
      fetchLayerReportsFromBackend,
      setDimensionContents,
    ]
  );

  // 【新增】处理维度修复完成事件
  // ✅ Signal-Fetch 模式：SSE 事件只发送轻量信号，内容通过 REST API 获取
  const handleDimensionRevised = useCallback(
    async (data: {
      dimension: string;
      layer: number;
      timestamp: string;
      // 注意：SSE 事件不再携带 newContent，需要通过 REST API 获取
    }) => {
      const dimensionName = getDimensionName(data.dimension);
      const revisionId = `revision-${data.timestamp}-${data.dimension}`; // 可预测 ID，便于去重

      try {
        // ✅ Signal-Fetch 模式：调用 REST API 获取维度内容
        const dimensionData = await planningApi.getDimensionContent(taskId || '', data.dimension);

        if (!dimensionData.exists) {
          console.warn(`[ChatPanel] Dimension ${data.dimension} content not found`);
          return;
        }

        const newContent = dimensionData.content;
        const previousContent = dimensionData.previous_content;
        const version = dimensionData.version || 1;

        // 添加修复后的维度报告
        const dimensionReportMsg = {
          ...createBaseMessage(),
          id: revisionId, // 使用可预测 ID
          type: 'dimension_report' as const,
          role: 'assistant' as const,
          layer: data.layer,
          dimensionKey: data.dimension,
          dimensionName: dimensionName,
          content: newContent,
          // ✅ 保存原始内容引用，用于显示修复前后对比
          previousContent: previousContent || undefined,
          revisionVersion: version,
          isRevision: true,
          streamingState: 'completed' as const,
          wordCount: newContent.length,
        };
        addMessage(dimensionReportMsg);

        // 更新维度内容到状态
        setDimensionContents((prev) => ({
          ...prev,
          [data.dimension]: newContent,
        }));
      } catch (error) {
        console.error(`[ChatPanel] Failed to fetch dimension content:`, error);
        // 降级处理：添加错误提示消息
        addMessage(
          createSystemMessage(`获取维度 ${dimensionName} 内容失败，请刷新页面重试`, 'error')
        );
      }
    },
    [addMessage, taskId, setDimensionContents]
  );

  // SSE 连接成功回调 - 连接成功后触发状态恢复检查
  const handleConnected = useCallback(() => {
    sseConnectedRef.current = true;

    // 串行处理，避免并发竞态
    for (const layer of LAYER_IDS) {
      restoreLayerData(layer);
    }
  }, [restoreLayerData]);

  // Stable callbacks object using useMemo
  // Note: callbacks are used by SSE event handlers via dispatch, kept for reference
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const callbacks = useMemo(
    () => ({
      // ✅ 删除所有业务逻辑回调 - 现在使用状态驱动 UI
      // Controller 只负责数据搬运,不做任何业务逻辑判断
      onTextDelta: handleTextDelta,
      // 维度级流式回调
      onDimensionDelta: handleDimensionDelta,
      onDimensionComplete: handleDimensionComplete,
      // 层级开始回调
      onLayerStarted: handleLayerStarted,
      onLayerProgress: handleLayerProgress,
      // 层级完成回调
      onLayerCompleted: handleLayerCompleted,
      // 暂停回调
      onPause: handlePause,
      // 【新增】维度修复完成回调
      onDimensionRevised: handleDimensionRevised,
      // ✅ Fix 2: SSE 连接成功回调
      onConnected: handleConnected,
      // Tool event callbacks
      onToolCall: handleToolCall,
      onToolProgress: handleToolProgress,
      onToolResult: handleToolResult,
    }),
    [
      handleTextDelta,
      handleDimensionDelta,
      handleDimensionComplete,
      handleLayerStarted,
      handleLayerProgress,
      handleLayerCompleted,
      handlePause,
      handleDimensionRevised,
      handleConnected,
      handleToolCall,
      handleToolProgress,
      handleToolResult,
    ]
  );

  // Use actions directly from PlanningProvider (no TaskController needed)
  // SSE is handled by PlanningProvider internally

  // Stable handler for SegmentedControl onChange
  const handleLayerChange = useCallback(
    async (layer: string) => {
      const layerNumber = LAYER_LABEL_MAP[layer];

      if (layerNumber !== undefined && taskId) {
        // 1. Fetch latest reports from backend
        try {
          const reports = await planningApi.getLayerReports(taskId, layerNumber);

          // 2. Update reports in state
          const layerKey = `layer${layerNumber}` as 'layer1' | 'layer2' | 'layer3';
          usePlanningStore.getState().setReports({
            [layerKey]: reports.reports || {},
          });
        } catch (error) {
          console.error('[ChatPanel] Failed to fetch Layer reports:', error);
        }

        // 3. Open sidebar
        onOpenLayerSidebar?.(layerNumber);
      }
    },
    [onOpenLayerSidebar, taskId]
  );

  // ❌ DELETED: useLayoutEffect that causes status bounce
  // The pendingLayerCompletionRef mechanism has been removed

  // Auto-scroll to bottom - DISABLED for manual scrolling control
  // useEffect(() => {
  //   messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  // }, [messages]);

  // Scroll detection and jump-to-bottom button
  const [showScrollButton, setShowScrollButton] = useState(false);

  useEffect(() => {
    const container = document.querySelector('.flex-1.overflow-y-auto');
    if (!container) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container as HTMLElement;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
      setShowScrollButton(!isNearBottom);
    };

    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, []);

  // ✅ NEW: Cleanup effect - clear typing timeout on unmount
  useEffect(() => {
    return () => {
      if (typingTimeoutRef.current) {
        clearTimeout(typingTimeoutRef.current);
      }
    };
  }, []);

  // ✅ 新增：从 TaskController 同步状态到 Context
  useEffect(() => {
    if (!taskId) return;

    // 直接将 taskState 同步到 Context
    // Controller 只负责数据搬运,不做任何业务逻辑判断
    syncBackendState(taskState);
  }, [taskId, taskState, syncBackendState]);

  // SSE 断线重连后的层级状态恢复机制（备用保护）
  // 主要恢复逻辑在 handleConnected 回调中执行
  useEffect(() => {
    if (!taskId || status === 'idle' || !sseConnectedRef.current) return;

    // 串行处理，避免并发竞态
    for (const layer of LAYER_IDS) {
      restoreLayerData(layer);
    }
  }, [taskId, status, restoreLayerData]);

  // Determine if input should be disabled
  const inputDisabled = isInputDisabled(status);

  // 审查状态: 状态驱动，由后端同步 (isPaused, pendingReviewLayer)
  // 不再依赖 messages 中的 ReviewInteractionMessage
  const hasPendingReview = isPaused && pendingReviewLayer !== null;

  // Review handlers - use PlanningProvider actions
  const handleReviewApprove = useCallback(async () => {
    try {
      await actions.approve();
      addMessage(createSystemMessage('✅ Approved, continuing to next layer...'));
    } catch (error: unknown) {
      addMessage(createErrorMessage(`Approval failed: ${getErrorMessage(error, 'Unknown error')}`));
    }
  }, [actions, addMessage]);

  const handleRollbackAction = useCallback(
    async (checkpointId: string) => {
      if (!confirm('Are you sure you want to rollback? Subsequent content will be deleted.'))
        return;

      setIsRollingBack(true);
      try {
        await rollback(checkpointId);
        addMessage(createSystemMessage(`↩️ Rolled back to checkpoint: ${checkpointId}`));
      } catch (error: unknown) {
        addMessage(createErrorMessage(`回退失败: ${getErrorMessage(error, '未知错误')}`));
      } finally {
        setIsRollingBack(false);
      }
    },
    [rollback, addMessage]
  );

  // Handler: Start planning from form submission
  const handleStartPlanning = useCallback(async () => {
    if (!villageFormData) return;

    logger.chatPanel.info('点击"开始规划"按钮', { projectName: villageFormData.projectName });

    try {
      setIsPlanning(true);

      // 1. 构建村庄现状数据：优先使用聊天界面上传的文件
      let villageData = uploadedFileContent || '';

      // 2. 合并表单上传的文件内容
      if (villageFormData.taskDescriptionFiles && villageFormData.taskDescriptionFiles.length > 0) {
        const fileContents = villageFormData.taskDescriptionFiles
          .map((f) => `## 📎 文件：${f.filename}\n\n${f.content}`)
          .join('\n\n---\n\n');

        villageData = villageData ? `${villageData}\n\n---\n\n${fileContents}` : fileContents;
      }

      // 注意：删除默认示例数据，villageData 可能为空字符串
      // 后端 prompt 模板已有默认处理：raw_data 为空时显示占位提示

      // 提取村名（优先从文件内容匹配，其次使用项目名称）
      const villageNameMatch = villageData.match(/(?:广东省|梅州市|平远县|泗水镇)?(.{2,8}村)/);
      const villageName = villageNameMatch ? villageNameMatch[1] : villageFormData.projectName;

      // taskDescription 仅使用表单文本输入（文件内容已合并到 villageData）
      const taskDescription = villageFormData.taskDescription || PLANNING_DEFAULTS.defaultTask;

      // 合并上传的文件内容到 constraints
      let constraints = villageFormData.constraints || PLANNING_DEFAULTS.defaultConstraints;
      if (villageFormData.constraintsFiles && villageFormData.constraintsFiles.length > 0) {
        const fileContents = villageFormData.constraintsFiles
          .map((f) => `### 📎 文件：${f.filename}\n\n${f.content}`)
          .join('\n\n---\n\n');
        constraints = constraints ? `${constraints}\n\n---\n\n${fileContents}` : fileContents;
      }

      await startPlanning({
        projectName: villageFormData.projectName,
        villageData,
        villageName,
        taskDescription,
        constraints,
        enableReview: PLANNING_DEFAULTS.enableReview,
        stepMode,
        streamMode: PLANNING_DEFAULTS.streamMode,
      });
      logger.chatPanel.info('规划启动成功', { status: 'planning' });
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, '未知错误');
      logger.chatPanel.error('规划启动失败', { error: errorMessage });
      console.error('[ChatPanel] Failed to start planning:', error);

      // Detect rate limit errors
      if (
        errorMessage.includes('过于频繁') ||
        (typeof error === 'object' &&
          error !== null &&
          'status' in error &&
          (error as { status?: number }).status === 429)
      ) {
        setRateLimitError({ projectName: villageFormData.projectName });
      }

      addMessage(createErrorMessage(`启动规划失败: ${errorMessage}`));
    } finally {
      setIsPlanning(false);
    }
  }, [villageFormData, uploadedFileContent, startPlanning, addMessage, stepMode]);

  // Handler: Reset rate limit for a project
  const handleResetRateLimit = useCallback(
    async (projectName: string) => {
      try {
        logger.chatPanel.info(`Resetting rate limit for project: ${projectName}`);
        await planningApi.resetProject(projectName);
        setRateLimitError(null);
        addMessage(createSystemMessage(`✅ 已重置项目 "${projectName}" 的限流状态，请重试`));
      } catch (error: unknown) {
        const errorMessage = getErrorMessage(error, '未知错误');
        logger.chatPanel.error('Failed to reset rate limit', { error: errorMessage });
        addMessage(createErrorMessage(`重置限流失败: ${errorMessage}`));
      }
    },
    [addMessage]
  );

  // Note: Form submission is now handled by UnifiedContentSwitcher
  // ChatPanel only handles the planning session after it has started
  // Review 功能现在通过 ReviewPanel 组件处理，基于状态驱动

  // Send message handler
  const handleSendMessage = useCallback(async () => {
    const userText = inputText.trim();
    if (!userText) return;

    setInputText('');

    // 保存当前选中的维度，然后清除
    const dimensionsToSubmit = selectedDimensions.length > 0 ? [...selectedDimensions] : undefined;
    setSelectedDimensions([]);

    // 审查状态下的特殊处理
    if (isPaused && pendingReviewLayer) {
      // 用户消息
      const now = new Date();
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: now,
        created_at: now.toISOString(),
        role: 'user',
        type: 'text',
        content: userText,
      });

      // Check if this is an approval command
      if (userText === '批准' || userText === '继续' || userText.toLowerCase() === 'approve') {
        try {
          addMessage(createSystemMessage('✅ Approved, continuing to next layer...'));
          await approve();
        } catch (error: unknown) {
          addMessage(
            createErrorMessage(`Approval failed: ${getErrorMessage(error, 'Unknown error')}`)
          );
        }
        return;
      }

      // Rejection/revision request - send feedback via chat
      try {
        addMessage(
          createSystemMessage(
            `🔄 Revising based on feedback${dimensionsToSubmit ? '...' : ' (auto-detecting dimensions)...'} `
          )
        );
        await reject(userText, dimensionsToSubmit);
      } catch (error: unknown) {
        addMessage(
          createErrorMessage(`Revision failed: ${getErrorMessage(error, 'Unknown error')}`)
        );
      }
      return;
    }

    // Normal chat message
    const userMsgNow = new Date();
    addMessage({
      id: `msg-${Date.now()}`,
      timestamp: userMsgNow,
      created_at: userMsgNow.toISOString(),
      role: 'user',
      type: 'text',
      content: userText,
    });

    setIsTyping(true);

    // TODO: Process message with AI
    // ✅ FIXED: Store timeout ID for cleanup
    typingTimeoutRef.current = setTimeout(() => {
      const assistantMsgNow = new Date();
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: assistantMsgNow,
        created_at: assistantMsgNow.toISOString(),
        role: 'assistant',
        type: 'text',
        content: `收到: ${userText}`,
      });
      setIsTyping(false);
      typingTimeoutRef.current = null;
    }, 500);
  }, [inputText, addMessage, isPaused, pendingReviewLayer, approve, reject, selectedDimensions]);

  // File selection handler
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    try {
      setIsUploadingFile(true);

      // 支持多文件上传
      const uploadPromises = Array.from(files).map(async (file) => {
        const response = await fileApi.uploadFile(file);
        return { file, response };
      });

      const results = await Promise.all(uploadPromises);

      // 合并所有文件内容
      const allContents: string[] = [];
      const messagesToAdd: Message[] = [];

      for (const { file, response } of results) {
        allContents.push(response.content);

        messagesToAdd.push({
          ...createBaseMessage('user'),
          type: 'file',
          filename: file.name,
          fileContent: response.content,
          fileSize: response.size,
          encoding: response.encoding,
          fileType: response.fileType,
          imageBase64: response.imageBase64,
          imageFormat: response.imageFormat,
          thumbnailBase64: response.thumbnailBase64,
          imageWidth: response.imageWidth,
          imageHeight: response.imageHeight,
          embeddedImages: response.embeddedImages,
        } as FileMessage);

        const encodingInfo = response.encoding ? `\n编码: ${response.encoding}` : '';
        messagesToAdd.push(
          createSystemMessage(
            `✅ 文件 "${file.name}" 已上传${encodingInfo}\n内容长度: ${response.content.length} 字符`
          )
        );
      }

      // 存储合并后的内容
      const combinedContent = allContents.join('\n\n---\n\n');

      // 添加最后的提示消息
      if (results.length > 1) {
        messagesToAdd.push(
          createSystemMessage(
            `✅ 已上传 ${results.length} 个文件，总内容长度: ${combinedContent.length} 字符\n点击 "开始规划" 按钮启动任务`
          )
        );
      } else {
        messagesToAdd.push(createSystemMessage(`点击 "开始规划" 按钮启动任务`));
      }

      // 批量添加所有消息（只触发一次渲染）
      addMessages(messagesToAdd);
      setUploadedFileContent(combinedContent);

      e.target.value = '';
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, '未知错误');
      addMessage(createErrorMessage(`❌ 文件上传失败: ${errorMessage}`));
    } finally {
      setIsUploadingFile(false);
    }
  };

  // Default village data template
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const getDefaultVillageData = useCallback(
    (projectName: string) => `# 村庄现状数据（示例）

## 基本信息
- 村庄名称：${projectName}
- 地理位置：中国某省某市某县
- 人口规模：约1000人
- 土地面积：约5000亩

## 产业现状
- 主要产业：农业、手工业
- 经济水平：中等偏下
`,
    []
  );

  // Handler: 查看完整报告（移除侧边栏功能，保留日志）
  const handleOpenInSidebar = useCallback(
    (layer: number) => {
      const layerId = getLayerId(layer);
      if (layerId) {
        showViewer();
      }
    },
    [showViewer]
  );

  // Handler: 在侧边栏查看文件内容
  const handleViewFileInSidebar = useCallback(
    (file: FileMessage) => {
      showFileViewer(file);
    },
    [showFileViewer]
  );

  return (
    <div className={`flex flex-col h-full bg-[#F9FBF9] ${className}`}>
      {/* Top: Status indicators only - Card-style design */}
      {(status === 'collecting' ||
        status === 'planning' ||
        status === 'paused' ||
        status === 'revising') && (
        <div className="flex-shrink-0 border-b border-gray-200 bg-white p-3 shadow-sm">
          <div className="max-w-6xl mx-auto">
            {/* Status badge - Colored + Icon + Shadow */}
            <div className="flex items-center gap-2">
              {(() => {
                const badge = getStatusBadge(status);
                return (
                  <span className={`status-badge ${badge.className}`}>
                    <span className="text-base">{badge.icon}</span>
                    {badge.label}
                  </span>
                );
              })()}

              {currentLayer && (
                <span className="status-badge status-badge-success">
                  <FontAwesomeIcon icon={faLayerGroup} className="icon-xs" />
                  Layer {currentLayer}
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Middle: Message list - Centered container + max width */}
      {/* Layer Segmented Control - 固定在 ChatPanel 顶部，不随消息滚动 */}
      {taskId && taskId !== 'new' && (
        <div className="sticky top-0 bg-[#F9FBF9] border-b border-gray-200 z-10">
          <div className="max-w-6xl mx-auto p-4">
            <SegmentedControl
              options={LAYER_OPTIONS_ARRAY}
              value={currentLayer ? LAYER_VALUE_MAP[currentLayer] : LAYER_OPTIONS_ARRAY[0]}
              onChange={handleLayerChange}
            />
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-6xl mx-auto">
          <MessageList
            messages={messages}
            isTyping={isTyping}
            onOpenInSidebar={handleOpenInSidebar}
            onViewFileInSidebar={handleViewFileInSidebar}
            onViewLayerDetails={(layer) => {
              const layerId = getLayerId(layer);
              if (layerId) {
                showViewer();
              }
            }}
            onToggleAllDimensions={(_layer, _expand) => {
              // This would expand/collapse all dimensions in the viewer
              // TODO: Implement expand/collapse all in LayerReportViewer
            }}
            currentLayer={currentLayer ?? undefined}
            dimensionContents={dimensionContents}
            checkpoints={checkpoints}
            onRollback={handleRollbackAction}
            isRollingBack={isRollingBack}
          />
          <div ref={messagesEndRef} />
        </div>

        {/* Jump to bottom button */}
        {showScrollButton && (
          <button
            onClick={() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })}
            className="fixed bottom-24 right-8 bg-blue-100 text-gray-900 border border-blue-300 p-3 rounded-full shadow-lg hover:bg-blue-200 transition-colors z-50"
            title="跳转到底部"
          >
            ↓
          </button>
        )}
      </div>

      {/* 审查功能已通过 ReviewInteractionMessage 组件嵌入在 MessageList 中 */}
      {/* 不需要额外的审查面板 */}

      {/* Bottom: Floating Capsule Input Area - Gemini Style */}
      <div className="sticky bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-gray-50 via-gray-50/95 to-transparent">
        <div className="max-w-6xl mx-auto">
          {/* Rate limit warning and reset button */}
          {rateLimitError && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-3 px-4 py-3 bg-amber-50 border border-amber-200 rounded-2xl flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl">⚠️</span>
                <div>
                  <div className="font-semibold text-amber-800">请求过于频繁</div>
                  <div className="text-sm text-amber-700">
                    项目 &quot;{rateLimitError.projectName}&quot; 触发了速率限制
                  </div>
                </div>
              </div>
              <button
                className="px-4 py-2 text-sm font-medium text-amber-700 bg-white border border-amber-300 rounded-full hover:bg-amber-100 transition-colors"
                onClick={() => handleResetRateLimit(rateLimitError.projectName)}
              >
                🔄 重置限制
              </button>
            </motion.div>
          )}

          {/* Planning ready indicator with Start Planning button */}
          {status === 'collecting' && villageFormData && !taskId && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-3 px-4 py-3 bg-emerald-50 border border-emerald-200 rounded-2xl flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl">📋</span>
                <div>
                  <div className="font-semibold text-emerald-800">规划任务已准备</div>
                  <div className="text-sm text-emerald-700">
                    村庄：{villageFormData.projectName}
                  </div>
                </div>
              </div>
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                className="px-5 py-2 font-medium text-white rounded-full"
                style={{
                  background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                  boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)',
                }}
                onClick={handleStartPlanning}
                disabled={isPlanning}
              >
                {isPlanning ? (
                  <span className="flex items-center gap-2">
                    <i className="fas fa-spinner fa-spin text-sm" />
                    启动中...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <span>🚀</span>
                    开始规划
                  </span>
                )}
              </motion.button>
            </motion.div>
          )}

          {/* Progress Panel - 执行进度面板 */}
          <ProgressPanel
            visible={progressPanelVisible}
            currentLayer={currentLayer}
            currentPhase={currentPhase}
            dimensionProgress={dimensionProgress}
            executingDimensions={executingDimensions}
            onClose={() => setProgressPanelVisible(false)}
          />

          {/* Tool Status Panel - 工具执行状态面板 */}
          <div className="px-4 py-2">
            <ToolStatusPanel tools={toolStatusMap} />
          </div>

          {/* Review Panel - 状态驱动 */}
          {isPaused && pendingReviewLayer && (
            <ReviewPanel
              layer={pendingReviewLayer}
              dimensions={getDimensionsByLayer(pendingReviewLayer)}
              dimensionNames={DIMENSION_NAMES}
              onApprove={handleReviewApprove}
              isSubmitting={false}
            />
          )}

          {/* 维度选择器 - 仅在审查状态下显示 */}
          {isPaused && pendingReviewLayer && (
            <div className="mb-3">
              <DimensionSelector
                layer={pendingReviewLayer}
                selectedDimensions={selectedDimensions}
                onChange={setSelectedDimensions}
                disabled={isTyping}
              />
            </div>
          )}

          {/* Floating Capsule Input */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className={`relative flex items-end gap-2 p-2 bg-white rounded-3xl shadow-lg border transition-all duration-300 ${
              hasPendingReview
                ? 'border-amber-200 shadow-amber-100/50'
                : 'border-gray-100 hover:border-gray-200'
            }`}
          >
            {/* Hidden file input */}
            <input
              type="file"
              multiple
              accept={FILE_ACCEPT}
              onChange={handleFileSelect}
              disabled={inputDisabled || isTyping || isUploadingFile}
              className="hidden"
              id="file-upload"
            />

            {/* File upload button - icon only */}
            <motion.label
              htmlFor="file-upload"
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className={`flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full cursor-pointer transition-colors ${
                inputDisabled || isTyping || isUploadingFile
                  ? 'text-gray-300 cursor-not-allowed'
                  : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
              }`}
            >
              <i className={`fas ${isUploadingFile ? 'fa-spinner fa-spin' : 'fa-paperclip'}`} />
            </motion.label>

            {/* GIS Upload Button - map icon */}
            <motion.button
              type="button"
              onClick={() => setShowGISUploadSidebar(true)}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
              title="上传 GIS 数据"
            >
              <FontAwesomeIcon icon={faMap} />
            </motion.button>

            {/* Step Mode Toggle - Gemini style pill switch */}
            <div className="flex items-center p-0.5 bg-gray-100 rounded-full flex-shrink-0">
              <motion.button
                type="button"
                onClick={() => setStepMode(false)}
                whileHover={!stepMode ? {} : { scale: 1.02 }}
                whileTap={!stepMode ? {} : { scale: 0.98 }}
                className={`px-2.5 py-1 text-xs font-medium rounded-full transition-all duration-200 ${
                  !stepMode
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                连续
              </motion.button>
              <motion.button
                type="button"
                onClick={() => setStepMode(true)}
                whileHover={stepMode ? {} : { scale: 1.02 }}
                whileTap={stepMode ? {} : { scale: 0.98 }}
                className={`px-2.5 py-1 text-xs font-medium rounded-full transition-all duration-200 ${
                  stepMode
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                分步
              </motion.button>
            </div>

            {/* Progress Panel Toggle - 进度面板开关 */}
            <motion.button
              type="button"
              onClick={() => setProgressPanelVisible(!progressPanelVisible)}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full transition-all duration-200 flex-shrink-0 ${
                progressPanelVisible
                  ? 'bg-blue-100 text-blue-700 ring-1 ring-blue-300'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
              title={progressPanelVisible ? '隐藏进度面板' : '显示进度面板'}
            >
              <span>📊</span>
              <span>{progressPanelVisible ? '隐藏进度' : '进度'}</span>
            </motion.button>

            {/* Text input - grows dynamically */}
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (inputText.trim() && !isTyping) handleSendMessage();
                }
              }}
              disabled={inputDisabled || isTyping}
              placeholder={
                hasPendingReview && pendingReviewLayer
                  ? '请输入修改意见，或输入"批准"继续...'
                  : status === 'planning' || status === 'collecting'
                    ? '规划进行中...'
                    : '输入消息...'
              }
              rows={1}
              className="flex-1 min-h-[40px] max-h-32 px-2 py-2 text-gray-900 placeholder-gray-400 bg-transparent border-0 resize-none focus:outline-none focus:ring-0 text-sm leading-relaxed"
              style={{
                height: 'auto',
                overflow: inputText.split('\n').length > 2 ? 'auto' : 'hidden',
              }}
            />

            {/* Send button - gradient circle */}
            <motion.button
              onClick={handleSendMessage}
              disabled={inputDisabled || isTyping || !inputText.trim() || isUploadingFile}
              whileHover={inputText.trim() ? { scale: 1.05 } : {}}
              whileTap={inputText.trim() ? { scale: 0.95 } : {}}
              className={`flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full transition-all duration-300 ${
                inputText.trim() && !inputDisabled
                  ? 'text-white shadow-lg'
                  : 'text-gray-300 bg-gray-100 cursor-not-allowed'
              }`}
              style={
                inputText.trim() && !inputDisabled
                  ? {
                      background: 'linear-gradient(135deg, #10b981 0%, #14b8a6 50%, #0891b2 100%)',
                      boxShadow: '0 4px 15px rgba(16, 185, 129, 0.4)',
                    }
                  : {}
              }
            >
              {isUploadingFile ? (
                <i className="fas fa-spinner fa-spin text-sm" />
              ) : isTyping ? (
                <i className="fas fa-spinner fa-spin text-sm" />
              ) : (
                <i className="fas fa-arrow-up text-sm" />
              )}
            </motion.button>
          </motion.div>

          {/* Helper text */}
          <p className="text-center text-xs text-gray-400 mt-2">Enter 发送 · Shift+Enter 换行</p>
        </div>
      </div>

      {/* GIS Upload Sidebar */}
      <GISUploadSidebar
        isOpen={showGISUploadSidebar}
        onClose={() => setShowGISUploadSidebar(false)}
        onDataUploaded={(result: UploadResult) => {
          // 添加系统消息通知用户
          const systemMsg = createSystemMessage(
            `GIS 数据已上传: ${result.metadata.fileName} (${result.metadata.featureCount} 个特征，类型: ${result.dataType})`
          );
          addMessage(systemMsg);
          setShowGISUploadSidebar(false);
        }}
      />
    </div>
  );
}
