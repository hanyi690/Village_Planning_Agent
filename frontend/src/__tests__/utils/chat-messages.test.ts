import type { Message } from '@/features/planning/types';
import {
  isConversationMessage,
  restoreChatHistoryMessages,
  selectConversationMessages,
} from '@/features/planning/utils/chat-messages';
import type { ChatHistoryMessage } from '@/features/planning/api';

const message = (overrides: Partial<Message>): Message => ({
  id: `message-${Math.random()}`,
  timestamp: new Date('2026-07-21T08:00:00.000Z'),
  role: 'assistant',
  type: 'text',
  content: 'hello',
  ...overrides,
} as Message);

describe('chat message selection', () => {
  it('keeps user and assistant conversation turns in their original order', () => {
    const user = message({ role: 'user', content: '请分析道路交通' });
    const assistant = message({ content: '可以，我会结合当前规划回答。' });
    const file = message({
      type: 'file',
      role: 'user',
      filename: '道路资料.pdf',
      fileContent: '',
    });

    expect(selectConversationMessages([user, assistant, file])).toEqual([
      user,
      assistant,
      file,
    ]);
  });

  it.each([
    'progress',
    'dimension_report',
    'layer_completed',
    'tool_status',
    'gis_result',
  ] as const)('excludes %s workflow artifacts from chat', (type) => {
    expect(isConversationMessage(message({ type } as Partial<Message>))).toBe(false);
  });

  it('does not mutate the workflow message collection', () => {
    const chat = message({ role: 'user', content: '你好' });
    const workflow = message({ type: 'layer_completed' } as Partial<Message>);
    const source = [workflow, chat];

    const selected = selectConversationMessages(source);

    expect(selected).toEqual([chat]);
    expect(source).toEqual([workflow, chat]);
  });

  it('restores only explicitly tagged user and assistant chat text', () => {
    const history = [
      {
        id: 'turn-1:user',
        source: 'chat',
        type: 'text',
        role: 'user',
        content: '道路交通有什么结论？',
        timestamp: '2026-07-21T08:00:00.000Z',
      },
      {
        id: 'turn-1:assistant',
        source: 'chat',
        type: 'text',
        role: 'assistant',
        content: '主要结论是村道较窄。',
        timestamp: '2026-07-21T08:00:01.000Z',
      },
      // Duplicate ids are ignored rather than rendered twice after restore.
      {
        id: 'turn-1:assistant',
        source: 'chat',
        type: 'text',
        role: 'assistant',
        content: '重复内容',
        timestamp: '2026-07-21T08:00:02.000Z',
      },
      // A workflow-like payload cannot cross the explicit source boundary.
      {
        id: 'layer-3',
        source: 'workflow',
        type: 'text',
        role: 'assistant',
        content: '整个 Layer 3 报告',
        timestamp: '2026-07-21T08:00:03.000Z',
      },
    ] as unknown as ChatHistoryMessage[];

    const restored = restoreChatHistoryMessages(history);

    expect(restored.map(({ id, role, content }) => ({ id, role, content }))).toEqual([
      {
        id: 'turn-1:user',
        role: 'user',
        content: '道路交通有什么结论？',
      },
      {
        id: 'turn-1:assistant',
        role: 'assistant',
        content: '主要结论是村道较窄。',
      },
    ]);
  });
});
