'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { faCopy } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import type { Message } from '../../types';
import { isUserMessage } from '../../types';
import MessageContent from './MessageContent';
import { formatMessageTimestamp } from '@/features/planning/utils';

interface MessageBubbleProps {
  message: Message;
  onCopy?: (message: Message) => void;
  enableStreaming?: boolean;
  dimensionContents?: Record<string, string>;
  children?: React.ReactNode;
}

const bubbleVariants = {
  hidden: { opacity: 0, y: 6 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.18 },
  },
};

function MessageBubble({
  message,
  onCopy,
  enableStreaming = false,
  dimensionContents,
  children,
}: MessageBubbleProps) {
  const content = children || (
    <MessageContent
      message={message}
      enableStreaming={enableStreaming}
      dimensionContents={dimensionContents}
    />
  );

  if (isUserMessage(message)) {
    return (
      <motion.div
        variants={bubbleVariants}
        initial="hidden"
        animate="visible"
        className="flex justify-end py-2"
      >
        <div className="max-w-[85%] rounded-3xl rounded-br-lg bg-slate-100 px-4 py-2.5 text-sm text-slate-800">
          {content}
          <div className="mt-1.5 text-right text-[10px] text-slate-400">
            {formatMessageTimestamp(message.timestamp)}
          </div>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      variants={bubbleVariants}
      initial="hidden"
      animate="visible"
      className="group flex items-start gap-3 py-3"
    >
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-cyan-500 text-[10px] font-semibold text-white shadow-sm">
        AI
      </div>

      <div className="min-w-0 flex-1">
        <div className="text-sm leading-6 text-slate-700">{content}</div>
        <div className="mt-1 flex min-h-6 items-center gap-2 text-[10px] text-slate-400">
          {onCopy && message.type === 'text' && (
            <button
              type="button"
              onClick={() => onCopy(message)}
              aria-label="复制消息"
              title="复制消息"
              className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 opacity-0 transition-all hover:bg-slate-100 hover:text-slate-600 group-hover:opacity-100 focus:opacity-100"
            >
              <FontAwesomeIcon icon={faCopy} style={{ width: 11, height: 11 }} />
            </button>
          )}
          <span>{formatMessageTimestamp(message.timestamp)}</span>
        </div>
      </div>
    </motion.div>
  );
}

export default React.memo(MessageBubble);
