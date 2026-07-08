// ============================================
// Planning API - 规划相关 API (Session 架构适配)
// ============================================

import { apiRequest, API_BASE_URL } from './client';
import { downloadBlob } from '../utils/download';
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
  PlanningTextDocument,
  PlanningTextVersionList,
  GeneratePlanningTextRequest,
  GeneratePlanningTextResponse,
  RagConfigRequest,
  RagConfigResponse,
  StepModeRequest,
  StepModeResponse,
  GeocodeResponse,
  GisDataUploadResponse,
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
    formData.append('province', request.province || '');
    formData.append('city', request.city || '');
    formData.append('county', request.county || '');
    formData.append('township', request.township || '');
    formData.append('planning_period', request.planning_period || '');
    formData.append('village_data', request.village_data);
    formData.append('task_description', request.task_description || '');
    formData.append('constraints', request.constraints || '');
    formData.append('step_mode', String(request.step_mode || false));
    // RAG Configuration
    formData.append('rag_enabled', String(request.rag_enabled ?? true));
    if (request.rag_layer_config) {
      formData.append('rag_layer_config', request.rag_layer_config);
    }

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
        } else if (type === 'dimension_start') {
          const dimKey = data.dimension_key || '?';
          const dimName = data.dimension_name || '?';
          const layer = data.layer ?? '?';
          console.log(`[SSE] dimension_start: ${dimKey} (${dimName}), layer=${layer}`);
        } else if (type === 'rag_result') {
          const dimKey = data.dimension_key || '?';
          const totalResults = data.total_results || 0;
          const query = data.query || '?';
          console.log(`[SSE] rag_result: ${dimKey}, query="${query}", results=${totalResults}`);
        } else if (type === 'gis_result') {
          const dimKey = data.dimensionKey || '?';
          const dimName = data.dimensionName || '?';
          console.log(`[SSE] gis_result: ${dimKey} (${dimName})`);
        }

        onEvent({ type, data, session_id: sessionId });
      } catch (error) {
        console.error(`[SSE] Failed to parse ${type}:`, error);
        console.error(`[SSE] Raw data length: ${event.data?.length || 0}`);
        console.error(`[SSE] Raw data preview: ${event.data?.substring(0, 500)}...`);
      }
    }

    // ⚠️ IMPORTANT: Every SSE event type MUST be listed here, otherwise the
    // frontend will silently drop it (EventSource only fires for registered types).
    // When adding a new SSE event:
    //   1. Add the type constant in backend/app/core/events.py
    //   2. Add cache config in backend/app/services/sse.py CACHE_CONFIG (if critical)
    //   3. Add the handler in planningStore.ts handleSSEEvent switch
    //   4. Add to useSSE.ts criticalEventTypes (if it should skip batch delay)
    //   5. Add the type string HERE
    const eventTypes: PlanningSSEEventType[] = [
      // Connection Events
      'connected',
      'heartbeat',
      'error',
      // Layer Events
      'layer_started',
      'layer_completed',
      'layer_paused',
      'execution_resumed',
      // Dimension Events
      'dimension_start',
      'dimension_delta',
      'dimension_complete',
      // Progress Events
      'checkpoint_saved',
      'pause',
      'resumed',
      'completed',
      'revision_completed',
      // Tool Events (NEW)
      'tool_started',
      'tool_status',
      // Tool Events (Legacy)
      'tool_call',
      'tool_progress',
      'tool_result',
      // AI Response Events
      'ai_response_delta',
      'ai_response_complete',
      // GIS & RAG Events
      'rag_result',
      'gis_result',
      'gis_layer_update',
      // Cascade Events
      'cascade_impact',
      'cascade_complete',
      // Settings Events
      'rag_config_updated',
      'step_mode_updated',
    ];

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (e) => parseEvent(e, eventType));
    }

    es.addEventListener('pause', (e) => {
      parseEvent(e, 'pause');
      console.log('[SSE] pause event received, keeping connection open for resume');
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
    current_layer?: number;
    review_layer?: number;
    next_phase?: string;
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

  /**
   * Get checkpoints for a session
   * GET /api/sessions/{session_id}/checkpoints
   */
  async getCheckpoints(sessionId: string): Promise<{ session_id: string; checkpoints: { checkpoint_id: string; phase: string; layer: number }[]; count: number }> {
    return apiRequest(`/api/sessions/${sessionId}/checkpoints`);
  },

  /**
   * Export layer report in a given format (direct file stream)
   * POST /api/sessions/{session_id}/export?layer=N&format=...
   */
  async exportLayerFormat(
    sessionId: string,
    layer: number,
    format: 'docx' | 'json' | 'md',
    extraParams: string = '',
  ): Promise<string> {
    const url = `${API_BASE_URL}/api/sessions/${sessionId}/export?layer=${layer}&format=${format}${extraParams}`;
    const response = await fetch(url, { method: 'POST' });
    if (!response.ok) {
      let detail = `导出失败: ${response.status}`;
      try {
        const errorData = await response.json();
        if (errorData.detail) detail = errorData.detail;
      } catch { /* response body may not be JSON */ }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const filename = this.extractFilename(response);
    downloadBlob(blob, filename);
    return filename;
  },

  async exportLayerDocx(
    sessionId: string,
    layer: number,
    includeSummaries: boolean = false,
  ): Promise<string> {
    return this.exportLayerFormat(sessionId, layer, 'docx', `&include_summaries=${includeSummaries}`);
  },

  async exportLayerJson(sessionId: string, layer: number): Promise<string> {
    return this.exportLayerFormat(sessionId, layer, 'json');
  },

  async exportLayerMd(sessionId: string, layer: number): Promise<string> {
    return this.exportLayerFormat(sessionId, layer, 'md');
  },

  async exportPlanningTextDocx(
    sessionId: string,
    projectName: string = '村庄规划',
  ): Promise<string> {
    const url = `${API_BASE_URL}/api/sessions/${sessionId}/export?planning_text=true&project_name=${encodeURIComponent(projectName)}`;
    const response = await fetch(url, { method: 'POST' });
    if (!response.ok) {
      let detail = `导出失败: ${response.status}`;
      try {
        const errorData = await response.json();
        if (errorData.detail) detail = errorData.detail;
      } catch { /* response body may not be JSON */ }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const filename = this.extractFilename(response);
    downloadBlob(blob, filename);
    return filename;
  },

  /**
   * Extract filename from Content-Disposition header
   */
  extractFilename(response: Response): string {
    const disposition = response.headers.get('Content-Disposition');
    if (disposition) {
      const utf8Match = disposition.match(/filename\*=UTF-8''(.+?)(?:;|$)/i);
      if (utf8Match) return decodeURIComponent(utf8Match[1]);
      const quotedMatch = disposition.match(/filename="(.+?)"/);
      if (quotedMatch) {
        try { return decodeURIComponent(quotedMatch[1]); }
        catch { return quotedMatch[1]; }
      }
    }
    return 'export.docx';
  },

  // ============================================
  // Planning Text API
  // ============================================

  /**
   * Get planning text document (latest or specific version)
   * GET /api/sessions/{session_id}/planning-text
   * GET /api/sessions/{session_id}/planning-text/versions/{version}
   */
  async getPlanningText(sessionId: string, version?: number): Promise<PlanningTextDocument | null> {
    const url = version
      ? `/api/sessions/${sessionId}/planning-text/versions/${version}`
      : `/api/sessions/${sessionId}/planning-text`;
    return apiRequest<PlanningTextDocument | null>(url);
  },

  /**
   * Get all planning text versions
   * GET /api/sessions/{session_id}/planning-text/versions
   */
  async getPlanningTextVersions(sessionId: string, limit?: number): Promise<PlanningTextVersionList> {
    const url = limit
      ? `/api/sessions/${sessionId}/planning-text/versions?limit=${limit}`
      : `/api/sessions/${sessionId}/planning-text/versions`;
    return apiRequest<PlanningTextVersionList>(url);
  },

  /**
   * Generate planning text document
   * POST /api/sessions/{session_id}/planning-text
   */
  async generatePlanningText(
    sessionId: string,
    request?: GeneratePlanningTextRequest
  ): Promise<GeneratePlanningTextResponse> {
    return apiRequest<GeneratePlanningTextResponse>(
      `/api/sessions/${sessionId}/planning-text`,
      {
        method: 'POST',
        body: JSON.stringify(request || { trigger_reason: 'initial' }),
      }
    );
  },

  // ============================================
  // Settings API
  // ============================================

  /**
   * Update RAG configuration (runtime)
   * PATCH /api/sessions/{session_id}/rag-config
   */
  async updateRagConfig(
    sessionId: string,
    request: RagConfigRequest
  ): Promise<RagConfigResponse> {
    return apiRequest<RagConfigResponse>(
      `/api/sessions/${sessionId}/rag-config`,
      {
        method: 'PATCH',
        body: JSON.stringify(request),
      }
    );
  },

  /**
   * Update step mode (runtime)
   * PATCH /api/sessions/{session_id}/step-mode
   */
  async updateStepMode(
    sessionId: string,
    request: StepModeRequest
  ): Promise<StepModeResponse> {
    return apiRequest<StepModeResponse>(
      `/api/sessions/${sessionId}/step-mode`,
      {
        method: 'PATCH',
        body: JSON.stringify(request),
      }
    );
  },

  /**
   * Geocode village address to center coordinates + boundary
   * GET /api/sessions/{session_id}/geocode
   */
  async geocodeVillage(
    sessionId: string,
    params: {
      village_name?: string;
      province?: string;
      city?: string;
      county?: string;
      township?: string;
    }
  ): Promise<GeocodeResponse> {
    const qs = new URLSearchParams();
    if (params.village_name) qs.set('village_name', params.village_name);
    if (params.province) qs.set('province', params.province);
    if (params.city) qs.set('city', params.city);
    if (params.county) qs.set('county', params.county);
    if (params.township) qs.set('township', params.township);
    return apiRequest<GeocodeResponse>(
      `/api/sessions/${sessionId}/geocode?${qs.toString()}`
    );
  },

  /**
   * Upload GIS data (GeoJSON) to an existing session
   * POST /api/sessions/{session_id}/gis-data
   */
  async uploadGisData(
    sessionId: string,
    file: File,
    dataType?: string,
  ): Promise<GisDataUploadResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    if (dataType) formData.append('data_type', dataType);

    const response = await fetch(
      `${API_BASE_URL}/api/sessions/${sessionId}/gis-data`,
      { method: 'POST', body: formData },
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const detail = errorData.detail || `HTTP ${response.status}`;
      throw new Error(detail);
    }

    return response.json();
  },
};
