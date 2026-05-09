'use client';

/**
 * MessagePanel - 消息侧边栏组件
 *
 * 30%~40%宽度，从右侧滑入
 * 完整消息历史列表，可滚动
 * 使用现有MessageBubble样式（复用）
 *
 * Gemini aesthetic: light background, rounded corners, glass effect
 */

import React from 'react';
import { motion } from 'framer-motion';
import { faXmark } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import type { Message } from '../types';
import MessageBubble from './chat/MessageBubble';

interface MessagePanelProps {
  messages: Message[];
  onClose: () => void;
}

export default function MessagePanel({ messages, onClose }: MessagePanelProps) {
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-200 rounded-t-xl">
        <span className="text-sm text-emerald-600 uppercase tracking-wider font-medium">消息记录</span>
        <button
          onClick={onClose}
          className="p-1 text-slate-400 hover:text-amber-500 transition-colors"
        >
          <FontAwesomeIcon icon={faXmark} style={{ width: 14, height: 14 }} />
        </button>
      </div>

      {/* Message list - scrollable */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-2">
        {/* System message placeholder */}
        {messages.length === 0 && (
          <div className="px-3 py-2 text-sm text-slate-500 rounded-lg border border-slate-200 bg-white">
            暂无消息记录
          </div>
        )}

        {/* Render messages */}
        {messages.map((message) => (
          <motion.div
            key={message.id || message.timestamp?.toString() || Math.random()}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.2 }}
          >
            <MessageBubble message={message} />
          </motion.div>
        ))}
      </div>

      {/* Scrollbar styling */}
      <style>{`
        .overflow-y-auto::-webkit-scrollbar {
          width: 6px;
        }
        .overflow-y-auto::-webkit-scrollbar-track {
          background: #F1F5F9;
        }
        .overflow-y-auto::-webkit-scrollbar-thumb {
          background: #10B981;
          border-radius: 3px;
        }
      `}</style>
    </div>
  );
}