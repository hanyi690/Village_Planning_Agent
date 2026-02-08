/**
 * Unified API Client for Village Planning System
 * Refactored to match simplified backend architecture
 */

// ============================================
// Configuration
// ============================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

// ============================================
// Types
// ============================================

export interface VillageInfo {
  name: string;
  display_name: string;
  session_count: number;
  sessions: VillageSession[];
}

export interface VillageSession {
  session_id: string;
  timestamp: string;
  checkpoint_count: number;
  has_final_report: boolean;
}

export interface Checkpoint {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
}

export interface LayerContent {
  content: string;
  layer: string;
  session?: string;
  timestamp?: string;
  checkpoint_id?: string;
}

// ============================================
// Request/Response Types
// ============================================

export interface StartPlanningRequest {
  project_name: string;
  village_data: string;
  task_description?: string;
  constraints?: string;
  enable_review?: boolean;
  step_mode?: boolean;
  need_human_review?: boolean;
  stream_mode?: boolean;
  input_mode?: 'file' | 'text';
}

export interface StartPlanningResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface ReviewActionRequest {
  action: 'approve' | 'reject' | 'rollback';
  feedback?: string;
  dimensions?: string[];
  checkpoint_id?: string;
  review_id?: string;  // 新增：用于标识审查请求
}

export interface SessionStatusResponse {
  session_id: string;
  status: string;
  current_layer?: number;
  created_at: string;
  checkpoints: Checkpoint[];
  checkpoint_count: number;
  progress?: number;
}

export interface FileUploadResponse {
  content: string;
  encoding: string;
  size: number;
}

// SSE Event Types
export interface PlanningSSEEvent {
  type: 'layer_started' | 'layer_completed' | 'checkpoint_saved' | 'pause' | 'progress' | 'completed' | 'error' | 'resumed' | 'complete' | 'text_chunk' | 'thinking_start' | 'thinking' | 'thinking_end' | 'review_request' | 'content_delta';
  session_id?: string;
  data: {
    progress?: number;
    current_layer?: number;
    layer_number?: number;
    message?: string;
    result?: any;
    error?: string;
    // review_request 事件额外字段
    review_id?: string;
    title?: string;
    content?: string;
    status?: string;
    chunk?: string;
    message_id?: string;
    state?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
    // content_delta 事件额外字段
    delta?: string;
    accumulated?: string;
    dimension?: string;
    timestamp?: number;
    [key: string]: any;
  };
}

// ============================================
// Helper Functions
// ============================================

/**
 * Make an API request with error handling
 */
