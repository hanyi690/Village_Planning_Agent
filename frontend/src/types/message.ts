/**
 * Message Types for Conversational UI
 * 对话式UI的消息类型定义
 */

// Base Types
export interface BaseMessage {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
}

export type MessageRole = BaseMessage['role'];
export type MessageType = 'text' | 'file' | 'progress' | 'action' | 'result' | 'error' | 'system' | 'layer_completed' | 'review_request' | 'checkpoint_list' | 'review_interaction';

// Knowledge Reference Types (RAG集成)
export interface KnowledgeReference {
  source: string;
  chapter?: string;
  page?: string;
  excerpt?: string;
}

// Streaming State (for Gemini-style streaming output)
export type StreamingState = 'idle' | 'streaming' | 'paused' | 'completed';

// Message Types
export interface TextMessage extends BaseMessage {
  type: 'text';
  content: string;
  // Streaming support
  streamingState?: StreamingState;
  streamingContent?: string; // 当前已显示的内容
  // RAG知识引用
  knowledgeReferences?: KnowledgeReference[];
}

export interface FileMessage extends BaseMessage {
  type: 'file';
  filename: string;
  fileContent: string;
  fileSize?: number;
  encoding?: string;
}

export interface ProgressMessage extends BaseMessage {
  type: 'progress';
  content: string;
  progress: number;
  currentLayer?: string;
  taskId?: string;
}

export interface ActionMessage extends BaseMessage {
  type: 'action';
  content: string;
  actions: ActionButton[];
  taskId?: string;
}

export interface ResultMessage extends BaseMessage {
  type: 'result';
  content: string;
  villageName: string;
  sessionId: string;
  layers: string[];
  resultUrl?: string;
}

export interface ErrorMessage extends BaseMessage {
  type: 'error';
  content: string;
  error?: string;
  recoverable?: boolean;
}

export interface SystemMessage extends BaseMessage {
  type: 'system';
  content: string;
  level?: 'info' | 'warning' | 'error';
}

// Layer Completed Message
export interface LayerCompletedMessage extends BaseMessage {
  type: 'layer_completed';
  layer: number;
  content: string;
  summary: {
    word_count: number;
    key_points: string[];
    dimension_count?: number;
    dimension_names?: string[];
  };
  fullReportContent?: string;
  dimensionReports?: Record<string, string>;
  actions: ActionButton[];
}

// Review Request Message
export interface ReviewRequestMessage extends BaseMessage {
  type: 'review_request';
  content: string;
  layer: number;
  taskId: string;
  summary: {
    word_count: number;
    section_count: number;
  };
  actions: ActionButton[];
}

// Checkpoint List Message
export interface CheckpointListMessage extends BaseMessage {
  type: 'checkpoint_list';
  content: string;
  checkpoints: Checkpoint[];
  currentCheckpoint?: string;
  actions: ActionButton[];
}

// Review Interaction Message - Interactive review UI embedded in chat
export interface ReviewInteractionMessage extends BaseMessage {
  type: 'review_interaction';
  role: 'assistant';
  layer: number;
  content: string;
  reviewState: 'pending' | 'approved' | 'rejected' | 'rolled_back';

  // Review options
  availableActions: ('approve' | 'reject' | 'rollback')[];

  // Dimension selection
  enableDimensionSelection: boolean;
  availableDimensions?: DimensionInfo[];

  // Checkpoint rollback
  enableRollback: boolean;
  checkpoints?: Checkpoint[];

  // Feedback input
  feedbackPlaceholder: string;
  quickFeedbackOptions?: string[];

  // Submission status
  submittedAt?: Date;
  submittedBy?: 'user';
  submissionType?: 'approve' | 'reject' | 'rollback';
  submissionFeedback?: string;
  submissionDimensions?: string[];
}

// Dimension Info for review selection
export interface DimensionInfo {
  id: string;
  label: string;
  description?: string;
}

// Checkpoint type
export interface Checkpoint {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
}

export type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | ActionMessage
  | ResultMessage
  | ErrorMessage
  | SystemMessage
  | LayerCompletedMessage
  | ReviewRequestMessage
  | CheckpointListMessage
  | ReviewInteractionMessage;

// Action Button
export interface ActionButton {
  id: string;
  label: string;
  action: 'approve' | 'reject' | 'view' | 'download' | 'continue' | 'modify';
  variant?: 'primary' | 'secondary' | 'success' | 'danger' | 'warning';
  onClick?: () => void | Promise<void>;
}

// State Types
export interface ConversationState {
  conversationId: string;
  messages: Message[];
  taskId: string | null;
  projectName: string | null;
  status: 'idle' | 'collecting' | 'planning' | 'paused' | 'reviewing' | 'revising' | 'completed' | 'failed';
  viewerVisible: boolean;
  referencedSection?: string;
}

export interface PlanningParams {
  projectName: string;
  villageData: string;
  taskDescription?: string;
  constraints?: string;
  stepMode?: boolean;
  streamMode?: boolean;
  enableReview?: boolean;
}

