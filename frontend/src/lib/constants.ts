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

// ============================================
// File Upload Constants
// ============================================

export const MIN_FILE_CONTENT_LENGTH = 50;
export const FILE_ACCEPT = '.docx,.pdf,.txt,.md';

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

/**
 * Check if input should be disabled for a given status
 */
export function isInputDisabled(status: PlanningStatus): boolean {
  return DISABLE_INPUT_STATUSES.has(status as any);
}
