/**
 * Base Message Types
 *
 * Foundation types for the message system.
 * This file has no dependencies on other type files to avoid circular imports.
 */

// Base Message interface
export interface BaseMessage {
  id: string;
  timestamp: Date;
  role: 'user' | 'assistant' | 'system';
  created_at?: string;
  _pendingStorage?: boolean;
}

export type MessageRole = BaseMessage['role'];

// Supporting types
export interface KnowledgeReference {
  source: string;
  chapter?: string;
  page?: string;
  excerpt?: string;
}

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

export interface RevisionItem {
  dimension: string;
  dimensionName: string;
  layer: number;
  isTarget: boolean;
  revisionType: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  oldContent?: string;
  newContent?: string;
  feedback?: string;
  timestamp: string;
}

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

export interface ActionButton {
  id: string;
  label: string;
  action: 'approve' | 'reject' | 'view' | 'download' | 'continue' | 'modify';
  variant?: 'primary' | 'secondary' | 'success' | 'danger' | 'warning';
  onClick?: () => void | Promise<void>;
}

// Planning Params
export interface PlanningParams {
  projectName: string;
  villageData: string;
  villageName?: string;
  taskDescription?: string;
  constraints?: string;
  enableReview?: boolean;
  stepMode?: boolean;
  streamMode?: boolean;
  images?: import('../api/types').ImageData[];
  villageDataFiles?: File[];
  taskFiles?: File[];
  constraintFiles?: File[];
}