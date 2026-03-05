'use client';

/**
 * MessageBubble Component - Gemini Style
 * Individual message bubble with hover actions
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
  dimensionContents?: Map<string, string>;
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
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4 animate-slide-up`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className={`relative max-w-[75%] rounded-2xl px-4 py-3 transition-all duration-200 ${
          isUser
            ? 'bg-gradient-to-r from-green-600 to-green-500 text-white shadow-lg shadow-green-500/20 rounded-br-md'
            : 'bg-[#1e1e1e] border border-[#2d2d2d] text-white hover:border-[#3f3f46] rounded-bl-md'
        }`}
      >
        {/* Message Actions (AI messages only) */}
        {!isUser && (
          <div className={`absolute -top-2 right-3 flex gap-1 transition-all duration-200 ${isHovered ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1'}`}>
            <button
              className="p-1.5 bg-[#2d2d2d] border border-[#3f3f46] rounded-lg text-zinc-400 hover:text-green-400 hover:border-green-500/50 transition-all duration-150"
              title="复制"
              onClick={handleCopy}
              aria-label="复制消息"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </button>
            {message.type === 'text' && (
              <button
                className="p-1.5 bg-[#2d2d2d] border border-[#3f3f46] rounded-lg text-zinc-400 hover:text-green-400 hover:border-green-500/50 transition-all duration-150"
                title="重新生成"
                onClick={handleRegenerate}
                aria-label="重新生成"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            )}
          </div>
        )}

        {/* AI Assistant Label */}
        {!isUser && message.type !== 'progress' && (
          <div className="flex items-center gap-2 mb-2 pb-2 border-b border-[#2d2d2d]">
            <div className="flex items-center justify-center w-5 h-5 rounded-full bg-gradient-to-br from-green-500 to-green-600">
              <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </div>
            <span className="text-xs font-medium text-zinc-400">AI 助手</span>
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

        {/* Knowledge References */}
        {!isUser && message.type === 'text' && message.knowledgeReferences && message.knowledgeReferences.length > 0 && (
          <div className="mt-3 pt-3 border-t border-[#2d2d2d]">
            <KnowledgeReference references={message.knowledgeReferences} />
          </div>
        )}

        {/* Timestamp */}
        <div className={`flex items-center justify-end gap-1 mt-2 ${isUser ? 'text-white/60' : 'text-zinc-500'}`}>
          <span className="text-[10px] font-medium">
            {formatMessageTimestamp(message.timestamp)}
          </span>
        </div>
      </div>
    </div>
  );
}