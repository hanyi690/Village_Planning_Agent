/**
 * Specific Message Type Definitions
 * 特定消息类型定义
 *
 * This file contains all specific message type implementations that extend BaseMessage.
 * Each type represents a different kind of message in the conversational UI.
 */

import type { BaseMessage, ActionButton, KnowledgeReference } from './message';

// ============================================================================
// Basic Message Types
// ============================================================================

/**
 * Text Message - Standard text content with optional streaming and knowledge references
 */
export interface TextMessage extends BaseMessage {
  type: 'text';
  content: string;
  // Streaming support
  streamingState?: 'idle' | 'streaming' | 'paused' | 'completed';
  streamingContent?: string; // 当前已显示的内容
  // RAG知识引用
  knowledgeReferences?: KnowledgeReference[];
}

/**
 * File Message - File upload/download messages
 */
export interface FileMessage extends BaseMessage {
  type: 'file';
  filename: string;
  fileContent: string;
  fileSize?: number;
  encoding?: string;
}

/**
 * Progress Message - Task progress updates
 */
export interface ProgressMessage extends BaseMessage {
  type: 'progress';
  content: string;
  progress: number;
  currentLayer?: string;
  taskId?: string;
}

/**
 * Action Message - Messages with action buttons
 */
export interface ActionMessage extends BaseMessage {
  type: 'action';
  content: string;
  actions: ActionButton[];
  taskId?: string;
}

/**
 * Result Message - Final task results
 */
export interface ResultMessage extends BaseMessage {
  type: 'result';
  content: string;
  villageName: string;
  sessionId: string;
  layers: string[];
  resultUrl?: string;
}

/**
 * Error Message - Error notifications
 */
export interface ErrorMessage extends BaseMessage {
  type: 'error';
  content: string;
  error?: string;
  recoverable?: boolean;
}

/**
 * System Message - System-level notifications
 */
export interface SystemMessage extends BaseMessage {
  type: 'system';
  content: string;
  level?: 'info' | 'warning' | 'error';
}

// ============================================================================
// Planning & Review Message Types
// ============================================================================

/**
 * Layer Completed Message - Shown when a planning layer is completed
 */
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

/**
 * Review Request Message - Request user review/approval
 */
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

/**
 * Checkpoint List Message - Display available checkpoints
 */
export interface CheckpointListMessage extends BaseMessage {
  type: 'checkpoint_list';
  content: string;
  checkpoints: import('./message').Checkpoint[];
  currentCheckpoint?: string;
  actions: ActionButton[];
}

/**
 * Review Interaction Message - Interactive review UI embedded in chat
 */
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
  availableDimensions?: import('./message').DimensionInfo[];

  // Checkpoint rollback
  enableRollback: boolean;
  checkpoints?: import('./message').Checkpoint[];

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
