/**
 * Message Helpers
 * Common message creation and manipulation utilities
 */

import { Message, ActionButton, BaseMessage, TextMessage, Checkpoint } from '@/types';

const MESSAGE_ID_COUNTER = { value: 0 };

/**
 * Generate unique message ID
 */
export function generateMessageId(): string {
  MESSAGE_ID_COUNTER.value += 1;
  return `msg-${Date.now()}-${MESSAGE_ID_COUNTER.value}`;
}

/**
 * Create a base message with common fields
 * Returns complete BaseMessage with required fields
 */
export function createBaseMessage(role: Message['role'] = 'assistant'): BaseMessage {
  const now = new Date();
  return {
    id: generateMessageId(),
    timestamp: now,
    created_at: now.toISOString(),  // ✅ 原始创建时间，用于历史消息正确排序
    role,
  };
}

/**
 * Create a system notification message (as TextMessage)
 * Note: System notifications are ephemeral UI signals and should NOT be persisted to database.
 * The _pendingStorage flag prevents automatic storage in addMessage().
 *
 * @param content - 消息内容
 * @param level - 消息级别
 * @param timestamp - 可选的时间戳（ISO 字符串），用于排序。如果不提供则使用当前时间
 */
export function createSystemMessage(
  content: string,
  level: 'info' | 'warning' | 'error' = 'info',
  timestamp?: string
): TextMessage & { created_at: string } {
  const prefix = level === 'error' ? '❌ ' : level === 'warning' ? '⚠️ ' : 'ℹ️ ';
  const createdAt = timestamp || new Date().toISOString();
  return {
    ...createBaseMessage('assistant'),
    type: 'text',
    content: `${prefix}${content}`,
    created_at: createdAt,  // ✅ 添加 created_at 用于排序
  } as TextMessage & { created_at: string };
}

/**
 * Create action buttons for pause/revision scenarios
 */
export function createActionButtons(type: 'pause' | 'revision'): ActionButton[] {
  const buttons: ActionButton[] = [
    { id: 'view', label: type === 'pause' ? '查看内容' : '查看修订', action: 'view' },
    { id: 'approve', label: '批准继续', action: 'approve', variant: 'success' },
  ];

  if (type === 'pause') {
    buttons.push({ id: 'reject', label: '请求修改', action: 'reject', variant: 'warning' });
  } else {
    buttons.push({ id: 'modify', label: '继续修改', action: 'modify', variant: 'warning' });
  }

  return buttons;
}

/**
 * Create success message
 */
export function createSuccessMessage(content: string): TextMessage {
  return createSystemMessage(`✅ ${content}`, 'info');
}

/**
 * Create error message
 */
export function createErrorMessage(content: string, _recoverable = false): TextMessage {
  return {
    ...createBaseMessage('assistant'),
    type: 'text',
    content: `❌ ${content}`,
  };
}

/**
 * Create warning message
 */
export function createWarningMessage(content: string): TextMessage {
  return createSystemMessage(`⚠️ ${content}`, 'warning');
}

/**
 * Create info message
 */
export function createInfoMessage(content: string): TextMessage {
  return createSystemMessage(content, 'info');
}

/**
 * Truncate ID for display
 */
export function truncateId(id: string, length: number = 8): string {
  return id.length > length ? `${id.slice(0, length)}...` : id;
}

/**
 * Format timestamp for display
 */
export function formatMessageTimestamp(date: Date): string {
  return date.toLocaleTimeString();
}

/**
 * Format full timestamp for display
 */
export function formatFullTimestamp(timestamp: string): string {
  try {
    const date = parseTimestamp(timestamp);
    if (!date) return timestamp;
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return timestamp;
  }
}

/**
 * Parse timestamp safely
 * Handles ISO 8601, custom formats, and returns null for invalid dates
 */
