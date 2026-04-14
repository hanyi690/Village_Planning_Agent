'use client';

/**
 * ProgressPanel - 执行进度面板
 *
 * 显示维度级执行进度，支持多维度并行执行
 * 内嵌在 ChatPanel 底部，用户手动控制显示/隐藏
 * 支持切换查看历史层级进度（已完成层级的快照）
 */

import React, { useMemo, useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn, formatWordCount } from '@/lib/utils';
import { getDimensionConfigsByLayer, getDimensionsByLayer } from '@/config/dimensions';
import type { DimensionProgressItem, DimensionStatus } from '@/types';

interface LayerProgressSnapshot {
  completedAt: string;
  dimensionCount: number;
  completedCount: number;
  totalWordCount: number;
  dimensionDetails: DimensionProgressItem[];
}

interface CompletedLayers {
  1: boolean;
  2: boolean;
  3: boolean;
}

interface LayerProgressHistory {
  layer1?: LayerProgressSnapshot;
  layer2?: LayerProgressSnapshot;
  layer3?: LayerProgressSnapshot;
}

interface ProgressPanelProps {
  visible: boolean;
  currentLayer: number | null;
  currentPhase: 'idle' | '现状分析' | '规划思路' | '详细规划' | '修复中';
  dimensionProgress: Record<string, DimensionProgressItem>;
  executingDimensions: string[];
  layerDimensionCount: Record<number, number>;
  layerProgressHistory: LayerProgressHistory;
  completedLayers: CompletedLayers;
  onClose: () => void;
}

// 阶段标签映射
const PHASE_LABELS: Record<string, string> = {
  idle: '等待开始',
  现状分析: 'Layer 1: 现状分析',
  规划思路: 'Layer 2: 规划思路',
  详细规划: 'Layer 3: 详细规划',
  修复中: '修复中',
};

// 阶段颜色映射
const PHASE_COLORS: Record<string, string> = {
  idle: 'bg-gray-100 text-gray-600',
  现状分析: 'bg-blue-100 text-blue-700',
  规划思路: 'bg-purple-100 text-purple-700',
  详细规划: 'bg-emerald-100 text-emerald-700',
  修复中: 'bg-amber-100 text-amber-700',
};

// 状态图标和颜色配置
const STATUS_CONFIG: Record<
  DimensionStatus,
  { icon: string; colorClass: string; label: string; animate?: boolean }
> = {
  pending: { icon: '⏳', colorClass: 'text-gray-400', label: '等待中' },
  streaming: { icon: '🔄', colorClass: 'text-blue-500', label: '执行中', animate: true },
  completed: { icon: '✅', colorClass: 'text-emerald-500', label: '已完成' },
  failed: { icon: '❌', colorClass: 'text-red-500', label: '失败' },
};

