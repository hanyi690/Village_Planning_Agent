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
  status:
    | 'idle'
    | 'pending'
    | 'running'
    | 'paused'
    | 'reviewing'
    | 'revising'
    | 'completed'
    | 'failed';
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
    onDimensionDelta?: (
      dimensionKey: string,
      delta: string,
      accumulated: string,
      layer?: number
    ) => void;
    onDimensionComplete?: (
      dimensionKey: string,
      dimensionName: string,
      fullContent: string,
      layer?: number
    ) => void;
    onLayerStarted?: (layer: number, layerName: string) => void;
    onLayerCompleted?: (
      layer: number,
      reportContent: string,
      dimensionReports: Record<string, string>
    ) => void;
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
    // ✅ Fix 2: SSE 连接状态回调
    onConnected?: () => void;
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

  // ✅ Fix 1: 使用 ref 追踪层级完成状态，避免 fetchStatus 依赖循环
  const prevLayerCompletedRef = useRef({
    layer_1: false,
    layer_2: false,
    layer_3: false,
  });

  // ✅ Fix ESLint: 使用 ref 追踪 execution_error，避免 SSE useEffect 频繁重建
  const executionErrorRef = useRef<string | null>(null);

  // Update callbacks ref
  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  // ✅ 简化：只在 SSE 断线重连时获取状态
  // 🔧 增强：检测层级状态变化并触发回调
  const fetchStatus = useCallback(async () => {
    if (!taskId) return;

    try {
      const statusData = await planningApi.getStatus(taskId);

      // ✅ Fix 1: 使用 ref 比较而非 state，避免依赖循环
      const layerCompletedChanged =
        (statusData.layer_1_completed && !prevLayerCompletedRef.current.layer_1) ||
        (statusData.layer_2_completed && !prevLayerCompletedRef.current.layer_2) ||
        (statusData.layer_3_completed && !prevLayerCompletedRef.current.layer_3);

      if (layerCompletedChanged) {
        console.log('[TaskController] 🔄 检测到层级完成状态变化，触发恢复回调:', {
          layer_1: statusData.layer_1_completed,
          layer_2: statusData.layer_2_completed,
          layer_3: statusData.layer_3_completed,
        });

        // 检查每层的完成状态变化
        const layerNames: Record<number, string> = {
          1: '现状分析',
          2: '规划思路',
          3: '详细规划',
        };

        // Layer 1 完成状态变化
        if (statusData.layer_1_completed && !prevLayerCompletedRef.current.layer_1) {
          console.log('[TaskController] 🔄 触发 Layer 1 started 回调（断线恢复）');
          callbacksRef.current.onLayerStarted?.(1, layerNames[1]);
          callbacksRef.current.onLayerCompleted?.(1, '', {});
        }

        // Layer 2 完成状态变化
        if (statusData.layer_2_completed && !prevLayerCompletedRef.current.layer_2) {
          console.log('[TaskController] 🔄 触发 Layer 2 started 回调（断线恢复）');
          callbacksRef.current.onLayerStarted?.(2, layerNames[2]);
          callbacksRef.current.onLayerCompleted?.(2, '', {});
        }

        // Layer 3 完成状态变化
        if (statusData.layer_3_completed && !prevLayerCompletedRef.current.layer_3) {
          console.log('[TaskController] 🔄 触发 Layer 3 started 回调（断线恢复）');
          callbacksRef.current.onLayerStarted?.(3, layerNames[3]);
          callbacksRef.current.onLayerCompleted?.(3, '', {});
        }
      }

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

      // ✅ Fix 1: 更新 ref 追踪的层级完成状态
      prevLayerCompletedRef.current = {
        layer_1: statusData.layer_1_completed,
        layer_2: statusData.layer_2_completed,
        layer_3: statusData.layer_3_completed,
      };

      // ✅ Fix ESLint: 同步 execution_error 到 ref
      executionErrorRef.current = statusData.execution_error ?? null;

      console.log('[TaskController] ✅ 状态同步完成:', {
        status: statusData.status,
        current_layer: statusData.current_layer,
        pause_after_step: statusData.pause_after_step,
        layer_completed: [
          statusData.layer_1_completed,
          statusData.layer_2_completed,
          statusData.layer_3_completed,
        ],
      });
    } catch (error: unknown) {
      console.error('[TaskController] 获取状态失败:', error);
    }
  }, [taskId]); // ✅ Fix 1: 只依赖 taskId，移除 state.layer_X_completed 依赖循环

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

          if (
            [
              'layer_completed',
              'layer_started',
              'dimension_complete',
              'pause',
              'stream_paused',
              'connected',
            ].includes(eventType)
          ) {
            console.log(`[TaskController] 📩 SSE 事件: ${eventType}`, event.data);
          }

          if (eventType === 'content_delta') {
            callbacksRef.current.onTextDelta?.(
              event.data?.delta || '',
              typeof event.data?.layer === 'number' ? event.data.layer : undefined
            );
          } else if (eventType === 'dimension_delta') {
            const data =
              (event.data as {
                dimension_key?: string;
                delta?: string;
                accumulated?: string;
                layer?: number;
              }) || {};

            callbacksRef.current.onDimensionDelta?.(
              data.dimension_key || '',
              data.delta || '',
              data.accumulated || '',
              data.layer
            );
          } else if (eventType === 'dimension_complete') {
            const data =
              (event.data as {
                dimension_key?: string;
                dimension_name?: string;
                full_content?: string;
                layer?: number;
              }) || {};

            console.log(
              `[TaskController] ✅ dimension_complete: layer=${data.layer}, dimension=${data.dimension_key}`
            );

            callbacksRef.current.onDimensionComplete?.(
              data.dimension_key || '',
              data.dimension_name || '',
              data.full_content || '',
              data.layer
            );
          } else if (eventType === 'layer_started') {
            const data =
              (event.data as {
                layer?: number;
                layer_number?: number;
                layer_name?: string;
              }) || {};

            const layerNum = data.layer || data.layer_number || 1;
            console.log(
              `[TaskController] 🚀 layer_started 事件接收: layer=${layerNum}, layer_name="${data.layer_name || ''}"`
            );
            console.log(`[TaskController] 🚀 准备调用 onLayerStarted 回调...`);

            // 调用回调
            if (callbacksRef.current.onLayerStarted) {
              callbacksRef.current.onLayerStarted(layerNum, data.layer_name || '');
              console.log(`[TaskController] 🚀 onLayerStarted 回调已调用`);
            } else {
              console.warn(`[TaskController] ⚠️ onLayerStarted 回调未定义！`);
            }
          } else if (eventType === 'layer_completed') {
            const data =
              (event.data as {
                layer?: number;
                has_data?: boolean;
                dimension_count?: number;
                dimension_reports?: Record<string, string>;
              }) || {};

            console.log(`[TaskController] ✅ layer_completed signal: Layer ${data.layer}`);

            callbacksRef.current.onLayerCompleted?.(
              data.layer || 1,
              '',
              data.dimension_reports || {}
            );
          } else if (eventType === 'pause') {
            const data =
              (event.data as {
                current_layer?: number;
                checkpoint_id?: string;
              }) || {};

            console.log(`[TaskController] ⏸️ pause: layer=${data.current_layer}`);

            callbacksRef.current.onPause?.(data.current_layer || 1, data.checkpoint_id || '');
          } else if (eventType === 'stream_paused') {
            console.log(`[TaskController] 🔚 stream_paused: SSE 流关闭`);
          } else if (eventType === 'dimension_revised') {
            const data =
              (event.data as {
                dimension?: string;
                layer?: number;
                new_content?: string;
                timestamp?: string;
              }) || {};

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
          } else if (eventType === 'connected') {
            // ✅ Fix 2: SSE 连接成功回调
            console.log('[TaskController] 🔗 SSE connected event received');
            callbacksRef.current.onConnected?.();
          }
        },
        (error) => {
          console.error('[TaskController] SSE error:', error);

          // 🔧 修复：检查是否是后端错误导致的断开
          // ✅ Fix ESLint: 使用 ref 而不是 state.execution_error
          if (executionErrorRef.current) {
            console.error(
              '[TaskController] 检测到后端错误，跳过重连:',
              executionErrorRef.current
            );
            callbacksRef.current.onError?.(
              `后端错误：${executionErrorRef.current}，请检查任务配置或联系管理员`
            );
            return;
          }

          // ✅ 断线重连逻辑
          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttemptsRef.current++;
            const delay = Math.min(1000 * reconnectAttemptsRef.current, 5000);

            console.log(
              `[TaskController] SSE 断线，${delay}ms 后重连 (尝试 ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`
            );

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
        },
        // 🔧 新增：浏览器自动重连成功后的回调
        () => {
          console.log('[TaskController] 🔄 浏览器自动重连成功，同步最新状态...');
          console.log('[TaskController] 🔄 断线恢复机制：将检测层级完成状态变化并触发回调');
          // 重连成功后获取完整状态，确保不错过断开期间的事件
          fetchStatus();
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
    // ✅ 优化：移除 fetchStatus() 串行等待，SSE 重连后会自动同步状态
    // 减少约 100-200ms 延迟
    approve: useCallback(async () => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.approveReview(taskId);
      // 🔧 触发 SSE 重连，状态由 SSE 历史事件同步
      console.log('[TaskController] 批准完成，触发 SSE 重连');
      setSseReconnectKey((prev) => prev + 1);
    }, [taskId]),

    reject: useCallback(
      async (feedback: string, dimensions?: string[]) => {
        if (!taskId) throw new Error('No task ID');
        await planningApi.rejectReview(taskId, feedback, dimensions);
        // 🔧 触发 SSE 重连，状态由 SSE 历史事件同步
        console.log('[TaskController] 拒绝完成，触发 SSE 重连');
        setSseReconnectKey((prev) => prev + 1);
      },
      [taskId]
    ),

    rollback: useCallback(
      async (checkpointId: string) => {
        if (!taskId) throw new Error('No task ID');
        await planningApi.rollbackCheckpoint(taskId, checkpointId);
        // 🔧 回滚后显式同步状态，确保审查面板正确显示
        console.log('[TaskController] 回滚完成，同步状态');
        await fetchStatus();
        setSseReconnectKey((prev) => prev + 1);
      },
      [taskId, fetchStatus]
    ),
  };

  return [state, actions];
}
