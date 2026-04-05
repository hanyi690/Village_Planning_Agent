/**
 * SSE Connection Hook
 *
 * Manages SSE connection lifecycle with batch optimization.
 * Extracted from PlanningProvider for better separation of concerns.
 *
 * Features:
 * - Automatic connection/disconnection based on taskId
 * - Batch processing for dimension_delta events (50ms window)
 * - Reconnection with exponential backoff
 * - State sync on reconnect
 */

import { useEffect, useRef, useCallback } from 'react';
import { planningApi } from '@/lib/api';
import { usePlanningStore } from '@/stores/planningStore';
import type { PlanningSSEEvent } from '@/lib/api/types';

// Internal batch event representation
interface BatchEvent {
  type: string;
  data?: unknown;
}

interface UseSSEConnectionOptions {
  taskId: string | null;
  enabled?: boolean;
  onReconnect?: () => void;
  resumeTrigger?: number; // Value changes trigger SSE reconnect
}

const MAX_RECONNECT_ATTEMPTS = 5;
const BATCH_WINDOW = 50; // ms
const MAX_BATCH_SIZE = 50; // Maximum events in queue before forced flush

export function useSSEConnection({
  taskId,
  enabled = true,
  onReconnect,
  resumeTrigger = 0,
}: UseSSEConnectionOptions): void {
  // Refs for connection management
  const sseConnectionRef = useRef<EventSource | null>(null);
  const prevTaskIdRef = useRef<string | null>(null);
  const prevResumeTriggerRef = useRef<number>(0);
  const reconnectAttemptsRef = useRef(0);

  // Batch processing refs
  const batchQueueRef = useRef<BatchEvent[]>([]);
  const batchTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Store actions
  const handleSSEEvent = usePlanningStore((state) => state.handleSSEEvent);
  const syncBackendState = usePlanningStore((state) => state.syncBackendState);

  // Process batched events - merge dimension_delta events by key, send critical events immediately
  const processBatch = useCallback(() => {
    const events = batchQueueRef.current;
    batchQueueRef.current = [];

    if (events.length === 0) return;

    // Critical event types that should never be merged/deferred
    const criticalEventTypes = ['dimension_start', 'dimension_complete', 'layer_completed', 'layer_started'];

    // Group events by type
    const dimensionDeltaMap = new Map<string, BatchEvent>();
    const criticalEvents: BatchEvent[] = [];
    const otherEvents: BatchEvent[] = [];

    for (const event of events) {
      if (criticalEventTypes.includes(event.type)) {
        // Critical events: send immediately, no merging
        criticalEvents.push(event);
      } else if (event.type === 'dimension_delta') {
        const data = event.data as { layer?: number; dimension_key?: string };
        const key = `${data.layer || 1}_${data.dimension_key || ''}`;
        // Keep only the last event for each dimension key
        dimensionDeltaMap.set(key, event);
      } else {
        otherEvents.push(event);
      }
    }

    // Dispatch critical events first (no delay)
    for (const event of criticalEvents) {
      handleSSEEvent(event);
    }

    // Dispatch merged dimension_delta events
    for (const event of dimensionDeltaMap.values()) {
      handleSSEEvent(event);
    }

    // Dispatch other events
    for (const event of otherEvents) {
      handleSSEEvent(event);
    }
  }, [handleSSEEvent]);

  // Enqueue event for batch processing
  const enqueueEvent = useCallback(
    (event: BatchEvent) => {
      batchQueueRef.current.push(event);

      // Force flush if queue exceeds max size
      if (batchQueueRef.current.length >= MAX_BATCH_SIZE) {
        if (batchTimeoutRef.current) {
          clearTimeout(batchTimeoutRef.current);
          batchTimeoutRef.current = null;
        }
        processBatch();
        return;
      }

      if (!batchTimeoutRef.current) {
        batchTimeoutRef.current = setTimeout(() => {
          batchTimeoutRef.current = null;
          processBatch();
        }, BATCH_WINDOW);
      }
    },
    [processBatch]
  );

  // Connect to SSE
  const connectSSE = useCallback(
    (taskIdParam: string) => {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
      }

      console.log('[useSSEConnection] Connecting to SSE for task:', taskIdParam);

      const es = planningApi.createStream(
        taskIdParam,
        (event: PlanningSSEEvent) => {
          reconnectAttemptsRef.current = 0;

          // Log dimension_complete events
          if (event.type === 'dimension_complete') {
            const data = event.data as { dimension_key?: string; layer?: number };
            console.log(
              `[useSSEConnection] dimension_complete RECEIVED: layer=${data.layer}, key=${data.dimension_key}`
            );
          }

          enqueueEvent({
            type: event.type,
            data: event.data,
          });
        },
        (error) => {
          console.error('[useSSEConnection] SSE error:', error);

          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttemptsRef.current++;
            const delay = Math.min(1000 * reconnectAttemptsRef.current, 5000);
            console.log(
              `[useSSEConnection] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`
            );
            setTimeout(() => {
              const currentTaskId = usePlanningStore.getState().taskId;
              if (currentTaskId) {
                connectSSE(currentTaskId);
              }
            }, delay);
          }
        },
        () => {
          console.log('[useSSEConnection] SSE reconnected, syncing state...');
          const currentTaskId = usePlanningStore.getState().taskId;
          if (currentTaskId) {
            planningApi.getStatus(currentTaskId).then((statusData) => {
              syncBackendState(statusData);
            });
          }
          onReconnect?.();
        }
      );

      console.log('[useSSEConnection] SSE connection created, readyState:', es.readyState);
      sseConnectionRef.current = es;
      return es;
    },
    [enqueueEvent, syncBackendState, onReconnect]
  );

  // Connection lifecycle
  useEffect(() => {
    if (!enabled || !taskId) {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
      return;
    }

    // Reconnect trigger: taskId change or resumeTrigger change
    const taskIdChanged = prevTaskIdRef.current !== taskId;
    const resumeTriggered = prevResumeTriggerRef.current !== resumeTrigger;
    const shouldReconnect = taskIdChanged || resumeTriggered;

    if (shouldReconnect) {
      prevTaskIdRef.current = taskId;
      prevResumeTriggerRef.current = resumeTrigger;

      // Log reconnect reason
      if (taskIdChanged) {
        console.log('[useSSEConnection] TaskId changed, reconnecting...');
      } else {
        console.log('[useSSEConnection] Resume triggered, reconnecting...');
      }

      connectSSE(taskId);
    }

    return () => {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
    };
  }, [taskId, enabled, resumeTrigger, connectSSE]);

  // Cleanup batch timeout on unmount
  useEffect(() => {
    return () => {
      if (batchTimeoutRef.current) {
        clearTimeout(batchTimeoutRef.current);
        batchTimeoutRef.current = null;
      }
      // Process remaining events in queue
      if (batchQueueRef.current.length > 0) {
        console.log('[useSSEConnection] Cleanup: flushing', batchQueueRef.current.length, 'queued events');
        processBatch();
      }
    };
  }, [processBatch]);
}

export default useSSEConnection;