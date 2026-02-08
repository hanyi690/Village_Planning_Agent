/**
 * useTaskSSE Hook
 * SSE连接处理Hook - 管理任务SSE连接和事件处理
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { planningApi, PlanningSSEEvent } from '@/lib/api';

type ThinkingState = 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';

export interface UseTaskSSECallbacks {
  onStatusUpdate?: (data: any) => void;
  onLayerCompleted?: (data: any) => void;
  onComplete?: (result: any) => void;
  onError?: (error: string) => void;
  onPause?: (data: any) => void;
  onReviewRequest?: (data: any) => void;
  onMessage?: (event: PlanningSSEEvent) => void;
  onTextChunk?: (chunk: string, messageId: string) => void;
  onThinkingStart?: (state: ThinkingState, message?: string) => void;
  onThinkingEnd?: () => void;
  onContentDelta?: (delta: string, layer: number, metadata: any) => void;
}

// Event handler mapping
const EVENT_HANDLERS: Record<
  PlanningSSEEvent['type'],
  (event: PlanningSSEEvent, callbacks: UseTaskSSECallbacks) => void
> = {
  layer_started: (event, callbacks) => callbacks.onStatusUpdate?.(event.data),
  layer_completed: (event, callbacks) => {
    console.log('[useTaskSSE] Layer completed:', event.data);
    callbacks.onLayerCompleted?.(event.data);
  },
  checkpoint_saved: (event, callbacks) => callbacks.onStatusUpdate?.(event.data),
  pause: (event, callbacks) => callbacks.onPause?.(event.data),
  progress: (event, callbacks) => callbacks.onStatusUpdate?.(event.data),
  resumed: (event, callbacks) => callbacks.onStatusUpdate?.(event.data),
  completed: (event, callbacks) => {
    console.log('[useTaskSSE] Task completed');
    callbacks.onComplete?.(event.data);
  },
  complete: (event, callbacks) => {
    console.log('[useTaskSSE] Task completed');
    callbacks.onComplete?.(event.data);
  },
  error: (event, callbacks) => {
    console.error('[useTaskSSE] Task error:', event.data);
    callbacks.onError?.(event.data?.error || event.data?.message || '任务失败');
  },
  text_chunk: (event, callbacks) => {
    console.log('[useTaskSSE] Text chunk received:', event.data?.chunk?.substring(0, 50));
    callbacks.onTextChunk?.(event.data?.chunk || '', event.data?.message_id || '');
  },
  thinking_start: (event, callbacks) => {
    const state = (event.data?.state || 'processing') as ThinkingState;
    console.log('[useTaskSSE] Thinking started:', state);
    callbacks.onThinkingStart?.(state, event.data?.message);
  },
  thinking: (event, callbacks) => {
    const state = (event.data?.state || 'processing') as ThinkingState;
    console.log('[useTaskSSE] Thinking started:', state);
    callbacks.onThinkingStart?.(state, event.data?.message);
  },
  thinking_end: (event, callbacks) => {
    console.log('[useTaskSSE] Thinking ended');
    callbacks.onThinkingEnd?.();
  },
  review_request: (event, callbacks) => {
    console.log('[useTaskSSE] Review request received:', event.data);
    callbacks.onReviewRequest?.(event.data);
  },
  content_delta: (event, callbacks) => {
    const delta = event.data?.delta || '';
    const layer = event.data?.current_layer || 1;
    console.log('[useTaskSSE] Content delta received:', delta.substring(0, 50));
    callbacks.onContentDelta?.(delta, layer, event.data);
  },
};

export function useTaskSSE(taskId: string | null | undefined, callbacks: UseTaskSSECallbacks) {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const initializingRef = useRef(false);

  useEffect(() => {
    if (!taskId) {
      setIsConnected(false);
      return;
    }

    if (initializingRef.current) {
      console.log('[useTaskSSE] Already initializing, skipping duplicate connection');
      return;
    }

    initializingRef.current = true;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    console.log(`[useTaskSSE] ===== Creating SSE for task: ${taskId} =====`);

    try {
      const es = planningApi.createStream(
        taskId,
        (event: PlanningSSEEvent) => {
          const { type } = event;
          console.log(`[useTaskSSE] ✓ Event: ${type}`);

          setError(null);

          // Call general message handler first
          callbacks.onMessage?.(event);

          // Call specific event handler
          EVENT_HANDLERS[type]?.(event, callbacks);
        },
        (err) => {
          console.error('[useTaskSSE] ✗ Error:', err);
          console.error('[useTaskSSE] ReadyState:', es?.readyState);
          setError('连接错误');
          setIsConnected(false);
          callbacks.onError?.('连接错误');
        }
      );

      es.onopen = () => {
        console.log('[useTaskSSE] ✓ Connection opened successfully');
      };

      eventSourceRef.current = es;
      setIsConnected(true);
      console.log('[useTaskSSE] EventSource created, waiting for connection...');

    } catch (err) {
      console.error('[useTaskSSE] ✗ Failed to create EventSource:', err);
      setError('无法连接到服务器');
      setIsConnected(false);
    }

    return () => {
      if (eventSourceRef.current) {
        console.log('[useTaskSSE] Closing connection');
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setIsConnected(false);
      initializingRef.current = false;
    };
  }, [taskId, callbacks]);

  const close = useCallback(() => {
    if (eventSourceRef.current) {
      console.log('[useTaskSSE] Manually closing connection');
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setIsConnected(false);
    }
  }, []);

  const reconnect = useCallback(() => {
    console.log('[useTaskSSE] Manual reconnect requested');
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    initializingRef.current = false;
    setIsConnected(false);
  }, []);

  return { isConnected, error, close, reconnect };
}
