'use client';

/**
 * ToolStatusCard - Single tool status card for MessageList
 */

import React from 'react';
import { motion } from 'framer-motion';
import type { ToolStatusMessage } from '@/types';
import { parseTimestamp } from '@/lib/utils';
import { getToolIconFA } from '@/lib/constants';

interface ToolStatusCardProps {
  message: ToolStatusMessage;
}

// Status styles
const STATUS_STYLES: Record<string, { bg: string; border: string; icon: string }> = {
  pending: {
    bg: 'bg-gray-50',
    border: 'border-gray-200',
    icon: 'fa-clock text-gray-500',
  },
  running: {
    bg: 'bg-blue-50',
    border: 'border-blue-300',
    icon: 'fa-spinner fa-spin text-blue-600',
  },
  success: {
    bg: 'bg-emerald-50',
    border: 'border-emerald-200',
    icon: 'fa-check-circle text-emerald-600',
  },
  error: {
    bg: 'bg-red-50',
    border: 'border-red-200',
    icon: 'fa-exclamation-circle text-red-600',
  },
};

function ToolStatusCard({ message }: ToolStatusCardProps) {
  const style = STATUS_STYLES[message.status] || STATUS_STYLES.pending;
  const iconClass = getToolIconFA(message.toolName);
  const progress = message.progress ?? (message.status === 'success' ? 100 : 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex justify-start mb-4`}
    >
      <div
        className={`max-w-[70%] ${style.bg} border ${style.border} rounded-2xl px-4 py-3 shadow-sm`}
      >
        {/* Header */}
        <div className="flex items-center gap-3 mb-3 pb-2 border-b border-white/20">
          <i className={`fas ${iconClass} text-lg text-gray-700`} />
          <div className="flex-1 min-w-0">
            <span className="font-medium text-gray-800 truncate">
              {message.toolDisplayName}
            </span>
            {message.estimatedTime && (
              <span className="text-xs text-gray-500 ml-2">
                (~{Math.round(message.estimatedTime)}s)
              </span>
            )}
          </div>
          <i className={`fas ${style.icon}`} />
        </div>

        {/* Description */}
        {message.description && (
          <div className="text-sm text-gray-600 mb-3">{message.description}</div>
        )}

        {/* Stage & Progress */}
        {message.status === 'running' && (
          <div className="mb-3">
            {message.stage && (
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs text-blue-600 font-medium">{message.stage}</span>
                {message.stageMessage && (
                  <span className="text-xs text-gray-500">{message.stageMessage}</span>
                )}
              </div>
            )}
            <div className="h-2 bg-blue-100 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-blue-500"
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
            <div className="text-xs text-gray-500 mt-1">{Math.round(progress)}%</div>
          </div>
        )}

        {/* Summary (success) */}
        {message.status === 'success' && message.summary && (
          <div className="bg-emerald-100/50 rounded-lg px-3 py-2 text-sm text-emerald-700 mb-3">
            <i className="fas fa-check-circle mr-2" />
            {message.summary}
          </div>
        )}

        {/* Error */}
        {message.status === 'error' && message.error && (
          <div className="bg-red-100/50 rounded-lg px-3 py-2 text-sm text-red-700 mb-3">
            <i className="fas fa-exclamation-circle mr-2" />
            {message.error}
          </div>
        )}

        {/* Timestamp */}
        <div className="text-xs opacity-60 text-right">
          {(() => {
            const date = parseTimestamp(message.timestamp);
            return date ? date.toLocaleTimeString() : '刚刚';
          })()}
        </div>
      </div>
    </motion.div>
  );
}

export default React.memo(ToolStatusCard);