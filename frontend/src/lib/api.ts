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
  | 'dimension_revised'
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

  // 【新增】消息历史和修订历史
  messages?: Array<{
    type: string;
    content: string;
    role: string;
  }>;
  revision_history?: Array<{
    dimension: string;
    layer: number;
    old_content: string;
    new_content: string;
    feedback: string;
    timestamp: string;
  }>;

  // 【新增】UI 消息列表
  ui_messages?: UIMessage[];
  
  // ✅ 新增：维度报告数据（用于历史加载恢复完整报告）
  analysis_reports?: Record<string, string>;
  concept_reports?: Record<string, string>;
  detail_reports?: Record<string, string>;
}

// UI 消息类型（用于持久化存储）
export interface UIMessage {
  id: number;
  session_id: string;
  message_id: string;  // ✅ 前端消息 ID（用于 upsert）
  role: 'user' | 'assistant' | 'system';
  content: string;
  message_type: string;
  message_metadata?: Record<string, unknown>;
  created_at?: string;  // ✅ 原始创建时间（用于排序）
  timestamp: string;    // 最后更新时间
}

// 【Signal-Fetch Pattern】层级报告响应类型
export interface LayerReportsResponse {
  layer: number;
  reports: Record<string, string>;  // 维度键 -> 维度内容
  report_content: string;           // 合并后的完整报告
  project_name: string;
  completed: boolean;               // 该层级是否完成
  stats: {
    dimension_count: number;
    total_chars: number;
  };
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
   * 
   * @param sessionId - 会话 ID
   * @param onEvent - 事件回调
   * @param onError - 错误回调（仅用于不可恢复的错误）
   * @param onReconnect - 重连成功回调（浏览器自动重连后触发，用于同步状态）
   */
  createStream(
    sessionId: string,
    onEvent: (event: PlanningSSEEvent) => void,
    onError?: (error: Error) => void,
    onReconnect?: () => void
  ): EventSource {
    const url = `${API_BASE_URL}/api/planning/stream/${sessionId}`;
    const es = new EventSource(url);
    let connectionState: 'connecting' | 'connected' | 'paused' | 'closing' = 'connecting';
    
    // 🔧 重连检测：标记是否正在重连
    let isReconnecting = false;
    let wasConnected = false;

    // 🔧 空闲超时保护：跟踪最后活动时间
    // 注意：必须在 parseEvent 之前定义，以便闭包访问
    const IDLE_TIMEOUT_MS = 5 * 60 * 1000; // 5 分钟
    let lastActivityTime = Date.now();

    // Helper to parse SSE event
    function parseEvent(event: MessageEvent, type: PlanningSSEEventType): void {
      // ✅ 重置空闲计时器 - 命名事件也需要重置活动时间
      lastActivityTime = Date.now();
      
      try {
        const rawData = event.data;
        const data = JSON.parse(rawData) as PlanningSSEDataBase;
        
        // ✅ Signal-Fetch Pattern: SSE 只发送轻量信号
        if (type === 'layer_completed') {
          const layer = (data as any).layer || '?';
          const hasData = (data as any).has_data ?? false;
          const dimensionCount = (data as any).dimension_count || 0;
          const totalChars = (data as any).total_chars || 0;
          
          console.log(`[SSE] layer_completed signal received:`, {
            layer,
            has_data: hasData,
            dimension_count: dimensionCount,
            total_chars: totalChars,
            rawDataLength: rawData?.length || 0,
          });
          
          // 信号模式下，has_data 表示后端是否有数据
          if (!hasData) {
            console.warn(`[SSE] ⚠️ layer_completed 信号显示后端无数据，前端将从 REST API 获取`);
          }
        } else if (type === 'dimension_complete') {
          const dimKey = (data as any).dimension_key || '?';
          const fullContent = (data as any).full_content || '';
          console.log(`[SSE] dimension_complete: ${dimKey} (${fullContent.length} chars)`);
        } else if (type === 'dimension_delta') {
          // ✅ 增强日志：记录详细的事件信息
          const dimKey = (data as any).dimension_key || '?';
          const accumulated = (data as any).accumulated || '';
          const delta = (data as any).delta || '';
          const layer = (data as any).layer || '?';
          
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
      'layer_completed',
      'checkpoint_saved',
      'review_request',
      'content_delta',
      'resumed',
      'progress',
      'dimension_delta',
      'dimension_complete',
      'dimension_revised',
    ];

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (e) => parseEvent(e, eventType));
    }

    // Special handling for terminal events
    // 🔧 架构优化：遵循"显式终态协议"
    // 后端发送 stream_paused/completed 表示所有数据已发送完毕
    // 使用 queueMicrotask 确保 UI 更新已提交后再关闭连接

    es.addEventListener('pause', (e) => {
      connectionState = 'paused';
      parseEvent(e, 'pause');
      // 使用 queueMicrotask 确保 React state 更新已提交后再关闭
      queueMicrotask(() => {
        if (es.readyState !== EventSource.CLOSED) {
          es.close();
          console.log('[SSE] Connection closed after pause event (via queueMicrotask)');
        }
      });
    });

    es.addEventListener('stream_paused', (e) => {
      connectionState = 'paused';
      parseEvent(e, 'pause'); // Also trigger pause for compatibility
      // 后端确保所有事件已发送，可以安全关闭
      queueMicrotask(() => {
        if (es.readyState !== EventSource.CLOSED) {
          es.close();
          console.log('[SSE] Connection closed after stream_paused event (via queueMicrotask)');
        }
      });
    });

    es.addEventListener('completed', (e) => {
      parseEvent(e, 'completed');
      // 任务完成，立即关闭连接
      queueMicrotask(() => {
        if (es.readyState !== EventSource.CLOSED) {
          es.close();
          console.log('[SSE] Connection closed after completed event');
        }
      });
    });

    // Error event listener for named 'error' events from server
    es.addEventListener('error', (e) => {
      // 这是一个命名事件，不是连接错误
      // 服务端发送的 error 事件
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

    // Connection error handler (onerror is for connection-level errors)
    // MDN: 当连接失败时触发 error 事件
    es.onerror = () => {
      // readyState 2 = CLOSED：连接已正常关闭（后端结束了响应）
      if (es.readyState === EventSource.CLOSED) {
        console.log('[SSE] Connection closed by server (readyState=CLOSED)');
        return;
      }

      // readyState 0 = CONNECTING：浏览器正在尝试重连
      if (es.readyState === EventSource.CONNECTING) {
        // 🔧 修复：如果之前已连接过，说明是断线重连
        if (wasConnected) {
          isReconnecting = true;
          console.log('[SSE] Connection lost, browser is auto-reconnecting...');
        } else {
          console.log('[SSE] Initial connection in progress...');
        }
        return;
      }

      // 其他情况才是真正的错误
      console.error('[SSE] Unexpected connection error, readyState:', es.readyState);
      onError?.(new Error('SSE connection error'));
    };

    es.onopen = () => {
      // 🔧 重连检测：如果之前设置过重连标记，说明这是重连成功
      if (isReconnecting) {
        console.log('[SSE] ✅ Auto-reconnect successful! Calling onReconnect callback...');
        isReconnecting = false;
        // 调用重连回调，让上层决定是否需要同步状态
        onReconnect?.();
      }
      connectionState = 'connected';
      wasConnected = true;
    };

    // 🔧 空闲超时检查：定期检查连接活动状态
    // 注意：lastActivityTime 已在函数开头定义，parseEvent 中会重置
    const idleCheckInterval = setInterval(() => {
      const idleTime = Date.now() - lastActivityTime;
      if (idleTime > IDLE_TIMEOUT_MS && es.readyState !== EventSource.CLOSED) {
        console.warn('[SSE] Connection idle timeout (5 min), closing');
        clearInterval(idleCheckInterval);
        es.close();
      }
    }, 60000); // 每分钟检查一次

    // 清理函数：关闭连接时清除定时器
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
   * 【Signal-Fetch Pattern】获取指定层级的维度报告
   * GET /api/planning/sessions/{session_id}/layer/{layer}/reports
   * 
   * 从 Checkpoint 获取完整、可靠的维度报告数据，
   * 避免依赖 SSE 传输中可能不完整的数据。
   */
  async getLayerReports(sessionId: string, layer: number): Promise<LayerReportsResponse> {
    return apiRequest<LayerReportsResponse>(`/api/planning/sessions/${sessionId}/layer/${layer}/reports`);
  },

  /**
   * Get dimension content (Signal-Fetch Pattern)
   * GET /api/planning/sessions/{session_id}/dimensions/{dimension_key}
   * 
   * 当收到 dimension_revised SSE 信号后，调用此 API 获取完整内容。
   */
  async getDimensionContent(sessionId: string, dimensionKey: string): Promise<{
    dimension_key: string;
    layer: number;
    content: string;
    version: number;
    exists: boolean;
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

  /**
   * Create UI message (with upsert)
   * POST /api/planning/messages/{session_id}
   * 
   * 使用前端消息 ID 进行 upsert：
   * - 如果消息已存在（相同 session_id + message_id），则更新
   * - 否则创建新消息
   */
  async createMessage(sessionId: string, message: {
    id: string;  // 前端消息 ID（唯一标识，用于 upsert）
    role: string;
    content: string;
    message_type?: string;
    metadata?: Record<string, unknown>;
  }): Promise<{ success: boolean; message_id: number; frontend_id: string }> {
    return apiRequest(`/api/planning/messages/${sessionId}`, {
      method: 'POST',
      body: JSON.stringify({
        message_id: message.id,  // 传递前端消息 ID
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
  async getMessages(sessionId: string, role?: string, limit?: number): Promise<{ success: boolean; messages: UIMessage[] }> {
    const params = new URLSearchParams();
    if (role) params.append('role', role);
    if (limit) params.append('limit', String(limit));
    const query = params.toString() ? `?${params.toString()}` : '';
    return apiRequest(`/api/planning/messages/${sessionId}${query}`);
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
// Knowledge Base Types
// ============================================

export interface KnowledgeDocument {
  source: string;
  chunk_count: number;
  doc_type: string;
}

export interface KnowledgeStats {
  total_documents: number;
  total_chunks: number;
  vector_db_path: string;
  source_dir: string;
}

export interface AddDocumentResponse {
  status: string;
  message: string;
  source?: string;
  chunks_added?: number;
}

export interface SyncResponse {
  status: string;
  message: string;
  added_count?: number;
}

// ============================================
// Knowledge API
// ============================================

export const knowledgeApi = {
  /**
   * 列出知识库中的所有文档
   * GET /api/knowledge/documents
   */
  async listDocuments(): Promise<KnowledgeDocument[]> {
    return apiRequest<KnowledgeDocument[]>('/api/knowledge/documents');
  },

  /**
   * 上传文档到知识库（增量添加）
   * POST /api/knowledge/documents
   */
  async addDocument(file: File, category?: string): Promise<AddDocumentResponse> {
    const formData = new FormData();
    formData.append('file', file);
    if (category) {
      formData.append('category', category);
    }

    const response = await fetch(`${API_BASE_URL}/api/knowledge/documents`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        message: response.statusText || 'Upload failed',
      }));
      throw new Error(error.message || error.detail || 'Upload failed');
    }

    return response.json();
  },

  /**
   * 删除文档
   * DELETE /api/knowledge/documents/{filename}
   */
  async deleteDocument(filename: string): Promise<{ status: string; message: string }> {
    return apiRequest(`/api/knowledge/documents/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    });
  },

  /**
   * 获取知识库统计信息
   * GET /api/knowledge/stats
   */
  async getStats(): Promise<KnowledgeStats> {
    return apiRequest<KnowledgeStats>('/api/knowledge/stats');
  },

  /**
   * 同步源目录
   * POST /api/knowledge/sync
   */
  async syncDocuments(): Promise<SyncResponse> {
    return apiRequest<SyncResponse>('/api/knowledge/sync', {
      method: 'POST',
    });
  },
};

// ============================================
// Default Export
// ============================================

const api = {
  planningApi,
  dataApi,
  fileApi,
  knowledgeApi,
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
