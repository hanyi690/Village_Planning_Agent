/**
 * Specific Message Type Definitions
 * 特定消息类型定义
 *
 * This file contains all specific message type implementations that extend BaseMessage.
 * Each type represents a different kind of message in the conversational UI.
 */

import type { BaseMessage, ActionButton, KnowledgeReference } from './message';

// ============================================================================
// Core Message Types (实际使用的5种类型)
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
 * Dimension Report Message - Real-time streaming dimension report content
 */
export interface DimensionReportMessage extends BaseMessage {
  type: 'dimension_report';
  layer: number;
  dimensionKey: string;
  dimensionName: string;
  content: string;
  streamingState: 'streaming' | 'completed' | 'error';
  wordCount: number;
  progress?: {
    current: number;
    total: number;
  };
}

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

