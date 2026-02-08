/**
 * Message Helpers
 * Common message creation and manipulation utilities
 */

import { Message, SystemMessage, ActionButton, BaseMessage } from '@/types';

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
  return {
    id: generateMessageId(),
    timestamp: new Date(),
    role,
  };
}

/**
 * Create a system notification message
 */
export function createSystemMessage(content: string, level: 'info' | 'warning' | 'error' = 'info'): SystemMessage {
  return {
    ...createBaseMessage('system'),
    type: 'system',
    content,
    level,
  } as SystemMessage;
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
export function createSuccessMessage(content: string): SystemMessage {
  return createSystemMessage(`✅ ${content}`, 'info');
}

/**
 * Create error message
 */
export function createErrorMessage(content: string, recoverable = false): SystemMessage {
  return {
    ...createBaseMessage('system'),
    type: 'system',
    content: `❌ ${content}`,
    level: 'error',
    recoverable,
  } as SystemMessage & { recoverable?: boolean };
}

/**
 * Create warning message
 */
export function createWarningMessage(content: string): SystemMessage {
  return createSystemMessage(`⚠️ ${content}`, 'warning');
}

/**
 * Create info message
 */
export function createInfoMessage(content: string): SystemMessage {
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
    const date = new Date(timestamp);
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
 * Parse custom timestamp format (YYYYMMDD_HHMMSS)
 */
export function parseCustomTimestamp(timestamp: string): string {
  const match = timestamp.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (!match) return timestamp;

  const [, year, month, day, hour, minute] = match;
  return `${year}-${month}-${day} ${hour}:${minute}`;
}
