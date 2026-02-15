/**
 * Message Helper Functions
 * 消息辅助函数
 *
 * Helper functions for converting SSE events to frontend messages.
 */

import type {
  Message,
  ActionButton,
  SSEEvent,
} from './message';
import type { ProgressMessage, ActionMessage, ResultMessage, ErrorMessage } from './message-types';
import { createActionButtons } from '@/lib/utils';

/**
 * Convert SSE event to Message type
 * Maps backend SSE events to frontend Message types
 */
export function convertSSEToMessage(event: SSEEvent): Message {
  const base = {
    id: `msg-${Date.now()}-${Math.random()}`,
    timestamp: new Date(),
    role: 'assistant' as const,
  };

  // Progress updates
  if (event.status === 'running' && event.progress !== undefined) {
    return {
      ...base,
      type: 'progress',
      content: event.message || '正在处理...',
      progress: event.progress,
      currentLayer: event.current_layer,
      taskId: event.task_id,
    } as ProgressMessage;
  }

  // Paused state
  if (event.status === 'paused' || event.event_type === 'pause') {
    return {
      ...base,
      type: 'action',
      content: '当前层级已完成，请审查后继续',
      actions: createActionButtons('pause'),
      taskId: event.task_id,
    } as ActionMessage;
  }

  // Revision complete
  if (event.event_type === 'revision_complete') {
    return {
      ...base,
      type: 'action',
      content: '修订已完成，请审查修订内容',
      actions: createActionButtons('revision'),
      taskId: event.task_id,
    } as ActionMessage;
  }

  // Task completed
  if (event.status === 'completed' && event.result) {
    return {
      ...base,
      type: 'result',
      content: '规划已完成！',
      villageName: event.result.project_name || '未知村庄',
      sessionId: event.result.session_id || '',
      layers: event.result.layers || [],
      resultUrl: `/villages/${encodeURIComponent(event.result.project_name || '')}`,
    } as ResultMessage;
  }

  // Error state
  if (event.status === 'failed' || event.error) {
    return {
      ...base,
      type: 'error',
      content: event.message || '任务失败',
      error: event.error,
      recoverable: false,
    } as ErrorMessage;
  }

  // Default text message
  return {
    ...base,
    type: 'text',
    content: event.message || '处理中...',
  };
}