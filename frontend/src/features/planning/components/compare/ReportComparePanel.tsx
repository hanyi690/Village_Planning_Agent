'use client';

/**
 * ReportComparePanel - 报告对比面板
 *
 * 选择其他会话的报告进行对比，并排展示两份报告，高亮差异部分。
 * 后端API占位: GET /api/projects/{name}/compare?dim_key={dim}&session_a={id}&session_b={id}
 */

import React, { memo, useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faExchangeAlt,
  faCodeBranch,
  faChevronDown,
  faChevronUp,
  faCheck,
  faTimes,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import MarkdownRenderer from '../ui/MarkdownRenderer';

interface CompareSession {
  id: string;
  name: string;
  timestamp: string;
}

interface ReportComparePanelProps {
  dimensionKey: string;
  currentSessionId: string;
  currentContent: string;
  availableSessions: CompareSession[];
  isLoading?: boolean;
  onCompare?: (sessionId: string) => void;
}

const ReportComparePanel = memo(function ReportComparePanel({
  dimensionKey: _dimensionKey,
  currentSessionId: _currentSessionId,
  currentContent,
  availableSessions,
  isLoading: _isLoading = false,
  onCompare,
}: ReportComparePanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);
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
    // const result = await compareApi.compare(dimensionKey, currentSessionId, sessionId);
    // setCompareContent(result.session_b.content);

    // Simulated delay for demo
    setTimeout(() => {
      setCompareContent(`# 对比报告内容\n\n这是来自会话 ${sessionId} 的报告内容。\n\n与当前报告进行对比时，差异部分将高亮显示。`);
      setIsComparing(false);
    }, 500);

    onCompare?.(sessionId);
  };

  const selectedSession = useMemo(() => {
    return availableSessions.find((s) => s.id === selectedSessionId);
  }, [availableSessions, selectedSessionId]);

  return (
    <div className="border-t border-slate-200 bg-white">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <FontAwesomeIcon icon={faExchangeAlt} className="text-[#0ea5e9]" style={{ width: 14, height: 14 }} />
          <span className="text-sm font-medium text-slate-700">报告对比</span>
          {selectedSessionId && (
            <span className="px-2 py-0.5 rounded-full bg-[#e0f2fe] text-xs text-[#0369a1]">
              已选择
            </span>
          )}
        </div>
        <FontAwesomeIcon
          icon={isExpanded ? faChevronUp : faChevronDown}
          className="text-slate-400"
          style={{ width: 12, height: 12 }}
        />
      </button>

      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4">
              {/* Session selector */}
              <div className="mb-3">
                <label className="text-xs text-slate-500 mb-2 block">选择对比会话：</label>
                <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
                  {availableSessions.length === 0 ? (
                    <div className="text-xs text-slate-400 py-2">暂无其他会话可对比</div>
                  ) : (
                    availableSessions.map((session) => (
                      <button
                        key={session.id}
                        onClick={() => handleSessionSelect(session.id)}
                        className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-all ${
                          selectedSessionId === session.id
                            ? 'bg-[#e0f2fe] border border-[#0ea5e9]'
                            : 'bg-slate-50 border border-slate-200 hover:border-slate-300'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <FontAwesomeIcon
                            icon={faCodeBranch}
                            className={selectedSessionId === session.id ? 'text-[#0ea5e9]' : 'text-slate-400'}
                            style={{ width: 12, height: 12 }}
                          />
                          <span className={selectedSessionId === session.id ? 'text-slate-700' : 'text-slate-500'}>
                            {session.name}
                          </span>
                        </div>
                        <span className="text-xs text-slate-400">{session.timestamp}</span>
                      </button>
                    ))
                  )}
                </div>
              </div>

              {/* Compare view */}
              {selectedSessionId && (
                <div className="grid grid-cols-2 gap-4">
                  {/* Current report */}
                  <div className="rounded-lg border border-slate-200 overflow-hidden">
                    <div className="px-3 py-2 bg-slate-50 border-b border-slate-200 flex items-center gap-2">
                      <span className="text-xs font-medium text-slate-700">当前报告</span>
                      <FontAwesomeIcon icon={faCheck} className="text-emerald-500" style={{ width: 10, height: 10 }} />
                    </div>
                    <div className="p-3 max-h-[300px] overflow-y-auto">
                      <div className="text-xs text-slate-500 prose prose-sm max-w-none">
                        <MarkdownRenderer content={currentContent || '暂无内容'} />
                      </div>
                    </div>
                  </div>

                  {/* Compare report */}
                  <div className="rounded-lg border border-slate-200 overflow-hidden">
                    <div className="px-3 py-2 bg-slate-50 border-b border-slate-200 flex items-center gap-2">
                      <span className="text-xs font-medium text-slate-700">
                        {selectedSession?.name || '对比报告'}
                      </span>
                      {isComparing ? (
                        <div className="w-3 h-3 border-2 border-[#0ea5e9] border-t-transparent rounded-full animate-spin" />
                      ) : compareContent ? (
                        <FontAwesomeIcon icon={faCheck} className="text-emerald-500" style={{ width: 10, height: 10 }} />
                      ) : (
                        <FontAwesomeIcon icon={faTimes} className="text-slate-400" style={{ width: 10, height: 10 }} />
                      )}
                    </div>
                    <div className="p-3 max-h-[300px] overflow-y-auto">
                      {isComparing ? (
                        <div className="flex items-center justify-center h-20">
                          <div className="w-4 h-4 border-2 border-[#0ea5e9] border-t-transparent rounded-full animate-spin" />
                        </div>
                      ) : compareContent ? (
                        <div className="text-xs text-slate-500 prose prose-sm max-w-none">
                          <MarkdownRenderer content={compareContent} />
                        </div>
                      ) : (
                        <div className="flex items-center justify-center h-20 text-xs text-slate-400">
                          选择会话后显示对比内容
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Placeholder notice */}
              <div className="mt-3 p-2 rounded-lg bg-slate-50 border border-slate-200">
                <p className="text-xs text-slate-400">
                  💡 报告对比功能为占位实现，后端API待开发。
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default ReportComparePanel;

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