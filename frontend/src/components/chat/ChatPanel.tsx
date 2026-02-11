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
  ReviewInteractionMessage,
  FileMessage,
} from '@/types';
import {
  isReviewInteractionMessage,
  isProgressMessage,
} from '@/types';
import { planningApi, dataApi, fileApi } from '@/lib/api';
import { createBaseMessage, createSystemMessage, createErrorMessage } from '@/lib/utils';
import { logger } from '@/lib/logger';
import SegmentedControl from '@/components/ui/SegmentedControl';
import { useTaskController } from '@/controllers/TaskController';
import MessageList from './MessageList';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEdit, faLayerGroup } from '@fortawesome/free-solid-svg-icons';
import {
  LAYER_OPTIONS_ARRAY,
  LAYER_LABEL_MAP,
  LAYER_VALUE_MAP,
  getLayerId,
  MIN_FILE_CONTENT_LENGTH,
  FILE_ACCEPT,
  isInputDisabled,
} from '@/lib/constants';
import { useStreamingRender } from '@/hooks/useStreamingRender';

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
    showReviewPanel,
    setShowReviewPanel,
    checkpoints,
    setCheckpoints,
    currentLayer,
    setCurrentLayer,
    startPlanning,
    loadLayerContent,
    showViewer,
    setPendingReviewMessage,
  } = useUnifiedPlanningContext();

  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [uploadedFileContent, setUploadedFileContent] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

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

  // Create a layer completed message
  function createLayerCompletedMessage(
    layer: number,
    content: string,
    stats: { wordCount?: number } | null,
    dimensions: Array<{ name: string }> = []
  ) {
    return {
      ...createBaseMessage('assistant'),
      type: 'layer_completed' as const,
      layer,
      content,
      summary: {
        word_count: stats?.wordCount || content.length || 0,
        key_points: [],
        dimension_count: dimensions.length,
        dimension_names: dimensions.map(d => d.name),
      },
      fullReportContent: content,
      dimensionReports: undefined,
      actions: [
        { id: 'open_review', label: '查看详情', action: 'view' as const, variant: 'primary' as const },
        { id: 'approve_quick', label: '快速批准', action: 'approve' as const, variant: 'success' as const },
      ],
    };
  }

  // ✅ Stabilize all callbacks using useCallback to prevent TaskController restarts
  const handleLayerCompleted = useCallback(async (layer: number) => {
    console.log(`[ChatPanel] handleLayerCompleted called`, {
      layer,
      taskId,
      timestamp: new Date().toISOString(),
    });

    logger.chatPanel.info(`Layer ${layer} completed (detected via REST polling)`, { layer }, taskId);

    const layerId = getLayerId(layer);
    if (!layerId) {
      console.error('[ChatPanel] Invalid layer number:', layer);
      return;
    }

    const result = await loadLayerReportContent(layer);

    // Handle empty report content
    if (!result || result.trim().length === 0) {
      console.warn(`[ChatPanel] Layer ${layer} report content is empty, creating placeholder message`);
      addMessage({
        ...createBaseMessage('assistant'),
        type: 'layer_completed',
        layer,
        content: `✅ Layer ${layer} 已完成 (报告生成中...)`,
        summary: {
          word_count: 0,
          key_points: [],
          dimension_count: 0,
          dimension_names: [],
        },
        fullReportContent: '',
        dimensionReports: undefined,
        actions: [
          { id: 'view', label: '查看详情', action: 'view' as const, variant: 'primary' as const },
        ],
      });
      return;
    }

    // Parse report
    const { parseLayerReport, getReportStats } = await import('@/lib/layerReportParser');
    const dimensions = parseLayerReport(result);
    const stats = getReportStats(result);

    console.log(`[ChatPanel] Layer ${layer} report parsed:`, {
      dimensions: dimensions.length,
      wordCount: stats?.wordCount,
    });

    // Create and add message
    addMessage(createLayerCompletedMessage(layer,
      `✅ Layer ${layer} 已完成 (${stats?.wordCount || result.length}字, ${dimensions.length}个维度)`,
      stats,
      dimensions
    ));
  }, [taskId, loadLayerReportContent, addMessage]);

  const handlePause = useCallback((layer: number) => {
    logger.chatPanel.info(`Task paused at Layer ${layer} (detected via REST polling)`, { layer }, taskId);

    setMessages((prevMessages) => {
      // ✅ 改进：检查是否已存在【同层级】的审查消息（无论状态如何）
      // 这样可以防止状态抖动（如LLM失败后状态回滚）触发重复弹窗
      const hasAnyReviewForLayer = prevMessages.some(m =>
        m.type === 'review_interaction' && m.layer === layer
      );

      const hasPendingReviewForLayer = prevMessages.some(m =>
        m.type === 'review_interaction' && m.layer === layer && (m as ReviewInteractionMessage).reviewState === 'pending'
      );

      if (hasPendingReviewForLayer) {
        // 已有待处理的审查消息，跳过
        logger.chatPanel.debug(`[幂等性] 跳过 Layer ${layer} 的重复暂停信号（已存在待处理的审查消息）`);
        return prevMessages;
      }

      if (hasAnyReviewForLayer) {
        // 该层级已有过审查消息（但不是pending状态），可能是状态抖动
        // 仍然创建新的审查消息，但记录警告日志
        logger.chatPanel.warn(`[状态抖动检测] Layer ${layer} 已有过审查消息，但仍收到暂停信号（可能是LLM失败后状态回滚）`);
      }

      // Find the layer_completed message
      const lastLayerCompletedMsg = prevMessages.findLast(
        m => m.type === 'layer_completed' && m.layer === layer
      );

      if (lastLayerCompletedMsg) {
        // Update existing message
        return prevMessages.map(msg =>
          msg.id === lastLayerCompletedMsg.id
            ? { ...msg, actions: [
                { id: 'open_review', label: '查看详情', action: 'view' as const, variant: 'primary' as const },
                { id: 'approve_quick', label: '批准继续', action: 'approve' as const, variant: 'success' as const },
              ]}
            : msg
        );
      }

      // Fallback: create review message (should rarely happen)
      logger.chatPanel.warn(`No layer_completed message found for Layer ${layer}, creating review_interaction`);
      return [
        ...prevMessages,
        {
          ...createBaseMessage('assistant'),
          type: 'review_interaction',
          layer,
          content: '规划已暂停，请审查后决定下一步操作',
          reviewState: 'pending',
          availableActions: ['approve', 'reject', 'rollback'],
          enableDimensionSelection: true,
          enableRollback: true,
          feedbackPlaceholder: '请描述需要修改的内容（选填）',
          quickFeedbackOptions: [
            '内容结构需要优化，请重新组织',
            '部分内容不够详细，需要补充',
            '存在错误或不准确的信息',
          ],
        } as ReviewInteractionMessage,
      ];
    });

    loadCheckpoints();
  }, [taskId, loadCheckpoints, setMessages]);

  const handleComplete = useCallback(() => {
    logger.chatPanel.info('Task completed (detected via REST polling)', {}, taskId);
    setStatus('completed');
    const projectName = villageFormData?.projectName || '村庄';
    addMessage({
      ...createBaseMessage('assistant'),
      type: 'result',
      content: `🎉 规划任务已完成！\n\n村庄：${projectName}`,
      villageName: projectName,
      sessionId: taskId || '',
      layers: ['Layer 1', 'Layer 2', 'Layer 3'],
      resultUrl: `/village/${taskId}`,
    } as any);
  }, [taskId, villageFormData?.projectName, setStatus, addMessage]);

  const handleError = useCallback((error: string) => {
    logger.chatPanel.error('Task error (detected via REST polling)', { error }, taskId);
    setStatus('failed');
    addMessage(createErrorMessage(`执行失败: ${error}`));
  }, [taskId, setStatus, addMessage]);

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
  const handleDimensionDelta = useCallback((
    dimensionKey: string,
    dimensionName: string,
    layer: number,
    chunk: string,
    accumulated: string
  ) => {
    // 使用批处理渲染
    addToken(dimensionKey, chunk, accumulated);
  }, [addToken]);

  const handleDimensionComplete = useCallback((
    dimensionKey: string,
    dimensionName: string,
    layer: number,
    fullContent: string
  ) => {
    // 标记维度完成，刷新剩余内容
    completeDimension(dimensionKey);
    console.log(`[ChatPanel] Dimension complete: ${dimensionKey} (${fullContent.length} chars)`);
  }, [completeDimension]);

  const handleLayerProgress = useCallback((
    layer: number,
    completed: number,
    total: number
  ) => {
    // 可以更新进度条
    console.log(`[ChatPanel] Layer ${layer} progress: ${completed}/${total}`);
  }, []);

  // Stable callbacks object using useMemo
  const callbacks = useMemo(() => ({
    onLayerCompleted: handleLayerCompleted,
    onPause: handlePause,
    onComplete: handleComplete,
    onError: handleError,
    onTextDelta: handleTextDelta,
    // 维度级流式回调
    onDimensionDelta: handleDimensionDelta,
    onDimensionComplete: handleDimensionComplete,
    onLayerProgress: handleLayerProgress,
  }), [handleLayerCompleted, handlePause, handleComplete, handleError, handleTextDelta, handleDimensionDelta, handleDimensionComplete, handleLayerProgress]);

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

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Determine if input should be disabled
  const inputDisabled = isInputDisabled(status);

  // Derive pending review message from messages (single source of truth)
  const pendingReviewMessage = useMemo(() => {
    return messages.findLast(m =>
      isReviewInteractionMessage(m) && (m as ReviewInteractionMessage).reviewState === 'pending'
    ) as ReviewInteractionMessage | null;
  }, [messages]);

  // Check for pending review state
  const hasPendingReview = messages.some(m =>
    isReviewInteractionMessage(m) && (m as ReviewInteractionMessage).reviewState === 'pending'
  );

  // Review handlers - use TaskController actions
  const handleReviewApprove = useCallback(async () => {
    try {
      await approve();
      addMessage(createSystemMessage('✅ 已批准，继续执行下一层...'));
      setShowReviewPanel(false);
      setStatus('planning');
      setPendingReviewMessage(null);  // ✅ Clear pending review
    } catch (error: any) {
      addMessage(createErrorMessage(`批准失败: ${error.message || '未知错误'}`));
    }
  }, [approve, addMessage, setShowReviewPanel, setStatus, setPendingReviewMessage]);

  const handleReviewReject = useCallback(async (feedback: string, dimensions?: string[]) => {
    try {
      addMessage({
        ...createBaseMessage('user'),
        type: 'text',
        content: `📝 修改请求：${feedback}`,
      });
      addMessage(createSystemMessage('🔄 正在根据反馈修复规划内容...'));
      await reject(feedback);
      setShowReviewPanel(false);
      setStatus('revising');
    } catch (error: any) {
      addMessage(createErrorMessage(`驳回失败: ${error.message || '未知错误'}`));
    }
  }, [reject, addMessage, setShowReviewPanel, setStatus]);

  const handleRollback = useCallback(async (checkpointId: string) => {
    if (!confirm('确定要回退吗？之后的内容将被删除。')) return;

    try {
      await rollback(checkpointId);
      addMessage(createSystemMessage(`↩️ 已回退到检查点: ${checkpointId}`));
      setShowReviewPanel(false);
    } catch (error: any) {
      addMessage(createErrorMessage(`回退失败: ${error.message || '未知错误'}`));
    }
  }, [rollback, addMessage, setShowReviewPanel]);

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
        taskDescription: villageFormData.taskDescription || '制定村庄总体规划方案',
        constraints: villageFormData.constraints || '无特殊约束',
        enableReview: true,
        stepMode: true,
        streamMode: true,
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

  // Review interaction handlers for embedded message UI
  const handleReviewInteractionApprove = useCallback(async (message: ReviewInteractionMessage) => {
    if (!taskId) return;

    try {
      await planningApi.approveReview(taskId);

      // Update the review message state
      addMessage({
        ...message,
        reviewState: 'approved',
        submittedAt: new Date(),
        submittedBy: 'user',
        submissionType: 'approve',
      } as ReviewInteractionMessage);

      addMessage(createSystemMessage('✅ 已批准，继续执行下一层...'));
      setShowReviewPanel(false);
      setStatus('planning');
      setPendingReviewMessage(null);
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      addMessage(createErrorMessage(`批准失败: ${errorMessage}`));
    }
  }, [taskId, addMessage, setShowReviewPanel, setStatus, setPendingReviewMessage]);

  const handleReviewInteractionReject = useCallback(async (
    message: ReviewInteractionMessage,
    feedback: string,
    dimensions?: string[]
  ) => {
    if (!taskId) return;

    try {
      // Update the review message state
      addMessage({
        ...message,
        reviewState: 'rejected',
        submittedAt: new Date(),
        submittedBy: 'user',
        submissionType: 'reject',
        submissionFeedback: feedback,
        submissionDimensions: dimensions,
      } as ReviewInteractionMessage);

      addMessage(createSystemMessage('🔄 正在根据反馈修复规划内容...'));
      await planningApi.rejectReview(taskId, feedback, dimensions);
      setStatus('revising');
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      addMessage(createErrorMessage(`驳回失败: ${errorMessage}`));
    }
  }, [taskId, addMessage, setStatus]);

  const handleReviewInteractionRollback = useCallback(async (
    message: ReviewInteractionMessage,
    checkpointId: string
  ) => {
    if (!taskId) return;

    try {
      // Update the review message state
      addMessage({
        ...message,
        reviewState: 'rolled_back',
        submittedAt: new Date(),
        submittedBy: 'user',
        submissionType: 'rollback',
      } as ReviewInteractionMessage);

      await planningApi.rollbackCheckpoint(taskId, checkpointId);
      addMessage(createSystemMessage(`↩️ 已回退到检查点: ${checkpointId}`));
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      addMessage(createErrorMessage(`回退失败: ${errorMessage}`));
    }
  }, [taskId, addMessage]);

  // Send message handler - now supports review feedback
  const handleSendMessage = useCallback(async () => {
    const userText = inputText.trim();
    if (!userText) return;

    setInputText('');

    // Check if in review state
    if (hasPendingReview && pendingReviewMessage) {
      if (userText === '批准' || userText.toLowerCase() === 'approve') {
        await handleReviewInteractionApprove(pendingReviewMessage);
      } else {
        await handleReviewInteractionReject(pendingReviewMessage, userText);
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
    setTimeout(() => {
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant',
        type: 'text',
        content: `收到: ${userText}`,
      });
      setIsTyping(false);
    }, 500);
  }, [inputText, addMessage, hasPendingReview, pendingReviewMessage,
      handleReviewInteractionApprove, handleReviewInteractionReject]);

  // File selection handler
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setIsUploadingFile(true);
      const response = await fileApi.uploadFile(file);

      // Store file content for later use when starting planning
      setUploadedFileContent(response.content);

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
        `✅ 文件 "${file.name}" 已上传，点击 "开始规划" 按钮启动任务\n${encodingInfo}\n内容长度: ${response.content.length} 字符`
      ));

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
              taskDescription: villageFormData.taskDescription || '制定村庄总体规划方案',
              constraints: villageFormData.constraints || '无特殊约束',
              enableReview: true,
              stepMode: true,
              streamMode: true,
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
    <div className={`flex flex-col h-full bg-gray-50 ${className}`}>
      {/* Top: Progress bar and indicators - Card-style design */}
      {(status === 'collecting' || status === 'planning' || status === 'paused' || status === 'revising') && (
        <div className="flex-shrink-0 border-b border-gray-200 bg-white p-4 shadow-sm">
          {/* Progress bar - Card-style design */}
          {messages.filter(m => m.type === 'progress').length > 0 && (
            <div className="mb-3 bg-gray-50 rounded-xl p-4 shadow-sm border border-gray-200 animate-[fadeIn_0.3s_ease-in-out]">
              {messages.filter(m => m.type === 'progress').map(msg => (
                isProgressMessage(msg) && (
                  <div key={msg.id}>
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                        <span className="w-2 h-2 bg-green-600 rounded-full animate-pulse"></span>
                        {msg.content}
                      </span>
                      <span className="text-sm font-bold text-green-600">{msg.progress}%</span>
                    </div>
                    <div className="w-full bg-green-100 rounded-full h-2.5 overflow-hidden shadow-inner">
                      <div
                        className="bg-green-600 h-2.5 rounded-full transition-all duration-300 shadow-sm"
                        style={{ width: `${msg.progress}%` }}
                      />
                    </div>
                    {msg.currentLayer && (
                      <div className="text-xs text-gray-600 mt-2 font-medium flex items-center gap-1">
                        <FontAwesomeIcon icon={faLayerGroup} className="icon-xs text-green-600" />
                        当前层级: {msg.currentLayer}
                      </div>
                    )}
                  </div>
                )
              ))}
            </div>
          )}

          {/* Status badge - Colored + Icon + Shadow */}
          <div className="flex items-center gap-2">
            <span className={`status-badge ${
              status === 'collecting' || status === 'planning' ? 'status-badge-info' :
              status === 'paused' ? 'status-badge-warning' :
              status === 'revising' ? 'status-badge-warning' :
              status === 'completed' ? 'status-badge-success' :
              status === 'failed' ? 'status-badge-error' :
              'bg-gray-100 text-gray-700'
            }`}>
              <span className="text-base">
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
              <span className="status-badge status-badge-success">
                <FontAwesomeIcon icon={faLayerGroup} className="icon-xs" />
                Layer {currentLayer}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Middle: Message list - Centered container + max width */}
      <div className="flex-1 overflow-y-auto p-4">
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
            onReviewApprove={handleReviewInteractionApprove}
            onReviewReject={handleReviewInteractionReject}
            onReviewRollback={handleReviewInteractionRollback}
            reviewDisabled={status === 'revising'}
          />
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Bottom: Input area */}
      <div className="border-t bg-white p-4">
        <div className="max-w-3xl mx-auto">
          {/* Rate limit warning and reset button */}
          {rateLimitError && (
            <div className="mb-3 px-4 py-3 bg-warning bg-opacity-10 border border-warning rounded-lg flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-2xl">⚠️</span>
                <div>
                  <div className="font-semibold text-warning-800">请求过于频繁</div>
                  <div className="text-sm text-warning-700">
                    项目 "{rateLimitError.projectName}" 触发了速率限制
                  </div>
                </div>
              </div>
              <button
                className="btn btn-outline-warning btn-sm px-4"
                onClick={() => handleResetRateLimit(rateLimitError.projectName)}
              >
                <span className="me-1">🔄</span>
                重置限制
              </button>
            </div>
          )}

          {/* Planning ready indicator with Start Planning button */}
          {status === 'collecting' && villageFormData && !taskId && (
            <div className="mb-3 px-4 py-3 bg-success bg-opacity-10 border border-success rounded-lg flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-2xl">📋</span>
                <div>
                  <div className="font-semibold text-success-800">规划任务已准备</div>
                  <div className="text-sm text-success-700">
                    村庄：{villageFormData.projectName}
                  </div>
                </div>
              </div>
              <button
                className="btn btn-success px-4"
                onClick={handleStartPlanning}
                disabled={isPlanning}
              >
                {isPlanning ? (
                  <>
                    <span className="spinner-border spinner-border-sm me-2"></span>
                    启动中...
                  </>
                ) : (
                  <>
                    <span className="me-2">🚀</span>
                    开始规划
                  </>
                )}
              </button>
            </div>
          )}

          {/* Review mode indicator */}
          {hasPendingReview && pendingReviewMessage && (
            <div className="mb-2 px-3 py-1.5 bg-orange-50 border border-orange-200 rounded-lg flex items-center gap-2">
              <FontAwesomeIcon icon={faEdit} className="text-orange-500" />
              <span className="text-sm text-orange-700 font-medium">
                审查模式：输入修改意见后按 Enter 发送驳回，或输入 &quot;批准&quot; 继续
              </span>
            </div>
          )}

          {/* Input area: file upload and text input */}
          <div className="flex items-center gap-2">
            {/* File upload button (native) */}
            <input
              type="file"
              accept={FILE_ACCEPT}
              onChange={handleFileSelect}
              disabled={inputDisabled || isTyping || isUploadingFile}
              className="form-control form-control-sm"
              style={{ width: 'auto' }}
            />

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
                hasPendingReview && pendingReviewMessage
                  ? `请输入对 Layer ${pendingReviewMessage.layer} 的修改意见... (Enter 发送驳回，留空输入 "批准" 继续)`
                  : status === 'planning' || status === 'collecting'
                    ? '规划进行中...'
                    : '输入消息... (Enter 发送, Shift+Enter 换行)'
              }
              className={`form-control flex-1 ${
                hasPendingReview ? 'border-orange-400 border-2 shadow-orange-100' : ''
              }`}
              rows={1}
            />

            {/* Send button */}
            <button
              onClick={handleSendMessage}
              disabled={inputDisabled || isTyping || !inputText.trim() || isUploadingFile}
              className="btn btn-success"
            >
              {isUploadingFile ? '上传中...' : isTyping ? '发送中...' : '发送'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
