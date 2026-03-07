'use client';

/**
 * ChatPanel - Unified chat interface integrating messaging and progress display
 * Refactored to use TaskController for state management (REST polling + SSE for text only)
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
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
    // 🔧 新增：同步消息到后端（用于延迟存储）
    syncMessageToBackend,
  } = useUnifiedPlanningContext();

  const [inputText, setInputText] = useState('');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [uploadedFileContent, setUploadedFileContent] = useState<string | null>(null);
  const [stepMode, setStepMode] = useState<boolean>(PLANNING_DEFAULTS.stepMode);
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

    // 更新消息状态为完成（如果消息存在）
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
      const wordCount = Object.values(dimensionReports).reduce((sum, content) => sum + content.length, 0);
      
      setMessages(prev => {
        const updated = prev.map(msg => {
          if (msg.id === layerReportId && msg.type === 'layer_completed') {
            // 🔧 移除 _pendingStorage 标记，更新完整数据
            const { _pendingStorage, ...rest } = msg as any;
            return {
              ...rest,
              content: reportContent,
              fullReportContent: reportContent,
              dimensionReports: dimensionReports,
              summary: {
                word_count: wordCount as number,
                key_points: rest.summary?.key_points || [],
                dimension_count: Object.keys(dimensionReports).length,
              },
            };
          }
          return msg;
        });
        
        // 🔧 存储完整数据到数据库
        const updatedMsg = updated.find(m => m.id === layerReportId);
        if (updatedMsg) {
          syncMessageToBackend(updatedMsg);
          console.log(`[ChatPanel] Synced completed layer_report_${layer} to backend`);
        }
        
        return updated;
      });
    }
  }, [messages, addMessage, setMessages, showViewer, syncMessageToBackend]);

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
        // 🔧 标记为延迟存储，等待 handleLayerCompleted 完成后再存储
        _pendingStorage: true,
      });
    }

    // 🔧 修复：添加层级开始提示消息前检查是否已存在
    // 使用 currentLayer 属性（字符串类型）或内容匹配来检查
    const layerProgressContent = `🔄 正在执行 Layer ${layer}:`;
    const hasProgressMsg = messages.some(m => 
      m.type === 'progress' && m.content.startsWith(layerProgressContent)
    );
    
    if (!hasProgressMsg) {
      addMessage({
        ...createBaseMessage(),
        type: 'progress',
        role: 'assistant',
        content: `🔄 正在执行 Layer ${layer}: ${layerLabels[layer] || layerName}...`,
        progress: 0,
      } as ProgressMessage);
    }
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
        stepMode,
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
  }, [villageFormData, uploadedFileContent, startPlanning, addMessage, stepMode]);

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
              stepMode,
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
  }, [messages, villageFormData, startPlanning, handleReviewApprove, addMessage, getDefaultVillageData, stepMode]);

  // Handler: 查看完整报告（移除侧边栏功能，保留日志）
  const handleOpenInSidebar = useCallback((layer: number) => {
    const layerId = getLayerId(layer);
    if (layerId) {
      console.log('[ChatPanel] Open layer report in viewer:', layerId);
      showViewer();
    }
  }, [showViewer]);

  return (
    <div className={`flex flex-col h-full bg-[#F9FBF9] ${className}`}>
      {/* Top: Status indicators only - Card-style design */}
      {(status === 'collecting' || status === 'planning' || status === 'paused' || status === 'revising') && (
        <div className="flex-shrink-0 border-b border-gray-200 bg-white p-3 shadow-sm">
          <div className="max-w-6xl mx-auto">
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
        </div>
      )}

      {/* Middle: Message list - Centered container + max width */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-6xl mx-auto">
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

          {/* Review Panel - 状态驱动 */}
          {isPaused && pendingReviewLayer && (
            <ReviewPanel
              layer={pendingReviewLayer}
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
          <p className="text-center text-xs text-gray-400 mt-2">
            Enter 发送 · Shift+Enter 换行
          </p>
        </div>
      </div>
    </div>
  );
}

