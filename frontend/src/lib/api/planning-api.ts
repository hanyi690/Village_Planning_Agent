// ============================================
// Planning API - 规划相关 API
// ============================================

import { apiRequest, API_BASE_URL } from './client';
import type {
  StartPlanningRequest,
  StartPlanningResponse,
  ReviewActionRequest,
  SessionStatusResponse,
  LayerReportsResponse,
  PlanningSSEEvent,
  PlanningSSEEventType,
  PlanningSSEDataBase,
  ImageData,
} from './types';

// ============================================
// Planning API
// ============================================

export const planningApi = {
  /**
   * Start a new planning session
   * POST /api/planning/start
   */
  async startPlanning(request: StartPlanningRequest): Promise<StartPlanningResponse> {
    return apiRequest<StartPlanningResponse>('/api/planning/start', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /**
   * Get SSE stream for planning session
   * GET /api/planning/stream/{session_id}
   */
  createStream(
    sessionId: string,
    onEvent: (event: PlanningSSEEvent) => void,
    onError?: (error: Error) => void,
    onReconnect?: () => void
  ): EventSource {
    const url = `${API_BASE_URL}/api/planning/stream/${sessionId}`;
    const es = new EventSource(url);

    // 重连检测：标记是否正在重连
    let isReconnecting = false;
    let wasConnected = false;
    let shouldSuppressReconnect = false;

    // 空闲超时保护：跟踪最后活动时间
    const IDLE_TIMEOUT_MS = 5 * 60 * 1000; // 5 分钟
    let lastActivityTime = Date.now();

    // Helper to parse SSE event
    function parseEvent(event: MessageEvent, type: PlanningSSEEventType): void {
      // 重置空闲计时器
      lastActivityTime = Date.now();

      try {
        const rawData = event.data;
        const data = JSON.parse(rawData) as PlanningSSEDataBase;

        // Signal-Fetch Pattern: SSE 只发送轻量信号
        if (type === 'layer_completed') {
          const layer = data.layer ?? '?';
          const hasData = data.has_data ?? false;
          const dimensionCount = data.dimension_count || 0;
          const totalChars = data.total_chars || 0;

          console.log(`[SSE] layer_completed signal received:`, {
            layer,
            has_data: hasData,
            dimension_count: dimensionCount,
            total_chars: totalChars,
            rawDataLength: rawData?.length || 0,
          });

          if (!hasData) {
            console.warn(`[SSE] layer_completed 信号显示后端无数据，前端将从 REST API 获取`);
          }
        } else if (type === 'dimension_complete') {
          const dimKey = data.dimension_key || '?';
          const fullContent = data.full_content || '';
          console.log(`[SSE] dimension_complete: ${dimKey} (${fullContent.length} chars)`);
        } else if (type === 'layer_started') {
          const layer = data.layer ?? '?';
          const layerName = data.layer_name ?? '?';
          const dimensionCount = data.dimension_count ?? 0;
          console.log(`[SSE] layer_started: layer=${layer} (${layerName}), dimensions=${dimensionCount}`);
        } else if (type === 'dimension_delta') {
          const dimKey = data.dimension_key || '?';
          const accumulated = data.accumulated || '';
          const delta = data.delta || '';
          const layer = data.layer ?? '?';

          // 每隔一定字符数记录一次（里程碑日志）
          const milestones = [100, 500, 1000, 2000, 5000];
          const isMilestone = milestones.some(m =>
            accumulated.length >= m && accumulated.length < m + 50
          );

          if (accumulated.length <= 10 || isMilestone) {
            console.log(`[SSE] dimension_delta: ${dimKey} (layer=${layer}, accumulated=${accumulated.length}, delta=${delta.length})`);
          }
        }

        onEvent({ type, data, session_id: sessionId });
      } catch (error) {
        console.error(`[SSE] Failed to parse ${type}:`, error);
        console.error(`[SSE] Raw data length: ${event.data?.length || 0}`);
        console.error(`[SSE] Raw data preview: ${event.data?.substring(0, 500)}...`);
      }
    }

    // Define event listeners for each event type
    const eventTypes: PlanningSSEEventType[] = [
      'layer_started',
      'dimension_start',
      'dimension_error',
      'layer_completed',
      'checkpoint_saved',
      'review_request',
      'content_delta',
      'resumed',
      'progress',
      'dimension_delta',
      'dimension_complete',
      'dimension_revised',
      'connected',
      'tool_call',
      'tool_progress',
      'tool_result',
      'ai_response_delta',
      'ai_response_complete',
    ];

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (e) => parseEvent(e, eventType));
    }

    // Special handling for terminal events
    // 架构优化：遵循"显式终态协议"
    // 注意：pause 事件不应该关闭 SSE 连接，因为用户审批后需要继续接收事件
    // 只有 completed 和 error 才是真正的终端事件
    es.addEventListener('pause', (e) => {
      parseEvent(e, 'pause');
      // 不关闭连接，保持 SSE 连接以接收后续的 resumed 事件
      console.log('[SSE] pause event received, keeping connection open for resume');
    });

    es.addEventListener('stream_paused', (e) => {
      parseEvent(e, 'pause');
      // 不关闭连接，保持 SSE 连接以接收后续的 resumed 事件
      console.log('[SSE] stream_paused event received, keeping connection open for resume');
    });

    es.addEventListener('completed', (e) => {
      parseEvent(e, 'completed');
      shouldSuppressReconnect = true;
      if (es.readyState !== EventSource.CLOSED) {
        es.close();
        console.log('[SSE] Connection closed after completed event');
      }
    });

    // Error event listener for named 'error' events from server
    es.addEventListener('error', (e) => {
      try {
        const data = e as MessageEvent;
        const parsed = JSON.parse(data.data);
        onEvent({
          type: 'error',
          data: parsed,
        });
      } catch {
        onEvent({
          type: 'error',
          data: { error: 'Server sent error event' },
        });
      }
    });

    // Connection error handler
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        console.log('[SSE] Connection closed by server (readyState=CLOSED)');
        return;
      }

      if (es.readyState === EventSource.CONNECTING) {
        if (shouldSuppressReconnect) {
          // Suppress auto-reconnect log when we intentionally closed the connection
          return;
        }
        if (wasConnected) {
          isReconnecting = true;
          console.log('[SSE] Connection lost, browser is auto-reconnecting...');
        } else {
          console.log('[SSE] Initial connection in progress...');
        }
        return;
      }

      console.error('[SSE] Unexpected connection error, readyState:', es.readyState);
      onError?.(new Error('SSE connection error'));
    };

    es.onopen = () => {
      if (isReconnecting) {
        console.log('[SSE] Auto-reconnect successful! Calling onReconnect callback...');
        isReconnecting = false;
        onReconnect?.();
      }
      wasConnected = true;
    };

    // 空闲超时检查
    const idleCheckInterval = setInterval(() => {
      const idleTime = Date.now() - lastActivityTime;
      if (idleTime > IDLE_TIMEOUT_MS && es.readyState !== EventSource.CLOSED) {
        console.warn('[SSE] Connection idle timeout (5 min), closing');
        clearInterval(idleCheckInterval);
        es.close();
      }
    }, 60000);

    // 清理函数
    const originalClose = es.close.bind(es);
    es.close = () => {
      clearInterval(idleCheckInterval);
      originalClose();
    };

    return es;
  },

  /**
   * Submit review action
   * POST /api/planning/review/{session_id}
   */
  async reviewAction(sessionId: string, request: ReviewActionRequest): Promise<{ message: string; current_layer?: number; resumed?: boolean }> {
    return apiRequest(`/api/planning/review/${sessionId}`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /**
   * Approve current review
   */
  async approveReview(sessionId: string): Promise<{ message: string; current_layer?: number; resumed?: boolean }> {
    return this.reviewAction(sessionId, { action: 'approve' });
  },

  /**
   * Reject current review with feedback
   */
  async rejectReview(sessionId: string, feedback: string, dimensions?: string[], images?: ImageData[]): Promise<{ message: string; resumed?: boolean }> {
    return this.reviewAction(sessionId, {
      action: 'reject',
      feedback,
      dimensions,
      images,
    });
  },

  /**
   * Rollback to checkpoint
   */
  async rollbackCheckpoint(sessionId: string, checkpointId: string): Promise<{ message: string; resumed?: boolean }> {
    return this.reviewAction(sessionId, {
      action: 'rollback',
      checkpoint_id: checkpointId,
    });
  },

  /**
   * Get session status
   * GET /api/planning/status/{session_id}
   */
  async getStatus(sessionId: string): Promise<SessionStatusResponse> {
    return apiRequest<SessionStatusResponse>(`/api/planning/status/${sessionId}`);
  },

  /**
   * Sync events from a specific sequence number (for SSE reconnection)
   * GET /api/planning/stream/{session_id}/sync?from_seq=N
   */
  async syncEvents(sessionId: string, fromSeq: number): Promise<{
    events: PlanningSSEEvent[];
    last_seq: number;
    from_seq: number;
  }> {
    return apiRequest(`/api/planning/stream/${sessionId}/sync?from_seq=${fromSeq}`);
  },

  /**
   * 获取指定层级的维度报告
   * GET /api/planning/sessions/{session_id}/layer/{layer}/reports
   */
  async getLayerReports(sessionId: string, layer: number): Promise<LayerReportsResponse> {
    return apiRequest<LayerReportsResponse>(`/api/planning/sessions/${sessionId}/layer/${layer}/reports`);
  },

  /**
   * Get dimension content (Signal-Fetch Pattern)
   * GET /api/planning/sessions/{session_id}/dimensions/{dimension_key}
   */
  async getDimensionContent(sessionId: string, dimensionKey: string): Promise<{
    dimension_key: string;
    layer: number;
    content: string;
    previous_content: string | null;
    version: number;
    exists: boolean;
    has_previous: boolean;
  }> {
    return apiRequest(`/api/planning/sessions/${sessionId}/dimensions/${dimensionKey}`);
  },

  /**
   * Get dimension revision history
   * GET /api/planning/sessions/{session_id}/dimensions/{dimension_key}/revisions
   */
  async getDimensionRevisions(sessionId: string, dimensionKey: string, limit: number = 20): Promise<{
    dimension_key: string;
    layer: number;
    revisions: Array<{
      id: number;
      layer: number;
      dimension_key: string;
      content: string;
      version: number;
      reason: string | null;
      created_by: string | null;
      created_at: string;
    }>;
    count: number;
  }> {
    return apiRequest(`/api/planning/sessions/${sessionId}/dimensions/${dimensionKey}/revisions?limit=${limit}`);
  },

  /**
   * Delete session
   * DELETE /api/planning/sessions/{session_id}
   */
  async deleteSession(sessionId: string): Promise<{ message: string }> {
    return apiRequest(`/api/planning/sessions/${sessionId}`, {
      method: 'DELETE',
    });
  },

  /**
   * Reset rate limit for a project
   * POST /api/planning/rate-limit/reset/{project_name}
   */
  async resetProject(projectName: string): Promise<{ message: string }> {
    return apiRequest<{ message: string }>(
      `/api/planning/rate-limit/reset/${encodeURIComponent(projectName)}`,
      { method: 'POST' }
    );
  },

  /**
   * Create UI message (with upsert)
   * POST /api/planning/messages/{session_id}
   */
  async createMessage(sessionId: string, message: {
    id: string;
    role: string;
    content: string;
    message_type?: string;
    metadata?: Record<string, unknown>;
  }): Promise<{ success: boolean; message_id: number; frontend_id: string }> {
    return apiRequest(`/api/planning/messages/${sessionId}`, {
      method: 'POST',
      body: JSON.stringify({
        message_id: message.id,
        role: message.role,
        content: message.content,
        message_type: message.message_type,
        metadata: message.metadata,
      }),
    });
  },

  /**
   * Get UI messages
   * GET /api/planning/messages/{session_id}
   */
  async getMessages(sessionId: string, role?: string, limit?: number): Promise<{ success: boolean; messages: import('./types').UIMessage[] }> {
    const params = new URLSearchParams();
    if (role) params.append('role', role);
    if (limit) params.append('limit', String(limit));
    const query = params.toString() ? `?${params.toString()}` : '';
    return apiRequest(`/api/planning/messages/${sessionId}${query}`);
  },

  /**
   * Send chat message to planning session
   * POST /api/planning/chat/{session_id}
   *
   * 通过对话模式与规划助手交互，支持：
   * - 普通对话（问答）
   * - 工具调用
   * - 推进规划（触发 AdvancePlanningIntent）
   * - 多模态对话（带图片）
   *
   * SSE 会推送响应事件
   */
  async sendChatMessage(sessionId: string, message: string, images?: ImageData[]): Promise<{
    success: boolean;
    session_id: string;
    message: string;
  }> {
    return apiRequest(`/api/planning/chat/${sessionId}`, {
      method: 'POST',
      body: JSON.stringify({ message, images }),
    });
  },
};