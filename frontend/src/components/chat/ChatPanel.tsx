'use client';

/**
 * ChatPanel - Unified chat interface integrating messaging and progress display
 * Refactored to use PlanningProvider for state management (SSE-based)
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import { usePlanningContext } from '@/providers/PlanningProvider';
import { useStreamingRender } from '@/hooks/useStreamingRender';
import { useThrottleCallback } from '@/hooks/useThrottleCallback';
import type { Message, FileMessage, ProgressMessage, Checkpoint } from '@/types';
import { planningApi, fileApi } from '@/lib/api';
import { createBaseMessage, createSystemMessage, createErrorMessage, getErrorMessage } from '@/lib/utils';
import { logger } from '@/lib/logger';
import SegmentedControl from '@/components/ui/SegmentedControl';
import MessageList from './MessageList';
import ReviewPanel from './ReviewPanel';
import ProgressPanel from './ProgressPanel';
import ToolStatusPanel from './ToolStatusPanel';
import DimensionSelector from './DimensionSelector';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faLayerGroup } from '@fortawesome/free-solid-svg-icons';
import { getDimensionName, getDimensionsByLayer } from '@/config/dimensions';
import { PLANNING_DEFAULTS } from '@/config/planning';
import {
  LAYER_OPTIONS_ARRAY,
  LAYER_LABEL_MAP,
  LAYER_VALUE_MAP,
  LAYER_IDS,
  getLayerId,
  MIN_SSE_DATA_CHARS,
  FILE_ACCEPT,
  isInputDisabled,
  getStatusBadge,
} from '@/lib/constants';

interface ChatPanelProps {
  className?: string;
  onOpenLayerSidebar?: (layer: number) => void;
}

export default function ChatPanel({ className = '', onOpenLayerSidebar }: ChatPanelProps) {
  const { state, dispatch, actions } = usePlanningContext();

  // Derive values from state
  const messages = state.messages;
  const status = state.status;
  const taskId = state.taskId;
  const villageFormData = state.villageFormData;
  const currentLayer = state.currentLayer;
  const isPaused = state.isPaused;
  const pendingReviewLayer = state.pendingReviewLayer;
  const progressPanelVisible = state.progressPanelVisible;
  const dimensionProgress = state.dimensionProgress;
  const executingDimensions = state.executingDimensions;
  const currentPhase = state.currentPhase;
  const completedLayers = useMemo(() => ({
    1: state.completedDimensions.layer1.length > 0,
    2: state.completedDimensions.layer2.length > 0,
    3: state.completedDimensions.layer3.length > 0,
  }), [state.completedDimensions]);
  const toolStatusMap = state.toolStatuses;

  const [inputText, setInputText] = useState('');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [isRollingBack, setIsRollingBack] = useState(false);
  const [uploadedFileContent, setUploadedFileContent] = useState<string | null>(null);
  const [stepMode, setStepMode] = useState<boolean>(PLANNING_DEFAULTS.stepMode);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Track typing timeout for cleanup
  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Track layer report message creation state
  const layerReportCreatedRef = useRef<Record<number, boolean>>({});

  // Track layer progress message creation state
  const layerProgressCreatedRef = useRef<Record<number, boolean>>({});

  // SSE connection state tracking ref
  const sseConnectedRef = useRef(false);

  // Debounce tracking for REST API calls
  const restoringLayersRef = useRef<Set<number>>(new Set());

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

  // Throttle setDimensionStreaming
  const throttledSetDimensionStreaming = useThrottleCallback(
    (layer: number, dimensionKey: string, dimensionName: string) => {
      dispatch({ type: 'SET_DIMENSION_STREAMING', layer, dimensionKey, dimensionName });
    },
    300
  );

  // Rate limit error tracking
  const [rateLimitError, setRateLimitError] = useState<{ projectName: string } | null>(null);

  // Tool status handlers (dispatch to PlanningProvider)
  const handleToolCall = useCallback((data: {
    toolName: string;
    toolDisplayName: string;
    description: string;
    estimatedTime?: number;
    stage?: string;
  }) => {
    dispatch({
      type: 'SET_TOOL_STATUS',
      toolName: data.toolName,
      status: {
        toolName: data.toolName,
        status: 'running',
        stage: data.stage,
        message: data.description,
      },
    });
  }, [dispatch]);

  const handleToolProgress = useCallback((data: {
    toolName: string;
    stage: string;
    progress: number;
    message: string;
  }) => {
    const existing = toolStatusMap[data.toolName];
    if (existing) {
      dispatch({
        type: 'SET_TOOL_STATUS',
        toolName: data.toolName,
        status: {
          ...existing,
          stage: data.stage,
          progress: data.progress,
          message: data.message,
        },
      });
    }
  }, [dispatch, toolStatusMap]);

  const handleToolResult = useCallback((data: {
    toolName: string;
    status: 'success' | 'error';
    summary: string;
    displayHints?: {
      primary_view?: 'text' | 'table' | 'map' | 'chart' | 'json';
      priority_fields?: string[];
    };
    dataPreview?: string;
  }) => {
    const existing = toolStatusMap[data.toolName];
    if (existing) {
      dispatch({
        type: 'SET_TOOL_STATUS',
        toolName: data.toolName,
        status: {
          ...existing,
          status: data.status,
          summary: data.summary,
        },
      });
    }
  }, [dispatch, toolStatusMap]);

  // Helper functions for message operations
  const addMessage = useCallback((message: Message) => {
    dispatch({ type: 'ADD_MESSAGE', message });
  }, [dispatch]);

  const setMessages = useCallback((messagesOrUpdater: Message[] | ((prev: Message[]) => Message[])) => {
    if (typeof messagesOrUpdater === 'function') {
      const newMessages = messagesOrUpdater(state.messages);
      dispatch({ type: 'SET_MESSAGES', messages: newMessages });
    } else {
      dispatch({ type: 'SET_MESSAGES', messages: messagesOrUpdater });
    }
  }, [dispatch, state.messages]);

  const showViewer = useCallback(() => {
    dispatch({ type: 'SET_VIEWER_VISIBLE', visible: true });
  }, [dispatch]);

  const syncMessageToBackend = useCallback((message: Message) => {
    // Handled by PlanningProvider when adding messages
    console.log('[ChatPanel] Message synced:', message.id);
  }, []);

  const startPlanning = actions.startPlanning;

  // Additional helper functions
  const setDimensionCompleted = useCallback((layer: number, dimensionKey: string, wordCount: number) => {
    dispatch({ type: 'SET_DIMENSION_COMPLETED', layer, dimensionKey, wordCount });
  }, [dispatch]);

  const setUILayerCompleted = useCallback((layer: number, completed: boolean) => {
    dispatch({ type: 'SET_LAYER_COMPLETED', layer, completed });
  }, [dispatch]);

  const setCurrentLayerAndPhase = useCallback((layer: number) => {
    dispatch({ type: 'SET_DIMENSION_STREAMING', layer, dimensionKey: '', dimensionName: '' });
  }, [dispatch]);

  const setProgressPanelVisible = useCallback((visible: boolean) => {
    // Not directly supported in PlanningProvider yet - placeholder
    console.log('[ChatPanel] setProgressPanelVisible:', visible);
  }, []);

  const setIsPaused = useCallback((paused: boolean) => {
    dispatch({ type: 'SET_PAUSED', paused });
  }, [dispatch]);

  const setPendingReviewLayer = useCallback((layer: number | null) => {
    dispatch({ type: 'SET_PENDING_REVIEW_LAYER', layer });
  }, [dispatch]);

  const setLayerReports = useCallback((reports: Partial<{
    analysis_reports: Record<string, string>;
    concept_reports: Record<string, string>;
    detail_reports: Record<string, string>;
    analysis_report_content: string;
    concept_report_content: string;
    detail_report_content: string;
  }>) => {
    const newReports: Partial<{
      layer1: Record<string, string>;
      layer2: Record<string, string>;
      layer3: Record<string, string>;
    }> = {};
    if (reports.analysis_reports) newReports.layer1 = reports.analysis_reports;
    if (reports.concept_reports) newReports.layer2 = reports.concept_reports;
    if (reports.detail_reports) newReports.layer3 = reports.detail_reports;
    dispatch({ type: 'SET_REPORTS', reports: newReports });
  }, [dispatch]);

  const setCheckpoints = useCallback((checkpointsOrUpdater: Checkpoint[] | ((prev: Checkpoint[]) => Checkpoint[])) => {
    if (typeof checkpointsOrUpdater === 'function') {
      const newCheckpoints = checkpointsOrUpdater(state.checkpoints);
      dispatch({ type: 'SET_CHECKPOINTS', checkpoints: newCheckpoints });
    } else {
      dispatch({ type: 'SET_CHECKPOINTS', checkpoints: checkpointsOrUpdater });
    }
  }, [dispatch, state.checkpoints]);

  const syncBackendState = useCallback((backendData: Partial<{
    status: string;
    previous_layer: number;
    current_layer: number;
    layer_1_completed: boolean;
    layer_2_completed: boolean;
    layer_3_completed: boolean;
    last_checkpoint_id: string;
    phase: string;
    version: number;
  }>) => {
    dispatch({ type: 'SYNC_BACKEND_STATE', backendData });
  }, [dispatch]);

  const showFileViewer = useCallback((file: FileMessage) => {
    dispatch({ type: 'SET_VIEWING_FILE', file });
  }, [dispatch]);

  // Derive taskState-like object for compatibility
  const taskState = useMemo(() => ({
    status: state.status,
    current_layer: state.currentLayer ?? undefined,
    previous_layer: undefined as number | undefined,
    layer_1_completed: completedLayers[1],
    layer_2_completed: completedLayers[2],
    layer_3_completed: completedLayers[3],
    pause_after_step: state.isPaused,
    last_checkpoint_id: state.selectedCheckpoint ?? undefined,
    execution_error: null,
    execution_complete: completedLayers[1] && completedLayers[2] && completedLayers[3],
    progress: null,
  }), [state, completedLayers]);

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

  // 维度级流式回调
  // 🔧 使用批处理 Hook + throttle 减少高频事件的 React 重渲染压力
  const handleDimensionDelta = useCallback(
    (dimensionKey: string, delta: string, accumulated: string, layer?: number) => {
      const layerNum = layer || currentLayer || 1;

      // 🔧 FIX: 将 layerNum 传递给 addToken，解决闭包陷阱问题
      addToken(dimensionKey, delta, accumulated, layerNum);

      // 🔧 throttle 更新进度面板状态，减少渲染频率
      throttledSetDimensionStreaming(layerNum, dimensionKey, getDimensionName(dimensionKey));
    },
    [currentLayer, throttledSetDimensionStreaming, addToken]
  );

  const handleDimensionComplete = useCallback(
    (dimensionKey: string, dimensionName: string, fullContent: string, layer?: number) => {
      const layerNum = layer || currentLayer || 1;

      // 🔧 FIX: 将 layerNum 传递给 completeDimension，解决闭包陷阱问题
      completeDimension(dimensionKey, layerNum);

      // 更新维度内容缓存（使用完整内容覆盖）
      setDimensionContents((prev) => {
        const key = `${layerNum}_${dimensionKey}`;
        return { ...prev, [key]: fullContent };
      });

      // 更新消息状态为完成（如果消息存在）
      const messageId = `dimension_${layerNum}_${dimensionKey}`;
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === messageId
            ? {
                ...msg,
                content: fullContent,
                wordCount: fullContent.length,
                streamingState: 'completed' as const,
              }
            : msg
        )
      );

      // 更新进度面板状态：标记维度完成
      setDimensionCompleted(layerNum, dimensionKey, fullContent.length);

      console.log(`[ChatPanel] Dimension complete: ${dimensionKey} (${fullContent.length} chars)`);
    },
    [setMessages, currentLayer, setDimensionCompleted, completeDimension]
  );

  const handleLayerProgress = useCallback((layer: number, completed: number, total: number) => {
    // 可以更新进度条
    console.log(`[ChatPanel] Layer ${layer} progress: ${completed}/${total}`);
  }, []);

  // ✅ Signal-Fetch Pattern: 层级完成后的数据拉取函数
  const fetchLayerReportsFromBackend = useCallback(
    async (
      layer: number
    ): Promise<{
      reports: Record<string, string>;
      reportContent: string;
    } | null> => {
      if (!taskId) {
        console.warn('[ChatPanel] No taskId, cannot fetch layer reports');
        return null;
      }

      // 🔧 新增：记录调用开始时间
      const startTime = Date.now();
      console.log(
        `[ChatPanel] 📡 REST API 调用开始: GET /layer/${layer}/reports, taskId=${taskId}`
      );

      try {
        const response = await planningApi.getLayerReports(taskId, layer);

        // 🔧 新增：记录调用耗时
        const elapsed = Date.now() - startTime;

        // ✅ 增强调试日志：追踪 REST API 返回数据的完整性
        const reportKeys = Object.keys(response.reports || {});
        const reportsWithContent = reportKeys.filter(
          (k) => response.reports[k] && response.reports[k].length > 0
        );

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
          console.warn(
            `[ChatPanel] ⚠️ REST API 返回的维度报告部分为空: ${reportKeys.length - reportsWithContent.length} 个维度`
          );
        }

        return {
          reports: response.reports,
          reportContent: response.report_content,
        };
      } catch (error) {
        console.error(`[ChatPanel] Failed to fetch layer ${layer} reports:`, error);
        return null;
      }
    },
    [taskId]
  );

  const handleLayerCompleted = useCallback(
    async (layer: number, reportContent: string, dimensionReports: Record<string, string>) => {
      // 🔧 强制刷新所有批处理事件，确保流式数据完整
      flushBatch();

      console.log(`[ChatPanel] Layer ${layer} completed signal received (SSE data)`, {
        reportLength: reportContent?.length || 0,
        dimensionCount: Object.keys(dimensionReports || {}).length,
      });

      // ✅ 调试日志：追踪 dimensionContents 当前状态
      const currentLayerContents: string[] = [];
      Object.entries(dimensionContents).forEach(([key, content]) => {
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

      // ✅ 优化：优先使用 SSE 携带的 dimension_reports 数据
      // SSE 已携带完整维度数据，避免 Signal-Fetch 模式的 REST API 延迟
      let finalReports: Record<string, string> = {};
      let finalReportContent = reportContent;

      // 优先检查 SSE 携带的维度数据是否完整
      const sseDataComplete = dimensionReports && Object.keys(dimensionReports).length > 0;
      const sseTotalChars = sseDataComplete
        ? Object.values(dimensionReports).reduce((sum, c) => sum + (c?.length || 0), 0)
        : 0;

      if (sseDataComplete && sseTotalChars > MIN_SSE_DATA_CHARS) {
        // SSE 数据完整，直接使用，无需 REST API 调用
        finalReports = dimensionReports;
        console.log(`[ChatPanel] Using SSE data directly: ${Object.keys(finalReports).length} dimensions, ${sseTotalChars} chars`);
        Object.entries(finalReports).forEach(([key, content]) => {
          console.log(`[ChatPanel]   - ${key}: ${content?.length || 0} chars`);
        });
      } else {
        // SSE 数据不完整，调用 REST API 作为兜底
        console.log(`[ChatPanel] SSE data incomplete, fetching from REST API...`);

        // 尝试从后端获取完整数据
        const backendData = await fetchLayerReportsFromBackend(layer);

        if (backendData && backendData.reports && Object.keys(backendData.reports).length > 0) {
          // 使用后端 REST API 返回的完整数据
          finalReports = backendData.reports;
          finalReportContent = backendData.reportContent;

          // ✅ 详细日志：追踪每个维度的内容长度
          console.log(
            `[ChatPanel] Using REST API data: ${Object.keys(finalReports).length} dimensions, ${finalReportContent?.length || 0} chars`
          );
          Object.entries(finalReports).forEach(([key, content]) => {
            console.log(`[ChatPanel]   - ${key}: ${content?.length || 0} chars`);
          });
        } else {
          // 最后回退：合并 dimensionContents（流式累积数据）
          console.log(`[ChatPanel] REST API failed, falling back to dimensionContents merge`);

          Object.entries(dimensionContents).forEach(([key, content]) => {
            const parts = key.split('_');
            if (parts.length >= 2) {
              const keyLayer = parseInt(parts[0], 10);
              const dimKey = parts.slice(1).join('_');

              if (keyLayer === layer && content && content.length > 0) {
                const existingContent = finalReports[dimKey] || '';
                if (content.length > existingContent.length) {
                  finalReports[dimKey] = content;
                }
              }
            }
          });

          // 重新生成报告内容
          const fallbackTotalChars = Object.values(finalReports).reduce(
            (sum, c) => sum + (c?.length || 0),
            0
          );
          finalReportContent = Object.entries(finalReports)
            .map(([key, content]) => `## ${getDimensionName(key)}\n\n${content}`)
            .join('\n\n---\n\n');
          console.log(`[ChatPanel] Fallback generated: ${fallbackTotalChars} chars`);
        }
      }

      const finalWordCount = Object.values(finalReports).reduce(
        (sum, c) => sum + (c?.length || 0),
        0
      );

      // ✅ 调试日志：追踪最终数据的完整性
      const finalReportDetails = Object.entries(finalReports).map(
        ([key, content]) => `${key}: ${content?.length || 0} chars`
      );
      console.log(`[ChatPanel] Layer ${layer} 最终数据:`, {
        dimensionCount: Object.keys(finalReports).length,
        totalChars: finalWordCount,
        details: finalReportDetails,
      });

      // ✅ 更新层级完成状态
      setUILayerCompleted(layer, true);

      // 🔧 同步 Layer 报告内容到 Context（用于侧边栏显示）
      if (layer === 1) {
        setLayerReports({
          analysis_reports: finalReports,
          analysis_report_content: finalReportContent,
        });
      } else if (layer === 2) {
        setLayerReports({
          concept_reports: finalReports,
          concept_report_content: finalReportContent,
        });
      } else if (layer === 3) {
        setLayerReports({
          detail_reports: finalReports,
          detail_report_content: finalReportContent,
        });
      }
      console.log(`[ChatPanel] Synced Layer ${layer} reports to Context`);

      const layerReportId = `layer_report_${layer}`;

      // ✅ 关键修复：使用 ref 检查而不是 messages.some()，解决 React 闭包陷阱问题
      // handleLayerStarted 已创建空消息并设置 ref 标记
      const hasLayerReport = layerReportCreatedRef.current[layer] || false;

      console.log(
        `[ChatPanel] Layer ${layer} completed - hasLayerReport (ref): ${hasLayerReport}, messages.some: ${messages.some((m) => m.id === layerReportId)}`
      );

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
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        syncMessageToBackend(newMsg as any);
        console.log(
          `[ChatPanel] Created and synced layer_report_${layer} to backend (first creation), wordCount=${finalWordCount}`
        );

        // 更新 ref 标记
        layerReportCreatedRef.current[layer] = true;
      } else {
        // 更新现有消息（从 handleLayerStarted 创建的空消息更新为完整数据）
        setMessages((prev) => {
          const updated = prev.map((msg) => {
            if (msg.id === layerReportId && msg.type === 'layer_completed') {
              // ✅ 关键修复：移除 _pendingStorage 标记，确保数据被存储
              // eslint-disable-next-line @typescript-eslint/no-unused-vars, @typescript-eslint/no-explicit-any
              const { _pendingStorage: _unused, ...rest } = msg as any;
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
          const updatedMsg = updated.find((m) => m.id === layerReportId);
          if (updatedMsg) {
            // ✅ 关键修复：显式调用 syncMessageToBackend 存储完整数据
            syncMessageToBackend(updatedMsg);
            console.log(
              `[ChatPanel] Synced completed layer_report_${layer} to backend, wordCount=${finalWordCount}`
            );
          }

          return updated;
        });
      }
    },
    [
      messages,
      addMessage,
      setMessages,
      showViewer,
      syncMessageToBackend,
      dimensionContents,
      fetchLayerReportsFromBackend,
      flushBatch,
      setUILayerCompleted,
      setLayerReports,
    ]
  );

  // 统一层级数据恢复函数 - 消除 handleConnected 和 useEffect 中的重复逻辑
  const restoreLayerData = useCallback(
    async (layer: number) => {
      if (!completedLayers[layer as 1 | 2 | 3]) return;

      // 防抖检查 - 避免重复调用同一 layer
      if (restoringLayersRef.current.has(layer)) {
        console.log(`[ChatPanel] Layer ${layer} restoration in progress, skipping`);
        return;
      }

      const layerReportId = `layer_report_${layer}`;
      const existingMsg = messages.find((m) => m.id === layerReportId);
      if (
        existingMsg &&
        'fullReportContent' in existingMsg &&
        (existingMsg.fullReportContent ?? '').length > 0
      ) {
        return;
      }

      restoringLayersRef.current.add(layer);
      try {
        const backendData = await fetchLayerReportsFromBackend(layer);
        if (backendData?.reports && Object.keys(backendData.reports).length > 0) {
          await handleLayerCompleted(layer, backendData.reportContent, backendData.reports);
          console.log(`[ChatPanel] Layer ${layer} data restored successfully`);
        }
      } catch (error) {
        console.error(`[ChatPanel] Layer ${layer} restore failed:`, error);
      } finally {
        restoringLayersRef.current.delete(layer);
      }
    },
    [completedLayers, messages, fetchLayerReportsFromBackend, handleLayerCompleted]
  );

  // 新增：处理层级开始事件 - 创建空的 LayerReportMessage（预填充维度槽位）
  // 使用函数式更新 + ref 双重检查，确保消息不会被重复创建或跳过
  const handleLayerStarted = useCallback(
    (layer: number, layerName: string) => {
      console.log(
        `[ChatPanel] 🚀 handleLayerStarted 被调用: Layer ${layer}, layerName="${layerName}"`
      );

      // 更新当前层级和阶段（用于 ProgressPanel 显示）
      setCurrentLayerAndPhase(layer);

      // 创建层级报告消息（预填充维度槽位，等待流式更新）
      const layerReportId = `layer_report_${layer}`;

      // 🔧 关键修复：使用函数式更新，在 setMessages 回调中检查消息是否存在
      // 这样避免了 React 状态闭包问题和 ref 过早设置的问题
      setMessages((prev) => {
        // 在回调中检查消息是否已存在
        const exists = prev.some((m) => m.id === layerReportId);

        if (exists) {
          console.log(`[ChatPanel] Layer ${layer} 占位消息已存在，跳过创建`);
          return prev; // 消息已存在，不做任何修改
        }

        // 创建新的占位消息
        const dimensionKeys = getDimensionsByLayer(layer);
        const emptyDimensionReports: Record<string, string> = {};
        dimensionKeys.forEach((key) => {
          emptyDimensionReports[key] = ''; // 空字符串，等待流式填充
        });

        console.log(
          `[ChatPanel] ✅ 创建 Layer ${layer} 占位消息，${dimensionKeys.length} 个维度槽位`
        );

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
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;

        return [...prev, newMsg];
      });

      // 🔧 修复：添加层级开始提示消息（使用函数式更新避免闭包问题）
      setMessages((prev) => {
        const progressId = `progress_layer_${layer}`;
        const hasProgress = prev.some((m) => m.id === progressId && m.type === 'progress');

        if (hasProgress) {
          return prev;
        }

        return [
          ...prev,
          {
            ...createBaseMessage(),
            id: progressId,
            type: 'progress',
            role: 'assistant',
            content: `Executing Layer ${layer}: ${LAYER_VALUE_MAP[layer] || layerName}...`,
            progress: 0,
          } as ProgressMessage,
        ];
      });

      // 更新进度消息的 ref 标记
      layerProgressCreatedRef.current[layer] = true;
    },
    [setMessages, setCurrentLayerAndPhase]
  );

  const handlePause = useCallback(
    async (layer: number, checkpointId: string) => {
      console.log(`[ChatPanel] Pause event received`, { layer, checkpointId });

      // 🔧 修复：更新审查状态，使 ReviewPanel 能够正确显示
      setIsPaused(true);
      setPendingReviewLayer(layer);
      console.log(`[ChatPanel] Set isPaused=true, pendingReviewLayer=${layer}`);

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
        console.log(`[ChatPanel] Pause fallback: fetching layer ${layer} data from REST API...`);
        try {
          const backendData = await fetchLayerReportsFromBackend(layer);
          if (backendData && backendData.reports && Object.keys(backendData.reports).length > 0) {
            console.log(
              `[ChatPanel] Pause fallback: got ${Object.keys(backendData.reports).length} dimensions, updating dimensionContents`
            );
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
          } else {
            console.log(`[ChatPanel] Pause fallback: REST API returned no data for layer ${layer}`);
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
      console.log('[ChatPanel] Dimension revised signal received', data);

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
        syncMessageToBackend(dimensionReportMsg); // ✅ 持久化修复后的维度报告

        // 更新维度内容到状态
        setDimensionContents((prev) => ({
          ...prev,
          [data.dimension]: newContent,
        }));

        console.log(
          `[ChatPanel] 维度 ${data.dimension} 修复完成 (v${version})，已添加并持久化消息`
        );
        if (previousContent) {
          console.log(`[ChatPanel] 包含原始内容用于对比，原始长度: ${previousContent.length}`);
        }
      } catch (error) {
        console.error(`[ChatPanel] Failed to fetch dimension content:`, error);
        // 降级处理：添加错误提示消息
        addMessage(
          createSystemMessage(`获取维度 ${dimensionName} 内容失败，请刷新页面重试`, 'error')
        );
      }
    },
    [addMessage, syncMessageToBackend, taskId, setDimensionContents]
  );

  // SSE 连接成功回调 - 连接成功后触发状态恢复检查
  const handleConnected = useCallback(() => {
    console.log('[ChatPanel] SSE connected, triggering layer restoration');
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
      console.log('[ChatPanel] Layer change requested:', layer);
      const layerNumber = LAYER_LABEL_MAP[layer];
      console.log('[ChatPanel] Mapped layer number:', layerNumber);
      console.log('[ChatPanel] onOpenLayerSidebar:', onOpenLayerSidebar);

      if (layerNumber !== undefined && taskId) {
        // 1. Fetch latest reports from backend
        try {
          const reports = await planningApi.getLayerReports(taskId, layerNumber);
          console.log('[ChatPanel] Layer reports fetched:', reports);

          // 2. Update reports in state
          const layerKey = `layer${layerNumber}` as 'layer1' | 'layer2' | 'layer3';
          dispatch({
            type: 'SET_REPORTS',
            reports: {
              [layerKey]: reports.reports || {},
            },
          });
        } catch (error) {
          console.error('[ChatPanel] Failed to fetch Layer reports:', error);
        }

        // 3. Open sidebar
        console.log('[ChatPanel] Calling onOpenLayerSidebar with:', layerNumber);
        onOpenLayerSidebar?.(layerNumber);
      }
    },
    [onOpenLayerSidebar, taskId, dispatch]
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
      addMessage(
        createErrorMessage(`Approval failed: ${getErrorMessage(error, 'Unknown error')}`)
      );
    }
  }, [actions, addMessage]);

  const handleReviewReject = useCallback(
    async (feedback: string, dimensions?: string[]) => {
      try {
        addMessage({
          ...createBaseMessage('user'),
          type: 'text',
          content: `📝 Revision request: ${feedback}${dimensions ? ` (Dimensions: ${dimensions.map((d) => getDimensionName(d)).join(', ')})` : ''}`,
        });
        addMessage(createSystemMessage('🔄 Revising based on feedback...'));
        await actions.reject(feedback, dimensions);
      } catch (error: unknown) {
        addMessage(
          createErrorMessage(`Rejection failed: ${getErrorMessage(error, 'Unknown error')}`)
        );
      }
    },
    [actions, addMessage]
  );

  const handleRollbackAction = useCallback(
    async (checkpointId: string) => {
      if (!confirm('Are you sure you want to rollback? Subsequent content will be deleted.')) return;

      setIsRollingBack(true);
      try {
        await actions.rollback(checkpointId);
        addMessage(createSystemMessage(`↩️ Rolled back to checkpoint: ${checkpointId}`));
      } catch (error: unknown) {
        addMessage(
          createErrorMessage(`回退失败: ${getErrorMessage(error, '未知错误')}`)
        );
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

      // Use uploaded file content or generate default
      const villageData =
        uploadedFileContent ||
        `# 村庄现状数据（示例）

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
          .map((f) => `### 📎 文件：${f.filename}\n\n${f.content}`)
          .join('\n\n---\n\n');
        taskDescription = taskDescription
          ? `${taskDescription}\n\n---\n\n${fileContents}`
          : fileContents;
      }

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
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'user',
        type: 'text',
        content: userText,
      });

      // Check if this is an approval command
      if (userText === '批准' || userText === '继续' || userText.toLowerCase() === 'approve') {
        try {
          addMessage(createSystemMessage('✅ Approved, continuing to next layer...'));
          await actions.approve();
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
        await actions.reject(userText, dimensionsToSubmit);
      } catch (error: unknown) {
        addMessage(
          createErrorMessage(`Revision failed: ${getErrorMessage(error, 'Unknown error')}`)
        );
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
        addMessage(
          createSystemMessage(
            `✅ 文件 "${file.name}" 已上传${encodingInfo}\n内容长度: ${response.content.length} 字符`
          )
        );
      }

      // 存储合并后的内容
      const combinedContent = allContents.join('\n\n---\n\n');
      setUploadedFileContent(combinedContent);

      if (results.length > 1) {
        addMessage(
          createSystemMessage(
            `✅ 已上传 ${results.length} 个文件，总内容长度: ${combinedContent.length} 字符\n点击 "开始规划" 按钮启动任务`
          )
        );
      } else {
        addMessage(createSystemMessage(`点击 "开始规划" 按钮启动任务`));
      }

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
        console.log('[ChatPanel] Open layer report in viewer:', layerId);
        showViewer();
      }
    },
    [showViewer]
  );

  // Handler: 在侧边栏查看文件内容
  const handleViewFileInSidebar = useCallback(
    (file: FileMessage) => {
      console.log('[ChatPanel] View file in sidebar:', file.filename);
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
                console.log('[ChatPanel] View layer details:', layerId);
                showViewer();
              }
            }}
            onToggleAllDimensions={(layer, expand) => {
              // This would expand/collapse all dimensions in the viewer
              console.log('[ChatPanel] Toggle all dimensions for layer', layer, expand);
              // TODO: Implement expand/collapse all in LayerReportViewer
            }}
            currentLayer={currentLayer ?? undefined}
            dimensionContents={dimensionContents}
            checkpoints={state.checkpoints}
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
              onApprove={handleReviewApprove}
              onReject={(feedback) =>
                handleReviewReject(
                  feedback,
                  selectedDimensions.length > 0 ? selectedDimensions : undefined
                )
              }
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
          <p className="text-center text-xs text-gray-400 mt-2">Enter 发送 · Shift+Enter 换行</p>
        </div>
      </div>
    </div>
  );
}
