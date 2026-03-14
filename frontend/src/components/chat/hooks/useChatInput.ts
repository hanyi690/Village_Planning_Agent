// ============================================
// useChatInput Hook - 聊天输入逻辑
// ============================================

import { useState, useRef, useCallback } from 'react';
import { createSystemMessage, createErrorMessage } from '@/lib/utils';
import type { Message } from '@/types';

interface UseChatInputOptions {
  addMessage: (message: Message) => void;
  isPaused: boolean;
  pendingReviewLayer: number | null;
  approve: () => Promise<void>;
  reject: (feedback: string, dimensions?: string[]) => Promise<void>;
}

interface UseChatInputReturn {
  inputText: string;
  setInputText: (text: string) => void;
  isTyping: boolean;
  selectedDimensions: string[];
  setSelectedDimensions: (dimensions: string[]) => void;
  handleSendMessage: () => Promise<void>;
}

/**
 * 聊天输入 Hook
 * 处理消息发送、输入状态和审查模式下的特殊处理
 */
export function useChatInput({
  addMessage,
  isPaused,
  pendingReviewLayer,
  approve,
  reject,
}: UseChatInputOptions): UseChatInputReturn {
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);

  // Track typing timeout for cleanup
  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const handleSendMessage = useCallback(async () => {
    const userText = inputText.trim();
    if (!userText) return;

    setInputText('');

    // 保存当前选中的维度，然后清除
    const dimensionsToSubmit = selectedDimensions.length > 0 ? [...selectedDimensions] : undefined;
    setSelectedDimensions([]);

    // 审查状态下的特殊处理
    if (isPaused && pendingReviewLayer) {
      // 用户消息
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'user',
        type: 'text',
        content: userText,
      });

      // 判断是否为批准指令
      if (userText === '批准' || userText === '继续' || userText.toLowerCase() === 'approve') {
        try {
          addMessage(createSystemMessage('✅ 已批准，继续执行下一层...'));
          await approve();
        } catch (error: unknown) {
          const errorMessage = error instanceof Error ? error.message : '未知错误';
          addMessage(createErrorMessage(`批准失败: ${errorMessage}`));
        }
        return;
      }

      // 驳回/修改请求
      try {
        addMessage(createSystemMessage(`🔄 正在根据反馈修复规划内容${dimensionsToSubmit ? '...' : '（自动识别维度）...'} `));
        await reject(userText, dimensionsToSubmit);
      } catch (error: unknown) {
        const errorMessage = error instanceof Error ? error.message : '未知错误';
        addMessage(createErrorMessage(`修复失败: ${errorMessage}`));
      }
      return;
    }

    // Normal chat message
    addMessage({
      id: `msg-${Date.now()}`,
      timestamp: new Date(),
      role: 'user',
      type: 'text',
      content: userText,
    });

    setIsTyping(true);

    // Store timeout ID for cleanup
    typingTimeoutRef.current = setTimeout(() => {
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant',
        type: 'text',
        content: `收到: ${userText}`,
      });
      setIsTyping(false);
      typingTimeoutRef.current = null;
    }, 500);
  }, [inputText, addMessage, isPaused, pendingReviewLayer, approve, reject, selectedDimensions]);

  return {
    inputText,
    setInputText,
    isTyping,
    selectedDimensions,
    setSelectedDimensions,
    handleSendMessage,
  };
}