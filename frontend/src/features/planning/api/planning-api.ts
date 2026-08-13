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
  RenderLayersResponse,
  DeliveryProjection,
  HumanReviewListResponse,
  HumanReviewResolveRequest,
  HumanReviewResolveResponse,
} from './types';

// ============================================
// Planning API
// ============================================

export const planningApi = {
  /**
   * Start a new planning session (multipart/form-data)
   * POST /api/v1/sessions
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

    const response = await fetch(`${API_BASE_URL}/api/v1/sessions`, {
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
   * GET /api/v1/sessions/{session_id}/events
   */
  createStream(
    sessionId: string,
    onEvent: (event: PlanningSSEEvent) => void,
    onError?: (error: Error) => void,
    onReconnect?: () => void
  ): EventSource {
    const url = `${API_BASE_URL}/api/v1/sessions/${sessionId}/events`;
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
        const envelope = JSON.parse(rawData) as {
          type: string;
          seq: number;
          data: PlanningSSEDataBase & { type?: PlanningSSEEventType };
        };
        const legacyType = envelope.type === 'progress' && envelope.data.type
          ? envelope.data.type
          : envelope.type === 'human_review'
            ? 'human_review_paused'
            : envelope.type === 'failed'
              ? 'error'
              : envelope.type as PlanningSSEEventType;
        const data = { ...envelope.data, seq: envelope.seq } as PlanningSSEDataBase;

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

        onEvent({ type: legacyType, data, session_id: sessionId });
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
    const eventTypes = [
      'progress', 'human_review', 'delivery_ready', 'completed', 'failed',
      'resync_required',
    ] as const;

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (e) => parseEvent(e, eventType as PlanningSSEEventType));
    }

    es.addEventListener('completed', () => {
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
  async submitFeedback(_sessionId: string, _request: FeedbackRequest): Promise<{
    status: string;
    reply?: string;
    draft_feedback?: string;
    dimensions?: string[];
    layer?: number;
    current_layer?: number;
    review_layer?: number;
    next_phase?: string;
  }> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 对话/反馈端点已下线（POST /api/sessions/{id}/feedback）；人工审核请使用 POST /api/v1/sessions/{id}/human-review');
  },

  /**
   * Send chat message to planning session
   * POST /api/sessions/{session_id}/feedback
   */
  async sendChatMessage(
    _sessionId: string,
    _message: string,
    _images?: ImageData[],
  ): Promise<{ status: string; reply?: string; draft_feedback?: string; dimensions?: string[] }> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 对话端点已下线（POST /api/sessions/{id}/feedback）');
  },

  /**
   * Get session status
   * GET /api/v1/sessions/{session_id}/state
   */
  async getStatus(sessionId: string): Promise<SessionStatusResponse> {
    const state = await apiRequest<SessionStatusResponse>(`/api/v1/sessions/${sessionId}/state`);
    return state;
  },

  /**
   * Sync events from a specific sequence number (for SSE reconnection)
   * GET /api/v1/sessions/{session_id}/events/sync?after=N
   */
  async syncEvents(sessionId: string, fromSeq: number): Promise<{
    events: PlanningSSEEvent[];
    last_seq: number;
    from_seq: number;
    resync_required: boolean;
  }> {
    const result = await apiRequest<{
      events: Array<{ type: string; seq: number; data: PlanningSSEDataBase & { type?: PlanningSSEEventType } }>;
      last_seq: number;
      resync_required: boolean;
    }>(`/api/v1/sessions/${sessionId}/events/sync?after=${fromSeq}`);
    return {
      events: result.events.map((event) => ({
        type: event.type === 'progress' && event.data.type
          ? event.data.type
          : event.type === 'human_review'
            ? 'human_review_paused'
            : event.type === 'failed' ? 'error' : event.type as PlanningSSEEventType,
        data: { ...event.data, seq: event.seq },
      })),
      last_seq: result.last_seq,
      from_seq: fromSeq,
      resync_required: Boolean(result.resync_required),
    };
  },

  /**
   * Get layer reports
   * GET /api/sessions/{session_id}/layer/{layer}/reports
   */
  async getLayerReports(_sessionId: string, _layer: number): Promise<LayerReportsResponse> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 报告端点已下线（GET /api/sessions/{id}/layer/{layer}/reports）；报告由 SSE dimension_complete 事件提供');
  },

  /**
   * Get dimension report (Signal-Fetch Pattern)
   * GET /api/sessions/{session_id}/reports/{dim_key}
   */
  async getDimensionReport(_sessionId: string, _dimensionKey: string): Promise<DimensionReportResponse> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 报告端点已下线（GET /api/sessions/{id}/reports/{dim_key}）');
  },

  /**
   * Delete session
   * DELETE /api/sessions/{session_id}
   */
  async deleteSession(_sessionId: string): Promise<{ message: string }> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 删除会话端点已下线（DELETE /api/sessions/{id}），删除仅作用于本地历史');
  },

  /**
   * Get checkpoints for a session
   * GET /api/sessions/{session_id}/checkpoints
   */
  async getCheckpoints(_sessionId: string): Promise<{ session_id: string; checkpoints: { checkpoint_id: string; phase: string; layer: number }[]; count: number }> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 检查点端点已下线（GET /api/sessions/{id}/checkpoints）');
  },

  /**
   * Export layer report in a given format (direct file stream)
   * POST /api/sessions/{session_id}/export?layer=N&format=...
   */
  async exportLayerFormat(
    _sessionId: string,
    _layer: number,
    _format: 'docx' | 'json' | 'md',
    _extraParams: string = '',
  ): Promise<string> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 导出端点已下线（POST /api/sessions/{id}/export）；下载请等后端提供 /delivery.downloads 服务');
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
    _sessionId: string,
    _projectName: string = '村庄规划',
  ): Promise<string> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 导出端点已下线（POST /api/sessions/{id}/export）');
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
  async getPlanningText(_sessionId: string, _version?: number): Promise<PlanningTextDocument | null> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 规划文本端点已下线（GET /api/sessions/{id}/planning-text）');
  },

  /**
   * Get all planning text versions
   * GET /api/sessions/{session_id}/planning-text/versions
   */
  async getPlanningTextVersions(_sessionId: string, _limit?: number): Promise<PlanningTextVersionList> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 规划文本端点已下线（GET /api/sessions/{id}/planning-text/versions）');
  },

  /**
   * Generate planning text document
   * POST /api/sessions/{session_id}/planning-text
   */
  async generatePlanningText(
    _sessionId: string,
    _request?: GeneratePlanningTextRequest
  ): Promise<GeneratePlanningTextResponse> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 规划文本端点已下线（POST /api/sessions/{id}/planning-text）');
  },

  // ============================================
  // Settings API
  // ============================================

  /**
   * Update RAG configuration (runtime)
   * PATCH /api/sessions/{session_id}/rag-config
   */
  async updateRagConfig(
    _sessionId: string,
    _request: RagConfigRequest
  ): Promise<RagConfigResponse> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] RAG 配置端点已下线（PATCH /api/sessions/{id}/rag-config）');
  },

  /**
   * Update step mode (runtime)
   * PATCH /api/sessions/{session_id}/step-mode
   */
  async updateStepMode(
    _sessionId: string,
    _request: StepModeRequest
  ): Promise<StepModeResponse> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 分步模式端点已下线（PATCH /api/sessions/{id}/step-mode）');
  },

  /**
   * Geocode village address to center coordinates + boundary
   * GET /api/sessions/{session_id}/geocode
   */
  async geocodeVillage(
    _sessionId: string,
    _params: {
      village_name?: string;
      province?: string;
      city?: string;
      county?: string;
      township?: string;
    }
  ): Promise<GeocodeResponse> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] 地理编码端点已下线（GET /api/sessions/{id}/geocode）');
  },

  /**
   * Upload GIS data (GeoJSON) to an existing session
   * POST /api/sessions/{session_id}/gis-data
   */
  async uploadGisData(
    _sessionId: string,
    _file: File,
    _dataType?: string,
  ): Promise<GisDataUploadResponse> {
    // 该端点已从后端 v1 删除；此方法保留签名仅为类型兼容，运行时不再发起网络请求。
    throw new Error('[v1] GIS 上传端点已下线（POST /api/sessions/{id}/gis-data）');
  },

  /**
   * Get authoritative snapshot layers for a session.
   */
  async getRenderLayers(sessionId: string): Promise<RenderLayersResponse> {
    const response = await apiRequest<{
      layers: Array<{ layer_type: string; layer_name: string; geojson: RenderLayersResponse['layers'][number]['data'] }>;
      snapshot_checksum?: string;
      delivery_status?: RenderLayersResponse['delivery_status'];
    }>(`/api/v1/sessions/${sessionId}/map-layers`);
    return {
      session_id: sessionId,
      snapshot_checksum: response.snapshot_checksum,
      delivery_status: response.delivery_status,
      layers: response.layers.map((layer) => ({
        // Preserve the raw v1 layer_type so the adapter can map authoritatively.
        layerType: layer.layer_type,
        layerName: layer.layer_name,
        data: layer.geojson,
      })),
    };
  },

  /**
   * Get delivery projection for a session.
   * GET /api/v1/sessions/{session_id}/delivery
   */
  async getDelivery(sessionId: string): Promise<DeliveryProjection> {
    return apiRequest<DeliveryProjection>(`/api/v1/sessions/${sessionId}/delivery`);
  },

  /**
   * Read a typed artifact by explicit key.
   * GET /api/v1/sessions/{session_id}/artifacts/{artifact_key}
   * 404 means the stage has not produced it yet, not a session failure.
   */
  async getArtifact(
    sessionId: string,
    artifactKey: string,
  ): Promise<{
    session_id: string;
    artifact_key: string;
    artifact_ref: { digest: string; descriptor_digest: string };
    payload: Record<string, unknown>;
  }> {
    return apiRequest<{
      session_id: string;
      artifact_key: string;
      artifact_ref: { digest: string; descriptor_digest: string };
      payload: Record<string, unknown>;
    }>(`/api/v1/sessions/${sessionId}/artifacts/${artifactKey}`);
  },

  /**
   * Get pending human-review items for a paused post-L3 chain
   * GET /api/v1/sessions/{session_id}/human-review
   */
  async getHumanReview(sessionId: string): Promise<HumanReviewListResponse> {
    const response = await apiRequest<{
      pending: boolean;
      event_id?: string;
      paused_stage: string;
      items: HumanReviewListResponse['pending_items'];
    }>(`/api/v1/sessions/${sessionId}/human-review`);
    return {
      session_id: sessionId,
      post_l3_status: response.pending ? 'paused' : 'running',
      event_id: response.event_id,
      pending_items: response.items,
      count: response.items.length,
    };
  },

  /**
   * Submit human-review decisions and resume the post-L3 chain.
   * POST /api/v1/sessions/{session_id}/human-review
   * action ∈ approve | retry | reject. Must echo the current event_id as an
   * optimistic lock; a stale/conflicting decision returns 409.
   */
  async resolveHumanReview(
    sessionId: string,
    eventId: string,
    options: {
      action?: 'approve' | 'retry' | 'reject';
      feedback?: string;
      decisions?: Record<string, unknown>;
    } = {},
  ): Promise<HumanReviewResolveResponse> {
    const action = options.action ?? 'approve';
    const decisions = options.decisions ?? {};
    return apiRequest<HumanReviewResolveResponse>(`/api/v1/sessions/${sessionId}/human-review`, {
      method: 'POST',
      body: JSON.stringify({ event_id: eventId, action, decisions } satisfies HumanReviewResolveRequest & { action: string }),
    });
  },

  /**
   * Resume a workflow from a checkpoint or an active interrupt.
   * POST /api/v1/sessions/{session_id}/resume
   * - interrupt: resumes the current HUMAN checkpoint with the same event_id.
   * - checkpoint: forks a historical checkpoint into a new branch.
   */
  async resumeSession(
    sessionId: string,
    request: {
      mode: 'interrupt' | 'checkpoint';
      event_id?: string;
      action?: 'approve' | 'retry' | 'reject';
      feedback?: string;
      checkpoint_id?: string;
      replay_from_stage?: string;
    },
  ): Promise<{
    session_id: string;
    mode: 'interrupt' | 'checkpoint';
    status: string;
    checkpoint_id: string;
    branch_id: string;
    resume_plan: Record<string, unknown>;
  }> {
    return apiRequest<{
      session_id: string;
      mode: 'interrupt' | 'checkpoint';
      status: string;
      checkpoint_id: string;
      branch_id: string;
      resume_plan: Record<string, unknown>;
    }>(`/api/v1/sessions/${sessionId}/resume`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },
};
