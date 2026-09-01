// ============================================
// Planning API - 规划相关 API (Session 架构适配)
// ============================================

import { apiRequest, API_BASE_URL } from './client';
import { usePlanningStore } from '../store/planningStore';
import { isGisAttachment, isMineruAttachment } from '../constants';
import {
  assemblePlanningTextDocument,
  assemblePlanningTextVersions,
} from '../utils/assemble-planning-text';
import {
  exportLayerJsonClient,
  exportLayerMdClient,
  exportPlanningTextMdClient,
} from '../utils/export-reports';
import type {
  StartPlanningRequest,
  StartPlanningResponse,
  SessionStatusResponse,
  PlanningSSEEvent,
  PlanningSSEEventType,
  PlanningSSEDataBase,
  PlanningTextDocument,
  PlanningTextVersionList,
  GeneratePlanningTextRequest,
  GeneratePlanningTextResponse,
  StepModeRequest,
  StepModeResponse,
  RenderLayersResponse,
  PositioningTraceResponse,
  DeliveryProjection,
  HumanReviewListResponse,
  HumanReviewResolveRequest,
  HumanReviewResolveResponse,
  EvidenceQueryRequest,
  EvidenceQueryResponse,
  PlanningDependencyGraphResponse,
  PersistedHistoryResponse,
  CurrentSourceLayerCollection,
} from './types';

const PLANNING_ARTIFACT_FILENAME_PATTERNS = [
  /(?:^|[^a-z0-9])planned(?:$|[^a-z0-9])/i,
  /(?:^|[^a-z0-9])planning[\s_-]*(?:result|output|artifact)(?:$|[^a-z0-9])/i,
  /(?:plan[\s_-]*result|planned[\s_-]*(?:state|features)|selection[\s_-]*decision|execution[\s_-]*result|spatial[\s_-]*changeset|approved[\s_-]*execution[\s_-]*input)/i,
  /规划[\s_-]*(?:结果|成果|方案|思路|细化|文本|说明书|用地|道路|产物|输出|图件?)/u,
  /(?:详细规划|产业规划)/u,
];

const GIS_OR_TABLE_FILENAME_PATTERN = /\.(?:geojson|json|zip|shp|gpkg|kml|kmz|gml|csv|tsv|xlsx?|tif|tiff)$/i;

/**
 * Return whether a filename explicitly identifies a planning artifact.
 *
 * This is intentionally only a conflict check.  A filename must never be
 * used to infer that a document describes current conditions or to classify
 * its contents.
 */
export function isPlanningArtifactFilename(fileOrFilename: File | string): boolean {
  const filename = typeof fileOrFilename === 'string' ? fileOrFilename : fileOrFilename.name;
  const basename = filename.split(/[\\/]/).pop() || filename;
  const stem = basename.replace(/\.[^.]+$/, '');
  return (
    PLANNING_ARTIFACT_FILENAME_PATTERNS.some((pattern) => pattern.test(stem)) ||
    (GIS_OR_TABLE_FILENAME_PATTERN.test(basename) && /(?:规划|planned|planning)/iu.test(stem))
  );
}

// ============================================
// Planning API
// ============================================

