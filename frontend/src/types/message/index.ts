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
  // ✅ 原始创建时间（ISO 字符串），用于历史消息正确排序
  // 后端数据库在插入时设置，更新时保持不变
  created_at?: string;
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
  type?: 'key' | 'regular';
  phase?: string;
  current_layer?: number;
  previous_layer?: number;
  isRevision?: boolean;
  revisedDimensions?: string[];
}

// Revision Item - 修复项（区分目标维度和级联维度）
export interface RevisionItem {
  dimension: string;
  dimensionName: string;
  layer: number;
  isTarget: boolean; // 是否是用户选择的目标维度
  revisionType: string; // "目标维度修复" | "级联更新"
  status: 'pending' | 'processing' | 'completed' | 'failed';
  oldContent?: string;
  newContent?: string;
  feedback?: string;
  timestamp: string;
}

// Dimension Progress - 维度进度项（支持多维度并行执行）
export type DimensionStatus = 'pending' | 'streaming' | 'completed' | 'failed';

export interface DimensionProgressItem {
  dimensionKey: string;
  dimensionName: string;
  layer: number;
  status: DimensionStatus;
  wordCount: number;
  startedAt?: string;
  completedAt?: string;
  error?: string;
  isRevision?: boolean;
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

/**
 * SSE Event result 类型
 * 包含状态、消息和可选的数据负载
 */
export interface SSEEventResult {
  status?: string;
  message?: string;
  data?: unknown;
  [key: string]: unknown;
}

export interface SSEEvent {
  event_type?: string;
  status?: string;
  progress?: number;
  current_layer?: string;
  message?: string;
  task_id?: string;
  result?: SSEEventResult;
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
  status:
    | 'idle'
    | 'collecting'
    | 'planning'
    | 'paused'
    | 'reviewing'
    | 'revising'
    | 'completed'
    | 'failed';
  viewerVisible: boolean;
  referencedSection?: string;
}

export interface PlanningParams {
  projectName: string;
  villageData: string;
  villageName?: string;
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
  DimensionReportMessage,
  LayerCompletedMessage,
  ToolCallMessage,
  ToolProgressMessage,
  ToolResultMessage,
} from './message-types';

export type Message =
  | TextMessage
  | FileMessage
  | ProgressMessage
  | DimensionReportMessage
  | LayerCompletedMessage
  | ToolCallMessage
  | ToolProgressMessage
  | ToolResultMessage;

// Re-export message types for convenience
export type {
  TextMessage,
  FileMessage,
  ProgressMessage,
  DimensionReportMessage,
  LayerCompletedMessage,
  ToolCallMessage,
  ToolProgressMessage,
  ToolResultMessage,
};

// Re-export guards and helpers
export * from './message-guards';
export * from './message-helpers';
