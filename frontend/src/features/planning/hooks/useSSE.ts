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
import { buildDimensionProgressKey } from '@/lib/utils/message-helpers';
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

  // Delta override tracking - track dimensions that have received complete events
  const completedDimensionKeysRef = useRef<Set<string>>(new Set());

  // Store actions
  const handleSSEEvent = usePlanningStore((state) => state.handleSSEEvent);
  const syncBackendState = usePlanningStore((state) => state.syncBackendState);

  // Process batched events - merge dimension_delta events by key, send critical events immediately
  // Implements override mechanism: critical events skip pending delta events
  const processBatch = useCallback(() => {
    const events = batchQueueRef.current;
    batchQueueRef.current = [];

    if (events.length === 0) return;

    // Critical event types that should never be merged/deferred
    const criticalEventTypes = ['dimension_start', 'dimension_complete', 'layer_completed', 'layer_started'];

    // Keep last N delta events per key for better accumulated content accuracy
    const MAX_DELTA_PER_KEY = 3;
    const dimensionDeltaMap = new Map<string, BatchEvent[]>();
    const criticalEvents: BatchEvent[] = [];
    const otherEvents: BatchEvent[] = [];

    // Track dimensions/layers that have received complete events
    // These will skip pending delta events to avoid redundant processing
    const completedKeys = completedDimensionKeysRef.current;

    for (const event of events) {
      if (criticalEventTypes.includes(event.type)) {
        // Critical events: send immediately, no merging
        criticalEvents.push(event);

        // Override mechanism: mark dimension as completed when dimension_complete arrives
        if (event.type === 'dimension_complete') {
          const data = event.data as { layer?: number; dimension_key?: string };
          const key = buildDimensionProgressKey(data.layer || 1, data.dimension_key || '');
          completedKeys.add(key);
        }

        // Override mechanism: clear all layer deltas when layer_completed arrives
        if (event.type === 'layer_completed') {
          const data = event.data as { layer?: number };
          const layer = data.layer || 1;
          // Remove all delta events for this layer from the map
          for (const k of dimensionDeltaMap.keys()) {
            if (k.startsWith(`${layer}_`)) {
              dimensionDeltaMap.delete(k);
            }
          }
          // Clear completed keys for next layer
          completedKeys.clear();
        }

        // Reset completed keys when a new layer starts
        if (event.type === 'layer_started') {
          completedKeys.clear();
        }
      } else if (event.type === 'dimension_delta') {
        const data = event.data as { layer?: number; dimension_key?: string };
        const key = buildDimensionProgressKey(data.layer || 1, data.dimension_key || '');

        // Skip delta if dimension already received complete event
        if (completedKeys.has(key)) {
          continue;
        }

        // Keep last N events for each dimension key, take latest accumulated
        let deltaList = dimensionDeltaMap.get(key);
        if (!deltaList) {
          deltaList = [];
          dimensionDeltaMap.set(key, deltaList);
        }
        deltaList.push(event);
        if (deltaList.length > MAX_DELTA_PER_KEY) {
          deltaList.shift();
        }
      } else {
        otherEvents.push(event);
      }
    }

    // Dispatch critical events first (no delay)
    for (const event of criticalEvents) {
      handleSSEEvent(event);
    }

    // Dispatch dimension_delta events - use the latest one (has most accumulated content)
    // Skip any delta events for dimensions that have received complete events
    for (const [key, deltaList] of dimensionDeltaMap) {
      // Double-check: skip if dimension_complete was processed in this batch
      if (completedKeys.has(key)) {
        continue;
      }
      const latestDelta = deltaList[deltaList.length - 1];
      handleSSEEvent(latestDelta);
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
      // Close old connection first to prevent race conditions
      if (sseConnectionRef.current) {
        const oldEs = sseConnectionRef.current;
        sseConnectionRef.current = null;  // Clear ref immediately to prevent reuse
        oldEs.close();
        console.log('[useSSEConnection] Closed old SSE connection before reconnect');
      }

      const es = planningApi.createStream(
        taskIdParam,
        (event: PlanningSSEEvent) => {
          reconnectAttemptsRef.current = 0;

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
            setTimeout(() => {
              const currentTaskId = usePlanningStore.getState().taskId;
              if (currentTaskId) {
                connectSSE(currentTaskId);
              }
            }, delay);
          }
        },
        () => {
          const currentTaskId = usePlanningStore.getState().taskId;
          if (currentTaskId) {
            // Sync missed events using seq-based sync API
            const lastSeq = usePlanningStore.getState().lastProcessedSeq;
            planningApi.syncEvents(currentTaskId, lastSeq).then((syncResult) => {
              if (syncResult.events.length > 0) {
                console.log(`[useSSEConnection] Synced ${syncResult.events.length} missed events from seq ${lastSeq}`);
                // Process missed events
                for (const event of syncResult.events) {
                  enqueueEvent({
                    type: event.type,
                    data: event.data,
                  });
                }
              }
            }).catch((err) => {
              console.warn('[useSSEConnection] Sync API failed, falling back to status sync:', err);
            });
            // Also sync backend state for non-event data
            planningApi.getStatus(currentTaskId).then((statusData) => {
              syncBackendState(statusData);
            });
          }
          onReconnect?.();
        }
      );

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
        processBatch();
      }
    };
  }, [processBatch]);
}

export default useSSEConnection;