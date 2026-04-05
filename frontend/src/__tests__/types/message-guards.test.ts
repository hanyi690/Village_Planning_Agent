/**
 * Message Type Guards Tests
 * 消息类型守卫函数测试
 */

import {
  isUserMessage,
  isTextMessage,
  isFileMessage,
  isProgressMessage,
  isLayerCompletedMessage,
  isDimensionReportMessage,
} from '@/types/message/message-guards';
import type {
  Message,
  TextMessage,
  FileMessage,
  ProgressMessage,
  LayerCompletedMessage,
  DimensionReportMessage,
} from '@/types';

describe('Message Type Guards', () => {
  // Helper to create base message
  const createBaseMessage = (role: Message['role'] = 'assistant') => ({
    id: 'test-msg-1',
    timestamp: new Date(),
    role,
  });

  describe('isUserMessage', () => {
    it('should return true for user messages', () => {
      const message: Message = {
        ...createBaseMessage('user'),
        type: 'text',
        content: 'Hello',
      };
      expect(isUserMessage(message)).toBe(true);
    });

    it('should return false for assistant messages', () => {
      const message: Message = {
        ...createBaseMessage('assistant'),
        type: 'text',
        content: 'Hi there',
      };
      expect(isUserMessage(message)).toBe(false);
    });

    it('should return false for system messages', () => {
      const message: Message = {
        ...createBaseMessage('system'),
        type: 'text',
        content: 'System message',
      };
      expect(isUserMessage(message)).toBe(false);
    });
  });

  describe('isTextMessage', () => {
    it('should return true for text messages', () => {
      const message: TextMessage = {
        ...createBaseMessage(),
        type: 'text',
        content: 'Hello world',
      };
      expect(isTextMessage(message)).toBe(true);
    });

    it('should return false for non-text messages', () => {
      const message: FileMessage = {
        ...createBaseMessage(),
        type: 'file',
        filename: 'test.txt',
        fileSize: 100,
        fileContent: 'content',
      };
      expect(isTextMessage(message)).toBe(false);
    });
  });

  describe('isFileMessage', () => {
    it('should return true for file messages', () => {
      const message: FileMessage = {
        ...createBaseMessage(),
        type: 'file',
        filename: 'test.txt',
        fileSize: 1024,
        fileContent: 'test content',
      };
      expect(isFileMessage(message)).toBe(true);
    });

    it('should return false for non-file messages', () => {
      const message: TextMessage = {
        ...createBaseMessage(),
        type: 'text',
        content: 'Hello world',
      };
      expect(isFileMessage(message)).toBe(false);
    });
  });

  describe('isProgressMessage', () => {
    it('should return true for progress messages', () => {
      const message: ProgressMessage = {
        ...createBaseMessage(),
        type: 'progress',
        content: 'Processing...',
        progress: 50,
      };
      expect(isProgressMessage(message)).toBe(true);
    });

    it('should return false for non-progress messages', () => {
      const message: TextMessage = {
        ...createBaseMessage(),
        type: 'text',
        content: 'Hello world',
      };
      expect(isProgressMessage(message)).toBe(false);
    });
  });

  describe('isLayerCompletedMessage', () => {
    it('should return true for layer completed messages', () => {
      const message: LayerCompletedMessage = {
        ...createBaseMessage(),
        type: 'layer_completed',
        layer: 1,
        content: 'Layer 1 completed',
        summary: {
          word_count: 100,
          key_points: ['point1'],
          dimension_count: 5,
        },
        dimensionReports: {},
        actions: [],
      };
      expect(isLayerCompletedMessage(message)).toBe(true);
    });

    it('should return false for non-layer completed messages', () => {
      const message: TextMessage = {
        ...createBaseMessage(),
        type: 'text',
        content: 'Hello world',
      };
      expect(isLayerCompletedMessage(message)).toBe(false);
    });
  });

  describe('isDimensionReportMessage', () => {
    it('should return true for dimension report messages', () => {
      const message: DimensionReportMessage = {
        ...createBaseMessage(),
        type: 'dimension_report',
        layer: 1,
        dimensionKey: 'industry',
        dimensionName: '产业现状',
        content: 'Industry analysis...',
        streamingState: 'completed',
        wordCount: 100,
      };
      expect(isDimensionReportMessage(message)).toBe(true);
    });

    it('should return false for non-dimension report messages', () => {
      const message: TextMessage = {
        ...createBaseMessage(),
        type: 'text',
        content: 'Hello world',
      };
      expect(isDimensionReportMessage(message)).toBe(false);
    });
  });

  describe('Type narrowing', () => {
    it('should correctly narrow types in conditional blocks', () => {
      const messages: Message[] = [
        { ...createBaseMessage('user'), type: 'text', content: 'User message' },
        {
          ...createBaseMessage(),
          type: 'file',
          filename: 'test.txt',
          fileSize: 100,
          fileContent: 'content',
        },
        { ...createBaseMessage(), type: 'progress', content: 'Loading...', progress: 30 },
      ];

      // TypeScript should correctly narrow types in these conditions
      const textMessages = messages.filter(isTextMessage);
      expect(textMessages).toHaveLength(1);
      expect(textMessages[0].content).toBe('User message');

      const fileMessages = messages.filter(isFileMessage);
      expect(fileMessages).toHaveLength(1);
      expect(fileMessages[0].filename).toBe('test.txt');

      const progressMessages = messages.filter(isProgressMessage);
      expect(progressMessages).toHaveLength(1);
      expect(progressMessages[0].progress).toBe(30);
    });
  });
});
