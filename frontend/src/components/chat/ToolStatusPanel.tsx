'use client';

/**
 * ToolStatusPanel - Tool execution status panel
 *
 * Displays real-time status, progress and result preview for tool calls
 */

import React, { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

// Simplified ToolStatus type
export interface SimpleToolStatus {
  toolName: string;
  status: 'running' | 'success' | 'error';
  stage?: string;
  progress?: number;
  message?: string;
  summary?: string;
}

interface ToolStatusPanelProps {
  tools: Record<string, SimpleToolStatus>;
  onClose?: () => void;
  maxVisible?: number;
}

// Tool icons mapping
const TOOL_ICONS: Record<string, string> = {
  gis_data_fetch: '🗺️',
  gis_analysis: '📊',
  poi_search: '🔍',
  route_planning: '🚗',
  accessibility_analysis: '🚶',
  population_prediction: '👥',
  network_analysis: '🌐',
  wfs_data_fetch: '📡',
  reverse_geocode: '📍',
  knowledge_search: '📚',
  web_search: '🔎',
};

// Status color mapping
const STATUS_COLORS: Record<string, string> = {
  running: 'bg-blue-50 text-blue-700 border-blue-300 ring-2 ring-blue-200',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  error: 'bg-red-50 text-red-700 border-red-200',
};

function ToolStatusPanel({ tools, onClose, maxVisible = 5 }: ToolStatusPanelProps) {
  const { toolList, runningCount, successCount, errorCount } = useMemo(() => {
    const list = Object.entries(tools)
      .map(([name, status]) => ({ name, ...status }))
      .slice(0, maxVisible);

    // Single-pass count using reduce
    const counts = list.reduce(
      (acc, t) => {
        if (t.status === 'running') acc.running++;
        else if (t.status === 'error') acc.error++;
        else acc.success++;
        return acc;
      },
      { running: 0, success: 0, error: 0 }
    );

    return {
      toolList: list,
      runningCount: counts.running,
      successCount: counts.success,
      errorCount: counts.error,
    };
  }, [tools, maxVisible]);

  return (
    <AnimatePresence>
      {toolList.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="bg-slate-50/95 border border-slate-200 rounded-lg overflow-hidden shadow-sm"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200/50 bg-white/50">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-slate-700">🔧 Tools</span>
              {runningCount > 0 && (
                <span className="text-xs text-blue-600 flex items-center gap-1">
                  <span className="animate-spin">🔄</span>
                  {runningCount} running
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">
                {successCount} success / {errorCount} failed
              </span>
              {onClose && (
                <button
                  onClick={onClose}
                  className="text-slate-400 hover:text-slate-600 transition-colors"
                  aria-label="Close tool panel"
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          {/* Tool Items */}
          <div className="max-h-60 overflow-y-auto">
            {toolList.map((tool) => {
              const progress = tool.progress ?? (tool.status === 'success' ? 100 : tool.status === 'running' ? 50 : 0);
              return (
                <motion.div
                  key={tool.name}
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className={`px-3 py-2 border-b border-slate-100 last:border-b-0 ${STATUS_COLORS[tool.status] || ''}`}
                >
                  {/* Tool Header */}
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-sm flex-shrink-0">
                        {TOOL_ICONS[tool.name] || '⚙️'}
                      </span>
                      <span className="font-medium truncate text-sm" title={tool.name}>
                        {tool.name}
                      </span>
                      {tool.status === 'running' && (
                        <span className="animate-spin text-xs">🔄</span>
                      )}
                    </div>
                    <span className="text-xs flex-shrink-0">{Math.round(progress)}%</span>
                  </div>

                  {/* Message */}
                  {tool.message && (
                    <div className="text-xs text-slate-500 mb-2 truncate">{tool.message}</div>
                  )}

                  {/* Progress Bar */}
                  <div className="h-1 bg-slate-200 rounded-full overflow-hidden mb-2">
                    <motion.div
                      className={`h-full ${
                        tool.status === 'error'
                          ? 'bg-red-400'
                          : tool.status === 'running'
                            ? 'bg-blue-400'
                            : 'bg-emerald-400'
                      }`}
                      initial={{ width: 0 }}
                      animate={{ width: `${progress}%` }}
                      transition={{ duration: 0.3 }}
                    />
                  </div>

                  {/* Result Summary */}
                  {tool.status === 'success' && tool.summary && (
                    <div className="text-xs text-emerald-600 bg-emerald-50/50 px-2 py-1 rounded mb-1">
                      {tool.summary}
                    </div>
                  )}

                  {/* Error Message */}
                  {tool.status === 'error' && tool.summary && (
                    <div className="text-xs text-red-600 bg-red-50/50 px-2 py-1 rounded mb-1">
                      ❌ {tool.summary}
                    </div>
                  )}
                </motion.div>
              );
            })}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// Export memoized version for performance
const MemoizedToolStatusPanel = React.memo(ToolStatusPanel);

export default MemoizedToolStatusPanel;
export type { ToolStatusPanelProps };