// SSE Types
export interface SSEEvent {
  event_type?: string;
  status?: string;
  progress?: number;
  current_layer?: string;
  message?: string;
  task_id?: string;
  result?: any;
  error?: string;
  // Streaming support
  text_chunk?: string;
  thinking_state?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
}

// Layer Completed Event Data (for SSE)
export interface LayerCompletedEventData {
  layer: number;
  layer_number: number;
  session_id: string;
  message: string;
  current_layer: number;
  // Report content included directly in SSE event
  report_content?: string;
  dimension_reports?: Record<string, string>;
  timestamp?: number;
}

// Enhanced SSE Event Types for Gemini-style streaming
export interface SSETextChunkEvent {
  type: 'text_chunk';
  chunk: string;
  message_id: string;
  is_complete: boolean;
}

export interface SSEThinkingEvent {
  type: 'thinking';
  state: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
  message?: string;
}

// Message Feedback (for message actions)
export interface MessageFeedback {
  positive?: boolean;
  negative?: boolean;
  timestamp?: Date;
  comment?: string;
}

// Message Edit History
export interface MessageEdit {
  originalContent: string;
  editedContent: string;
  timestamp: Date;
}

// Enhanced Message Metadata
export interface MessageMetadata {
  // Streaming
  streamingState?: StreamingState;
  streamingContent?: string;
  // Feedback
  feedback?: MessageFeedback;
  // Edit history
  editHistory?: MessageEdit[];
  // Thinking state
  thinkingState?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
  // Display options
  highlighted?: boolean;
  pinned?: boolean;
  // Timestamps
  editedAt?: Date;
  streamingStartedAt?: Date;
  streamingCompletedAt?: Date;
}

// Helper Functions
const createBaseMessage = (): BaseMessage => ({
  id: `msg-${Date.now()}-${Math.random()}`,
  timestamp: new Date(),
  role: 'assistant',
});

const createActionButtons = (type: 'pause' | 'revision'): ActionButton[] => {
  const baseButtons: ActionButton[] = [
    { id: 'view', label: type === 'pause' ? '查看内容' : '查看修订', action: 'view' },
    { id: 'approve', label: '批准继续', action: 'approve', variant: 'success' },
  ];

  if (type === 'pause') {
    baseButtons.push({ id: 'reject', label: '请求修改', action: 'reject', variant: 'warning' });
  } else {
    baseButtons.push({ id: 'modify', label: '继续修改', action: 'modify', variant: 'warning' });
  }

  return baseButtons;
};

export function convertSSEToMessage(event: SSEEvent): Message {
  const base = createBaseMessage();

  // Progress updates
  if (event.status === 'running' && event.progress !== undefined) {
    return {
      ...base,
      type: 'progress',
      content: event.message || '正在处理...',
      progress: event.progress,
      currentLayer: event.current_layer,
      taskId: event.task_id,
    };
  }

  // Paused state
  if (event.status === 'paused' || event.event_type === 'pause') {
    return {
      ...base,
      type: 'action',
      content: '当前层级已完成，请审查后继续',
      actions: createActionButtons('pause'),
      taskId: event.task_id,
    };
  }

  // Revision complete
  if (event.event_type === 'revision_complete') {
    return {
      ...base,
      type: 'action',
      content: '修订已完成，请审查修订内容',
      actions: createActionButtons('revision'),
      taskId: event.task_id,
    };
  }

  // Task completed
  if (event.status === 'completed' && event.result) {
    return {
      ...base,
      type: 'result',
      content: '规划已完成！',
      villageName: event.result.project_name || '未知村庄',
      sessionId: event.result.session_id || '',
      layers: event.result.layers || [],
      resultUrl: `/villages/${encodeURIComponent(event.result.project_name || '')}`,
    };
  }

  // Error state
  if (event.status === 'failed' || event.error) {
    return {
      ...base,
      type: 'error',
      content: event.message || '任务失败',
      error: event.error,
      recoverable: false,
    };
  }

  // Default text message
  return {
    ...base,
    type: 'text',
    content: event.message || '处理中...',
  };
}

// Type Guards
export const isUserMessage = (msg: Message): boolean => msg.role === 'user';

export const isActionMessage = (msg: Message): msg is ActionMessage => msg.type === 'action';

export const isProgressMessage = (msg: Message): msg is ProgressMessage => msg.type === 'progress';

export const isResultMessage = (msg: Message): msg is ResultMessage => msg.type === 'result';

export const isErrorMessage = (msg: Message): msg is ErrorMessage => msg.type === 'error';

export const isLayerCompletedMessage = (msg: Message): msg is LayerCompletedMessage => msg.type === 'layer_completed';

export const isReviewRequestMessage = (msg: Message): msg is ReviewRequestMessage => msg.type === 'review_request';

export const isCheckpointListMessage = (msg: Message): msg is CheckpointListMessage => msg.type === 'checkpoint_list';

export const isReviewInteractionMessage = (msg: Message): msg is ReviewInteractionMessage => msg.type === 'review_interaction';
