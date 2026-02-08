/**
 * Core Message Types
 * 对话式UI的核心消息类型定义
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

// Action Button
export interface ActionButton {
  id: string;
  label: string;
  action: 'approve' | 'reject' | 'view' | 'download' | 'continue' | 'modify';
  variant?: 'primary' | 'secondary' | 'success' | 'danger' | 'warning';
  onClick?: () => void | Promise<void>;
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

// Message union type - will be imported from message-types
import type {
  TextMessage,
  FileMessage,
  ProgressMessage,
  ActionMessage,
  ResultMessage,
  ErrorMessage,
  SystemMessage,
  LayerCompletedMessage,
  ReviewRequestMessage,
  CheckpointListMessage,
  ReviewInteractionMessage
} from './message-types';

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
