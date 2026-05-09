// ============================================
// Planning API - 规划相关 API (Session 架构适配)
// ============================================

import { apiRequest, API_BASE_URL } from './client';
import type {
  StartPlanningRequest,
  StartPlanningResponse,
  FeedbackRequest,
  SessionStatusResponse,
  LayerReportsResponse,
  DimensionReportResponse,
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
   * Start a new planning session (multipart/form-data)
   * POST /api/sessions
   */
  async startPlanning(request: StartPlanningRequest): Promise<StartPlanningResponse> {
    const formData = new FormData();
    formData.append('project_name', request.project_name);
    formData.append('village_name', request.village_name || '');
    formData.append('village_data', request.village_data);
    formData.append('task_description', request.task_description || '');
    formData.append('constraints', request.constraints || '');
    formData.append('step_mode', String(request.step_mode || false));

    if (request.villageDataFiles) {
      for (const f of request.villageDataFiles) formData.append('village_data_files', f, f.name);
    }
    if (request.taskFiles) {
      for (const f of request.taskFiles) formData.append('task_files', f, f.name);
    }
    if (request.constraintFiles) {
      for (const f of request.constraintFiles) formData.append('constraint_files', f, f.name);
    }

    const response = await fetch(`${API_BASE_URL}/api/sessions`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const detail = errorData.detail || `HTTP ${response.status}`;
      throw new Error(detail);
    }

    return response.json();
  },

  /**
   * Get SSE stream for planning session
   * GET /api/sessions/{session_id}/stream
   */
  createStream(
    sessionId: string,
    onEvent: (event: PlanningSSEEvent) => void,
    onError?: (error: Error) => void,
    onReconnect?: () => void
  ): EventSource {
    const url = `${API_BASE_URL}/api/sessions/${sessionId}/stream`;
    const es = new EventSource(url);

    let isReconnecting = false;
    let wasConnected = false;
    let shouldSuppressReconnect = false;

    const IDLE_TIMEOUT_MS = 5 * 60 * 1000;
    let lastActivityTime = Date.now();

    function parseEvent(event: MessageEvent, type: PlanningSSEEventType): void {
      lastActivityTime = Date.now();

      try {
        const rawData = event.data;
        const data = JSON.parse(rawData) as PlanningSSEDataBase;

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
            console.warn(`[SSE] layer_completed signal: no data, frontend will fetch via REST API`);
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

    es.addEventListener('pause', (e) => {
      parseEvent(e, 'pause');
      console.log('[SSE] pause event received, keeping connection open for resume');
    });

    es.addEventListener('stream_paused', (e) => {
      parseEvent(e, 'pause');
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

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        console.log('[SSE] Connection closed by server (readyState=CLOSED)');
        return;
      }

      if (es.readyState === EventSource.CONNECTING) {
        if (shouldSuppressReconnect) {
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

    const idleCheckInterval = setInterval(() => {
      const idleTime = Date.now() - lastActivityTime;
      if (idleTime > IDLE_TIMEOUT_MS && es.readyState !== EventSource.CLOSED) {
        console.warn('[SSE] Connection idle timeout (5 min), closing');
        clearInterval(idleCheckInterval);
        es.close();
      }
    }, 60000);

    const originalClose = es.close.bind(es);
    es.close = () => {
      clearInterval(idleCheckInterval);
      originalClose();
    };

    return es;
  },

  /**
   * Submit feedback (unified endpoint for approve/reject/chat)
   * POST /api/sessions/{session_id}/feedback
   */
  async submitFeedback(sessionId: string, request: FeedbackRequest): Promise<{
    status: string;
    dimensions?: string[];
    layer?: number;
  }> {
    return apiRequest(`/api/sessions/${sessionId}/feedback`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /**
   * Approve current review
   */
  async approveReview(sessionId: string): Promise<{ status: string }> {
    return this.submitFeedback(sessionId, { approve: true });
  },

  /**
   * Reject current review with feedback
   */
  async rejectReview(sessionId: string, feedback: string, dimensions?: string[], images?: ImageData[]): Promise<{ status: string; dimensions?: string[] }> {
    return this.submitFeedback(sessionId, {
      feedback,
      dimensions,
      images,
    });
  },

  /**
   * Send chat message to planning session
   * POST /api/sessions/{session_id}/feedback
   */
  async sendChatMessage(sessionId: string, message: string, images?: ImageData[]): Promise<{ status: string }> {
    return this.submitFeedback(sessionId, { message, images });
  },

  /**
   * Rollback / resume from checkpoint
   * POST /api/sessions/{session_id}/resume/{checkpoint_id}
   */
  async rollbackCheckpoint(sessionId: string, checkpointId: string): Promise<{
    status: string;
    checkpoint_id: string;
    layer: number;
  }> {
    return apiRequest(`/api/sessions/${sessionId}/resume/${checkpointId}`, {
      method: 'POST',
    });
  },

  /**
   * Get session status
   * GET /api/sessions/{session_id}/status
   */
  async getStatus(sessionId: string): Promise<SessionStatusResponse> {
    return apiRequest<SessionStatusResponse>(`/api/sessions/${sessionId}/status`);
  },

  /**
   * Sync events from a specific sequence number (for SSE reconnection)
   * GET /api/sessions/{session_id}/sync?from_seq=N
   */
  async syncEvents(sessionId: string, fromSeq: number): Promise<{
    events: PlanningSSEEvent[];
    last_seq: number;
    from_seq: number;
  }> {
    return apiRequest(`/api/sessions/${sessionId}/sync?from_seq=${fromSeq}`);
  },

  /**
   * Get layer reports
   * GET /api/sessions/{session_id}/layer/{layer}/reports
   */
  async getLayerReports(sessionId: string, layer: number): Promise<LayerReportsResponse> {
    return apiRequest<LayerReportsResponse>(`/api/sessions/${sessionId}/layer/${layer}/reports`);
  },

  /**
   * Get dimension report (Signal-Fetch Pattern)
   * GET /api/sessions/{session_id}/reports/{dim_key}
   */
  async getDimensionReport(sessionId: string, dimensionKey: string): Promise<DimensionReportResponse> {
    return apiRequest<DimensionReportResponse>(
      `/api/sessions/${sessionId}/reports/${dimensionKey}`
    );
  },

  /**
   * Delete session
   * DELETE /api/sessions/{session_id}
   */
  async deleteSession(sessionId: string): Promise<{ message: string }> {
    return apiRequest(`/api/sessions/${sessionId}`, {
      method: 'DELETE',
    });
  },
};
