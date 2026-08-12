import type {
  FileMessage,
  Message,
  TextMessage,
} from '@/features/planning/types';
import type { ChatHistoryMessage } from '@/features/planning/api';

/**
 * Messages that belong in the conversational transcript.
 *
 * The planning store deliberately keeps workflow artifacts (dimension reports,
 * layer reports, tool runs and GIS results) in the same collection because
 * persistence and the report workbench still consume them.  The chat surface
 * must not treat those artifacts as user/assistant turns.
 */
export type ConversationMessage = TextMessage | FileMessage;

export function isConversationMessage(
  message: Message,
): message is ConversationMessage {
  return message.type === 'text' || message.type === 'file';
}

/**
 * Return a stable, ordered chat transcript without mutating the source array.
 */
export function selectConversationMessages(
  messages: readonly Message[],
): ConversationMessage[] {
  return messages.filter(isConversationMessage);
}

/**
 * Hydrate only the backend's explicitly tagged side-chat channel.
 *
 * The status payload also contains a legacy `messages` collection used by the
 * planning graph.  That collection is intentionally ignored here because it
 * may contain reports, tool calls and GIS artifacts.
 */
export function restoreChatHistoryMessages(
  history: readonly ChatHistoryMessage[] | null | undefined,
): TextMessage[] {
  if (!Array.isArray(history)) return [];

  const seen = new Set<string>();
  const restored: TextMessage[] = [];

  for (const item of history) {
    if (
      !item ||
      item.source !== 'chat' ||
      item.type !== 'text' ||
      (item.role !== 'user' && item.role !== 'assistant') ||
      typeof item.id !== 'string' ||
      !item.id ||
      typeof item.content !== 'string' ||
      !item.content.trim() ||
      seen.has(item.id)
    ) {
      continue;
    }

    const parsedTimestamp = new Date(item.timestamp);
    restored.push({
      id: item.id,
      type: 'text',
      role: item.role,
      content: item.content,
      timestamp: Number.isNaN(parsedTimestamp.getTime())
        ? new Date(0)
        : parsedTimestamp,
    });
    seen.add(item.id);
  }

  return restored;
}
