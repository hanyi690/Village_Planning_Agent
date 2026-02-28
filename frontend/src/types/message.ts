/**
 * Message Types for Conversational UI
 * 对话式UI的消息类型定义
 *
 * This file contains base types and the Message union type.
 * Specific message type definitions are in message-types.ts
 */

// ============================================================================
// Base Types
// ============================================================================

export interface BaseMessage {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
}

export type MessageRole = BaseMessage['role'];

// ============================================================================
// Supporting Types
// ============================================================================

// Knowledge Reference (RAG)
export interface KnowledgeReference {
  source: string;
  chapter?: string;
  page?: string;
  excerpt?: string;
}

// Checkpoint type
export interface Checkpoint {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
}

// Action Button
export interface ActionButton {
  id: string;
  label: string;
  action: 'approve' | 'reject' | 'view' | 'download' | 'continue' | 'modify';
  variant?: 'primary' | 'secondary' | 'success' | 'danger' | 'warning';
  onClick?: () => void | Promise<void>;
}

// ============================================================================
// SSE Types
// ============================================================================

export interface SSEEvent {
  event_type?: string;
  status?: string;
  progress?: number;
  current_layer?: string;
  message?: string;
  task_id?: string;
  result?: any;
  error?: string;
}

// ============================================================================
// State Types
// ============================================================================

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
  enableReview?: boolean;
  stepMode?: boolean;
  streamMode?: boolean;
}

// ============================================================================
// Message Union Type
// ============================================================================

// Import specific message types and create union
import type {
  TextMessage,
  FileMessage,
  ProgressMessage,
  ActionMessage,
  ResultMessage,
  ErrorMessage,
  SystemMessage,
  DimensionReportMessage,
  LayerCompletedMessage,
  DimensionRevisedMessage,
  CheckpointListMessage,
  ReviewRequestMessage,
} from './message-types';

export type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | ActionMessage
  | ResultMessage
  | ErrorMessage
  | SystemMessage
  | DimensionReportMessage
  | LayerCompletedMessage
  | DimensionRevisedMessage
  | CheckpointListMessage
  | ReviewRequestMessage;

// Re-export message types for convenience
export type {
  TextMessage,
  FileMessage,
  ProgressMessage,
  ActionMessage,
  ResultMessage,
  ErrorMessage,
  SystemMessage,
  DimensionReportMessage,
  LayerCompletedMessage,
  DimensionRevisedMessage,
  CheckpointListMessage,
  ReviewRequestMessage,
};