export function parseTimestamp(timestamp: string | Date | undefined | null): Date | null {
  if (!timestamp) return null;

  // 如果已经是 Date 对象
  if (timestamp instanceof Date) {
    return isNaN(timestamp.getTime()) ? null : timestamp;
  }

  // 尝试解析字符串
  try {
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) {
      // 尝试解析 YYYYMMDD_HHMMSS 格式
      const match = timestamp.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
      if (match) {
        const [, year, month, day, hour, minute, second] = match;
        const parsed = new Date(
          parseInt(year),
          parseInt(month) - 1,
          parseInt(day),
          parseInt(hour),
          parseInt(minute),
          parseInt(second)
        );
        return isNaN(parsed.getTime()) ? null : parsed;
      }
      return null;
    }
    return date;
  } catch {
    return null;
  }
}

/**
 * Get timestamp for sorting (returns milliseconds or 0 for invalid dates)
 */
export function getSortTimestamp(timestamp: string | Date | undefined | null): number {
  const date = parseTimestamp(timestamp);
  return date ? date.getTime() : 0;
}

/**
 * Parse custom timestamp format (YYYYMMDD_HHMMSS)
 */
export function parseCustomTimestamp(timestamp: string): string {
  const match = timestamp.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (!match) return timestamp;

  const [, year, month, day, hour, minute] = match;
  return `${year}-${month}-${day} ${hour}:${minute}`;
}

/**
 * Extract error message from unknown error
 * Reusable helper to avoid duplicated error handling pattern
 */
export function getErrorMessage(error: unknown, fallback = '未知错误'): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'string') {
    return error;
  }
  if (error && typeof error === 'object' && 'message' in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

// ============================================
// Message ID Factories
// ============================================

/**
 * Build layer report message ID
 * Used for layer_report messages that aggregate dimension reports
 */
export function buildLayerReportId(layer: number): string {
  return `layer_report_${layer}`;
}

/**
 * Build revision report message ID
 * Used for revision_report messages that show revision results
 */
export function buildRevisionReportId(layer: number, dimensionKey: string): string {
  return `revision_report_${layer}_${dimensionKey}`;
}

/**
 * Build dimension progress key
 * Used as key in dimensionProgress state record
 */
export function buildDimensionProgressKey(layer: number, dimensionKey: string): string {
  return `${layer}_${dimensionKey}`;
}

// ============================================
// Dimension Report Utilities
// ============================================

/**
 * Format dimension reports as markdown content
 * Converts Record of dimension reports to a single markdown string
 */
export function formatDimensionReportsAsContent(
  dimensionReports: Record<string, string>
): string {
  return Object.entries(dimensionReports)
    .map(([key, content]) => `## ${key}\n\n${content}`)
    .join('\n\n---\n\n');
}

/**
 * Calculate summary from dimension reports
 * Returns word count and dimension count for progress tracking
 */
export function calculateReportSummary(
  dimensionReports: Record<string, string>
): { word_count: number; dimension_count: number } {
  return {
    word_count: Object.values(dimensionReports).reduce(
      (sum, content) => sum + (content?.length || 0),
      0
    ),
    dimension_count: Object.keys(dimensionReports).length,
  };
}

// ============================================
// Checkpoint Utilities
// ============================================

/**
 * Find the latest checkpoint matching a predicate
 * Filters checkpoints and returns the one with the latest timestamp
 */
export function findLatestCheckpoint(
  checkpoints: Checkpoint[],
  predicate: (cp: Checkpoint) => boolean
): Checkpoint | undefined {
  return checkpoints
    .filter(predicate)
    .sort((a, b) => (a.timestamp > b.timestamp ? 1 : -1))
    .at(-1);
}

/**
 * Build checkpoint lookup map by layer
 * Pre-computes checkpoint lookups for efficient access in render loops
 */
export function buildCheckpointByLayerMap(
  checkpoints: Checkpoint[]
): Map<number, Checkpoint[]> {
  const map = new Map<number, Checkpoint[]>();
  for (const cp of checkpoints) {
    const arr = map.get(cp.layer) ?? [];
    arr.push(cp);
    map.set(cp.layer, arr);
  }
  // Sort each layer's checkpoints by timestamp
  for (const [, arr] of map) {
    arr.sort((a, b) => (a.timestamp > b.timestamp ? 1 : -1));
  }
  return map;
}

// ============================================
// Word Count Utilities
// ============================================

/**
 * Format word count for display
 * Shows 'k' suffix for counts >= 1000
 */
export function formatWordCount(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return count.toString();
}