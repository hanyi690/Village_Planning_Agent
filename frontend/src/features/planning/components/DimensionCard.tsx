'use client';

/**
 * DimensionCard - 维度卡片组件
 *
 * 展示单个维度的分析状态和进度，支持：
 * - 依赖关系图形化表达
 * - 状态色块系统
 * - 流式文本显示
 * - RAG检索折叠面板
 * - 级联修复标记
 *
 * Gemini aesthetic: rounded corners, shadow, emerald colors, smooth transitions
 */

import React, { useState, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import { faLink, faChevronDown, faChevronUp } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { useDimensionRagSources, useIsDimensionResetting, useDimensionVersion } from '../hooks';
import type { DimensionStatus } from '../types';

// Status color mapping - Gemini style
const STATUS_COLORS: Record<string, string> = {
  pending: '#CBD5E1',      // slate-300
  streaming: '#10B981',    // emerald-500
  completed: '#34D399',    // emerald-400
  failed: '#EF4444',       // red-500
  resetting: '#F59E0B',    // amber-500
};

// Dimension name mapping (can be imported from config)
const DIMENSION_DISPLAY_NAMES: Record<string, string> = {
  resource_endowment: '资源禀赋',
  population_structure: '人口结构',
  spatial_layout: '空间布局',
  infrastructure: '基础设施',
  development_goal: '发展目标',
  landuse_planning: '土地利用',
  spatial_planning: '空间规划',
  detailed_planning: '详细规划',
};

interface DimensionCardProps {
  dimensionKey: string;  // e.g., "1_resource_endowment"
  dimensionName: string;
  layer: number;
  status: DimensionStatus;
  wordCount?: number;
  isExecuting?: boolean;
  isRevision?: boolean;
  onOpenLayerSidebar?: (layer: number) => void;
}

export default function DimensionCard({
  dimensionKey,
  dimensionName,
  layer,
  status,
  wordCount,
  isExecuting,
  isRevision,
  onOpenLayerSidebar,
}: DimensionCardProps) {
  // State
  const [ragExpanded, setRagExpanded] = useState(false);
  const [highlightMode, setHighlightMode] = useState(false);

  // Store - RAG sources and version
  const ragSources = useDimensionRagSources(dimensionKey);
  const isResetting = useIsDimensionResetting(dimensionKey);
  const version = useDimensionVersion(dimensionKey);

  // Derived display name
  const displayName = useMemo(() => {
    const keyPart = dimensionKey.split('_').slice(1).join('_');
    return dimensionName || DIMENSION_DISPLAY_NAMES[keyPart] || keyPart;
  }, [dimensionKey, dimensionName]);

  // Status color
  const statusColor = useMemo(() => {
    if (isResetting) return STATUS_COLORS.resetting;
    if (isExecuting) return STATUS_COLORS.streaming;
    return STATUS_COLORS[status] || STATUS_COLORS.pending;
  }, [status, isExecuting, isResetting]);

  // Version tag (only show if > 1)
  const showVersionTag = version > 1;

  // Handle click for dependency highlight
  const handleClick = useCallback(() => {
    setHighlightMode((prev) => !prev);
    if (onOpenLayerSidebar) {
      onOpenLayerSidebar(layer);
    }
  }, [layer, onOpenLayerSidebar]);

  // Streaming animation for executing state
  const isStreaming = isExecuting && status === 'streaming';

  return (
    <motion.div
      className={`relative rounded-lg border ${
        highlightMode ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 bg-white'
      } shadow-sm ${
        isResetting ? 'animate-pulse' : ''
      } transition-all duration-200 hover:shadow-md hover:border-emerald-200`}
      onClick={handleClick}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
    >
      {/* Left status bar */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-lg"
        style={{ backgroundColor: statusColor }}
      />

      {/* Reset badge */}
      {isResetting && (
        <div className="absolute top-0 right-0 px-2 py-0.5 rounded-bl-lg bg-amber-100 text-amber-700 text-xs font-bold">
          待修复
        </div>
      )}

      {/* Main content */}
      <div className="pl-4 pr-3 py-2">
        {/* Header row */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {/* Dimension name */}
            <span className="font-display text-sm text-slate-700">{displayName}</span>

            {/* Version tag */}
            {showVersionTag && (
              <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-600 text-xs font-mono">
                v{version}
              </span>
            )}

            {/* Revision tag */}
            {isRevision && (
              <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-500 text-xs">
                修订
              </span>
            )}
          </div>

          {/* Status indicators */}
          <div className="flex items-center gap-2">
            {/* Executing indicator */}
            {isStreaming && (
              <motion.div
                className="w-2 h-2 rounded-full bg-emerald-500"
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ repeat: Infinity, duration: 0.5 }}
              />
            )}

            {/* Word count */}
            {wordCount && wordCount > 0 && (
              <span className="text-xs text-slate-500 font-mono">{wordCount}字</span>
            )}

            {/* RAG indicator */}
            {ragSources && ragSources.documents.length > 0 && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setRagExpanded((prev) => !prev);
                }}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-xs hover:bg-emerald-50 hover:text-emerald-600 transition-colors"
              >
                <FontAwesomeIcon icon={faLink} style={{ width: 10, height: 10 }} />
                <span>{ragSources.documents.length}条</span>
                <FontAwesomeIcon
                  icon={ragExpanded ? faChevronUp : faChevronDown}
                  style={{ width: 8, height: 8 }}
                />
              </button>
            )}
          </div>
        </div>

        {/* RAG panel (collapsible) */}
        {ragExpanded && ragSources && (
          <motion.div
            className="mt-2 pt-2 border-t border-slate-200"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
          >
            {/* Query */}
            <div className="mb-1">
              <span className="text-xs text-slate-500">检索词：</span>
              <span className="text-xs text-emerald-600 font-mono">{ragSources.query}</span>
            </div>

            {/* Documents */}
            <div className="space-y-1">
              {ragSources.documents.map((doc, idx) => (
                <div key={idx} className="px-2 py-1 rounded bg-slate-50 border border-slate-200">
                  <span className="text-xs text-slate-600">{doc.title}</span>
                  {doc.snippet && (
                    <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{doc.snippet}</p>
                  )}
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {/* Status text */}
        <div className="mt-1 text-xs text-slate-500">
          {isResetting && '级联修复中...'}
          {isStreaming && '正在分析...'}
          {status === 'completed' && !isRevision && '已完成'}
          {status === 'completed' && isRevision && '修订完成'}
          {status === 'failed' && '分析失败'}
          {status === 'pending' && '等待执行'}
        </div>
      </div>
    </motion.div>
  );
}