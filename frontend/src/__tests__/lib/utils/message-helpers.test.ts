/**
 * Message Helpers Tests
 * 消息辅助函数测试
 */

import {
  generateMessageId,
  createBaseMessage,
  createSystemMessage,
  createSuccessMessage,
  createErrorMessage,
  createWarningMessage,
  createActionButtons,
} from '@/lib/utils/message-helpers';

describe('Message Helpers', () => {
  describe('generateMessageId', () => {
    it('should generate unique message IDs', () => {
      const id1 = generateMessageId();
      const id2 = generateMessageId();
      expect(id1).not.toBe(id2);
    });

    it('should generate IDs with correct format', () => {
      const id = generateMessageId();
      expect(id).toMatch(/^msg-\d+-\d+$/);
    });
  });

  describe('createBaseMessage', () => {
    it('should create a message with default role', () => {
      const message = createBaseMessage();
      expect(message.role).toBe('assistant');
      expect(message.id).toBeDefined();
      expect(message.timestamp).toBeInstanceOf(Date);
      expect(message.created_at).toBeDefined();
    });

    it('should create a message with specified role', () => {
      const userMessage = createBaseMessage('user');
      expect(userMessage.role).toBe('user');

      const systemMessage = createBaseMessage('system');
      expect(systemMessage.role).toBe('system');
    });
  });

  describe('createSystemMessage', () => {
    it('should create info message with default level', () => {
      const message = createSystemMessage('Test message');
      expect(message.type).toBe('text');
      expect(message.content).toBe('ℹ️ Test message');
      expect(message._pendingStorage).toBe(true);
    });

    it('should create warning message', () => {
      const message = createSystemMessage('Warning!', 'warning');
      expect(message.content).toBe('⚠️ Warning!');
    });

    it('should create error message', () => {
      const message = createSystemMessage('Error!', 'error');
      expect(message.content).toBe('❌ Error!');
    });

    it('should use provided timestamp', () => {
      const timestamp = '2024-01-01T00:00:00.000Z';
      const message = createSystemMessage('Test', 'info', timestamp);
      expect(message.created_at).toBe(timestamp);
    });
  });

  describe('createSuccessMessage', () => {
    it('should create success message with checkmark', () => {
      const message = createSuccessMessage('Operation completed');
      expect(message.content).toBe('ℹ️ ✅ Operation completed');
    });
  });

  describe('createErrorMessage', () => {
    it('should create error message with X mark', () => {
      const message = createErrorMessage('Something went wrong');
      expect(message.content).toBe('❌ Something went wrong');
    });
  });

  describe('createWarningMessage', () => {
    it('should create warning message', () => {
      const message = createWarningMessage('Be careful');
      expect(message.content).toBe('⚠️ ⚠️ Be careful');
    });
  });

  describe('createActionButtons', () => {
    it('should create pause action buttons', () => {
      const buttons = createActionButtons('pause');
      expect(buttons).toHaveLength(3);
      expect(buttons[0].action).toBe('view');
      expect(buttons[1].action).toBe('approve');
      expect(buttons[2].action).toBe('reject');
    });

    it('should create revision action buttons', () => {
      const buttons = createActionButtons('revision');
      expect(buttons).toHaveLength(3);
      expect(buttons[0].action).toBe('view');
      expect(buttons[1].action).toBe('approve');
      expect(buttons[2].action).toBe('modify');
    });
  });
});