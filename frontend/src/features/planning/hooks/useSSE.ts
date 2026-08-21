/**
 * SSE Connection Hook
 *
 * Manages SSE connection lifecycle with batch optimization.
 * Extracted from PlanningProvider for better separation of concerns.
 *
 * Features:
 * - Automatic connection/disconnection based on sessionId
 * - Batch processing for dimension_delta events (50ms window)
 * - Reconnection with exponential backoff
 * - State sync on reconnect
 */

import { useEffect, useRef, useCallback } from 'react';
import { planningApi } from '../api';
import { usePlanningStore } from '../store/planningStore';
import { buildDimensionProgressKey } from '@/features/planning/utils/message-helpers';
import { bootstrapPlanningSession } from '@/features/planning/utils/session-bootstrap';
import { syncMissedPlanningEvents } from '@/features/planning/utils/event-sync';
import type { PlanningSSEEvent } from '../api/types';

// Internal batch event representation
interface BatchEvent {
  type: string;
  data?: unknown;
}

interface UseSSEConnectionOptions {
  sessionId: string | null;
  enabled?: boolean;
  onReconnect?: () => void;
  resumeTrigger?: number; // Value changes trigger SSE reconnect
}

const MAX_RECONNECT_ATTEMPTS = 5;
const BATCH_WINDOW = 30; // ms
const MAX_BATCH_SIZE = 50; // Maximum events in queue before forced flush

export function useSSEConnection({
  sessionId,
  enabled = true,
  onReconnect,
  resumeTrigger = 0,
}: UseSSEConnectionOptions): void {
  // Refs for connection management
  const sseConnectionRef = useRef<EventSource | null>(null);
  const prevSessionIdRef = useRef<string | null>(null);
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

    // ⚠️ IMPORTANT: See SSEPublisher docstring for the full checklist when adding new SSE events.
    // Critical event types that should never be merged/deferred by batch processing
    const criticalEventTypes = [
      'dimension_start',
      'dimension_complete',
      'layer_completed',
      'layer_started',
      'tool_started',
      'tool_status',
      // NEW: RAG & Cascade events for Demo System
      'rag_query',
      'rag_result',
      'cascade_impact',
      'cascade_complete',
      'state_sync',
      'layer_paused',
      'execution_resumed',
      'completed',
      // v1 delivery / resync / human review — must never be merged or deferred
      'delivery_ready',
      'resync_required',
      'human_review',
      'human_review_paused',
      // GIS events —图层渲染必须立即可见
      'gis_result',
      'gis_layer_update',
    ];

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
        if (!event.data) continue;
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

    // Dispatch dimension_delta events first so accumulated content is available
    // before dimension_complete (which may arrive in the same batch).
    for (const [key, deltaList] of dimensionDeltaMap) {
      if (completedKeys.has(key)) {
        continue;
      }
      const latestDelta = deltaList[deltaList.length - 1];
      handleSSEEvent(latestDelta);
    }

    // Dispatch critical events (dimension_complete after deltas in same batch)
    for (const event of criticalEvents) {
      if (event.type === 'dimension_complete') {
        const data = event.data as { layer?: number; dimension_key?: string };
        const key = buildDimensionProgressKey(data.layer || 1, data.dimension_key || '');
        completedKeys.add(key);
      }
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
    (sessionIdParam: string) => {
      // Close old connection first to prevent race conditions
      if (sseConnectionRef.current) {
        const oldEs = sseConnectionRef.current;
        sseConnectionRef.current = null;  // Clear ref immediately to prevent reuse
        oldEs.close();
        console.log('[useSSEConnection] Closed old SSE connection before reconnect');
      }

      const es = planningApi.createStream(
        sessionIdParam,
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
              const currentSessionId = usePlanningStore.getState().sessionId;
              if (currentSessionId) {
                connectSSE(currentSessionId);
              }
            }, delay);
          }
        },
        () => {
          const currentSessionId = usePlanningStore.getState().sessionId;
          if (currentSessionId) {
            planningApi.getStatus(currentSessionId).then((statusData) => {
              syncBackendState(statusData);
              return syncMissedPlanningEvents(currentSessionId);
            }).then((syncResult) => {
              if (syncResult?.resync_required) {
                console.warn('[useSSEConnection] resync_required: full REST recovery needed');
              } else if (syncResult && syncResult.applied > 0) {
                console.log(`[useSSEConnection] Synced ${syncResult.applied} missed events`);
              }
            }).catch((err) => {
              console.warn('[useSSEConnection] Reconnect sync failed:', err);
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
    if (!enabled || !sessionId) {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
      // Drop the previous session marker so a later remount with the same
      // sessionId still reconnects (React Strict Mode closes EventSource on
      // the first effect cleanup).
      if (!sessionId) {
        prevSessionIdRef.current = null;
      }
      return;
    }

    // Reconnect when session/resume changes, OR when cleanup left us without
    // a live EventSource (common under Strict Mode double-mount).
    const sessionIdChanged = prevSessionIdRef.current !== sessionId;
    const resumeTriggered = prevResumeTriggerRef.current !== resumeTrigger;
    const connectionMissing = !sseConnectionRef.current;
    const shouldReconnect = sessionIdChanged || resumeTriggered || connectionMissing;

    if (shouldReconnect) {
      if (sessionIdChanged) {
        completedDimensionKeysRef.current.clear();
        batchQueueRef.current = [];
        if (batchTimeoutRef.current) {
          clearTimeout(batchTimeoutRef.current);
          batchTimeoutRef.current = null;
        }
      }
      prevSessionIdRef.current = sessionId;
      prevResumeTriggerRef.current = resumeTrigger;

      // Only re-bootstrap on a real session change / resume — not on the
      // Strict Mode reconnect that only restores the EventSource.
      if (sessionIdChanged || resumeTriggered) {
        void bootstrapPlanningSession(sessionId).catch((error) => {
          console.warn('[useSSEConnection] Session bootstrap failed:', error);
        });
      }
      connectSSE(sessionId);
    }

    return () => {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
    };
  }, [sessionId, enabled, resumeTrigger, connectSSE]);

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