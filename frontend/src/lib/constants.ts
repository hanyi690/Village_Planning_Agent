/**
 * Application Constants
 * Shared constants used across the application
 */

// ============================================
// Layer Constants
// ============================================

export const LAYER_ID_MAP: Record<number, 'layer_1_analysis' | 'layer_2_concept' | 'layer_3_detailed'> = {
  1: 'layer_1_analysis',
  2: 'layer_2_concept',
  3: 'layer_3_detailed',
} as const;

export const LAYER_LABEL_MAP: Record<string, number> = {
  '现状分析': 1,
  '规划思路': 2,
  '详细规划': 3,
};

export const LAYER_VALUE_MAP: Record<number, string> = {
  1: '现状分析',
  2: '规划思路',
  3: '详细规划',
};

export const LAYER_OPTIONS = ['现状分析', '规划思路', '详细规划'] as const;
export const LAYER_OPTIONS_ARRAY = ['现状分析', '规划思路', '详细规划'];

// 层级 ID 数组，用于遍历
export const LAYER_IDS = [1, 2, 3] as const;

// SSE 数据完整性阈值：超过此字符数视为数据完整
export const MIN_SSE_DATA_CHARS = 100;

// 层级阶段类型
export type LayerPhase = 'idle' | '现状分析' | '规划思路' | '详细规划';

/**
 * Get layer ID from layer number
 */
export function getLayerId(
  layer: number
): 'layer_1_analysis' | 'layer_2_concept' | 'layer_3_detailed' | null {
  return LAYER_ID_MAP[layer] || null;
}

/**
 * Get layer name from layer number
 */
export function getLayerName(layer: number): string {
  return LAYER_VALUE_MAP[layer] || `Layer ${layer}`;
}

/**
 * Get layer phase from layer number
 * Used for phase display in progress panels
 */
export function getLayerPhase(layer: number): LayerPhase {
  return (LAYER_VALUE_MAP[layer] as LayerPhase) || 'idle';
}

// ============================================
// File Upload Constants
// ============================================

export const MIN_FILE_CONTENT_LENGTH = 50;
export const FILE_ACCEPT = '.docx,.doc,.pdf,.pptx,.ppt,.xlsx,.xls,.txt,.md';

// ============================================
// Status Constants
// ============================================

export const DISABLE_INPUT_STATUSES = new Set([
  'planning',
  'revising',
] as const);

export type PlanningStatus =
  | 'idle'
  | 'collecting'
  | 'planning'
  | 'paused'
  | 'reviewing'
  | 'revising'
  | 'completed'
  | 'failed';

// ============================================
// Status Badge Constants
// ============================================

export interface StatusBadgeConfig {
  className: string;
  icon: string;
  label: string;
}

export const STATUS_BADGE_MAP: Record<PlanningStatus, StatusBadgeConfig> = {
  idle: { className: 'bg-gray-100 text-gray-700', icon: '💬', label: '就绪' },
  collecting: { className: 'status-badge-info', icon: '🔄', label: '执行中' },
  planning: { className: 'status-badge-info', icon: '🔄', label: '执行中' },
  paused: { className: 'status-badge-warning', icon: '⏸️', label: '等待审查' },
  reviewing: { className: 'status-badge-warning', icon: '🔍', label: '审查中' },
  revising: { className: 'status-badge-warning', icon: '🔧', label: '修复中' },
  completed: { className: 'status-badge-success', icon: '✅', label: '已完成' },
  failed: { className: 'status-badge-error', icon: '❌', label: '失败' },
};

/**
 * Get status badge config for a given status
 */
export function getStatusBadge(status: PlanningStatus): StatusBadgeConfig {
  return STATUS_BADGE_MAP[status] || STATUS_BADGE_MAP.idle;
}

/**
 * View mode for the main content switcher
 */
export type ViewMode = 'WELCOME_FORM' | 'SESSION_ACTIVE';

/**
 * Check if input should be disabled for a given status
 */
export function isInputDisabled(status: PlanningStatus): boolean {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return DISABLE_INPUT_STATUSES.has(status as any);
}
