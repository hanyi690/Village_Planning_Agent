// ============================================
// Request/Response Types
// ============================================

/**
 * 统一 API 响应格式
 * 提供一致的错误处理和类型安全
 */
export interface APIResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
  request_id?: string;
}

export interface ApiError {
  message?: string;
  detail?: string;
}

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
  | 'dimension_delta'
  | 'dimension_complete'
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
  pending_review_layer: null;
  previous_layer: null;
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

/**
 * 统一的 API 请求函数
 * 支持统一响应格式、重试和错误处理
 */
async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  let lastError: Error | null = null;
  let retryDelay = INITIAL_RETRY_DELAY;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(url, { ...options, method: options.method || 'GET', headers });

      // 解析响应数据
      const data = await response.json();

      // 非2xx响应必须抛出错误，绝不返回数据
      if (!response.ok) {
        // 尝试从错误响应中提取信息
        const errorData = data as ApiError;
        const errorMessage = errorData?.message || errorData?.detail || data?.error || 'API request failed';
        const requestId = (data as any)?.request_id;

        const error = new Error(errorMessage);
        (error as any).requestId = requestId;
        (error as any).status = response.status;
        throw error;
      }

      // 成功响应 - 检查标准格式并返回数据
      const apiResponse = data as APIResponse<any>;
      if (apiResponse?.success !== undefined) {
        // 标准格式响应
        if (!apiResponse.success) {
          // success=false 的错误响应
          const errorMessage = apiResponse.error || apiResponse.message || 'API request failed';
          const requestId = apiResponse.request_id;
          const error = new Error(errorMessage);
          (error as any).requestId = requestId;
          (error as any).status = response.status;
          throw error;
        }
        // 返回数据（支持 data 字段或直接返回 data 本身）
        return apiResponse.data ?? apiResponse;
      }

      // 旧格式直接返回
      return data;

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

  // 抛出最后的错误（如果所有重试都失败）
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
      'dimension_delta',
      'dimension_complete',
    ];

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (e) => parseEvent(e, eventType));
    }

    // Special handling for pause events
    // Note: Do NOT close SSE connection here - let it close naturally when backend finishes
    // The REST polling will detect pause_after_step and update UI state
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

// ============================================
// Compatibility Aliases
// ============================================

/**
 * taskApi - 别名指向 planningApi
 * 用于兼容使用 taskApi 的旧代码
 */
export const taskApi = planningApi;

/**
 * ReviewData 类型 - 用于 ReviewDrawer
 */
export interface ReviewData {
  current_layer: number;
  content: string;
  summary: {
    word_count: number;
    dimension_count?: number;
  };
  available_dimensions: string[];
  checkpoints: Checkpoint[];
}

export default api;
