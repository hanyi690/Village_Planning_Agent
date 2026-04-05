/**
 * usePlanningHandlers Hook - 规划事件处理逻辑
 *
 * 提取自 ChatPanel 的核心业务逻辑：
 * - handleLayerStarted: 层级开始处理
 * - handleLayerCompleted: 层级完成处理（Signal-Fetch 模式）
 * - handleDimensionDelta: 维度流式更新
 * - handleDimensionComplete: 维度完成处理
 * - handlePause: 暂停处理
 */

import { useRef, useCallback } from 'react';
import { usePlanningStore } from '@/stores/planningStore';
import { planningApi } from '@/lib/api';
import { createBaseMessage } from '@/lib/utils';
import { getDimensionName, getDimensionsByLayer } from '@/config/dimensions';
import { MIN_SSE_DATA_CHARS, LAYER_VALUE_MAP } from '@/lib/constants';
import type { Message, ProgressMessage, LayerCompletedMessage } from '@/types';

// ============================================
// Types
// ============================================

interface UsePlanningHandlersOptions {
  addToken: (dimensionKey: string, delta: string, accumulated: string, layer: number) => void;
  completeDimension: (dimensionKey: string, layer: number) => void;
  flushBatch: () => void;
  throttledSetDimensionStreaming: (layer: number, dimensionKey: string, dimensionName: string) => void;
  showViewer: () => void;
}

interface LayerReportData {
  reports: Record<string, string>;
  reportContent: string;
}

// ============================================
// Hook Implementation
// ============================================

