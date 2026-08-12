import { usePlanningStore } from '@/features/planning/store/planningStore';

describe('planning store chat event routing', () => {
  beforeEach(() => {
    usePlanningStore.getState().resetConversation();
    usePlanningStore.getState().clearMessages();
  });

  it('does not turn an unscoped planning AI completion into a chat message', () => {
    usePlanningStore.getState().handleSSEEvent({
      type: 'ai_response_complete',
      data: { content: 'Layer 3 自动生成的详细规划正文' },
    });

    expect(usePlanningStore.getState().messages).toEqual([]);
  });

  it('accepts an AI completion explicitly marked as conversational', () => {
    usePlanningStore.getState().handleSSEEvent({
      type: 'ai_response_complete',
      data: {
        content: '这是对用户问题的直接回答',
        channel: 'conversation',
      },
    });

    expect(usePlanningStore.getState().messages).toEqual([
      expect.objectContaining({
        role: 'assistant',
        type: 'text',
        content: '这是对用户问题的直接回答',
      }),
    ]);
  });
});