export const planningApi = {
  /**
   * Start a new planning session (multipart/form-data)
   * POST /api/v1/sessions
   */
  async startPlanning(request: StartPlanningRequest): Promise<StartPlanningResponse> {
    const attachmentGroups = [
      { label: '村庄基础数据', files: request.villageDataFiles || [] },
      { label: '任务描述', files: request.taskFiles || [] },
      { label: '约束条件', files: request.constraintFiles || [] },
    ];
    const planningArtifactConflicts = attachmentGroups.flatMap(({ label, files }) =>
      files
        .filter(isPlanningArtifactFilename)
        .map((file) => `${label}“${file.name}”`),
    );
    if (planningArtifactConflicts.length > 0) {
      throw new Error(
        `上传被拒绝：${planningArtifactConflicts.join('、')}的文件名明确指向规划成果，不能作为村庄基础数据、任务描述或约束条件输入。请移除后再上传。这里只做文件名冲突拒绝，不据此判断文件内容或现状真实性。`,
      );
    }

    const attachments = attachmentGroups.flatMap(({ files }) => files);
    const unsupported = attachments.filter((file) => !isMineruAttachment(file) && !isGisAttachment(file));
    if (unsupported.length > 0) {
      throw new Error(`附件格式不受支持：${unsupported.map((file) => file.name).join('、')}。非 GIS 附件必须由 MinerU 预处理为 Markdown，GIS 附件进入空间 DATA。`);
    }
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
    formData.append('rag_enabled', String(request.rag_enabled ?? false));
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
        const parsedData = JSON.parse(rawData) as Record<string, unknown>;

        // The local v1 backend emits resync_required as a control payload,
        // not as the normal public-event envelope. Keep the recovery marker
        // intact so the store can trigger the REST state recovery path.
        if (type === 'resync_required') {
          onEvent({
            type,
            data: parsedData as PlanningSSEDataBase,
            session_id: sessionId,
          });
          return;
        }

        const envelope = parsedData as {
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

    // The local v1 backend projects dimension and GIS source events under the
    // public `progress` event and keeps their source type in `data.type`.
    // Register the public event names here; registering source event names
    // would not make EventSource receive anything from this backend.
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
   * Export a layer report from the current v1 report projection.
   */
  async exportLayerFormat(
    sessionId: string,
    layer: number,
    format: 'docx' | 'json' | 'md',
    _extraParams: string = '',
  ): Promise<string> {
    const { reports } = usePlanningStore.getState();
    if (format === 'json') return exportLayerJsonClient(sessionId, layer, reports);
    if (format === 'md') return exportLayerMdClient(sessionId, layer, reports);
    throw new Error('[v1] DOCX 导出暂由 Markdown 代替；请使用 MD 格式或等待 DELIVER 产物下载');
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
    const state = usePlanningStore.getState();
    const name = projectName || state.projectName || '村庄规划';
    const doc = assemblePlanningTextDocument(sessionId, state.reports, name);
    return exportPlanningTextMdClient(sessionId, doc.markdown_content, name);
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
   * Read the local v1 document projection assembled from authoritative report
   * events.  The old server-side planning-text endpoint was removed with the
   * legacy session API; DELIVER remains the legal artifact boundary.
   */
  async getPlanningText(sessionId: string, version?: number): Promise<PlanningTextDocument | null> {
    const state = usePlanningStore.getState();
    const document = assemblePlanningTextDocument(
      sessionId,
      state.reports,
      state.projectName || '村庄规划',
    );
    if (document.article_count === 0) return null;
    return version === undefined || version === document.version ? document : null;
  },

  async getPlanningTextVersions(sessionId: string, _limit?: number): Promise<PlanningTextVersionList> {
    const document = await this.getPlanningText(sessionId);
    return assemblePlanningTextVersions(sessionId, document);
  },

  async generatePlanningText(
    sessionId: string,
    request?: GeneratePlanningTextRequest,
  ): Promise<GeneratePlanningTextResponse> {
    const document = assemblePlanningTextDocument(
      sessionId,
      usePlanningStore.getState().reports,
      usePlanningStore.getState().projectName || '村庄规划',
      request,
    );
    return {
      session_id: document.session_id,
      version: document.version,
      document_id: document.document_id,
      markdown_content: document.markdown_content,
      article_count: document.article_count,
      generated_at: document.generated_at,
      generation_duration_seconds: 0,
      status: document.article_count > 0 ? 'completed' : 'empty',
      trigger_reason: request?.trigger_reason || 'manual',
    };
  },

  // ============================================
  // Settings API
  // ============================================

  /**
   * Update the local step-mode preference.  v1 accepts it only at creation.
   */
  async updateStepMode(
    _sessionId: string,
    request: StepModeRequest,
  ): Promise<StepModeResponse> {
    // v1: step_mode 仅在创建会话时提交；会话进行中仅更新本地 store。
    usePlanningStore.getState().setStepMode(Boolean(request.step_mode));
    return { session_id: _sessionId, step_mode: Boolean(request.step_mode) };
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
   * Get the configured current GIS context from the backend DataCatalog.
   * This endpoint is intentionally separate from DELIVER /map-layers.
   */
  async getCurrentSourceLayers(villageName = '金田村'): Promise<CurrentSourceLayerCollection> {
    return apiRequest<CurrentSourceLayerCollection>(
      `/api/v1/source-layers?village_name=${encodeURIComponent(villageName)}`,
    );
  },

  /**
   * Query the unified L1/KG/bundle evidence boundary.
   * POST /api/v1/sessions/{session_id}/evidence/query
   */
  async queryEvidence(
    sessionId: string,
    request: EvidenceQueryRequest,
  ): Promise<EvidenceQueryResponse> {
    return apiRequest<EvidenceQueryResponse>(
      `/api/v1/sessions/${sessionId}/evidence/query`,
      {
        method: 'POST',
        body: JSON.stringify(request),
      },
    );
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

  async listArtifacts(sessionId: string): Promise<{
    session_id: string;
    artifacts: Array<{ artifact_key: string; artifact_ref: Record<string, unknown> }>;
  }> {
    return apiRequest<{
      session_id: string;
      artifacts: Array<{ artifact_key: string; artifact_ref: Record<string, unknown> }>;
    }>(`/api/v1/sessions/${sessionId}/artifacts`);
  },

  /**
   * Read persisted stage summaries for the spatial planning chain.
   * GET /api/v1/sessions/{session_id}/positioning-trace
   */
  async getPositioningTrace(sessionId: string): Promise<PositioningTraceResponse> {
    return apiRequest<PositioningTraceResponse>(
      `/api/v1/sessions/${sessionId}/positioning-trace`,
    );
  },

  /**
   * Read the backend-declared topic dependency graph.
   * GET /api/v1/planning/dependency-graph
   */
  async getDependencyGraph(): Promise<PlanningDependencyGraphResponse> {
    return apiRequest<PlanningDependencyGraphResponse>('/api/v1/planning/dependency-graph');
  },

  /**
   * Read persisted project/session metadata for the restart-safe history sidebar.
   * GET /api/v1/projects
   */
  async listProjects(): Promise<PersistedHistoryResponse['projects']> {
    const response = await apiRequest<PersistedHistoryResponse>('/api/v1/projects');
    return response.projects;
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
      paused_stage: response.paused_stage,
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
