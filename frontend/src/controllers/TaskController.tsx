/**
 * TaskController - Headless state management for planning tasks
 *
 * This hook provides:
 * - Polling /status endpoint for reliable state updates
 * - SSE connection lifecycle management based on status
 * - Clear API for UI components
 * - Single source of truth: database state
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { planningApi } from '../lib/api';

export interface TaskState {
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';
  currentLayer: number | null;
  layer1Completed: boolean;
  layer2Completed: boolean;
  layer3Completed: boolean;
  pauseAfterStep: boolean;
  waitingForReview: boolean;
  lastCheckpointId: string | null;
  executionError: string | null;
  executionComplete: boolean;
  progress: number | null;
}

export interface TaskControllerCallbacks {
  onLayerCompleted?: (layer: number) => void;
  onPause?: (layer: number) => void;
  onComplete?: () => void;
  onError?: (error: string) => void;
  onTextDelta?: (text: string, layer?: number) => void;
}

export interface TaskControllerActions {
  approve: () => Promise<void>;
  reject: (feedback: string) => Promise<void>;
  rollback: (checkpointId: string) => Promise<void>;
}

export function useTaskController(
  taskId: string | null,
  callbacks: TaskControllerCallbacks = {}
): [TaskState, TaskControllerActions] {
  const [state, setState] = useState<TaskState>({
    status: 'idle',
    currentLayer: null,
    layer1Completed: false,
    layer2Completed: false,
    layer3Completed: false,
    pauseAfterStep: false,
    waitingForReview: false,
    lastCheckpointId: null,
    executionError: null,
    executionComplete: false,
    progress: null,
  });

  const prevStateRef = useRef<TaskState>(state);
  const callbacksRef = useRef<TaskControllerCallbacks>(callbacks);
  const sseConnectionRef = useRef<EventSource | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const triggeredEventsRef = useRef<Set<string>>(new Set());

  // ✅ NEW: Track all timeout IDs for cleanup
  const timeoutIdsRef = useRef<Set<NodeJS.Timeout>>(new Set());

  // ✅ 新增：记录已触发暂停的最高层级，用于检测状态抖动
  const lastTriggeredPauseLayerRef = useRef<number>(0);

  // Update callbacks ref when callbacks change
  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  // Reset deduplication set when taskId changes
  useEffect(() => {
    triggeredEventsRef.current.clear();
    prevStateRef.current = state;
    // ✅ 新增：重置已触发的最高暂停层级
    lastTriggeredPauseLayerRef.current = 0;
    console.log(`[TaskController] TaskId changed, reset state tracking`);
  }, [taskId]);

  // Poll status endpoint every 2 seconds
  useEffect(() => {
    if (!taskId) return;

    const pollStatus = async () => {
      try {
        const statusData = await planningApi.getStatus(taskId);

        console.log(`[TaskController] Poll result:`, {
          taskId,
          status: statusData.status,
          layer: statusData.current_layer,
          layer1: statusData.layer_1_completed,
          layer2: statusData.layer_2_completed,
          layer3: statusData.layer_3_completed,
          pause: statusData.pause_after_step,
        });

        setState((currentState) => {
          const newState = {
            status: statusData.status as TaskState['status'],
            currentLayer: statusData.current_layer ?? null,
            layer1Completed: statusData.layer_1_completed,
            layer2Completed: statusData.layer_2_completed,
            layer3Completed: statusData.layer_3_completed,
            pauseAfterStep: statusData.pause_after_step,
            waitingForReview: statusData.waiting_for_review,
            lastCheckpointId: statusData.last_checkpoint_id ?? null,
            executionError: statusData.execution_error ?? null,
            executionComplete: statusData.execution_complete,
            progress: statusData.progress ?? null,
          };

          const prev = prevStateRef.current;
          console.log(`[TaskController] State change:`, {
            layer1: `${prev.layer1Completed} -> ${newState.layer1Completed}`,
            layer2: `${prev.layer2Completed} -> ${newState.layer2Completed}`,
            layer3: `${prev.layer3Completed} -> ${newState.layer3Completed}`,
            pause: `${prev.pauseAfterStep} -> ${newState.pauseAfterStep}`,
          });

          // Collect events to trigger - defer execution until after render
          const eventsToTrigger: Array<() => void> = [];

          // Layer completion detection with deduplication
          const layers = [
            { key: 'layer1', number: 1, completed: newState.layer1Completed },
            { key: 'layer2', number: 2, completed: newState.layer2Completed },
            { key: 'layer3', number: 3, completed: newState.layer3Completed },
          ] as const;

          for (const layer of layers) {
            const prevCompleted = layer.key === 'layer1' ? prev.layer1Completed :
                               layer.key === 'layer2' ? prev.layer2Completed :
                               prev.layer3Completed;
            const eventKey = `${layer.key}_completed_${layer.completed}`;

            if (!prevCompleted && layer.completed && !triggeredEventsRef.current.has(eventKey)) {
              const layerNum = layer.number;
              eventsToTrigger.push(() => {
                console.log(`[TaskController] Layer ${layerNum} completed, triggering callback`);
                callbacksRef.current.onLayerCompleted?.(layerNum);
              });
              triggeredEventsRef.current.add(eventKey);
            } else if (!prevCompleted && layer.completed && triggeredEventsRef.current.has(eventKey)) {
              console.log(`[TaskController] Layer ${layer.number} completion already triggered, skipping`);
            }
          }

          // Pause detection with layer-scoped deduplication
          const isPaused = newState.pauseAfterStep || newState.status === 'paused';
          const wasPaused = prev.pauseAfterStep || prev.status === 'paused';

          if (isPaused && !wasPaused) {
            const currentLayer = newState.currentLayer ?? 1;
            const pauseKey = `pause_${taskId}_layer_${currentLayer}`;

            // ✅ 新增：状态抖动检测
            // 如果当前层级 <= 已触发暂停的最高层级，说明是状态回滚（如LLM失败导致的回退）
            // 这种情况下不应该再次触发 onPause 回调
            if (currentLayer <= lastTriggeredPauseLayerRef.current) {
              console.log(`[TaskController] 检测到状态抖动：Layer ${currentLayer} <= 已触发的最高层级 ${lastTriggeredPauseLayerRef.current}，跳过 onPause`);
              console.log(`[TaskController] 这可能是由于 LLM 调用失败导致的状态回滚`);
            } else if (!triggeredEventsRef.current.has(pauseKey)) {
              eventsToTrigger.push(() => {
                console.log(`[TaskController] Pause detected at Layer ${currentLayer}`);
                callbacksRef.current.onPause?.(currentLayer);
              });
              triggeredEventsRef.current.add(pauseKey);

              // ✅ 新增：更新已触发的最高层级
              lastTriggeredPauseLayerRef.current = Math.max(lastTriggeredPauseLayerRef.current, currentLayer);
              console.log(`[TaskController] 更新已触发的最高暂停层级: ${lastTriggeredPauseLayerRef.current}`);

              // Auto-cleanup after 5 minutes to prevent memory leaks
              // ✅ FIXED: Store timeout ID for cleanup
              const timeoutId = setTimeout(() => {
                triggeredEventsRef.current.delete(pauseKey);
                timeoutIdsRef.current.delete(timeoutId);
                console.log(`[TaskController] Cleanup pause key ${pauseKey} after timeout`);
              }, 5 * 60 * 1000);

              timeoutIdsRef.current.add(timeoutId);
            } else {
              console.log(`[TaskController] Pause for Layer ${currentLayer} already triggered, skipping`);
            }
          }

          // Completion detection with deduplication
          const completeKey = `complete_${newState.executionComplete}_${newState.status}`;
          if (!prev.executionComplete && newState.executionComplete &&
              newState.status === 'completed' && !triggeredEventsRef.current.has(completeKey)) {
            eventsToTrigger.push(() => {
              callbacksRef.current.onComplete?.();
            });
            triggeredEventsRef.current.add(completeKey);
          }

          // Error detection with deduplication
          if (!prev.executionError && newState.executionError) {
            const errorKey = `error_${newState.executionError}`;
            if (!triggeredEventsRef.current.has(errorKey)) {
              const errorMsg = newState.executionError;
              eventsToTrigger.push(() => {
                callbacksRef.current.onError?.(errorMsg);
              });
              triggeredEventsRef.current.add(errorKey);
            }
          }

          // ✅ 新增：致命错误检测 - 当状态为 failed 时停止轮询
          if (newState.status === 'failed' && newState.executionError) {
            console.log(`[TaskController] 致命错误检测：状态为 failed，错误信息: ${newState.executionError}`);
            // 注意：不在这里停止轮询，让组件决定是否停止
          }

          // Defer all callback execution until after render to avoid "Cannot update during rendering" error
          if (eventsToTrigger.length > 0) {
            queueMicrotask(() => {
              eventsToTrigger.forEach(fn => fn());
            });
          }

          return newState;
        });
      } catch (error) {
        console.error('[TaskController] Poll error:', error);
      }
    };

    // ✅ NEW: Determine if polling should stop
    const shouldStopPolling = (taskState: TaskState): boolean => {
      return (
        !taskId ||
        taskState.status === 'completed' ||
        taskState.status === 'failed' ||
        (taskState.executionComplete && taskState.status !== 'revising')
      );
    };

    // Initial poll
    pollStatus();

  // ✅ FIXED: Add stop polling logic
    if (shouldStopPolling(state)) {
      console.log('[TaskController] Stopping polling - terminal state reached');
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    } else {
      // Set up polling interval
      pollingIntervalRef.current = setInterval(pollStatus, 2000);
    }

    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
    };
  }, [taskId]); // ✅ Only re-evaluate when taskId changes

  // Manage SSE connection based on status
  useEffect(() => {
    if (!taskId) return;

    // Only connect SSE when status is 'running'
    if (state.status === 'running') {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
      }

      const es = planningApi.createStream(
        taskId,
        (event) => {
          const eventType = event.type;
          if (eventType === 'content_delta') {
            const text = event.data?.delta || '';
            const layer = event.data?.layer;
            const layerNum = typeof layer === 'number' ? layer : undefined;
            callbacksRef.current.onTextDelta?.(text, layerNum);
          } else if (eventType === 'error') {
            callbacksRef.current.onError?.(event.data?.error || event.data?.message || 'Unknown error');
          }
        },
        (error) => {
          console.error('[TaskController] SSE error:', error);
        }
      );

      sseConnectionRef.current = es;

      return () => {
        if (sseConnectionRef.current) {
          sseConnectionRef.current.close();
          sseConnectionRef.current = null;
        }
      };
    } else {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
    }
  }, [taskId, state.status]);

  // Update previous state ref after state changes
  useEffect(() => {
    prevStateRef.current = state;
  }, [state]);

  // Action methods
  const actions: TaskControllerActions = {
    approve: useCallback(async () => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.approveReview(taskId);
    }, [taskId]),

    reject: useCallback(async (feedback: string) => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.rejectReview(taskId, feedback);
    }, [taskId]),

    rollback: useCallback(async (checkpointId: string) => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.rollbackCheckpoint(taskId, checkpointId);
    }, [taskId]),
  };

  // ✅ NEW: Cleanup effect - clear all timeouts on unmount
  useEffect(() => {
    return () => {
      // Clear all pending timeouts
      timeoutIdsRef.current.forEach(id => clearTimeout(id));
      timeoutIdsRef.current.clear();
      console.log('[TaskController] Cleaned up all timeouts');
    };
  }, []);

  return [state, actions];
}
