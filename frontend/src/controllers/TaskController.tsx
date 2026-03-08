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

  const callbacksRef = useRef(callbacks);
  const sseConnectionRef = useRef<EventSource | null>(null);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const prevTaskIdRef = useRef<string | null>(null);
  const stateRef = useRef(state);  // 🔧 用于在轮询循环中访问最新状态

  // 同步 state 到 ref
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

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

      // 🔧 修复：暂停/完成状态下停止轮询
      const currentState = stateRef.current;
      const shouldPausePolling = 
        currentState.status === 'paused' || 
        currentState.status === 'completed';

      if (!shouldStop && taskId && !shouldPausePolling) {
        // 继续轮询,2秒一次
        pollTimerRef.current = setTimeout(pollLoop, 2000);
      } else if (shouldPausePolling) {
        console.log('[TaskController] Polling paused due to status:', currentState.status);
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
  // 🔧 架构优化：SSE 连接仅依赖 taskId，完全解耦 UI 状态
  // 连接关闭由后端的显式结束信号（stream_paused/completed）控制
  // 遵循"职责单一原则"和"显式终态协议"
  useEffect(() => {
    if (!taskId) {
      // 无 taskId 时关闭连接
      if (sseConnectionRef.current) {
        console.log('[TaskController] === SSE 连接关闭 ===');
        console.log('[TaskController] 原因: taskId 为空');
        sseConnectionRef.current.close();
        sseConnectionRef.current = null;
      }
      return;
    }

    // 检查 taskId 是否变化（只有 taskId 变化时才重建连接）
    const taskIdChanged = prevTaskIdRef.current !== taskId;
    prevTaskIdRef.current = taskId;

    if (!taskIdChanged && sseConnectionRef.current) {
      // taskId 未变化且连接已存在，不需要重建
      return;
    }

    // taskId 变化或连接不存在，创建新连接
    console.log('[TaskController] === SSE 连接建立 ===');
    console.log('[TaskController] taskId:', taskId);
    
    // 关闭旧连接
    if (sseConnectionRef.current) {
      console.log('[TaskController] 关闭旧 SSE 连接');
      sseConnectionRef.current.close();
    }

    // 创建新连接
    const es = planningApi.createStream(
      taskId,
      (event) => {
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
        } else if (eventType === 'layer_started') {
          const data = event.data as {
            layer?: number;
            layer_number?: number;
            layer_name?: string;
            message?: string;
          } || {};

          callbacksRef.current.onLayerStarted?.(
            data.layer || data.layer_number || 1,
            data.layer_name || ''
          );
        } else if (eventType === 'layer_completed') {
          // ✅ Signal-Fetch Pattern: SSE 只发送轻量信号
          // 前端收到信号后会调用 REST API 获取完整数据
          const data = event.data as {
            layer?: number;
            has_data?: boolean;
            dimension_count?: number;
            total_chars?: number;
          } || {};

          console.log(`[TaskController] layer_completed signal received: Layer ${data.layer}, has_data=${data.has_data}`);

          // 调用回调，让前端从 REST API 获取完整数据
          // SSE 数据已不包含 report_content 和 dimension_reports
          callbacksRef.current.onLayerCompleted?.(
            data.layer || 1,
            '',  // SSE 不再传输 report_content
            {}   // SSE 不再传输 dimension_reports
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
          const data = event.data as {
            dimension?: string;
            layer?: number;
            old_content?: string;
            new_content?: string;
            feedback?: string;
            is_target?: boolean;
            revision_type?: string;
            timestamp?: string;
          } || {};
          
          callbacksRef.current.onDimensionRevised?.({
            dimension: data.dimension || '',
            layer: data.layer || 1,
            oldContent: data.old_content || '',
            newContent: data.new_content || '',
            feedback: data.feedback || '',
            isTarget: data.is_target ?? true,
            revisionType: data.revision_type || '',
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
  }, [taskId]);  // 🔧 仅依赖 taskId，连接关闭由后端显式信号控制

  // Action methods
  const actions: TaskControllerActions = {
    approve: useCallback(async () => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.approveReview(taskId);
      // ✅ 批准后立即获取最新状态，触发 UI 更新
      // 这会同步更新 isPaused 和 pendingReviewLayer
      await fetchStatus();
    }, [taskId, fetchStatus]),

    reject: useCallback(async (feedback: string, dimensions?: string[]) => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.rejectReview(taskId, feedback, dimensions);
      // ✅ 拒绝后立即获取最新状态，触发 UI 更新和 SSE 连接重建
      await fetchStatus();
    }, [taskId, fetchStatus]),

    rollback: useCallback(async (checkpointId: string) => {
      if (!taskId) throw new Error('No task ID');
      await planningApi.rollbackCheckpoint(taskId, checkpointId);
    }, [taskId]),
  };

  return [state, actions];
}