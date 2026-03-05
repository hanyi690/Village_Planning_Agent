'use client';

/**
 * ChatPanel - Unified chat interface integrating messaging and progress display
 * Refactored to use TaskController for state management (REST polling + SSE for text only)
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useUnifiedPlanningContext } from '@/contexts/UnifiedPlanningContext';
import type {
  Message,
  ActionButton,
  FileMessage,
  ProgressMessage,
} from '@/types';
import {
  isProgressMessage,
  LayerCompletedMessage,
} from '@/types';
import { planningApi, dataApi, fileApi } from '@/lib/api';
import { createBaseMessage, createSystemMessage, createErrorMessage } from '@/lib/utils';
import { logger } from '@/lib/logger';
import SegmentedControl from '@/components/ui/SegmentedControl';
import { useTaskController } from '@/controllers/TaskController';
import { useStreamingRender } from '@/hooks/useStreamingRender';
import MessageList from './MessageList';
import ReviewPanel from './ReviewPanel';
import DimensionSelector from './DimensionSelector';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEdit, faLayerGroup } from '@fortawesome/free-solid-svg-icons';
import { getDimensionName, getDimensionsByLayer, DIMENSION_NAMES } from '@/config/dimensions';
import { PLANNING_DEFAULTS } from '@/config/planning';
import {
  LAYER_OPTIONS_ARRAY,
  LAYER_LABEL_MAP,
  LAYER_VALUE_MAP,
  getLayerId,
  MIN_FILE_CONTENT_LENGTH,
  FILE_ACCEPT,
  isInputDisabled,
} from '@/lib/constants';

interface ChatPanelProps {
  className?: string;
}

export default function ChatPanel({ className = '' }: ChatPanelProps) {
  const {
    messages,
    setMessages,
    addMessage,
    updateLastMessage,
    status,
    taskId,
    projectName,
    setStatus,
    villageFormData,
    checkpoints,
    setCheckpoints,
    currentLayer,
    setCurrentLayer,
    startPlanning,
    loadLayerContent,
    showViewer,
    // 审查状态
    isPaused,
    pendingReviewLayer,
    // 层级完成状态
    completedLayers,
    // 同步后端状态
    syncBackendState,
    // ✅ 新增：SSE 驱动的层级完成状态更新
    setUILayerCompleted,
  } = useUnifiedPlanningContext();

  const [inputText, setInputText] = useState('');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [uploadedFileContent, setUploadedFileContent] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ✅ NEW: Track typing timeout for cleanup
  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // ✅ NEW: Use useMemo to cache filtered messages (P1.4 performance optimization)
  const progressMessages = useMemo(() => {
    return messages.filter(m => m.type === 'progress');
  }, [messages]);

  // 维度内容缓存 (用于流式渲染)
  const [dimensionContents, setDimensionContents] = useState<Map<string, string>>(new Map());

  // Rate limit error tracking
  const [rateLimitError, setRateLimitError] = useState<{ projectName: string } | null>(null);

  // Helper: Load checkpoints
  const loadCheckpoints = useCallback(async () => {
    if (!taskId) return;
    try {
      const statusData = await planningApi.getTaskStatus(taskId);
      const checkpointsList = statusData.checkpoints || [];
      setCheckpoints(checkpointsList);
    } catch (error: any) {
      console.error('Failed to load checkpoints:', error);
    }
  }, [taskId, setCheckpoints]);

  // Helper: Load layer report content
  const loadLayerReportContent = useCallback(async (layer: number): Promise<string | null> => {
    const layerId = getLayerId(layer);
    if (!layerId || !taskId || !projectName) {
      console.warn('[ChatPanel] Missing required data for layer content load', {
        layer,
        hasLayerId: !!layerId,
        hasTaskId: !!taskId,
        hasProjectName: !!projectName,
      });
      return null;
    }

    console.log(`[ChatPanel] Loading Layer ${layer} report...`, { layerId, taskId, projectName });

    try {
      const data = await dataApi.getLayerContent(projectName, layerId, taskId, 'markdown');

      if (data.content?.trim().length > 0) {
        console.log(`[ChatPanel] Layer ${layer} report loaded successfully, length: ${data.content.length}`);
        return data.content;
      }

      console.warn(`[ChatPanel] Layer ${layer} report content is empty`);
      return null;
    } catch (error) {
      console.error(`[ChatPanel] Layer ${layer} report loading failed:`, error);
      return null;
    }
  }, [taskId, projectName]);

  // ✅ 删除 createLayerCompletedMessage - 现在使用状态驱动

  // ✅ Stabilize all callbacks using useCallback to prevent TaskController restarts
  // ✅ 删除 handleLayerCompleted - 现在使用状态驱动,从 Context 状态派生

  // ✅ 删除 handleComplete - 现在使用状态驱动,从 Context 状态派生

  // ✅ 删除 handleError - 现在使用状态驱动,从 Context 状态派生

  const handleTextDelta = useCallback((text: string, layer?: number) => {
    setMessages(prevMessages => {
      const lastMsg = prevMessages[prevMessages.length - 1];
      if (lastMsg?.type === 'text') {
        return [...prevMessages.slice(0, -1), {
          ...lastMsg,
          content: (lastMsg as { content: string }).content + text
        }];
      }
      return [...prevMessages, {
        ...createBaseMessage('assistant'),
        type: 'text',
        content: text,
      } as Message & { layer?: number }];
    });
  }, [setMessages]);

  // 批处理渲染 Hook - 用于维度级流式显示
  const { addToken, completeDimension } = useStreamingRender(
    useCallback((dimensionKey: string, content: string) => {
      setDimensionContents(prev => {
        const next = new Map(prev);
        next.set(dimensionKey, content);
        return next;
      });

      // 可以在这里添加UI更新逻辑
      console.log(`[ChatPanel] Dimension content updated: ${dimensionKey}, length: ${content.length}`);
    }, []),
    { batchSize: 10, batchWindow: 50, debounceMs: 100 }
  );

  // 维度级流式回调
  // ✅ 修复：只更新 dimensionContents，不再更新 messages（解决并行更新竞态问题）
  // LayerReportMessage 组件从 dimensionContents 读取实时内容
  const handleDimensionDelta = useCallback((
    dimensionKey: string,
    delta: string,
    accumulated: string,
    layer?: number
  ) => {
    // 更新维度内容缓存（独立 Map，每个维度更新不会影响其他维度）
    setDimensionContents(prev => {
      const key = `${layer}_${dimensionKey}`;
      return new Map(prev).set(key, accumulated);
    });

    // 使用批处理渲染
    addToken(dimensionKey, delta, accumulated);

    // 不再调用 setMessages 更新 dimensionReports，避免竞态条件
    // LayerReportMessage 组件通过 dimensionContents prop 获取实时内容
  }, [addToken]);

  const handleDimensionComplete = useCallback((
    dimensionKey: string,
    dimensionName: string,
    fullContent: string,
    layer?: number
  ) => {
    // 更新维度内容缓存
    setDimensionContents(prev => {
      const key = `${layer}_${dimensionKey}`;
      return new Map(prev).set(key, fullContent);
    });

    // 标记维度完成，刷新剩余内容
    completeDimension(dimensionKey);

    // 更新消息状态为完成
    const messageId = `dimension_${layer}_${dimensionKey}`;
    setMessages(prev => prev.map(msg =>
      msg.id === messageId
        ? { ...msg, content: fullContent, wordCount: fullContent.length, streamingState: 'completed' as const }
        : msg
    ));

    console.log(`[ChatPanel] Dimension complete: ${dimensionKey} (${fullContent.length} chars)`);
  }, [completeDimension, setMessages]);

  const handleLayerProgress = useCallback((
    layer: number,
    completed: number,
    total: number
  ) => {
    // 可以更新进度条
    console.log(`[ChatPanel] Layer ${layer} progress: ${completed}/${total}`);
  }, []);

  const handleLayerCompleted = useCallback((
    layer: number,
    reportContent: string,
    dimensionReports: Record<string, string>
  ) => {
    console.log(`[ChatPanel] Layer ${layer} completed`, {
      reportLength: reportContent.length,
      dimensionCount: Object.keys(dimensionReports).length,
    });

    // ✅ 合并 layer_stream_complete 功能：直接更新 completedLayers 状态
    setUILayerCompleted(layer, true);

    const layerReportId = `layer_report_${layer}`;

    // 检查该层是否已有 LayerReportMessage
    const hasLayerReport = messages.some(m => m.id === layerReportId);

    if (!hasLayerReport) {
      // 创建 LayerReportMessage
      const wordCount = Object.values(dimensionReports).reduce((sum, content) => sum + content.length, 0);
      
      addMessage({
        ...createBaseMessage('assistant'),
        id: layerReportId,
        type: 'layer_completed' as const,
        layer: layer,
        content: reportContent,
        summary: {
          word_count: wordCount as number,
          key_points: [],
          dimension_count: Object.keys(dimensionReports).length,
        },
        fullReportContent: reportContent,
        dimensionReports: dimensionReports,
        actions: [
          {
            id: 'view_details',
            label: '查看详情',
            action: 'view',
            onClick: () => {
              showViewer();
            },
          },
        ],
      });
    } else {
      // 更新现有消息
      setMessages(prev => prev.map(msg => {
        if (msg.id === layerReportId && msg.type === 'layer_completed') {
          const wordCount = Object.values(dimensionReports).reduce((sum, content) => sum + content.length, 0);
          return {
            ...msg,
            content: reportContent,
            fullReportContent: reportContent,
            dimensionReports: dimensionReports,
            summary: {
              word_count: wordCount as number,
              key_points: msg.summary?.key_points || [],
              dimension_count: Object.keys(dimensionReports).length,
            },
          };
        }
        return msg;
      }));
    }
  }, [messages, addMessage, setMessages, showViewer]);

  // ✅ 新增：处理层级开始事件 - 创建空的 LayerReportMessage（预填充维度槽位）
  const handleLayerStarted = useCallback((layer: number, layerName: string) => {
    console.log(`[ChatPanel] Layer ${layer} started - ${layerName}`);

    const layerLabels: Record<number, string> = {
      1: '现状分析',
      2: '规划思路',
      3: '详细规划',
    };

    // 创建层级报告消息（预填充维度槽位，等待流式更新）
    const layerReportId = `layer_report_${layer}`;
    
    // 检查该层是否已有 LayerReportMessage
    const hasLayerReport = messages.some(m => m.id === layerReportId);
    
    if (!hasLayerReport) {
      // ✅ 预先获取该层级的所有维度，创建空槽位
      const dimensionKeys = getDimensionsByLayer(layer);
      const emptyDimensionReports: Record<string, string> = {};
      dimensionKeys.forEach(key => {
        emptyDimensionReports[key] = '';  // 空字符串，等待流式填充
      });
      
      console.log(`[ChatPanel] Pre-creating ${dimensionKeys.length} dimension slots for Layer ${layer}`);
      
      addMessage({
        ...createBaseMessage('assistant'),
        id: layerReportId,
        type: 'layer_completed' as const,
        layer: layer,
        content: '',
        summary: {
          word_count: 0,
          key_points: [],
          dimension_count: dimensionKeys.length,  // 预设维度数量
        },
        fullReportContent: '',
        dimensionReports: emptyDimensionReports,  // ✅ 预填充空维度槽位
        actions: [],
      });
    }

    // 添加层级开始提示消息
    addMessage({
      ...createBaseMessage(),
      type: 'progress',
      role: 'assistant',
      content: `🔄 正在执行 Layer ${layer}: ${layerLabels[layer] || layerName}...`,
      layer,
      progress: 0,
    } as ProgressMessage);
  }, [messages, addMessage]);

  const handlePause = useCallback((
    layer: number,
    checkpointId: string
  ) => {
    console.log(`[ChatPanel] Pause event received`, { layer, checkpointId });
    // 状态同步由 TaskController 通过轮询处理
    // 这里可以添加额外的 UI 更新逻辑
  }, []);

  // 【新增】处理维度修复完成事件
  const handleDimensionRevised = useCallback((data: {
    dimension: string;
    layer: number;
    oldContent: string;
    newContent: string;
    feedback: string;
    timestamp: string;
  }) => {
    console.log('[ChatPanel] Dimension revised event received', data);
    
    const dimensionName = getDimensionName(data.dimension);
    
    // 1. 添加用户反馈消息（如果有的话）
    if (data.feedback) {
      addMessage({
        ...createBaseMessage(),
        type: 'text',
        role: 'user',
        content: `修改意见：${data.feedback}`,
      });
    }
    
    // 2. 添加修复完成消息
    addMessage({
      ...createBaseMessage(),
      type: 'dimension_report',
      role: 'assistant',
      layer: data.layer,
      dimensionKey: data.dimension,
      dimensionName: dimensionName,
      content: data.newContent,
      streamingState: 'completed',
      wordCount: data.newContent.length,
    });
    
    console.log(`[ChatPanel] 维度 ${data.dimension} 修复完成，已添加消息`);
  }, [addMessage]);

  // Stable callbacks object using useMemo
  const callbacks = useMemo(() => ({
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
  }), [handleTextDelta, handleDimensionDelta, handleDimensionComplete, handleLayerStarted, handleLayerProgress, handleLayerCompleted, handlePause, handleDimensionRevised]);

  // Stable handler for SegmentedControl onChange
  const handleLayerChange = useCallback((layer: string) => {
    const layerNumber = LAYER_LABEL_MAP[layer];
    if (layerNumber !== undefined) {
      setCurrentLayer(layerNumber);
    }
  }, [setCurrentLayer]);

  // ✅ Use TaskController with stable callbacks
  const [taskState, { approve, reject, rollback }] = useTaskController(taskId, callbacks);

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
        console.log('[ChatPanel] Cleaned up typing timeout');
      }
    };
  }, []);

  // ✅ 新增：从 TaskController 同步状态到 Context
  useEffect(() => {
    if (!taskId) return;

    // 直接将 taskState 同步到 Context
    // Controller 只负责数据搬运,不做任何业务逻辑判断
    syncBackendState(taskState);

    console.log('[ChatPanel] Synced backend state:', {
      taskId,
      taskState,
    });
  }, [taskId, taskState, syncBackendState]);

  // Determine if input should be disabled
  const inputDisabled = isInputDisabled(status);

  // 审查状态: 状态驱动，由后端同步 (isPaused, pendingReviewLayer)
  // 不再依赖 messages 中的 ReviewInteractionMessage
  const hasPendingReview = isPaused && pendingReviewLayer !== null;

  // Review handlers - use TaskController actions
  // 状态驱动: 审查状态由后端同步 (isPaused, pendingReviewLayer)
  const handleReviewApprove = useCallback(async () => {
    try {
      await approve();
      addMessage(createSystemMessage('✅ 已批准，继续执行下一层...'));
      // 状态会通过 TaskController 轮询自动同步
    } catch (error: any) {
      addMessage(createErrorMessage(`批准失败: ${error.message || '未知错误'}`));
    }
  }, [approve, addMessage]);

  const handleReviewReject = useCallback(async (feedback: string, dimensions?: string[]) => {
    try {
      addMessage({
        ...createBaseMessage('user'),
        type: 'text',
        content: `📝 修改请求：${feedback}${dimensions ? ` (维度: ${dimensions.map(d => getDimensionName(d)).join(', ')})` : ''}`,
      });
      addMessage(createSystemMessage('🔄 正在根据反馈修复规划内容...'));
      await reject(feedback, dimensions);
      // 状态会通过 TaskController 轮询自动同步
    } catch (error: any) {
      addMessage(createErrorMessage(`驳回失败: ${error.message || '未知错误'}`));
    }
  }, [reject, addMessage]);

  const handleRollback = useCallback(async (checkpointId: string) => {
    if (!confirm('确定要回退吗？之后的内容将被删除。')) return;

    try {
      await rollback(checkpointId);
      addMessage(createSystemMessage(`↩️ 已回退到检查点: ${checkpointId}`));
      // 状态会通过 TaskController 轮询自动同步
    } catch (error: any) {
      addMessage(createErrorMessage(`回退失败: ${error.message || '未知错误'}`));
    }
  }, [rollback, addMessage]);

  // Handler: Start planning from form submission
  const handleStartPlanning = useCallback(async () => {
    if (!villageFormData) return;

    logger.chatPanel.info('点击"开始规划"按钮', { projectName: villageFormData.projectName });

    try {
      setIsPlanning(true);

      // Use uploaded file content or generate default
      const villageData = uploadedFileContent || `# 村庄现状数据（示例）

## 基本信息
- 村庄名称：${villageFormData.projectName}
- 地理位置：中国某省某市某县
- 人口规模：约1000人
- 土地面积：约5000亩

## 产业现状
- 主要产业：农业、手工业
- 经济水平：中等偏下
`;

      await startPlanning({
        projectName: villageFormData.projectName,
        villageData,
        taskDescription: villageFormData.taskDescription || PLANNING_DEFAULTS.defaultTask,
        constraints: villageFormData.constraints || PLANNING_DEFAULTS.defaultConstraints,
        enableReview: PLANNING_DEFAULTS.enableReview,
        stepMode: PLANNING_DEFAULTS.stepMode,
        streamMode: PLANNING_DEFAULTS.streamMode,
      });
      logger.chatPanel.info('规划启动成功', { status: 'planning' });
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      logger.chatPanel.error('规划启动失败', { error: errorMessage });
      console.error('[ChatPanel] Failed to start planning:', error);

      // Detect rate limit errors
      if (errorMessage.includes('过于频繁') || (error instanceof Error && 'status' in error && (error as any).status === 429)) {
        setRateLimitError({ projectName: villageFormData.projectName });
      }

      addMessage(createErrorMessage(`启动规划失败: ${errorMessage}`));
    } finally {
      setIsPlanning(false);
    }
  }, [villageFormData, uploadedFileContent, startPlanning, addMessage]);

  // Handler: Reset rate limit for a project
  const handleResetRateLimit = useCallback(async (projectName: string) => {
    try {
      logger.chatPanel.info(`Resetting rate limit for project: ${projectName}`);
      await planningApi.resetProject(projectName);
      setRateLimitError(null);
      addMessage(createSystemMessage(`✅ 已重置项目 "${projectName}" 的限流状态，请重试`));
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      logger.chatPanel.error('Failed to reset rate limit', { error: errorMessage });
      addMessage(createErrorMessage(`重置限流失败: ${errorMessage}`));
    }
  }, [addMessage]);

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
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'user',
        type: 'text',
        content: userText,
      });

      // 判断是否为批准指令
      if (userText === '批准' || userText === '继续' || userText.toLowerCase() === 'approve') {
        try {
          addMessage(createSystemMessage('✅ 已批准，继续执行下一层...'));
          await approve();
        } catch (error: any) {
          addMessage(createErrorMessage(`批准失败: ${error.message || '未知错误'}`));
        }
        return;
      }

      // 驳回/修改请求 - 通过聊天框发送反馈
      try {
        const dimensionInfo = dimensionsToSubmit 
          ? ` (维度: ${dimensionsToSubmit.map(d => getDimensionName(d)).join(', ')})` 
          : '';
        addMessage(createSystemMessage(`🔄 正在根据反馈修复规划内容${dimensionsToSubmit ? '...' : '（自动识别维度）...'} `));
        await reject(userText, dimensionsToSubmit);
      } catch (error: any) {
        addMessage(createErrorMessage(`修复失败: ${error.message || '未知错误'}`));
      }
      return;
    }

    // Normal chat message
    addMessage({
      id: `msg-${Date.now()}`,
      timestamp: new Date(),
      role: 'user',
      type: 'text',
      content: userText,
    });

    setIsTyping(true);

    // TODO: Process message with AI
    // ✅ FIXED: Store timeout ID for cleanup
    typingTimeoutRef.current = setTimeout(() => {
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
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
      
      for (const { file, response } of results) {
        allContents.push(response.content);

        addMessage({
          ...createBaseMessage('user'),
          type: 'file',
          filename: file.name,
          fileContent: response.content,
          fileSize: file.size,
          encoding: response.encoding,
        } as FileMessage);

        const encodingInfo = response.encoding ? `\n编码: ${response.encoding}` : '';
        addMessage(createSystemMessage(
          `✅ 文件 "${file.name}" 已上传${encodingInfo}\n内容长度: ${response.content.length} 字符`
        ));
      }

      // 存储合并后的内容
      const combinedContent = allContents.join('\n\n---\n\n');
      setUploadedFileContent(combinedContent);

      if (results.length > 1) {
        addMessage(createSystemMessage(
          `✅ 已上传 ${results.length} 个文件，总内容长度: ${combinedContent.length} 字符\n点击 "开始规划" 按钮启动任务`
        ));
      } else {
        addMessage(createSystemMessage(
          `点击 "开始规划" 按钮启动任务`
        ));
      }

      e.target.value = '';
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      addMessage(createErrorMessage(`❌ 文件上传失败: ${errorMessage}`));
    } finally {
      setIsUploadingFile(false);
    }
  };

  // Default village data template
  const getDefaultVillageData = useCallback((projectName: string) => `# 村庄现状数据（示例）

## 基本信息
- 村庄名称：${projectName}
- 地理位置：中国某省某市某县
- 人口规模：约1000人
- 土地面积：约5000亩

## 产业现状
- 主要产业：农业、手工业
- 经济水平：中等偏下
`, []);

  // Action handler
  const handleAction = useCallback(async (action: ActionButton, message: Message) => {
    if (action.onClick) {
      await action.onClick();
      return;
    }

    switch (action.action) {
      case 'approve':
        // Handle start planning button from file upload
        if (action.id === 'start_planning' && villageFormData) {
          const fileMessages = messages.filter((msg: Message) => msg.type === 'file');
          let villageData: string;

          if (fileMessages.length > 0) {
            villageData = fileMessages
              .map((msg: Message) => (msg as FileMessage).fileContent)
              .join('\n\n---\n\n');

            if (villageData.length < MIN_FILE_CONTENT_LENGTH) {
              addMessage(createSystemMessage(
                `⚠️ 上传的文件内容过短！\n\n要求：至少需要 ${MIN_FILE_CONTENT_LENGTH} 个字符\n当前：${villageData.length} 个字符\n\n请确保文件包含完整的村庄现状数据。`,
                'error'
              ));
              return;
            }
          } else {
            villageData = getDefaultVillageData(villageFormData.projectName);
          }

          try {
            await startPlanning({
              projectName: villageFormData.projectName || '未命名村庄',
              villageData,
              taskDescription: villageFormData.taskDescription || PLANNING_DEFAULTS.defaultTask,
              constraints: villageFormData.constraints || PLANNING_DEFAULTS.defaultConstraints,
              enableReview: PLANNING_DEFAULTS.enableReview,
              stepMode: PLANNING_DEFAULTS.stepMode,
              streamMode: PLANNING_DEFAULTS.streamMode,
            });
          } catch (error: unknown) {
            const errorMessage = error instanceof Error ? error.message : '未知错误';
            addMessage(createErrorMessage(`❌ 规划启动失败: ${errorMessage}`));
          }
        } else if (action.id === 'approve_quick') {
          await handleReviewApprove();
        } else {
          addMessage({
            ...createBaseMessage('user'),
            type: 'text',
            content: '批准继续',
          });
        }
        break;

      case 'reject':
        addMessage({
          ...createBaseMessage('user'),
          type: 'text',
          content: '请求修改',
        });
        break;

      case 'view':
        // View actions handled by component-specific handlers
        break;
    }
  }, [messages, villageFormData, startPlanning, handleReviewApprove, addMessage, getDefaultVillageData]);

  // Handler: 查看完整报告（移除侧边栏功能，保留日志）
  const handleOpenInSidebar = useCallback((layer: number) => {
    const layerId = getLayerId(layer);
    if (layerId) {
      console.log('[ChatPanel] Open layer report in viewer:', layerId);
      showViewer();
    }
  }, [showViewer]);

  return (
    <div className={`flex flex-col h-full bg-[#0f0f0f] ${className}`}>
      {/* Top: Progress bar and indicators - Gemini dark style */}
      {(status === 'collecting' || status === 'planning' || status === 'paused' || status === 'revising') && (
        <div className="flex-shrink-0 border-b border-[#2d2d2d] bg-[#1a1a1a] p-4">
          {/* Progress bar - Dark card style */}
          {progressMessages.length > 0 && (
            <div className="mb-3 bg-[#1e1e1e] rounded-xl p-4 border border-[#2d2d2d] animate-fade-in">
              {progressMessages.filter(msg => isProgressMessage(msg)).map(msg => (
                  <div key={msg.id}>
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm font-semibold text-zinc-200 flex items-center gap-2">
                        <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
                        {msg.content}
                      </span>
                      <span className="text-sm font-bold text-green-400">{msg.progress}%</span>
                    </div>
                    <div className="w-full bg-[#2d2d2d] rounded-full h-2 overflow-hidden">
                      <div
                        className="bg-gradient-to-r from-green-500 to-green-400 h-2 rounded-full transition-all duration-300"
                        style={{ width: `${msg.progress}%` }}
                      />
                    </div>
                    {msg.currentLayer && (
                      <div className="text-xs text-zinc-400 mt-2 font-medium flex items-center gap-1">
                        <FontAwesomeIcon icon={faLayerGroup} className="text-green-400" style={{ width: '12px', height: '12px' }} />
                        当前层级: {msg.currentLayer}
                      </div>
                    )}
                  </div>
              ))}
            </div>
          )}

          {/* Status badge - Gemini style */}
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium ${
              status === 'collecting' || status === 'planning' ? 'bg-blue-500/15 text-blue-400 border border-blue-500/30' :
              status === 'paused' ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30' :
              status === 'revising' ? 'bg-orange-500/15 text-orange-400 border border-orange-500/30' :
              status === 'completed' ? 'bg-green-500/15 text-green-400 border border-green-500/30' :
              status === 'failed' ? 'bg-red-500/15 text-red-400 border border-red-500/30' :
              'bg-zinc-700/50 text-zinc-300 border border-zinc-600'
            }`}>
              <span>
                {status === 'collecting' || status === 'planning' ? '🔄' :
                 status === 'paused' ? '⏸️' :
                 status === 'revising' ? '🔧' :
                 status === 'completed' ? '✅' :
                 status === 'failed' ? '❌' : '💬'}
              </span>
              {status === 'collecting' || status === 'planning' ? '执行中' :
               status === 'paused' ? '等待审查' :
               status === 'revising' ? '修复中' :
               status === 'completed' ? '已完成' :
               status === 'failed' ? '失败' : '就绪'}
            </span>

            {currentLayer && (
              <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/30">
                <FontAwesomeIcon icon={faLayerGroup} style={{ width: '12px', height: '12px' }} />
                Layer {currentLayer}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Middle: Message list - Gemini dark style */}
      <div className="flex-1 overflow-y-auto p-4 bg-gradient-radial">
        <div className="max-w-4xl mx-auto">
          {/* Layer Segmented Control - shown during planning/paused */}
          {(status === 'planning' || status === 'paused') && (
            <SegmentedControl
              options={LAYER_OPTIONS_ARRAY}
              value={currentLayer ? LAYER_VALUE_MAP[currentLayer] : LAYER_OPTIONS_ARRAY[0]}
              onChange={handleLayerChange}
              className="mb-4"
            />
          )}

          <MessageList
            messages={messages}
            isTyping={isTyping}
            onAction={handleAction}
            onOpenInSidebar={handleOpenInSidebar}
            onViewLayerDetails={(layer) => {
              const layerId = getLayerId(layer);
              if (layerId) {
                console.log('[ChatPanel] View layer details:', layerId);
                showViewer();
              }
            }}
            onToggleAllDimensions={(layer, expand) => {
              // This would expand/collapse all dimensions in the viewer
              console.log('[ChatPanel] Toggle all dimensions for layer', layer, expand);
              // TODO: Implement expand/collapse all in LayerReportViewer
            }}
            currentLayer={taskState.current_layer ?? undefined}
            dimensionContents={dimensionContents}  // NEW: 传递实时维度内容（解决并行更新竞态）
          />
          <div ref={messagesEndRef} />
        </div>

        {/* Jump to bottom button - Gemini style */}
        {showScrollButton && (
          <button
            onClick={() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })}
            className="fixed bottom-28 right-8 bg-[#2d2d2d] text-zinc-300 border border-[#3f3f46] p-3 rounded-full shadow-lg hover:bg-[#3f3f46] hover:text-white transition-all z-50"
            title="跳转到底部"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
          </button>
        )}
      </div>

      {/* 审查功能已通过 ReviewInteractionMessage 组件嵌入在 MessageList 中 */}
      {/* 不需要额外的审查面板 */}

      {/* Bottom: Input area - Gemini dark style */}
      <div className="border-t border-[#2d2d2d] bg-[#1a1a1a] p-4">
        <div className="max-w-3xl mx-auto">
          {/* Rate limit warning */}
          {rateLimitError && (
            <div className="mb-3 px-4 py-3 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-xl">⚠️</span>
                <div>
                  <div className="font-semibold text-amber-400">请求过于频繁</div>
                  <div className="text-sm text-amber-300/70">
                    项目 &quot;{rateLimitError.projectName}&quot; 触发了速率限制
                  </div>
                </div>
              </div>
              <button
                className="px-4 py-2 bg-[#2d2d2d] border border-amber-500/30 text-amber-400 rounded-lg text-sm font-medium hover:bg-amber-500/20 transition-colors"
                onClick={() => handleResetRateLimit(rateLimitError.projectName)}
              >
                🔄 重置限制
              </button>
            </div>
          )}

          {/* Planning ready indicator */}
          {status === 'collecting' && villageFormData && !taskId && (
            <div className="mb-3 px-4 py-3 bg-green-500/10 border border-green-500/30 rounded-xl flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-xl">📋</span>
                <div>
                  <div className="font-semibold text-green-400">规划任务已准备</div>
                  <div className="text-sm text-green-300/70">
                    村庄：{villageFormData.projectName}
                  </div>
                </div>
              </div>
              <button
                className="px-5 py-2.5 bg-gradient-to-r from-green-600 to-green-500 text-white rounded-lg font-medium hover:from-green-500 hover:to-green-400 transition-all shadow-lg shadow-green-500/20 disabled:opacity-50"
                onClick={handleStartPlanning}
                disabled={isPlanning}
              >
                {isPlanning ? (
                  <span className="flex items-center gap-2">
                    <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    启动中...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    🚀 开始规划
                  </span>
                )}
              </button>
            </div>
          )}

          {/* Review Panel - 状态驱动，基于 isPaused 和 pendingReviewLayer */}
          {isPaused && pendingReviewLayer && (
            <ReviewPanel
              layer={pendingReviewLayer}
              onApprove={handleReviewApprove}
              isSubmitting={false}
            />
          )}

          {/* Input area: file upload and text input */}
          {/* 维度选择器 - 仅在审查状态下显示 */}
          {isPaused && pendingReviewLayer && (
            <div className="mb-2">
              <DimensionSelector
                layer={pendingReviewLayer}
                selectedDimensions={selectedDimensions}
                onChange={setSelectedDimensions}
                disabled={isTyping}
              />
            </div>
          )}

          {/* Input area - Gemini style rounded container */}
          <div className="flex items-end gap-3 p-2 bg-[#242424] rounded-2xl border border-[#3f3f46] focus-within:border-green-500/50 focus-within:ring-2 focus-within:ring-green-500/10 transition-all">
            {/* File upload button */}
            <label className={`flex-shrink-0 p-2 rounded-lg transition-colors cursor-pointer ${
              inputDisabled || isTyping || isUploadingFile
                ? 'text-zinc-600 cursor-not-allowed'
                : 'text-zinc-400 hover:text-green-400 hover:bg-[#2d2d2d]'
            }`}>
              <input
                type="file"
                multiple
                accept={FILE_ACCEPT}
                onChange={handleFileSelect}
                disabled={inputDisabled || isTyping || isUploadingFile}
                className="hidden"
              />
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
            </label>

            {/* Text input */}
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
                  ? `请输入修改意见，或输入"批准"继续...`
                  : status === 'planning' || status === 'collecting'
                    ? '规划进行中...'
                    : '输入消息... (Enter 发送, Shift+Enter 换行)'
              }
              className="flex-1 bg-transparent text-white placeholder-zinc-500 resize-none py-2 focus:outline-none text-sm leading-relaxed max-h-32"
              rows={1}
              style={{ minHeight: '24px' }}
            />

            {/* Send button */}
            <button
              onClick={handleSendMessage}
              disabled={inputDisabled || isTyping || !inputText.trim() || isUploadingFile}
              className={`flex-shrink-0 p-2 rounded-lg transition-all ${
                inputDisabled || isTyping || !inputText.trim() || isUploadingFile
                  ? 'text-zinc-600 cursor-not-allowed'
                  : 'text-green-400 hover:bg-green-500/20 hover:text-green-300'
              }`}
            >
              {isUploadingFile || isTyping ? (
                <svg className="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