export function usePlanningHandlers({
  addToken,
  completeDimension,
  flushBatch,
  throttledSetDimensionStreaming,
  showViewer,
}: UsePlanningHandlersOptions) {
  // Store access
  const taskId = usePlanningStore((state) => state.taskId);
  const currentLayer = usePlanningStore((state) => state.currentLayer);
  const completedLayers = usePlanningStore((state) => state.completedLayers);
  const messages = usePlanningStore((state) => state.messages);
  const addMessage = usePlanningStore((state) => state.addMessage);
  const setMessages = usePlanningStore((state) => state.setMessages);
  const setDimensionCompleted = usePlanningStore((state) => state.setDimensionCompleted);
  const setLayerCompleted = usePlanningStore((state) => state.setLayerCompleted);
  const setReports = usePlanningStore((state) => state.setReports);
  const setDimensionStreaming = usePlanningStore((state) => state.setDimensionStreaming);

  // Refs for tracking state
  const layerReportCreatedRef = useRef<Record<number, boolean>>({});
  const layerProgressCreatedRef = useRef<Record<number, boolean>>({});
  const restoringLayersRef = useRef<Set<number>>(new Set());
  const dimensionContentsRef = useRef<Record<string, string>>({});

  // ============================================
  // Layer Reports Fetching (Signal-Fetch Pattern)
  // ============================================

  const fetchLayerReportsFromBackend = useCallback(
    async (layer: number): Promise<LayerReportData | null> => {
      if (!taskId) {
        console.warn('[usePlanningHandlers] No taskId, cannot fetch layer reports');
        return null;
      }

      const startTime = Date.now();
      console.log(`[usePlanningHandlers] 📡 REST API 调用开始: GET /layer/${layer}/reports, taskId=${taskId}`);

      try {
        const response = await planningApi.getLayerReports(taskId, layer);
        const elapsed = Date.now() - startTime;

        const reportKeys = Object.keys(response.reports || {});
        const reportsWithContent = reportKeys.filter(
          (k) => response.reports[k] && response.reports[k].length > 0
        );

        console.log(`[usePlanningHandlers] ✅ REST API 响应成功: Layer ${layer}, 耗时=${elapsed}ms`, {
          dimensionCount: response.stats.dimension_count,
          totalChars: response.stats.total_chars,
          completed: response.completed,
          reportKeysCount: reportKeys.length,
          reportsWithContentCount: reportsWithContent.length,
        });

        return {
          reports: response.reports,
          reportContent: response.report_content,
        };
      } catch (error) {
        console.error(`[usePlanningHandlers] Failed to fetch layer ${layer} reports:`, error);
        return null;
      }
    },
    [taskId]
  );

  // ============================================
  // Dimension Handlers
  // ============================================

  const handleDimensionDelta = useCallback(
    (dimensionKey: string, delta: string, accumulated: string, layer?: number) => {
      const layerNum = layer || currentLayer || 1;
      addToken(dimensionKey, delta, accumulated, layerNum);
      throttledSetDimensionStreaming(layerNum, dimensionKey, getDimensionName(dimensionKey));
    },
    [currentLayer, throttledSetDimensionStreaming, addToken]
  );

  const handleDimensionComplete = useCallback(
    (dimensionKey: string, _dimensionName: string, fullContent: string, layer?: number) => {
      const layerNum = layer || currentLayer || 1;
      completeDimension(dimensionKey, layerNum);

      // Update dimension content cache
      const key = `${layerNum}_${dimensionKey}`;
      dimensionContentsRef.current[key] = fullContent;

      // Update message state
      const messageId = `dimension_${layerNum}_${dimensionKey}`;
      const currentMessages = usePlanningStore.getState().messages;
      const updatedMessages = currentMessages.map((msg) =>
        msg.id === messageId && msg.type === 'dimension_report'
          ? { ...msg, content: fullContent, wordCount: fullContent.length, streamingState: 'completed' as const }
          : msg
      );
      setMessages(updatedMessages);

      setDimensionCompleted(layerNum, dimensionKey, fullContent.length);
      console.log(`[usePlanningHandlers] Dimension complete: ${dimensionKey} (${fullContent.length} chars)`);
    },
    [currentLayer, completeDimension, setMessages, setDimensionCompleted]
  );

  // ============================================
  // Layer Handlers
  // ============================================

  const handleLayerStarted = useCallback(
    (layer: number, layerName: string) => {
      console.log(`[usePlanningHandlers] 🚀 Layer ${layer} started: "${layerName}"`);

      setDimensionStreaming(layer, '', '');

      const layerReportId = `layer_report_${layer}`;

      // Check if message already exists
      const currentMessages = usePlanningStore.getState().messages;
      const exists = currentMessages.some((m) => m.id === layerReportId);

      if (exists) {
        console.log(`[usePlanningHandlers] Layer ${layer} 占位消息已存在，跳过创建`);
        return;
      }

      // Create placeholder message
      const dimensionKeys = getDimensionsByLayer(layer);
      const emptyDimensionReports: Record<string, string> = {};
      dimensionKeys.forEach((key) => {
        emptyDimensionReports[key] = '';
      });

      console.log(`[usePlanningHandlers] ✅ 创建 Layer ${layer} 占位消息，${dimensionKeys.length} 个维度槽位`);
      layerReportCreatedRef.current[layer] = true;

      const newMsg: Message = {
        ...createBaseMessage('assistant'),
        id: layerReportId,
        type: 'layer_completed',
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
      } as Message;

      addMessage(newMsg);

      // Add progress message
      const progressId = `progress_layer_${layer}`;
      const hasProgress = currentMessages.some((m) => m.id === progressId && m.type === 'progress');

      if (!hasProgress) {
        const progressMsg: ProgressMessage = {
          ...createBaseMessage('assistant'),
          id: progressId,
          type: 'progress',
          content: `🔄 正在执行 Layer ${layer}: ${LAYER_VALUE_MAP[layer] || layerName}...`,
          progress: 0,
        };
        addMessage(progressMsg);
        layerProgressCreatedRef.current[layer] = true;
      }
    },
    [addMessage, setDimensionStreaming]
  );

  const handleLayerCompleted = useCallback(
    async (layer: number, reportContent: string, dimensionReports: Record<string, string>) => {
      flushBatch();

      console.log(`[usePlanningHandlers] Layer ${layer} completed signal received`, {
        reportLength: reportContent?.length || 0,
        dimensionCount: Object.keys(dimensionReports || {}).length,
      });

      // SSE data completeness check
      let finalReports: Record<string, string> = {};
      let finalReportContent = reportContent;

      const sseDataComplete = dimensionReports && Object.keys(dimensionReports).length > 0;
      const sseTotalChars = sseDataComplete
        ? Object.values(dimensionReports).reduce((sum, c) => sum + (c?.length || 0), 0)
        : 0;

      if (sseDataComplete && sseTotalChars > MIN_SSE_DATA_CHARS) {
        finalReports = dimensionReports;
        console.log(`[usePlanningHandlers] Using SSE data: ${Object.keys(finalReports).length} dimensions, ${sseTotalChars} chars`);
      } else {
        console.log(`[usePlanningHandlers] SSE data incomplete, fetching from REST API...`);
        const backendData = await fetchLayerReportsFromBackend(layer);

        if (backendData?.reports && Object.keys(backendData.reports).length > 0) {
          finalReports = backendData.reports;
          finalReportContent = backendData.reportContent;
          console.log(`[usePlanningHandlers] Using REST API data: ${Object.keys(finalReports).length} dimensions`);
        } else {
          // Fallback: merge dimensionContents
          console.log(`[usePlanningHandlers] REST API failed, falling back to dimensionContents`);
          Object.entries(dimensionContentsRef.current).forEach(([key, content]) => {
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

          finalReportContent = Object.entries(finalReports)
            .map(([key, content]) => `## ${getDimensionName(key)}\n\n${content}`)
            .join('\n\n---\n\n');
        }
      }

      const finalWordCount = Object.values(finalReports).reduce((sum, c) => sum + (c?.length || 0), 0);

      // Update layer completion status
      setLayerCompleted(layer, true);

      // Sync reports to store
      const layerKey = `layer${layer}` as 'layer1' | 'layer2' | 'layer3';
      setReports({ [layerKey]: finalReports });
      console.log(`[usePlanningHandlers] Synced Layer ${layer} reports to store`);

      // Update or create layer report message
      const layerReportId = `layer_report_${layer}`;
      const hasLayerReport = layerReportCreatedRef.current[layer] || false;

      if (!hasLayerReport) {
        // Create new message
        const newMsg: Message = {
          ...createBaseMessage('assistant'),
          id: layerReportId,
          type: 'layer_completed',
          layer: layer,
          content: finalReportContent,
          summary: {
            word_count: finalWordCount,
            key_points: [],
            dimension_count: Object.keys(finalReports).length,
          },
          fullReportContent: finalReportContent,
          dimensionReports: finalReports,
          actions: [
            {
              id: 'view_details',
              label: '查看详情',
              action: 'view',
              onClick: () => showViewer(),
            },
          ],
        };

        addMessage(newMsg);
        layerReportCreatedRef.current[layer] = true;
        console.log(`[usePlanningHandlers] Created layer_report_${layer}`);
      } else {
        // Update existing message
        const currentMessages = usePlanningStore.getState().messages;
        const updatedMessages: Message[] = currentMessages.map((msg) => {
          if (msg.id === layerReportId && msg.type === 'layer_completed') {
            const layerMsg = msg as LayerCompletedMessage & { _pendingStorage?: boolean };
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const { _pendingStorage, ...rest } = layerMsg;
            return {
              ...rest,
              content: finalReportContent,
              fullReportContent: finalReportContent,
              dimensionReports: finalReports,
              summary: {
                word_count: finalWordCount,
                key_points: layerMsg.summary?.key_points || [],
                dimension_count: Object.keys(finalReports).length,
              },
            } as Message;
          }
          return msg;
        });
        setMessages(updatedMessages);
        console.log(`[usePlanningHandlers] Updated layer_report_${layer}`);
      }

      // Save layer report to backend (upsert)
      if (taskId) {
        try {
          await planningApi.createMessage(taskId, {
            id: layerReportId,
            role: 'assistant',
            content: finalReportContent,
            message_type: 'layer_completed',
            metadata: {
              layer: layer,
              summary: {
                word_count: finalWordCount,
                key_points: [],
                dimension_count: Object.keys(finalReports).length,
              },
              fullReportContent: finalReportContent,
              dimensionReports: finalReports,
            },
          });
          console.log(`[usePlanningHandlers] Saved layer_report_${layer} to backend`);
        } catch (error) {
          console.error(`[usePlanningHandlers] Failed to save layer_report_${layer}:`, error);
        }
      }
    },
    [flushBatch, fetchLayerReportsFromBackend, setLayerCompleted, setReports, addMessage, setMessages, showViewer]
  );

  // ============================================
  // Data Restoration
  // ============================================

  const restoreLayerData = useCallback(
    async (layer: number) => {
      if (!completedLayers[layer as 1 | 2 | 3]) return;

      if (restoringLayersRef.current.has(layer)) {
        console.log(`[usePlanningHandlers] Layer ${layer} restoration in progress, skipping`);
        return;
      }

      const layerReportId = `layer_report_${layer}`;
      const existingMsg = messages.find((m) => m.id === layerReportId);
      if (existingMsg && 'fullReportContent' in existingMsg && (existingMsg.fullReportContent ?? '').length > 0) {
        return;
      }

      restoringLayersRef.current.add(layer);
      try {
        const backendData = await fetchLayerReportsFromBackend(layer);
        if (backendData?.reports && Object.keys(backendData.reports).length > 0) {
          await handleLayerCompleted(layer, backendData.reportContent, backendData.reports);
          console.log(`[usePlanningHandlers] Layer ${layer} data restored`);
        }
      } catch (error) {
        console.error(`[usePlanningHandlers] Layer ${layer} restore failed:`, error);
      } finally {
        restoringLayersRef.current.delete(layer);
      }
    },
    [completedLayers, messages, fetchLayerReportsFromBackend, handleLayerCompleted]
  );

  // ============================================
  // Return
  // ============================================

  return {
    // Refs
    layerReportCreatedRef,
    layerProgressCreatedRef,
    dimensionContentsRef,

    // Dimension handlers
    handleDimensionDelta,
    handleDimensionComplete,

    // Layer handlers
    handleLayerStarted,
    handleLayerCompleted,
    fetchLayerReportsFromBackend,
    restoreLayerData,
  };
}

export default usePlanningHandlers;