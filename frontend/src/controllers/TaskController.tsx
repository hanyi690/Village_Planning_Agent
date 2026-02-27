/**
 * TaskController - 极简版状态管理
 *
 * 核心理念:
 * - 后端状态为单一真实源 (Single Source of Truth)
 * - Controller 只负责数据搬运,不做任何业务逻辑判断
 * - 幂等性: 无论轮询多少次,只要后端状态不变,前端渲染结果不变
 *
 * 功能:
 * - 轮询 /status 端点获取后端状态
 * - 将状态同步到 Context
 * - SSE 连接管理 (仅用于文本流)
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { planningApi } from '../lib/api';

export interface TaskState {
  status: 'idle' | 'pending' | 'running' | 'paused' | 'reviewing' | 'revising' | 'completed' | 'failed';
  current_layer: number | null;
  previous_layer: number | null;  // 刚完成的层级（待审查层级）
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
    onLayerCompleted?: (layer: number, reportContent: string, dimensionReports: Record<string, string>) => void;
    onPause?: (layer: number, checkpointId: string) => void;
    onDimensionRevised?: (data: {
      dimension: string;
      layer: number;
      oldContent: string;
      newContent: string;
      feedback: string;
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

  const callbacksRef = useRef(callbacks);
  const sseConnectionRef = useRef<EventSource | null>(null);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Update callbacks ref
  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  // 纯数据搬运逻辑 - 获取状态 -> 同步到 Context -> 检查是否停止
  const fetchStatus = useCallback(async () => {
    if (!taskId) return false;

    try {
      // 1. 获取后端全量状态
      const statusData = await planningApi.getStatus(taskId);

      // 2. 直接同步到状态 (不做任何判断)
      console.log('[TaskController] Syncing state from backend API:', {
        'Raw status data': statusData,
        'status': statusData.status,
        'pause_after_step': statusData.pause_after_step,
        'previous_layer': statusData.previous_layer,
        'current_layer': statusData.current_layer,
        'layer_1_completed': statusData.layer_1_completed,
        'layer_2_completed': statusData.layer_2_completed,
        'layer_3_completed': statusData.layer_3_completed,
        'execution_complete': statusData.execution_complete,
      });

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

      console.log('[TaskController] State updated successfully');

      // 3. 检查是否需要停止轮询
      // 只有当 execution_complete=true 时才彻底停止
      return statusData.execution_complete;

    } catch (error: any) {
      // 404 错误: 数据库尚未提交,跳过本次轮询
      const status = error?.status || error?.response?.status;
      if (status === 404) {
        console.warn(`[TaskController] Task ${taskId} initializing (404), will retry...`);
        return false;
      }

      // 其他错误: 记录日志,继续轮询
      console.error('[TaskController] Poll error:', error);
      return false;
    }
  }, [taskId]);

  // 轮询副作用
  useEffect(() => {
    if (!taskId) {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      return;
    }

    const pollLoop = async () => {
      const shouldStop = await fetchStatus();

      if (!shouldStop && taskId) {
        // 继续轮询,2秒一次
        pollTimerRef.current = setTimeout(pollLoop, 2000);
      }
    };

    // 立即执行一次,然后开始循环
    pollLoop();

    return () => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [taskId, fetchStatus]);

  // SSE 连接管理 (仅用于文本流,不做业务逻辑判断)
  useEffect(() => {
    if (!taskId) return;

    // ✅ 改用 pause_after_step 标志判断是否需要 SSE 连接
    // 暂停时不需要 SSE（已停止发送事件），批准后需要 SSE（继续执行）
    const shouldConnectSSE =
      !state.execution_complete &&
      !state.pause_after_step;

    if (shouldConnectSSE) {
      console.log('[TaskController] === SSE 连接建立 ===');
      console.log('[TaskController] taskId:', taskId);
      console.log('[TaskController] pause_after_step:', state.pause_after_step);
      console.log('[TaskController] execution_complete:', state.execution_complete);
      
      // 关闭旧连接
      if (sseConnectionRef.current) {
        console.log('[TaskController] 关闭旧 SSE 连接');
        sseConnectionRef.current.close();
      }

      // 创建新连接
      const es = planningApi.createStream(
        taskId,
        (event) => {
          console.log('[TaskController] === SSE 事件接收 ===');
          console.log('[TaskController] event.type:', event.type);
          console.log('[TaskController] event.data:', event.data);
          
          const eventType = event.type;
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
            
            callbacksRef.current.onDimensionComplete?.(
              data.dimension_key || '',
              data.dimension_name || '',
              data.full_content || '',
              data.layer
            );
          } else if (eventType === 'layer_completed') {
            const data = event.data as {
              layer?: number;
              report_content?: string;
              dimension_reports?: Record<string, string>;
            } || {};

            // ✅ 添加 Layer 2 专用调试日志
            if (data.layer === 2) {
              console.log('[TaskController] === Layer 2 Completed SSE Event ===');
              console.log('[TaskController] data:', data);
              console.log('[TaskController] dimension_reports:', data.dimension_reports);
              console.log('[TaskController] dimension_reports keys:', Object.keys(data.dimension_reports || {}));
              if (data.dimension_reports) {
                for (const [key, value] of Object.entries(data.dimension_reports)) {
                  console.log(`[TaskController]   - ${key}: ${value.length} chars`);
                }
              }
            }

            callbacksRef.current.onLayerCompleted?.(
              data.layer || 1,
              data.report_content || '',
              data.dimension_reports || {}
            );
          } else if (eventType === 'pause') {
            const data = event.data as {
              current_layer?: number;
              checkpoint_id?: string;
              reason?: string;
            } || {};
            
            callbacksRef.current.onPause?.(
              data.current_layer || 1,
              data.checkpoint_id || ''
            );
          } else if (eventType === 'dimension_revised') {
            // 【新增】处理维度修复完成事件
            const data = event.data as {
              dimension?: string;
              layer?: number;
              old_content?: string;
              new_content?: string;
              feedback?: string;
              timestamp?: string;
            } || {};
            
            console.log('[TaskController] === Dimension Revised SSE Event ===');
            console.log('[TaskController] dimension:', data.dimension);
            console.log('[TaskController] layer:', data.layer);
            console.log('[TaskController] new_content length:', data.new_content?.length || 0);
            
            callbacksRef.current.onDimensionRevised?.({
              dimension: data.dimension || '',
              layer: data.layer || 1,
              oldContent: data.old_content || '',
              newContent: data.new_content || '',
              feedback: data.feedback || '',
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
          callbacksRef.current.onError?.('SSE connection error');
        }
      );

      sseConnectionRef.current = es;

      return () => {
        if (sseConnectionRef.current) {
          sseConnectionRef.current.close();
          sseConnectionRef.current = null;
        }
      };
    } else if (state.execution_complete) {
      // 执行完成时关闭 SSE 连接
      // 注意：暂停时不关闭 SSE，让后端自然结束流，确保 layer_completed 和 pause 事件都能被接收
      console.log('[TaskController] === SSE 连接关闭 ===');
      console.log('[TaskController] 原因: 执行完成');
      if (sseConnectionRef.current) {
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
    }
    // 暂停时 (pause_after_step=true 但 execution_complete=false)：
    // 不主动关闭 SSE，让连接保持打开直到后端结束流
  }, [taskId, state.pause_after_step, state.execution_complete]);

  // Action methods
  const actions: TaskControllerActions = {
    approve: useCallback(async () => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.approveReview(taskId);
    }, [taskId]),

    reject: useCallback(async (feedback: string, dimensions?: string[]) => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.rejectReview(taskId, feedback, dimensions);
    }, [taskId]),

    rollback: useCallback(async (checkpointId: string) => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.rollbackCheckpoint(taskId, checkpointId);
    }, [taskId]),
  };

  return [state, actions];
}