async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        message: response.statusText || 'API request failed',
      }));
      throw new Error(error.message || error.detail || 'API request failed');
    }

    return response.json();
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    throw new Error('Unknown error occurred');
  }
}

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
    onError?: (error: Error) => void
  ): EventSource {
    const url = `${API_BASE_URL}/api/planning/stream/${sessionId}`;
    const es = new EventSource(url);

    // Helper to parse SSE event
    const parseEvent = (event: MessageEvent, type: PlanningSSEEvent['type']) => {
      try {
        const data = JSON.parse(event.data);
        onEvent({ type, data, session_id: sessionId });
      } catch (error) {
        console.error(`[SSE] Failed to parse ${type}:`, error);
      }
    };

    // Layer started
    es.addEventListener('layer_started', (e) => parseEvent(e, 'layer_started'));

    // Layer completed
    es.addEventListener('layer_completed', (e) => parseEvent(e, 'layer_completed'));

    // Checkpoint saved
    es.addEventListener('checkpoint_saved', (e) => parseEvent(e, 'checkpoint_saved'));

    // Pause
    es.addEventListener('pause', (e) => {
      parseEvent(e, 'pause');
      // Don't close connection, wait for resume
    });

    // Stream paused - 主动关闭连接
    es.addEventListener('stream_paused', (e) => {
      console.log('[SSE] Stream paused by backend, closing connection');
      parseEvent(e, 'pause');  // 兼容：也触发 pause 事件
      es.close();  // 主动关闭连接
    });

    // Review request (新増)
    es.addEventListener('review_request', (e) => {
      parseEvent(e, 'review_request');
      // Don't close connection, wait for review action
    });

    // Content delta (流式输出)
    es.addEventListener('content_delta', (e) => parseEvent(e, 'content_delta'));

    // Resumed
    es.addEventListener('resumed', (e) => parseEvent(e, 'resumed'));

    // Progress
    es.addEventListener('progress', (e) => parseEvent(e, 'progress'));

    // Completed
    es.addEventListener('completed', (e) => {
      parseEvent(e, 'completed');
      es.close();
    });

    // Error
    es.addEventListener('error', (e: Event) => {
      console.error('[SSE] SSE error:', e);
      // 改进：传递更多上下文信息
      onEvent({
        type: 'error',
        data: {
          error: 'SSE connection failed',
          details: 'Failed to establish SSE connection',
          hint: 'Check if backend is running on port 8080'
        }
      });
      es.close();
    });

    // Connection error
    es.onerror = (error) => {
      console.error('[SSE] Connection error:', error);
      if (onError) onError(new Error('SSE connection error'));
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
  async rejectReview(sessionId: string, feedback: string, dimensions?: string[]): Promise<{ message: string; resumed?: boolean }> {
    return this.reviewAction(sessionId, {
      action: 'reject',
      feedback,
      dimensions,
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
   * Get task status (backward compatibility alias for getStatus)
   */
  async getTaskStatus(taskId: string): Promise<{ status: string; progress: number; checkpoints: Checkpoint[] }> {
    const sessionStatus = await this.getStatus(taskId);
    const currentLayer = sessionStatus.current_layer || 1;
    const progress = currentLayer >= 4 ? 100 : (currentLayer / 3) * 100;

    return {
      status: sessionStatus.status,
      progress,
      checkpoints: sessionStatus.checkpoints,
    };
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
};

// ============================================
// Data API
// ============================================

export const dataApi = {
  /**
   * List all villages
   * GET /api/data/villages
   */
  async listVillages(): Promise<VillageInfo[]> {
    const response = await apiRequest<{villages: VillageInfo[]}>('/api/data/villages');
    return response.villages || [];
  },

  /**
   * Get sessions for a village
   * GET /api/data/villages/{name}/sessions
   */
  async getVillageSessions(villageName: string): Promise<VillageSession[]> {
    return apiRequest<VillageSession[]>(
      `/api/data/villages/${encodeURIComponent(villageName)}/sessions`
    );
  },

  /**
   * Get layer content
   * GET /api/data/villages/{name}/layers/{layer}
   */
  async getLayerContent(
    villageName: string,
    layerId: string,
    session?: string,
    format: 'markdown' | 'html' | 'json' = 'markdown'
  ): Promise<LayerContent> {
    const params = new URLSearchParams({ format });
    if (session) params.append('session', session);

    return apiRequest<LayerContent>(
      `/api/data/villages/${encodeURIComponent(villageName)}/layers/${layerId}?${params}`
    );
  },

  /**
   * Get checkpoints for a village
   * GET /api/data/villages/{name}/checkpoints
   */
  async getCheckpoints(
    villageName: string,
    session?: string
  ): Promise<{ checkpoints: Checkpoint[]; count: number; project_name: string; session?: string }> {
    const params = new URLSearchParams();
    if (session) params.append('session', session);

    const query = params.toString() ? `?${params}` : '';
    return apiRequest<{ checkpoints: Checkpoint[]; count: number; project_name: string; session?: string }>(
      `/api/data/villages/${encodeURIComponent(villageName)}/checkpoints${query}`
    );
  },

  /**
   * Compare two checkpoints
   * GET /api/data/villages/{name}/compare/{cp1}/{cp2}
   */
  async compareCheckpoints(
    villageName: string,
    cp1: string,
    cp2: string
  ): Promise<{ diff: string; summary: string }> {
    return apiRequest(
      `/api/data/villages/${encodeURIComponent(villageName)}/compare/${cp1}/${cp2}`
    );
  },

  /**
   * Get combined plan
   * GET /api/data/villages/{name}/plan
   */
  async getCombinedPlan(
    villageName: string,
    session?: string,
    format: 'markdown' | 'html' | 'pdf' = 'markdown'
  ): Promise<{ content: string }> {
    const params = new URLSearchParams({ format });
    if (session) params.append('session', session);

    return apiRequest(
      `/api/data/villages/${encodeURIComponent(villageName)}/plan?${params}`
    );
  },
};

// ============================================
// Files API
// ============================================

export const fileApi = {
  /**
   * Upload file and extract content
   * POST /api/files/upload
   */
  async uploadFile(file: File): Promise<FileUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${API_BASE_URL}/api/files/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        message: response.statusText || 'File upload failed',
      }));
      throw new Error(error.message || error.detail || 'File upload failed');
    }

    return response.json();
  },

  /**
   * Get file content from URL
   */
  async getFileContent(url: string): Promise<string> {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Failed to fetch file: ${response.statusText}`);
    }
    return response.text();
  },
};

// ============================================
// Default Export
// ============================================

const api = {
  planningApi,
  dataApi,
  fileApi,
};

export default api;