function ProgressPanel({
  visible,
  currentLayer,
  currentPhase,
  dimensionProgress,
  executingDimensions,
  layerDimensionCount,
  layerProgressHistory,
  completedLayers,
  onClose,
}: ProgressPanelProps) {
  // 当前查看的层级（支持切换查看历史）
  const [viewingLayer, setViewingLayer] = useState<number | null>(currentLayer);
  // 是否用户手动选择了层级（防止自动跟随打断用户的历史查看）
  const [userSelected, setUserSelected] = useState(false);

  // 自动跟随当前层级（仅在用户未手动选择时）
  useEffect(() => {
    if (
      !userSelected &&
      currentLayer &&
      currentLayer >= 1 &&
      currentLayer <= 3 &&
      !completedLayers[currentLayer as 1 | 2 | 3]
    ) {
      setViewingLayer(currentLayer);
    }
  }, [currentLayer, completedLayers, userSelected]);

  // 用户手动切换层级
  const handleLayerSelect = (layer: number) => {
    setViewingLayer(layer);
    setUserSelected(layer !== currentLayer); // 如果选择非当前层级，标记为用户选择
  };

  // 判断是否查看当前层级
  const isViewingCurrent = viewingLayer === currentLayer;

  // 显示数据：当前层级用实时数据，历史层级用快照
  const displayData = useMemo(() => {
    if (!viewingLayer) {
      return { type: 'empty', allDimensions: [], stats: null };
    }

    if (isViewingCurrent) {
      // 当前层级：实时数据
      const allDimensions = getDimensionConfigsByLayer(viewingLayer);
      const completedCount = allDimensions.filter((dim) => {
        const key = `${viewingLayer}_${dim.key}`;
        return dimensionProgress[key]?.status === 'completed';
      }).length;

      const total =
        layerDimensionCount[viewingLayer] ||
        allDimensions.length ||
        getDimensionsByLayer(viewingLayer).length;

      return {
        type: 'current',
        allDimensions,
        progress: dimensionProgress,
        stats: { completed: completedCount, executing: executingDimensions.length, total },
      };
    } else {
      // 历史层级：快照数据
      const layerKey = `layer${viewingLayer}` as keyof LayerProgressHistory;
      const snapshot = layerProgressHistory[layerKey];
      if (!snapshot) {
        return { type: 'empty', allDimensions: [], stats: null };
      }

      return {
        type: 'history',
        allDimensions: getDimensionConfigsByLayer(viewingLayer),
        snapshot,
        stats: { completed: snapshot.completedCount, executing: 0, total: snapshot.dimensionCount },
      };
    }
  }, [
    viewingLayer,
    currentLayer,
    dimensionProgress,
    layerProgressHistory,
    layerDimensionCount,
    executingDimensions,
    isViewingCurrent,
  ]);

  // 计算进度百分比
  const progressPercent = useMemo(() => {
    if (!displayData.stats) return 0;
    const { completed, total } = displayData.stats;
    return total > 0 ? (completed / total) * 100 : 0;
  }, [displayData.stats]);

  // 获取维度进度（兼容历史快照）
  const getDimensionProgress = (layer: number, dimKey: string): DimensionProgressItem | null => {
    if (displayData.type === 'history' && displayData.snapshot) {
      return (
        displayData.snapshot.dimensionDetails.find(
          (d: DimensionProgressItem) => d.dimensionKey === dimKey && d.layer === layer
        ) || null
      );
    }
    const key = `${layer}_${dimKey}`;
    return dimensionProgress[key] || null;
  };

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="bg-slate-50/95 border-t border-slate-200 overflow-hidden"
        >
          {/* 头部 */}
          <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200/50 bg-white/50">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-slate-700">📊 执行进度</span>
              {/* 层级标签切换 */}
              <div className="flex items-center gap-1">
                {[1, 2, 3].map((layer) => (
                  <button
                    key={layer}
                    onClick={() => handleLayerSelect(layer)}
                    className={cn(
                      'px-2 py-0.5 text-xs font-medium rounded-lg transition-all',
                      viewingLayer === layer
                        ? 'bg-cyan-100 text-cyan-700 ring-1 ring-cyan-300'
                        : completedLayers[layer as 1 | 2 | 3]
                          ? 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                          : 'bg-slate-100 text-slate-500 hover:bg-slate-200',
                      layer === currentLayer &&
                        !completedLayers[layer as 1 | 2 | 3] &&
                        'animate-pulse'
                    )}
                    aria-label={`查看 Layer ${layer} 进度`}
                  >
                    {completedLayers[layer as 1 | 2 | 3] ? '✓' : '○'}
                    <span className="ml-1">L{layer}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-3">
              {/* 历史/当前标识 */}
              {displayData.type === 'history' && (
                <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded">历史</span>
              )}
              {displayData.type === 'current' && executingDimensions.length > 0 && (
                <span className="text-xs text-blue-600 flex items-center gap-1">
                  <span className="animate-spin">🔄</span>
                  {executingDimensions.length} 执行中
                </span>
              )}
              {displayData.stats && (
                <span className="text-sm text-slate-500">
                  {displayData.stats.completed}/{displayData.stats.total} 维度
                </span>
              )}
              <button
                onClick={onClose}
                className="text-slate-400 hover:text-slate-600 transition-colors text-sm"
                aria-label="关闭进度面板"
              >
                ✕
              </button>
            </div>
          </div>

          {/* 进度条 */}
          <div className="px-4 py-2">
            <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
              <motion.div
                className={cn(
                  'h-full',
                  displayData.type === 'history'
                    ? 'bg-gradient-to-r from-amber-400 to-amber-500'
                    : 'bg-gradient-to-r from-emerald-400 to-emerald-500'
                )}
                initial={{ width: 0 }}
                animate={{ width: `${progressPercent}%` }}
                transition={{ duration: 0.3, ease: 'easeOut' }}
              />
            </div>
          </div>

          {/* 维度网格 */}
          {displayData.allDimensions.length > 0 && (
            <div className="max-h-40 overflow-y-auto px-4 py-2">
              <div className="grid grid-cols-2 gap-1.5">
                {displayData.allDimensions.map((dim) => {
                  const progress = getDimensionProgress(viewingLayer || 1, dim.key);
                  const status = progress?.status || 'pending';
                  const config = STATUS_CONFIG[status];
                  const isExecuting =
                    displayData.type === 'current' &&
                    executingDimensions.includes(`${viewingLayer}_${dim.key}`);

                  return (
                    <motion.div
                      key={dim.key}
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className={cn(
                        'flex items-center justify-between px-2 py-1.5 rounded-md text-xs transition-colors',
                        isExecuting
                          ? 'bg-blue-50 ring-1 ring-blue-300 shadow-sm'
                          : status === 'completed'
                            ? 'bg-emerald-50/50'
                            : status === 'failed'
                              ? 'bg-red-50/50'
                              : 'bg-white/50'
                      )}
                    >
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className={cn(config.colorClass, config.animate && 'animate-spin')}>
                          {config.icon}
                        </span>
                        <span className="truncate text-slate-700 font-medium" title={dim.name}>
                          {dim.name}
                        </span>
                      </div>
                      {/* 字数显示 */}
                      {progress?.wordCount && progress.wordCount > 0 && (
                        <span
                          className={cn(
                            'text-xs ml-1 flex-shrink-0',
                            isExecuting ? 'text-blue-600 font-medium' : 'text-slate-400'
                          )}
                        >
                          {formatWordCount(progress.wordCount)}字
                        </span>
                      )}
                    </motion.div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Empty state */}
          {displayData.allDimensions.length === 0 && (
            <div className="px-4 py-4 text-center text-sm text-slate-400">
              {!viewingLayer ? '等待规划任务开始...' : '无进度数据'}
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// React.memo 优化：减少高频 SSE 事件触发的不必要重渲染
const MemoizedProgressPanel = React.memo(ProgressPanel);

export default MemoizedProgressPanel;
