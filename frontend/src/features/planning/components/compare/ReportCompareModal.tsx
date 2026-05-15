'use client';

/**
 * ReportCompareModal - 报告对比模态框
 *
 * 浮动按钮触发的模态框，并排展示两份报告，高亮差异部分。
 */

import React, { memo, useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faExchangeAlt,
  faCodeBranch,
  faTimes,
  faCheck,
  faSpinner,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import MarkdownRenderer from '../ui/MarkdownRenderer';

interface CompareSession {
  id: string;
  name: string;
  timestamp: string;
}

interface ReportCompareModalProps {
  dimensionKey: string;
  currentSessionId: string;
  currentContent: string;
  availableSessions: CompareSession[];
  isOpen: boolean;
  onClose: () => void;
  onCompare?: (sessionId: string) => void;
}

const ReportCompareModal = memo(function ReportCompareModal({
  dimensionKey: _dimensionKey,
  currentSessionId: _currentSessionId,
  currentContent,
  availableSessions,
  isOpen,
  onClose,
  onCompare,
}: ReportCompareModalProps) {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [compareContent, setCompareContent] = useState<string | null>(null);
  const [isComparing, setIsComparing] = useState(false);

  const handleSessionSelect = async (sessionId: string) => {
    if (sessionId === selectedSessionId) {
      setSelectedSessionId(null);
      setCompareContent(null);
      return;
    }

    setSelectedSessionId(sessionId);
    setIsComparing(true);

    // Placeholder: In real implementation, this would call the API
    setTimeout(() => {
      setCompareContent(`# 对比报告内容\n\n这是来自会话 ${sessionId} 的报告内容。\n\n与当前报告进行对比时，差异部分将高亮显示。`);
      setIsComparing(false);
    }, 500);

    onCompare?.(sessionId);
  };

  const selectedSession = useMemo(() => {
    return availableSessions.find((s) => s.id === selectedSessionId);
  }, [availableSessions, selectedSessionId]);

  // Handle escape key
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Prevent body scroll when modal is open
  React.useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="fixed inset-4 md:inset-8 lg:inset-12 bg-white rounded-2xl shadow-2xl z-50 flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-100 to-teal-100 flex items-center justify-center">
                  <FontAwesomeIcon icon={faExchangeAlt} className="text-cyan-600" style={{ width: 18, height: 18 }} />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-slate-800">报告对比</h2>
                  <p className="text-xs text-slate-400">选择历史会话进行对比</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="w-9 h-9 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <FontAwesomeIcon icon={faTimes} style={{ width: 16, height: 16 }} />
              </button>
            </div>

            {/* Session selector */}
            <div className="px-6 py-4 border-b border-slate-100 shrink-0">
              <label className="text-sm text-slate-500 mb-3 block">选择对比会话：</label>
              <div className="flex flex-wrap gap-2">
                {availableSessions.length === 0 ? (
                  <div className="text-sm text-slate-400 py-2">暂无其他会话可对比</div>
                ) : (
                  availableSessions.map((session) => (
                    <button
                      key={session.id}
                      onClick={() => handleSessionSelect(session.id)}
                      className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm transition-all ${
                        selectedSessionId === session.id
                          ? 'bg-cyan-100 text-cyan-700 border border-cyan-200'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                      }`}
                    >
                      <FontAwesomeIcon
                        icon={faCodeBranch}
                        className={selectedSessionId === session.id ? 'text-cyan-500' : 'text-slate-400'}
                        style={{ width: 12, height: 12 }}
                      />
                      <span>{session.name}</span>
                      <span className="text-xs text-slate-400">{session.timestamp}</span>
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* Compare view */}
            <div className="flex-1 overflow-hidden">
              {selectedSessionId ? (
                <div className="h-full grid grid-cols-1 md:grid-cols-2 gap-4 p-6">
                  {/* Current report */}
                  <div className="h-full flex flex-col rounded-xl border border-slate-200 overflow-hidden">
                    <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center gap-2 shrink-0">
                      <span className="text-sm font-medium text-slate-700">当前报告</span>
                      <FontAwesomeIcon icon={faCheck} className="text-emerald-500" style={{ width: 12, height: 12 }} />
                    </div>
                    <div className="flex-1 overflow-y-auto p-4">
                      <MarkdownRenderer content={currentContent || '暂无内容'} />
                    </div>
                  </div>

                  {/* Compare report */}
                  <div className="h-full flex flex-col rounded-xl border border-slate-200 overflow-hidden">
                    <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center gap-2 shrink-0">
                      <span className="text-sm font-medium text-slate-700">
                        {selectedSession?.name || '对比报告'}
                      </span>
                      {isComparing ? (
                        <FontAwesomeIcon icon={faSpinner} className="text-cyan-500 animate-spin" style={{ width: 12, height: 12 }} />
                      ) : compareContent ? (
                        <FontAwesomeIcon icon={faCheck} className="text-emerald-500" style={{ width: 12, height: 12 }} />
                      ) : null}
                    </div>
                    <div className="flex-1 overflow-y-auto p-4">
                      {isComparing ? (
                        <div className="flex items-center justify-center h-full">
                          <div className="w-8 h-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
                        </div>
                      ) : compareContent ? (
                        <MarkdownRenderer content={compareContent} />
                      ) : (
                        <div className="flex items-center justify-center h-full text-sm text-slate-400">
                          选择会话后显示对比内容
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center">
                    <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mb-4 mx-auto">
                      <FontAwesomeIcon icon={faExchangeAlt} className="text-slate-300" style={{ width: 24, height: 24 }} />
                    </div>
                    <p className="text-sm text-slate-400">请选择一个历史会话进行对比</p>
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 shrink-0">
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-400">
                  💡 报告对比功能为占位实现，后端API待开发。
                </p>
                <button
                  onClick={onClose}
                  className="px-4 py-2 rounded-lg text-sm bg-slate-200 text-slate-600 hover:bg-slate-300 transition-colors"
                >
                  关闭
                </button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
});

export default ReportCompareModal;

// Mock data for development
export const mockCompareSessions: CompareSession[] = [
  {
    id: 'session-1',
    name: '金田村规划 v1',
    timestamp: '2026-05-10',
  },
  {
    id: 'session-2',
    name: '金田村规划 v2',
    timestamp: '2026-05-11',
  },
  {
    id: 'session-3',
    name: '金田村规划 v3',
    timestamp: '2026-05-12',
  },
];