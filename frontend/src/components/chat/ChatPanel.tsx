'use client';

/**
 * ChatPanel - Unified chat interface integrating messaging and progress display
 * Refactored to use TaskController for state management (REST polling + SSE for text only)
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import { useUnifiedPlanningContext } from '@/contexts/UnifiedPlanningContext';
import { useStreamingRender } from '@/hooks/useStreamingRender';
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
import MessageList from './MessageList';
import ReviewPanel from './ReviewPanel';
import ProgressPanel from './ProgressPanel';
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
    setIsPaused,  // 🔧 新增：用于 SSE pause 事件更新
    setPendingReviewLayer,  // 🔧 新增：用于 SSE pause 事件更新
    // 层级完成状态
    completedLayers,
    // 进度面板状态
    progressPanelVisible,
    setProgressPanelVisible,
    dimensionProgress,
    executingDimensions,
    currentPhase,
    setCurrentLayerAndPhase,
    setDimensionStreaming,
    setDimensionCompleted,
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

  // ✅ NEW: Track layer report message creation state (fix React closure trap)
  // 使用 ref 而不是依赖 messages 状态，确保 handleLayerCompleted 能正确检测消息是否存在
  const layerReportCreatedRef = useRef<Record<number, boolean>>({});
  
  // ✅ NEW: Track layer progress message creation state
  // 用于避免在连续模式下重复创建进度消息
  const layerProgressCreatedRef = useRef<Record<number, boolean>>({});

  // ✅ NEW: Use useMemo to cache filtered messages (P1.4 performance optimization)
  const progressMessages = useMemo(() => {
    return messages.filter(m => m.type === 'progress');
  }, [messages]);

  // 维度内容缓存 (用于流式渲染)
  const [dimensionContents, setDimensionContents] = useState<Map<string, string>>(new Map());

  // 🔧 批处理渲染 Hook：减少高频事件导致的 React 重渲染压力
  const { addToken, completeDimension, flushBatch } = useStreamingRender(
    (dimensionKey: string, content: string, layer?: number) => {
      // 批处理回调：更新维度内容缓存
      setDimensionContents(prev => {
        // 🔧 FIX: 优先使用传入的 layer 参数，解决闭包陷阱问题
        const layerNum = layer !== undefined ? layer : (currentLayer || 1);
        const key = `${layerNum}_${dimensionKey}`;
        return new Map(prev).set(key, content);
      });
    },
    {
      batchSize: 10,     // 每 10 个事件批处理一次
      batchWindow: 50,   // 或 50ms 时间窗口
      debounceMs: 30,    // 防抖延迟 30ms（降低延迟）
    }
  );

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

  // 维度级流式回调
  // 🔧 使用批处理 Hook 减少高频事件的 React 重渲染压力
  const handleDimensionDelta = useCallback((
    dimensionKey: string,
    delta: string,
    accumulated: string,
    layer?: number
  ) => {
    const layerNum = layer || currentLayer || 1;

    // 🔧 FIX: 将 layerNum 传递给 addToken，解决闭包陷阱问题
    addToken(dimensionKey, delta, accumulated, layerNum);

    // 更新进度面板状态（低频操作，直接更新）
    setDimensionStreaming(layerNum, dimensionKey, getDimensionName(dimensionKey));
  }, [currentLayer, setDimensionStreaming, addToken]);

  const handleDimensionComplete = useCallback((
    dimensionKey: string,
    dimensionName: string,
    fullContent: string,
    layer?: number
  ) => {
    const layerNum = layer || currentLayer || 1;

    // 🔧 FIX: 将 layerNum 传递给 completeDimension，解决闭包陷阱问题
    completeDimension(dimensionKey, layerNum);

    // 更新维度内容缓存（使用完整内容覆盖）
    setDimensionContents(prev => {
      const key = `${layerNum}_${dimensionKey}`;
      return new Map(prev).set(key, fullContent);
    });

    // 更新消息状态为完成（如果消息存在）
    const messageId = `dimension_${layerNum}_${dimensionKey}`;
    setMessages(prev => prev.map(msg =>
      msg.id === messageId
        ? { ...msg, content: fullContent, wordCount: fullContent.length, streamingState: 'completed' as const }
        : msg
    ));

    // 更新进度面板状态：标记维度完成
    setDimensionCompleted(layerNum, dimensionKey, fullContent.length);

    console.log(`[ChatPanel] Dimension complete: ${dimensionKey} (${fullContent.length} chars)`);
  }, [setMessages, currentLayer, setDimensionCompleted]);

  const handleLayerProgress = useCallback((
    layer: number,
    completed: number,
    total: number
  ) => {
    // 可以更新进度条
    console.log(`[ChatPanel] Layer ${layer} progress: ${completed}/${total}`);
  }, []);

  // ✅ Signal-Fetch Pattern: 层级完成后的数据拉取函数
  const fetchLayerReportsFromBackend = useCallback(async (layer: number): Promise<{
    reports: Record<string, string>;
    reportContent: string;
  } | null> => {
    if (!taskId) {
      console.warn('[ChatPanel] No taskId, cannot fetch layer reports');
      return null;
    }
    
    // 🔧 新增：记录调用开始时间
    const startTime = Date.now();
    console.log(`[ChatPanel] 📡 REST API 调用开始: GET /layer/${layer}/reports, taskId=${taskId}`);
    
    try {
      const response = await planningApi.getLayerReports(taskId, layer);
      
      // 🔧 新增：记录调用耗时
      const elapsed = Date.now() - startTime;
      
      // ✅ 增强调试日志：追踪 REST API 返回数据的完整性
      const reportKeys = Object.keys(response.reports || {});
      const reportsWithContent = reportKeys.filter(k => response.reports[k] && response.reports[k].length > 0);
      
      console.log(`[ChatPanel] ✅ REST API 响应成功: Layer ${layer}, 耗时=${elapsed}ms`, {
        dimensionCount: response.stats.dimension_count,
        totalChars: response.stats.total_chars,
        completed: response.completed,
        reportKeysCount: reportKeys.length,
        reportsWithContentCount: reportsWithContent.length,
        reportKeys: reportKeys,
      });
      
      // ✅ 检查数据完整性
      if (reportsWithContent.length === 0) {
        console.warn(`[ChatPanel] ⚠️ REST API 返回的维度报告内容全为空！`);
      } else if (reportsWithContent.length < reportKeys.length) {
        console.warn(`[ChatPanel] ⚠️ REST API 返回的维度报告部分为空: ${reportKeys.length - reportsWithContent.length} 个维度`);
      }
      
      return {
        reports: response.reports,
        reportContent: response.report_content,
      };
    } catch (error) {
      console.error(`[ChatPanel] Failed to fetch layer ${layer} reports:`, error);
      return null;
    }
  }, [taskId]);

  const handleLayerCompleted = useCallback(async (
    layer: number,
    reportContent: string,
    dimensionReports: Record<string, string>
  ) => {
    // 🔧 强制刷新所有批处理事件，确保流式数据完整
    flushBatch();

    console.log(`[ChatPanel] Layer ${layer} completed signal received (SSE data)`, {
      reportLength: reportContent?.length || 0,
      dimensionCount: Object.keys(dimensionReports || {}).length,
    });
    
    // ✅ 调试日志：追踪 dimensionContents 当前状态
    const currentLayerContents: string[] = [];
    dimensionContents.forEach((content, key) => {
      const parts = key.split('_');
      if (parts.length >= 2) {
        const keyLayer = parseInt(parts[0], 10);
        if (keyLayer === layer) {
          currentLayerContents.push(`${key}: ${content.length} chars`);
        }
      }
    });
    console.log(`[ChatPanel] dimensionContents 中 Layer ${layer} 的数据:`, {
      count: currentLayerContents.length,
      details: currentLayerContents,
    });
    
    // ✅ Signal-Fetch Pattern: 优先从后端 REST API 获取完整数据
    let finalReports: Record<string, string> = { ...dimensionReports };
    let finalReportContent = reportContent;
    
    // 尝试从后端获取完整数据
    const backendData = await fetchLayerReportsFromBackend(layer);
    
    if (backendData && backendData.reports && Object.keys(backendData.reports).length > 0) {
      // 使用后端 REST API 返回的完整数据
      finalReports = backendData.reports;
      finalReportContent = backendData.reportContent;
      
      // ✅ 详细日志：追踪每个维度的内容长度
      console.log(`[ChatPanel] Using REST API data: ${Object.keys(finalReports).length} dimensions, ${finalReportContent.length} chars`);
      Object.entries(finalReports).forEach(([key, content]) => {
        console.log(`[ChatPanel]   - ${key}: ${content?.length || 0} chars`);
      });
    } else {
      // 回退：合并 SSE 数据和 dimensionContents（流式累积数据）
      console.log(`[ChatPanel] REST API failed, falling back to SSE + dimensionContents merge`);
      
      dimensionContents.forEach((content, key) => {
        const parts = key.split('_');
        if (parts.length >= 2) {
          const keyLayer = parseInt(parts[0], 10);
          const dimKey = parts.slice(1).join('_');
          
          if (keyLayer === layer && content && content.length > 0) {
            const sseContent = finalReports[dimKey] || '';
            if (content.length > sseContent.length) {
              finalReports[dimKey] = content;
            }
          }
        }
      });
      
      // 重新生成报告内容（如果 SSE 的 reportContent 为空或太短）
      const totalChars = Object.values(finalReports).reduce((sum, c) => sum + (c?.length || 0), 0);
      if (!reportContent || reportContent.length < totalChars * 0.5) {
        finalReportContent = Object.entries(finalReports)
          .map(([key, content]) => `## ${getDimensionName(key)}\n\n${content}`)
          .join('\n\n---\n\n');
      }
    }

    const finalWordCount = Object.values(finalReports).reduce((sum, c) => sum + (c?.length || 0), 0);

    // ✅ 调试日志：追踪最终数据的完整性
    const finalReportDetails = Object.entries(finalReports).map(([key, content]) => 
      `${key}: ${content?.length || 0} chars`
    );
    console.log(`[ChatPanel] Layer ${layer} 最终数据:`, {
      dimensionCount: Object.keys(finalReports).length,
      totalChars: finalWordCount,
      details: finalReportDetails,
    });

    // ✅ 更新层级完成状态
    setUILayerCompleted(layer, true);

    const layerReportId = `layer_report_${layer}`;

    // ✅ 关键修复：使用 ref 检查而不是 messages.some()，解决 React 闭包陷阱问题
    // handleLayerStarted 已创建空消息并设置 ref 标记
    const hasLayerReport = layerReportCreatedRef.current[layer] || false;
    
    console.log(`[ChatPanel] Layer ${layer} completed - hasLayerReport (ref): ${hasLayerReport}, messages.some: ${messages.some(m => m.id === layerReportId)}`);

    if (!hasLayerReport) {
      // 创建 LayerReportMessage（首次创建路径）
      const newMsg = {
        ...createBaseMessage('assistant'),
        id: layerReportId,
        type: 'layer_completed' as const,
        layer: layer,
        content: finalReportContent,
        summary: {
          word_count: finalWordCount as number,
          key_points: [],
          dimension_count: Object.keys(finalReports).length,
        },
        fullReportContent: finalReportContent,
        dimensionReports: finalReports,
        actions: [
          {
            id: 'view_details',
            label: '查看详情',
            action: 'view' as const,
            onClick: () => {
              showViewer();
            },
          },
        ],
      };
      
      addMessage(newMsg);
      
      // ✅ 关键修复：首次创建路径也需要显式调用 syncMessageToBackend
      // 虽然没有 _pendingStorage 标记，但为了确保存储成功，显式调用更可靠
      syncMessageToBackend(newMsg as any);
      console.log(`[ChatPanel] Created and synced layer_report_${layer} to backend (first creation), wordCount=${finalWordCount}`);
      
      // 更新 ref 标记
      layerReportCreatedRef.current[layer] = true;
    } else {
      // 更新现有消息（从 handleLayerStarted 创建的空消息更新为完整数据）
      setMessages(prev => {
        const updated = prev.map(msg => {
          if (msg.id === layerReportId && msg.type === 'layer_completed') {
            // ✅ 关键修复：移除 _pendingStorage 标记，确保数据被存储
            const { _pendingStorage, ...rest } = msg as any;
            return {
              ...rest,
              content: finalReportContent,
              fullReportContent: finalReportContent,
              dimensionReports: finalReports,
              summary: {
                word_count: finalWordCount as number,
                key_points: msg.summary?.key_points || [],
                dimension_count: Object.keys(finalReports).length,
              },
            };
          }
          return msg;
        });
        
        // 存储完整数据到数据库
        const updatedMsg = updated.find(m => m.id === layerReportId);
        if (updatedMsg) {
          // ✅ 关键修复：显式调用 syncMessageToBackend 存储完整数据
          syncMessageToBackend(updatedMsg);
          console.log(`[ChatPanel] Synced completed layer_report_${layer} to backend, wordCount=${finalWordCount}`);
        }
        
        return updated;
      });
    }
  }, [messages, addMessage, setMessages, showViewer, syncMessageToBackend, dimensionContents, fetchLayerReportsFromBackend, flushBatch]);

  // ✅ 新增：处理层级开始事件 - 创建空的 LayerReportMessage（预填充维度槽位）
  // 🔧 修复：使用函数式更新 + ref 双重检查，确保消息不会被重复创建或跳过
  const handleLayerStarted = useCallback((layer: number, layerName: string) => {
    console.log(`[ChatPanel] 🚀 handleLayerStarted 被调用: Layer ${layer}, layerName="${layerName}"`);

    // 🔧 更新当前层级和阶段（用于 ProgressPanel 显示）
    setCurrentLayerAndPhase(layer);

    const layerLabels: Record<number, string> = {
      1: '现状分析',
      2: '规划思路',
      3: '详细规划',
    };

    // 创建层级报告消息（预填充维度槽位，等待流式更新）
    const layerReportId = `layer_report_${layer}`;
    
    // 🔧 关键修复：使用函数式更新，在 setMessages 回调中检查消息是否存在
    // 这样避免了 React 状态闭包问题和 ref 过早设置的问题
    let messageCreated = false;
    
    setMessages(prev => {
      // 在回调中检查消息是否已存在
      const exists = prev.some(m => m.id === layerReportId);
      
      if (exists) {
        console.log(`[ChatPanel] Layer ${layer} 占位消息已存在，跳过创建`);
        return prev;  // 消息已存在，不做任何修改
      }
      
      // 创建新的占位消息
      const dimensionKeys = getDimensionsByLayer(layer);
      const emptyDimensionReports: Record<string, string> = {};
      dimensionKeys.forEach(key => {
        emptyDimensionReports[key] = '';  // 空字符串，等待流式填充
      });
      
      console.log(`[ChatPanel] ✅ 创建 Layer ${layer} 占位消息，${dimensionKeys.length} 个维度槽位`);
      messageCreated = true;
      
      // 更新 ref 标记
      layerReportCreatedRef.current[layer] = true;
      
      const newMsg = {
        ...createBaseMessage('assistant'),
        id: layerReportId,
        type: 'layer_completed' as const,
        layer: layer,
        content: '',
        summary: {
          word_count: 0,
          key_points: [],
          dimension_count: dimensionKeys.length,
        },
        fullReportContent: '',
        dimensionReports: emptyDimensionReports,
        actions: [],
        _pendingStorage: true,
      } as any;
      
      return [...prev, newMsg];
    });

    // 🔧 修复：添加层级开始提示消息（使用函数式更新避免闭包问题）
    setMessages(prev => {
      const progressId = `progress_layer_${layer}`;
      const hasProgress = prev.some(m => m.id === progressId && m.type === 'progress');
      
      if (hasProgress) {
        return prev;
      }
      
      return [...prev, {
        ...createBaseMessage(),
        id: progressId,
        type: 'progress',
        role: 'assistant',
        content: `🔄 正在执行 Layer ${layer}: ${layerLabels[layer] || layerName}...`,
        progress: 0,
      } as ProgressMessage];
    });
    
    // 更新进度消息的 ref 标记
    layerProgressCreatedRef.current[layer] = true;
  }, [setMessages, setCurrentLayerAndPhase]);

  const handlePause = useCallback(async (
    layer: number,
    checkpointId: string
  ) => {
    console.log(`[ChatPanel] Pause event received`, { layer, checkpointId });
    
    // 🔧 修复：更新审查状态，使 ReviewPanel 能够正确显示
    setIsPaused(true);
    setPendingReviewLayer(layer);
    console.log(`[ChatPanel] Set isPaused=true, pendingReviewLayer=${layer}`);
    
    // 🔧 修复：添加新的 checkpoint 到状态，使 CheckpointMarker 能够正确显示
    if (checkpointId && layer > 0) {
      setCheckpoints(prev => {
        // 避免重复添加同一层的 checkpoint
        if (prev.some(cp => cp.layer === layer)) {
          return prev;
        }
        return [...prev, {
          checkpoint_id: checkpointId,
          layer: layer,
          timestamp: new Date().toISOString(),
          description: `Layer ${layer} checkpoint`
        }];
      });
    }
    
    // ✅ 兜底机制：从 REST API 获取最新层级数据
    // 当 SSE 的 layer_completed 事件丢失时，确保数据仍能被正确获取
    if (layer > 0) {
      console.log(`[ChatPanel] Pause fallback: fetching layer ${layer} data from REST API...`);
      try {
        const backendData = await fetchLayerReportsFromBackend(layer);
        if (backendData && backendData.reports && Object.keys(backendData.reports).length > 0) {
          console.log(`[ChatPanel] Pause fallback: got ${Object.keys(backendData.reports).length} dimensions, updating dimensionContents`);
          // 更新 dimensionContents 状态
          setDimensionContents(prev => {
            const newMap = new Map(prev);
            Object.entries(backendData.reports).forEach(([dimKey, content]) => {
              const key = `${layer}_${dimKey}`;
              const existing = newMap.get(key) || '';
              // 只有当 REST API 数据更长时才更新
              if (!existing || content.length > existing.length) {
                newMap.set(key, content);
              }
            });
            return newMap;
          });
        } else {
          console.log(`[ChatPanel] Pause fallback: REST API returned no data for layer ${layer}`);
        }
      } catch (error) {
        console.error(`[ChatPanel] Pause fallback: REST API error for layer ${layer}:`, error);
      }
    }
  }, [setCheckpoints, setIsPaused, setPendingReviewLayer, fetchLayerReportsFromBackend, setDimensionContents]);

  // 【新增】处理维度修复完成事件
  // ✅ Signal-Fetch 模式：SSE 事件只发送轻量信号，内容通过 REST API 获取
  const handleDimensionRevised = useCallback(async (data: {
    dimension: string;
    layer: number;
    timestamp: string;
    // 注意：SSE 事件不再携带 newContent，需要通过 REST API 获取
  }) => {
    console.log('[ChatPanel] Dimension revised signal received', data);
    
    const dimensionName = getDimensionName(data.dimension);
    const revisionId = `revision-${data.timestamp}-${data.dimension}`;  // 可预测 ID，便于去重
    
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
        id: revisionId,  // 使用可预测 ID
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
      syncMessageToBackend(dimensionReportMsg);  // ✅ 持久化修复后的维度报告
      
      // 更新维度内容到状态
      setDimensionContents(prev => {
        const newContents = new Map(prev);
        newContents.set(data.dimension, newContent);
        return newContents;
      });
      
      console.log(`[ChatPanel] 维度 ${data.dimension} 修复完成 (v${version})，已添加并持久化消息`);
      if (previousContent) {
        console.log(`[ChatPanel] 包含原始内容用于对比，原始长度: ${previousContent.length}`);
      }
    } catch (error) {
      console.error(`[ChatPanel] Failed to fetch dimension content:`, error);
      // 降级处理：添加错误提示消息
      addMessage(createSystemMessage(`获取维度 ${dimensionName} 内容失败，请刷新页面重试`, 'error'));
    }
  }, [addMessage, syncMessageToBackend, taskId, setDimensionContents]);

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

  // ✅ SSE 断线重连后的层级状态恢复机制
  // 当检测到 taskState.layer_X_completed 为 true 但 messages 中没有对应消息时
  // 主动从 REST API 获取数据并创建 LayerReportMessage
  // 🔧 修复：使用 messages 状态检查而非 ref，避免 ref 与实际状态不同步的问题
  useEffect(() => {
    if (!taskId || status === 'idle') return;

    const layersToCheck = [
      { layer: 1, completed: taskState.layer_1_completed },
      { layer: 2, completed: taskState.layer_2_completed },
      { layer: 3, completed: taskState.layer_3_completed },
    ];

    layersToCheck.forEach(async ({ layer, completed }) => {
      if (!completed) return;
      
      // 🔧 修复：在 messages 中检查是否存在对应的消息
      const layerReportId = `layer_report_${layer}`;
      const messageExists = messages.some(m => m.id === layerReportId);
      
      if (messageExists) {
        // 消息已存在，检查是否需要更新数据
        const existingMsg = messages.find(m => m.id === layerReportId);
        if (existingMsg && (existingMsg as any).fullReportContent && (existingMsg as any).fullReportContent.length > 0) {
          // 消息已有完整数据，无需恢复
          return;
        }
        // 消息存在但没有完整数据，需要获取数据
        console.log(`[ChatPanel] 🔄 SSE 断线恢复：Layer ${layer} 消息存在但数据不完整，补充数据...`);
      } else {
        console.log(`[ChatPanel] 🔄 SSE 断线恢复：Layer ${layer} 已完成但消息不存在，创建消息...`);
      }

      // 获取完整数据
      try {
        const backendData = await fetchLayerReportsFromBackend(layer);
        if (backendData && backendData.reports && Object.keys(backendData.reports).length > 0) {
          console.log(`[ChatPanel] 🔄 SSE 断线恢复：获取到 Layer ${layer} 数据，${Object.keys(backendData.reports).length} 个维度`);
          
          // 调用 handleLayerCompleted 来更新/创建消息
          // handleLayerCompleted 会自动处理消息存在/不存在的情况
          await handleLayerCompleted(layer, backendData.reportContent, backendData.reports);
        } else {
          console.warn(`[ChatPanel] 🔄 SSE 断线恢复：Layer ${layer} 数据为空`);
        }
      } catch (error) {
        console.error(`[ChatPanel] 🔄 SSE 断线恢复：获取 Layer ${layer} 数据失败:`, error);
      }
    });
  }, [
    taskId,
    status,
    taskState.layer_1_completed,
    taskState.layer_2_completed,
    taskState.layer_3_completed,
    messages,  // 🔧 添加 messages 依赖，确保能检测到消息状态
    handleLayerCompleted,
    fetchLayerReportsFromBackend,
  ]);

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

      // 合并上传的文件内容到 taskDescription
      let taskDescription = villageFormData.taskDescription || PLANNING_DEFAULTS.defaultTask;
      if (villageFormData.taskDescriptionFiles && villageFormData.taskDescriptionFiles.length > 0) {
        const fileContents = villageFormData.taskDescriptionFiles
          .map(f => `### 📎 文件：${f.filename}\n\n${f.content}`)
          .join('\n\n---\n\n');
        taskDescription = taskDescription
          ? `${taskDescription}\n\n---\n\n${fileContents}`
          : fileContents;
      }

      // 合并上传的文件内容到 constraints
      let constraints = villageFormData.constraints || PLANNING_DEFAULTS.defaultConstraints;
      if (villageFormData.constraintsFiles && villageFormData.constraintsFiles.length > 0) {
        const fileContents = villageFormData.constraintsFiles
          .map(f => `### 📎 文件：${f.filename}\n\n${f.content}`)
          .join('\n\n---\n\n');
        constraints = constraints
          ? `${constraints}\n\n---\n\n${fileContents}`
          : fileContents;
      }

      await startPlanning({
        projectName: villageFormData.projectName,
        villageData,
        taskDescription,
        constraints,
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
            checkpoints={checkpoints}
            onRollback={handleRollback}
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

          {/* Review Panel - 状态驱动 */}
          {isPaused && pendingReviewLayer && (
            <ReviewPanel
              layer={pendingReviewLayer}
              onApprove={handleReviewApprove}
              onReject={(feedback) => handleReviewReject(feedback, selectedDimensions.length > 0 ? selectedDimensions : undefined)}
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
          <p className="text-center text-xs text-gray-400 mt-2">
            Enter 发送 · Shift+Enter 换行
          </p>
        </div>
      </div>
    </div>
  );
}

