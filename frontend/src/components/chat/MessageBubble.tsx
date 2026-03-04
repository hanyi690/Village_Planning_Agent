'use client';

/**
 * MessageBubble Component
 * Individual message bubble with hover actions
 * 集成RAG知识引用显示
 */

import React, { useState } from 'react';
import { Message, ActionButton } from '@/types';
import { isUserMessage } from '@/types';
import MessageContent from './MessageContent';
import { formatMessageTimestamp } from '@/lib/utils';
import KnowledgeReference from '../report/KnowledgeReference';

interface MessageBubbleProps {
  message: Message;
  onAction?: (action: ActionButton, message: Message) => void;
  onCopy?: (message: Message) => void;
  onRegenerate?: (message: Message) => void;
  enableStreaming?: boolean;
  dimensionContents?: Map<string, string>;  // 实时流式内容（用于 token 级显示）
  children?: React.ReactNode;
}

export default function MessageBubble({
  message,
  onAction,
  onCopy,
  onRegenerate,
  enableStreaming = true,
  dimensionContents,
  children,
}: MessageBubbleProps) {
  const [isHovered, setIsHovered] = useState(false);
  const isUser = isUserMessage(message);

  const handleCopy = () => onCopy?.(message);
  const handleRegenerate = () => onRegenerate?.(message);

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className={`message-bubble relative max-w-[70%] rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 ${
          isUser
            ? 'bg-green-100 border border-green-300 text-gray-900 shadow-md hover:shadow-lg'
            : 'bg-white border border-gray-200 text-gray-900 hover:shadow-md'
        }`}
      >
        {/* Message Actions (Non-User Only) */}
        {!isUser && (
          <div className={`message-actions-container ${isHovered ? 'opacity-100' : 'opacity-0'}`}>
            <button
              className="message-action-btn"
              title="复制"
              onClick={handleCopy}
              aria-label="复制消息"
            >
              <i className="fas fa-copy" />
            </button>
            {message.type === 'text' && (
              <button
                className="message-action-btn"
                title="重新生成"
                onClick={handleRegenerate}
                aria-label="重新生成"
              >
                <i className="fas fa-redo" />
              </button>
            )}
          </div>
        )}

        {/* Assistant Label */}
        {!isUser && message.type !== 'progress' && (
          <div className="text-xs text-gray-600 mb-1 flex items-center gap-1.5 font-medium">
            <span className="w-1.5 h-1.5 bg-green-600 rounded-full" />
            AI 助手
          </div>
        )}

        {/* Message Content */}
        {children || (
          <MessageContent
            message={message}
            onAction={onAction}
            enableStreaming={enableStreaming}
            dimensionContents={dimensionContents}
          />
        )}

        {/* Knowledge References (RAG集成) */}
        {!isUser && message.type === 'text' && message.knowledgeReferences && message.knowledgeReferences.length > 0 && (
          <div className="mt-3">
            <KnowledgeReference references={message.knowledgeReferences} />
          </div>
        )}

        {/* Timestamp */}
        <div
          className={`text-[10px] mt-1.5 text-right ${
            isUser ? 'opacity-80' : 'opacity-60'
          } font-medium`}
        >
          {formatMessageTimestamp(message.timestamp)}
        </div>
      </div>
    </div>
  );
}
