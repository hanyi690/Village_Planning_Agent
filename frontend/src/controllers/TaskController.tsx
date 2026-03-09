/**
 * TaskController - 简化版状态管理
 *
 * ✅ SSOT 简化：
 * - 后端 LangGraph Checkpoint 为单一真实源
 * - 删除轮询逻辑，只依赖 SSE 推送
 * - SSE 断线重连后获取一次完整状态
 *
 * 功能:
 * - SSE 连接管理（唯一的状态更新渠道）
 * - 断线重连后调用 /status 获取完整状态
 * - 将状态同步到 Context
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { planningApi } from '../lib/api';

export interface TaskState {
  status: 'idle' | 'pending' | 'running' | 'paused' | 'reviewing' | 'revising' | 'completed' | 'failed';
  current_layer: number | null;
  previous_layer: number | null;
  layer_1_completed: boolean;
  layer_2_completed: boolean;
  layer_3_completed: boolean;
  pause_after_step: boolean;
  last_checkpoint_id: string | null;
  execution_error: string | null;
  execution_complete: boolean;
  progress: number | null;
}

export interface TaskControllerActions {
  approve: () => Promise<void>;
  reject: (feedback: string, dimensions?: string[]) => Promise<void>;
  rollback: (checkpointId: string) => Promise<void>;
}

export function useTaskController(
  taskId: string | null,
  callbacks: {
    onTextDelta?: (text: string, layer?: number) => void;
    onDimensionDelta?: (dimensionKey: string, delta: string, accumulated: string, layer?: number) => void;
    onDimensionComplete?: (dimensionKey: string, dimensionName: string, fullContent: string, layer?: number) => void;
    onLayerStarted?: (layer: number, layerName: string) => void;
    onLayerCompleted?: (layer: number, reportContent: string, dimensionReports: Record<string, string>) => void;
    onPause?: (layer: number, checkpointId: string) => void;
    onDimensionRevised?: (data: {
      dimension: string;
      layer: number;
      oldContent: string;
      newContent: string;
      feedback: string;
      isTarget: boolean;
      revisionType: string;
      timestamp: string;
    }) => void;
    onError?: (error: string) => void;
  } = {}
): [TaskState, TaskControllerActions] {
  const [state, setState] = useState<TaskState>({
    status: 'idle',
    current_layer: null,
    previous_layer: null,
    layer_1_completed: false,
    layer_2_completed: false,
    layer_3_completed: false,
    pause_after_step: false,
    last_checkpoint_id: null,
    execution_error: null,
    execution_complete: false,
    progress: null,
  });

  // 🔧 SSE 重连触发器：在 approve/reject 后更新此值来触发 SSE 重连
  const [sseReconnectKey, setSseReconnectKey] = useState(0);

  const callbacksRef = useRef(callbacks);
  const sseConnectionRef = useRef<EventSource | null>(null);
  const prevTaskIdRef = useRef<string | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 5;

  // Update callbacks ref
  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  // ✅ 简化：只在 SSE 断线重连时获取状态
  const fetchStatus = useCallback(async () => {
    if (!taskId) return;

    try {
      const statusData = await planningApi.getStatus(taskId);
      
      setState({
        status: statusData.status as TaskState['status'],
        current_layer: statusData.current_layer ?? null,
        previous_layer: statusData.previous_layer ?? null,
        layer_1_completed: statusData.layer_1_completed,
        layer_2_completed: statusData.layer_2_completed,
        layer_3_completed: statusData.layer_3_completed,
        pause_after_step: statusData.pause_after_step,
        last_checkpoint_id: statusData.last_checkpoint_id ?? null,
        execution_error: statusData.execution_error ?? null,
        execution_complete: statusData.execution_complete,
        progress: statusData.progress ?? null,
      });

      console.log('[TaskController] ✅ 状态同步完成:', {
        status: statusData.status,
        current_layer: statusData.current_layer,
        pause_after_step: statusData.pause_after_step,
      });

    } catch (error: any) {
      console.error('[TaskController] 获取状态失败:', error);
    }
  }, [taskId]);

  // ✅ SSE 连接管理（唯一的状态更新渠道）
  // 添加断线重连逻辑
  useEffect(() => {
    if (!taskId) {
      if (sseConnectionRef.current) {
        console.log('[TaskController] === SSE 连接关闭 ===');
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
      return;
    }

    const taskIdChanged = prevTaskIdRef.current !== taskId;
    prevTaskIdRef.current = taskId;

    // 🔧 修改：如果 taskId 没变但有 SSE 重连请求，也重新建立连接
    if (!taskIdChanged && sseConnectionRef.current && sseReconnectKey === 0) {
      return;
    }

    // 关闭旧连接
    if (sseConnectionRef.current) {
      console.log('[TaskController] 关闭旧 SSE 连接');
      sseConnectionRef.current.close();
    }

    // ✅ 创建新连接（带断线重连逻辑）
    const createSSEConnection = () => {
      console.log('[TaskController] === SSE 连接建立 ===');
      console.log('[TaskController] taskId:', taskId);
      
      const es = planningApi.createStream(
        taskId,
        (event) => {
          const eventType = event.type;
          
          // 重置重连计数（成功收到事件）
          reconnectAttemptsRef.current = 0;
          
          if (['layer_completed', 'layer_started', 'dimension_complete', 'pause', 'stream_paused', 'connected'].includes(eventType)) {
            console.log(`[TaskController] 📩 SSE 事件: ${eventType}`, event.data);
          }
          
          if (eventType === 'content_delta') {
            callbacksRef.current.onTextDelta?.(
              event.data?.delta || '',
              typeof event.data?.layer === 'number' ? event.data.layer : undefined
            );
          } else if (eventType === 'dimension_delta') {
            const data = event.data as {
              dimension_key?: string;
              delta?: string;
              accumulated?: string;
              layer?: number;
            } || {};
            
            callbacksRef.current.onDimensionDelta?.(
              data.dimension_key || '',
              data.delta || '',
              data.accumulated || '',
              data.layer
            );
          } else if (eventType === 'dimension_complete') {
            const data = event.data as {
              dimension_key?: string;
              dimension_name?: string;
              full_content?: string;
              layer?: number;
            } || {};
            
            console.log(`[TaskController] ✅ dimension_complete: layer=${data.layer}, dimension=${data.dimension_key}`);
            
            callbacksRef.current.onDimensionComplete?.(
              data.dimension_key || '',
              data.dimension_name || '',
              data.full_content || '',
              data.layer
            );
          } else if (eventType === 'layer_started') {
            const data = event.data as {
              layer?: number;
              layer_number?: number;
              layer_name?: string;
            } || {};

            console.log(`[TaskController] 🚀 layer_started: layer=${data.layer || data.layer_number}`);

            callbacksRef.current.onLayerStarted?.(
              data.layer || data.layer_number || 1,
              data.layer_name || ''
            );
          } else if (eventType === 'layer_completed') {
            const data = event.data as {
              layer?: number;
              has_data?: boolean;
              dimension_count?: number;
            } || {};

            console.log(`[TaskController] ✅ layer_completed signal: Layer ${data.layer}`);

            callbacksRef.current.onLayerCompleted?.(
              data.layer || 1,
              '',
              {}
            );
          } else if (eventType === 'pause') {
            const data = event.data as {
              current_layer?: number;
              checkpoint_id?: string;
            } || {};
            
            console.log(`[TaskController] ⏸️ pause: layer=${data.current_layer}`);
            
            callbacksRef.current.onPause?.(
              data.current_layer || 1,
              data.checkpoint_id || ''
            );
          } else if (eventType === 'stream_paused') {
            console.log(`[TaskController] 🔚 stream_paused: SSE 流关闭`);
          } else if (eventType === 'dimension_revised') {
            const data = event.data as {
              dimension?: string;
              layer?: number;
              new_content?: string;
              timestamp?: string;
            } || {};
            
            callbacksRef.current.onDimensionRevised?.({
              dimension: data.dimension || '',
              layer: data.layer || 1,
              oldContent: '',
              newContent: data.new_content || '',
              feedback: '',
              isTarget: true,
              revisionType: '',
              timestamp: data.timestamp || new Date().toISOString(),
            });
          } else if (eventType === 'error') {
            callbacksRef.current.onError?.(
              event.data?.error || event.data?.message || 'Unknown error'
            );
          }
        },
        (error) => {
          console.error('[TaskController] SSE error:', error);
          
          // ✅ 断线重连逻辑
          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttemptsRef.current++;
            const delay = Math.min(1000 * reconnectAttemptsRef.current, 5000);
            
            console.log(`[TaskController] SSE 断线，${delay}ms 后重连 (尝试 ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`);
            
            setTimeout(() => {
              // 重连前先获取一次完整状态
              fetchStatus().then(() => {
                if (sseConnectionRef.current) {
                  sseConnectionRef.current.close();
                }
                sseConnectionRef.current = createSSEConnection();
              });
            }, delay);
          } else {
            console.error('[TaskController] SSE 重连失败，已达到最大重试次数');
            callbacksRef.current.onError?.('SSE connection failed after multiple retries');
          }
        }
      );

      return es;
    };

    sseConnectionRef.current = createSSEConnection();

    return () => {
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
    };
  }, [taskId, fetchStatus, sseReconnectKey]);

  // Action methods
  const actions: TaskControllerActions = {
    approve: useCallback(async () => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.approveReview(taskId);
      // 批准后获取最新状态
      await fetchStatus();
      // 🔧 触发 SSE 重连（批准后 Layer 2 需要重新订阅）
      console.log('[TaskController] 批准完成，触发 SSE 重连');
      setSseReconnectKey(prev => prev + 1);
    }, [taskId, fetchStatus]),

    reject: useCallback(async (feedback: string, dimensions?: string[]) => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.rejectReview(taskId, feedback, dimensions);
      // 拒绝后获取最新状态
      await fetchStatus();
      // 🔧 触发 SSE 重连（拒绝后修正需要重新订阅）
      console.log('[TaskController] 拒绝完成，触发 SSE 重连');
      setSseReconnectKey(prev => prev + 1);
    }, [taskId, fetchStatus]),

    rollback: useCallback(async (checkpointId: string) => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.rollbackCheckpoint(taskId, checkpointId);
      // 🔧 触发 SSE 重连（回滚后需要重新订阅）
      console.log('[TaskController] 回滚完成，触发 SSE 重连');
      setSseReconnectKey(prev => prev + 1);
    }, [taskId]),
  };

  return [state, actions];
}
