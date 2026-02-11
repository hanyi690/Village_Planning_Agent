/**
 * Unified API Client for Village Planning System
 * Refactored to match simplified backend architecture
 */

// ============================================
// Configuration
// ============================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Retry configuration
const MAX_RETRIES = 3;
const INITIAL_RETRY_DELAY = 1000; // ms
const RETRY_BACKOFF_MULTIPLIER = 2;

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

// SSE Event type union for better type safety
export type PlanningSSEEventType =
  | 'layer_started'
  | 'layer_completed'
  | 'checkpoint_saved'
  | 'pause'
  | 'progress'
  | 'completed'
  | 'error'
  | 'resumed'
  | 'complete'
  | 'text_chunk'
  | 'thinking_start'
  | 'thinking'
  | 'thinking_end'
  | 'review_request'
  | 'content_delta'
  | 'stream_paused';

interface PlanningSSEDataBase {
  progress?: number;
  current_layer?: number;
  layer_number?: number;
  message?: string;
  result?: unknown;
  error?: string;
  review_id?: string;
  title?: string;
  content?: string;
  status?: string;
  chunk?: string;
  message_id?: string;
  state?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
  delta?: string;
  accumulated?: string;
  dimension?: string;
  timestamp?: number;
  [key: string]: unknown;
}

export interface PlanningSSEEvent {
  type: PlanningSSEEventType;
  session_id?: string;
  data: PlanningSSEDataBase;
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

  // Layer completion states
  layer_1_completed: boolean;
  layer_2_completed: boolean;
  layer_3_completed: boolean;

  // Pause/review states
  pause_after_step: boolean;
  waiting_for_review: boolean;
  last_checkpoint_id: string | null;

  // Error and completion states
  execution_error: string | null;
  execution_complete: boolean;

  // Timestamp
  updated_at?: string;
}

export interface FileUploadResponse {
  content: string;
  encoding: string;
  size: number;
}


// ============================================
// Helper Functions
// ============================================

interface ApiError {
  message?: string;
  detail?: string;
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  let lastError: Error | null = null;
  let retryDelay = INITIAL_RETRY_DELAY;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(url, { ...options, headers });

      if (response.ok) {
        return response.json();
      }

      // Don't retry client errors (4xx)
      if (response.status >= 400 && response.status < 500) {
        const error = await response.json().catch<ApiError>(() => ({
          message: response.statusText || 'API request failed',
        }));
        throw new Error(error.message || error.detail || 'API request failed');
      }

      // Server error (5xx) - retry
      lastError = new Error(`HTTP ${response.status}: ${response.statusText}`);

      if (attempt < MAX_RETRIES) {
        // Add jitter to prevent thundering herd
        const jitter = Math.random() * 200; // 0-200ms jitter
        await new Promise(resolve => setTimeout(resolve, retryDelay + jitter));
        retryDelay *= RETRY_BACKOFF_MULTIPLIER;
        console.warn(`[API] Retrying ${endpoint} (attempt ${attempt + 1}/${MAX_RETRIES})`);
      }

    } catch (error) {
      // Network error - retry
      if (error instanceof TypeError && attempt < MAX_RETRIES) {
        lastError = error;
        const jitter = Math.random() * 200;
        await new Promise(resolve => setTimeout(resolve, retryDelay + jitter));
        retryDelay *= RETRY_BACKOFF_MULTIPLIER;
        console.warn(`[API] Network error, retrying ${endpoint} (attempt ${attempt + 1}/${MAX_RETRIES})`);
      } else {
        throw error;
      }
    }
  }

  throw lastError || new Error('API request failed after retries');
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
    let connectionState: 'connecting' | 'connected' | 'paused' | 'closing' = 'connecting';

    // Helper to parse SSE event
    function parseEvent(event: MessageEvent, type: PlanningSSEEventType): void {
      try {
        const data = JSON.parse(event.data) as PlanningSSEDataBase;
        onEvent({ type, data, session_id: sessionId });
      } catch (error) {
        console.error(`[SSE] Failed to parse ${type}:`, error);
      }
    }

    // Define event listeners for each event type
    const eventTypes: PlanningSSEEventType[] = [
      'layer_started',
      'layer_completed',
      'checkpoint_saved',
      'review_request',
      'content_delta',
      'resumed',
      'progress',
    ];

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (e) => parseEvent(e, eventType));
    }

    // Special handling for pause events
    es.addEventListener('pause', (e) => {
      connectionState = 'paused';
      parseEvent(e, 'pause');
    });

    es.addEventListener('stream_paused', (e) => {
      connectionState = 'paused';
      parseEvent(e, 'pause'); // Also trigger pause for compatibility
      es.close();
    });

    // Completed event
    es.addEventListener('completed', (e) => {
      parseEvent(e, 'completed');
      es.close();
    });

    // Error event
    es.addEventListener('error', () => {
      onEvent({
        type: 'error',
        data: {
          error: 'SSE connection failed',
          details: 'Failed to establish SSE connection',
          hint: 'Check if backend is running on port 8000',
        },
      });
      es.close();
    });

    // Connection error handler
    es.onerror = (error) => {
      console.error('[SSE] Connection error:', error);
      console.error('[SSE] connectionState:', connectionState);
      console.error('[SSE] readyState:', es.readyState);

      // Distinguish between planned pause and actual error
      if (connectionState === 'paused' || es.readyState === 2) {
        console.log('[SSE] Connection closed as planned (pause state)');
        return;
      }

      console.error('[SSE] Unexpected connection error');
      onError?.(new Error('SSE connection error'));
    };

    es.onopen = () => {
      connectionState = 'connected';
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
