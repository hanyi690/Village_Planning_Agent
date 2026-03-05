/**
 * useTaskSSE Hook
 * SSE连接处理Hook - 管理任务SSE连接和事件处理
 * 新增: 重试限制和指数退避机制，防止无限重连导致系统卡死
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { planningApi, PlanningSSEEvent } from '@/lib/api';
import { logger } from '@/lib/logger';

type ThinkingState = 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'paused' | 'error';

// Retry configuration constants
const MAX_RETRY_COUNT = 3;
const BASE_RETRY_DELAY = 1000;

// ✅ NEW: Type guard interfaces for type safety (P1.2)
// ✅ FIXED: 将 chunk 改为 delta，与后端发送的字段名一致
interface DimensionDeltaData {
  dimension_key: string;
  dimension_name: string;
  layer: number;
  delta: string;
  accumulated: string;
}

function isDimensionDeltaData(data: unknown): data is DimensionDeltaData {
  return (
    typeof data === 'object' &&
    data !== null &&
    'dimension_key' in data &&
    'dimension_name' in data &&
    'layer' in data &&
    'delta' in data &&
    'accumulated' in data
  );
}

export interface UseTaskSSECallbacks {
  onStatusUpdate?: (data: unknown) => void;
  onLayerCompleted?: (data: unknown) => void;
  onComplete?: (result: unknown) => void;
  onError?: (error: string) => void;
  onPause?: (data: unknown) => void;
  onReviewRequest?: (data: unknown) => void;
  onMessage?: (event: PlanningSSEEvent) => void;
  onTextChunk?: (chunk: string, messageId: string) => void;
  onThinkingStart?: (state: ThinkingState, message?: string) => void;
  onThinkingEnd?: () => void;
  onContentDelta?: (delta: string, layer: number, metadata: unknown) => void;
  onLayerReportReady?: (layer: number) => void;
  onMaxRetriesReached?: () => void;

  // 新增：维度级流式回调
  onDimensionDelta?: (
    dimensionKey: string,
    dimensionName: string,
    layer: number,
    chunk: string,
    accumulated: string
  ) => void;
  onDimensionComplete?: (
    dimensionKey: string,
    dimensionName: string,
    layer: number,
    fullContent: string
  ) => void;
  onLayerProgress?: (
    layer: number,
    completed: number,
    total: number
  ) => void;
}

export function useTaskSSE(taskId: string | null | undefined, callbacks: UseTaskSSECallbacks) {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const eventSourceRef = useRef<EventSource | null>(null);
  const initializingRef = useRef(false);
  const retryCountRef = useRef(0);
  const retryTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isPausedRef = useRef(false);

  // Simplified: Only streaming text and error handlers
  // All state events (layer_completed, pause, etc.) handled by REST polling
  const createEventHandlers = () => ({
    // 维度级增量事件
    dimension_delta: (event: PlanningSSEEvent) => {
      const { dimension_key, dimension_name, layer, delta, accumulated } = event.data || {};

      // ✅ FIXED: Use type guard instead of as assertion
      if (!isDimensionDeltaData(event.data)) {
        console.error('[useTaskSSE] Invalid dimension_delta data:', event.data);
        return;
      }

      console.log(`[useTaskSSE] Dimension delta: ${dimension_key} (+${delta?.length || 0} chars)`);
      callbacks.onDimensionDelta?.(
        event.data.dimension_key,
        event.data.dimension_name ?? '',
        event.data.layer,
        event.data.delta ?? '',
        event.data.accumulated ?? ''
      );
    },
    // 维度完成事件
    dimension_complete: (event: PlanningSSEEvent) => {
      const { dimension_key, dimension_name, layer, full_content } = event.data || {};
      if (dimension_key) {
        console.log(`[useTaskSSE] Dimension complete: ${dimension_key} (${typeof full_content === 'string' ? full_content.length : 0} chars)`);
        callbacks.onDimensionComplete?.(
          dimension_key as string,
          dimension_name as string,
          layer as number,
          full_content as string
        );
      }
    },
    // 层级进度事件
    layer_progress: (event: PlanningSSEEvent) => {
      const { layer, completed, total } = event.data || {};
      if (layer) {
        console.log(`[useTaskSSE] Layer ${layer} progress: ${completed}/${total}`);
        callbacks.onLayerProgress?.(
          layer as number,
          completed as number,
          total as number
        );
      }
    },
    // KEEP: Streaming text
    text_delta: (event: PlanningSSEEvent) => {
      const text = event.data?.delta || '';
      const textStr = text as string;
      const layer = event.data?.layer;
      const layerNum = layer as number | undefined;
      console.log('[useTaskSSE] Text delta received:', textStr.substring(0, 50));
      callbacks.onContentDelta?.(textStr, layerNum || 1, event.data);
    },
    text_chunk: (event: PlanningSSEEvent) => {
      const chunk = event.data?.chunk || '';
      const chunkStr = chunk as string;
      console.log('[useTaskSSE] Text chunk received:', chunkStr.substring(0, 50));
      callbacks.onTextChunk?.(chunkStr, event.data?.message_id || '');
    },
    thinking_start: (event: PlanningSSEEvent) => {
      const state = (event.data?.state || 'processing') as ThinkingState;
      console.log('[useTaskSSE] Thinking started:', state);
      callbacks.onThinkingStart?.(state, event.data?.message);
    },
    thinking: (event: PlanningSSEEvent) => {
      const state = (event.data?.state || 'processing') as ThinkingState;
      console.log('[useTaskSSE] Thinking:', state);
      callbacks.onThinkingStart?.(state, event.data?.message);
    },
    thinking_end: (event: PlanningSSEEvent) => {
      console.log('[useTaskSSE] Thinking ended');
      callbacks.onThinkingEnd?.();
    },
    layer_report_ready: (event: PlanningSSEEvent) => {
      const layer = event.data?.layer;
      const layerNum = layer as number | undefined;
      console.log(`[useTaskSSE] Layer ${layerNum} report ready event received`);
      callbacks.onLayerReportReady?.(layerNum || 1);
    },
    // KEEP: Completion (as backup, though REST polling handles it)
    completed: (event: PlanningSSEEvent) => {
      logger.sse.info('任务完成', event.data);
      console.log('[useTaskSSE] Task completed');
      callbacks.onComplete?.(event.data);
    },
    complete: (event: PlanningSSEEvent) => {
      logger.sse.info('任务完成', event.data);
      console.log('[useTaskSSE] Task complete');
      callbacks.onComplete?.(event.data);
    },
    // KEEP: Errors
    error: (event: PlanningSSEEvent) => {
      logger.sse.error('任务错误', event.data);
      console.error('[useTaskSSE] Task error:', event.data);
      callbacks.onError?.(event.data?.error || event.data?.message || '任务失败');
    },
  });

  useEffect(() => {
    if (!taskId) {
      setIsConnected(false);
      return;
    }

    if (initializingRef.current) {
      logger.sse.warn('跳过重复的SSE连接', { taskId });
      console.log('[useTaskSSE] Already initializing, skipping duplicate connection');
      return;
    }

    initializingRef.current = true;
    logger.sse.info('建立 SSE 连接', { taskId });

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    console.log(`[useTaskSSE] Creating SSE for task: ${taskId}`);

    const eventHandlers = createEventHandlers();

    try {
      const es = planningApi.createStream(
        taskId,
        (event: PlanningSSEEvent) => {
          const { type } = event;
          console.log(`[useTaskSSE] Event: ${type}`);
          setError(null);

          // Reset retry count on layer_started
          if (type === 'layer_started') {
            retryCountRef.current = 0;
          }

          callbacks.onMessage?.(event);
          const handler = eventHandlers[event.type as keyof typeof eventHandlers];
          (handler as (event: PlanningSSEEvent) => void)?.(event);
        },
        (err) => {
          logger.sse.error('SSE 连接错误', {
            error: err,
            readyState: es?.readyState,
            retryCount: retryCountRef.current,
            connectionState,
            isPaused: isPausedRef.current,
          }, taskId);

          console.error('[useTaskSSE] Error:', err);
          console.error('[useTaskSSE] ReadyState:', es?.readyState);
          console.error('[useTaskSSE] Connection state:', connectionState);
          console.error('[useTaskSSE] Is paused ref:', isPausedRef.current);
          console.error('[useTaskSSE] Retry count:', retryCountRef.current);

          // Multi-layer pause detection
          const isPlannedPause =
            isPausedRef.current ||
            connectionState === 'paused' ||
            (es?.readyState === 2);

          if (isPlannedPause) {
            console.log('[useTaskSSE] Planned pause detected, no retry');
            console.log('[useTaskSSE] Detection basis:', {
              isPausedRef: isPausedRef.current,
              connectionState,
              readyState: es?.readyState,
            });

            setConnectionState('paused');

            if (eventSourceRef.current) {
              eventSourceRef.current.close();
              eventSourceRef.current = null;
            }
            initializingRef.current = false;
            return;
          }

          setConnectionState('error');
          retryCountRef.current++;

          if (retryCountRef.current >= MAX_RETRY_COUNT) {
            const errorMsg = `连接失败：已达到最大重试次数 (${MAX_RETRY_COUNT})。请检查后端服务是否正常运行。`;
            logger.sse.error('达到最大重试次数', { retryCount: retryCountRef.current });
            console.error('[useTaskSSE]', errorMsg);

            setError(errorMsg);
            setIsConnected(false);
            callbacks.onError?.(errorMsg);
            callbacks.onMaxRetriesReached?.();

            if (eventSourceRef.current) {
              eventSourceRef.current.close();
              eventSourceRef.current = null;
            }
            initializingRef.current = false;
            return;
          }

          // Exponential backoff
          const delay = Math.pow(2, retryCountRef.current) * BASE_RETRY_DELAY;
          console.warn(`[useTaskSSE] Will retry in ${delay}ms, attempt ${retryCountRef.current}/${MAX_RETRY_COUNT}`);
          setError(`连接错误，正在重试 (${retryCountRef.current}/${MAX_RETRY_COUNT})...`);
          setIsConnected(false);
          setConnectionState('connecting');

          if (retryTimeoutRef.current) {
            clearTimeout(retryTimeoutRef.current);
          }

          retryTimeoutRef.current = setTimeout(() => {
            console.log(`[useTaskSSE] Starting retry attempt ${retryCountRef.current}`);
            setConnectionState('connecting');
            initializingRef.current = false;
            setIsConnected(false);
          }, delay);
        }
      );

      es.onopen = () => {
        logger.sse.info('SSE 连接成功', { taskId });
        console.log('[useTaskSSE] Connection opened successfully');
        retryCountRef.current = 0;
        setError(null);
        setConnectionState('connected');
      };

      eventSourceRef.current = es;
      setIsConnected(true);
      console.log('[useTaskSSE] EventSource created, waiting for connection...');
    } catch (err) {
      logger.sse.error('创建 EventSource 失败', { error: err });
      console.error('[useTaskSSE] Failed to create EventSource:', err);
      setError('无法连接到服务器');
      setIsConnected(false);
    }

    return () => {
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
        retryTimeoutRef.current = null;
      }

      if (eventSourceRef.current) {
        logger.sse.info('关闭 SSE 连接', { taskId });
        console.log('[useTaskSSE] Closing connection');
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setIsConnected(false);
      initializingRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // Note: callbacks object is expected to be stable (referentially stable) when used by parent components.
    // Re-running this effect when callbacks change would cause unnecessary SSE reconnections.
    // The callbacks ref mechanism ensures we always use the latest callbacks without reconnecting.
  }, [taskId, callbacks]);

  const close = useCallback(() => {
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }

    if (eventSourceRef.current) {
      console.log('[useTaskSSE] Manually closing connection');
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setIsConnected(false);
    }

    retryCountRef.current = 0;
  }, []);

  const reconnect = useCallback(() => {
    console.log('[useTaskSSE] Manual reconnect requested');

    isPausedRef.current = false;
    setConnectionState('connecting');

    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    retryCountRef.current = 0;
    initializingRef.current = false;
    setError(null);
    setIsConnected(false);
  }, []);

  return { isConnected, error, close, reconnect, connectionState };
}
