'use client';

/**
 * MessageBubble Component - Gemini Style
 * Individual message bubble with Gemini-style design
 * - AI messages: transparent background, left-aligned with avatar
 * - User messages: pill-shaped, right-aligned
 */

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Message } from '@/types';
import { isUserMessage } from '@/types';
import MessageContent from './MessageContent';
import { formatMessageTimestamp } from '@/lib/utils';
import KnowledgeReference from '../report/KnowledgeReference';

interface MessageBubbleProps {
  message: Message;
  onCopy?: (message: Message) => void;
  onRegenerate?: (message: Message) => void;
  enableStreaming?: boolean;
  dimensionContents?: Map<string, string>;
  children?: React.ReactNode;
}

function MessageBubble({
  message,
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

  // Animation variants
  const bubbleVariants = {
    hidden: {
      opacity: 0,
      y: 10,
      scale: 0.98,
    },
    visible: {
      opacity: 1,
      y: 0,
      scale: 1,
      transition: {
        type: 'spring' as const,
        stiffness: 150,
        damping: 20,
      },
    },
  };

  // AI Avatar Component with gradient
  const AIAvatar = () => (
    <div
      className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-sm"
      style={{
        background: 'linear-gradient(135deg, #10b981 0%, #14b8a6 50%, #0891b2 100%)',
      }}
    >
      <i className="fas fa-sparkles text-[10px]" />
    </div>
  );

  // User messages: right-aligned pill shape
  if (isUser) {
    return (
      <motion.div
        variants={bubbleVariants}
        initial="hidden"
        animate="visible"
        className="flex justify-end mb-4"
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        <div className="max-w-[75%] bg-gradient-to-br from-emerald-100/80 to-teal-50 border border-emerald-200 text-gray-900 rounded-2xl rounded-br-md px-4 py-3 shadow-sm">
          {/* Message Content */}
          {children || (
            <MessageContent
              message={message}
              enableStreaming={enableStreaming}
              dimensionContents={dimensionContents}
            />
          )}

          {/* Timestamp */}
          <div className="text-[10px] text-gray-500 text-right mt-1.5 font-medium">
            {formatMessageTimestamp(message.timestamp)}
          </div>
        </div>
      </motion.div>
    );
  }

  // AI messages: left-aligned with avatar, transparent background (Gemini style)
  return (
    <motion.div
      variants={bubbleVariants}
      initial="hidden"
      animate="visible"
      className="flex justify-start mb-4 gap-3"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* AI Avatar */}
      <div className="flex-shrink-0 pt-1">
        <AIAvatar />
      </div>

      {/* Message Content Area */}
      <div className="flex-1 min-w-0">
        {/* AI Label */}
        {message.type !== 'progress' && (
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-xs font-medium text-transparent bg-clip-text bg-gradient-to-r from-emerald-500 to-teal-500">
              AI 助手
            </span>
          </div>
        )}

        {/* Message Body */}
        <div className="relative group">
          {/* Action Buttons (hover to show) */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: isHovered ? 1 : 0 }}
            className="absolute -right-2 top-0 flex items-center gap-1 bg-white rounded-lg shadow-md border border-gray-100 p-1 -translate-y-1/2 z-10"
          >
            <button
              className="w-7 h-7 flex items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
              title="复制"
              onClick={handleCopy}
              aria-label="复制消息"
            >
              <i className="fas fa-copy text-xs" />
            </button>
            {message.type === 'text' && (
              <button
                className="w-7 h-7 flex items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
                title="重新生成"
                onClick={handleRegenerate}
                aria-label="重新生成"
              >
                <i className="fas fa-redo text-xs" />
              </button>
            )}
          </motion.div>

          {/* Content - with background and border for visibility */}
          <div className="text-gray-800 leading-relaxed bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm">
            {children || (
              <MessageContent
                message={message}
                enableStreaming={enableStreaming}
                dimensionContents={dimensionContents}
              />
            )}
          </div>

          {/* Knowledge References */}
          {message.type === 'text' &&
            message.knowledgeReferences &&
            message.knowledgeReferences.length > 0 && (
              <div className="mt-3">
                <KnowledgeReference references={message.knowledgeReferences} />
              </div>
            )}

          {/* Timestamp */}
          <div className="text-[10px] text-gray-400 mt-2">
            {formatMessageTimestamp(message.timestamp)}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// React.memo 优化：减少不必要的重渲染
const MemoizedMessageBubble = React.memo(MessageBubble);

export default MemoizedMessageBubble;
