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
  // 🔧 内部标记：延迟存储（等待完整数据后再存储）
  _pendingStorage?: boolean;
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

// Revision Item - 修复项（区分目标维度和级联维度）
export interface RevisionItem {
  dimension: string;
  dimensionName: string;
  layer: number;
  isTarget: boolean;                    // 是否是用户选择的目标维度
  revisionType: string;                 // "目标维度修复" | "级联更新"
  status: 'pending' | 'processing' | 'completed' | 'failed';
  oldContent?: string;
  newContent?: string;
  feedback?: string;
  timestamp: string;
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

// Import specific message types and create union (只保留实际使用的5种类型)
import type {
  TextMessage,
  FileMessage,
  ProgressMessage,
  DimensionReportMessage,
  LayerCompletedMessage,
} from './message-types';

export type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | DimensionReportMessage
  | LayerCompletedMessage;

// Re-export message types for convenience
export type {
  TextMessage,
  FileMessage,
  ProgressMessage,
  DimensionReportMessage,
  LayerCompletedMessage,
};