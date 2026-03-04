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
import type { ProgressMessage, TextMessage } from './message-types';
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
    } satisfies ProgressMessage;
  }

  // Paused state - use TextMessage with action buttons info
  if (event.status === 'paused' || event.event_type === 'pause') {
    return {
      ...base,
      type: 'text',
      content: `⏸️ 当前层级已完成，请审查后继续\n\n可执行操作：查看内容、批准继续、请求修改`,
    } satisfies TextMessage;
  }

  // Revision complete - use TextMessage
  if (event.event_type === 'revision_complete') {
    return {
      ...base,
      type: 'text',
      content: `✅ 修订已完成，请审查修订内容\n\n可执行操作：查看修订、批准继续、继续修改`,
    } satisfies TextMessage;
  }

  // Task completed - use TextMessage with result info
  if (event.status === 'completed' && event.result) {
    const projectName = event.result.project_name || '未知村庄';
    return {
      ...base,
      type: 'text',
      content: `🎉 规划已完成！\n\n村庄：${projectName}\n\n您可以在左侧查看完整规划报告。`,
    } satisfies TextMessage;
  }

  // Error state - use TextMessage with error info
  if (event.status === 'failed' || event.error) {
    return {
      ...base,
      type: 'text',
      content: `❌ 任务失败\n\n错误：${event.message || event.error || '未知错误'}`,
    } satisfies TextMessage;
  }

  // Default text message
  return {
    ...base,
    type: 'text',
    content: event.message || '处理中...',
  } satisfies TextMessage;
}
