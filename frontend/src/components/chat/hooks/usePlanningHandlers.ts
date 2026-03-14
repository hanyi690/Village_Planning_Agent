// ============================================
// usePlanningHandlers Hook - 规划事件处理逻辑
// ============================================

import { useRef, useCallback } from 'react';
import { planningApi } from '@/lib/api';
import { createBaseMessage } from '@/lib/utils';
import { getDimensionName, getDimensionsByLayer } from '@/config/dimensions';
import type { Message, ProgressMessage } from '@/types';

interface UsePlanningHandlersOptions {
  currentLayer: number | null;
  taskId: string | null;
  messages: Message[];
  addMessage: (message: Message) => void;
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setDimensionContents: React.Dispatch<React.SetStateAction<Map<string, string>>>;
  setCurrentLayerAndPhase: (layer: number) => void;
  setDimensionStreaming: (layer: number, dimensionKey: string, dimensionName: string) => void;
  setDimensionCompleted: (layer: number, dimensionKey: string, charCount: number) => void;
  setUILayerCompleted: (layer: number, completed: boolean) => void;
  showViewer: () => void;
  syncMessageToBackend: (message: Message) => void;
  addToken: (dimensionKey: string, delta: string, accumulated: string, layer: number) => void;
  completeDimension: (dimensionKey: string, layer: number) => void;
  flushBatch: () => void;
}

interface LayerReportData {
  reports: Record<string, string>;
  reportContent: string;
}

/**
 * 规划事件处理 Hook
 * 处理层级开始、完成、维度更新等事件
 */
export function usePlanningHandlers({
  currentLayer,
  taskId,
  setMessages,
  setDimensionContents,
  setCurrentLayerAndPhase,
  setDimensionStreaming,
  setDimensionCompleted,
  addToken,
  completeDimension,
}: UsePlanningHandlersOptions) {
  // Track layer report message creation state (fix React closure trap)
  const layerReportCreatedRef = useRef<Record<number, boolean>>({});

  // Track layer progress message creation state
  const layerProgressCreatedRef = useRef<Record<number, boolean>>({});

  // 维度级流式回调
  const handleDimensionDelta = useCallback((
    dimensionKey: string,
    delta: string,
    accumulated: string,
    layer?: number
  ) => {
    const layerNum = layer || currentLayer || 1;
    addToken(dimensionKey, delta, accumulated, layerNum);
    setDimensionStreaming(layerNum, dimensionKey, getDimensionName(dimensionKey));
  }, [currentLayer, setDimensionStreaming, addToken]);

  const handleDimensionComplete = useCallback((
    dimensionKey: string,
    _dimensionName: string,
    fullContent: string,
    layer?: number
  ) => {
    const layerNum = layer || currentLayer || 1;
    completeDimension(dimensionKey, layerNum);

    // 更新维度内容缓存
    setDimensionContents(prev => {
      const key = `${layerNum}_${dimensionKey}`;
      return new Map(prev).set(key, fullContent);
    });

    // 更新消息状态为完成
    const messageId = `dimension_${layerNum}_${dimensionKey}`;
    setMessages(prev => prev.map(msg =>
      msg.id === messageId
        ? { ...msg, content: fullContent, wordCount: fullContent.length, streamingState: 'completed' as const }
        : msg
    ));

    setDimensionCompleted(layerNum, dimensionKey, fullContent.length);
    console.log(`[ChatPanel] Dimension complete: ${dimensionKey} (${fullContent.length} chars)`);
  }, [setMessages, currentLayer, setDimensionCompleted, setDimensionContents, completeDimension]);

  // Signal-Fetch Pattern: 层级完成后的数据拉取函数
  const fetchLayerReportsFromBackend = useCallback(async (layer: number): Promise<LayerReportData | null> => {
    if (!taskId) {
      console.warn('[ChatPanel] No taskId, cannot fetch layer reports');
      return null;
    }

    const startTime = Date.now();
    console.log(`[ChatPanel] 📡 REST API 调用开始: GET /layer/${layer}/reports, taskId=${taskId}`);

    try {
      const response = await planningApi.getLayerReports(taskId, layer);
      const elapsed = Date.now() - startTime;

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

  // 处理层级开始事件
  const handleLayerStarted = useCallback((layer: number, layerName: string) => {
    console.log(`[ChatPanel] 🚀 handleLayerStarted 被调用: Layer ${layer}, layerName="${layerName}"`);
    setCurrentLayerAndPhase(layer);

    const layerLabels: Record<number, string> = {
      1: '现状分析',
      2: '规划思路',
      3: '详细规划',
    };

    const layerReportId = `layer_report_${layer}`;

    setMessages(prev => {
      const exists = prev.some(m => m.id === layerReportId);

      if (exists) {
        console.log(`[ChatPanel] Layer ${layer} 占位消息已存在，跳过创建`);
        return prev;
      }

      const dimensionKeys = getDimensionsByLayer(layer);
      const emptyDimensionReports: Record<string, string> = {};
      dimensionKeys.forEach(key => {
        emptyDimensionReports[key] = '';
      });

      console.log(`[ChatPanel] ✅ 创建 Layer ${layer} 占位消息，${dimensionKeys.length} 个维度槽位`);
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
      } as unknown as Message;

      return [...prev, newMsg];
    });

    // 添加层级开始提示消息
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

    layerProgressCreatedRef.current[layer] = true;
  }, [setMessages, setCurrentLayerAndPhase]);

  return {
    layerReportCreatedRef,
    layerProgressCreatedRef,
    handleDimensionDelta,
    handleDimensionComplete,
    fetchLayerReportsFromBackend,
    handleLayerStarted,
  };
}