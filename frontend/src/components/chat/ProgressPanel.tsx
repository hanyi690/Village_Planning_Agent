'use client';

/**
 * ProgressPanel - 执行进度面板
 *
 * 显示维度级执行进度，支持多维度并行执行
 * 内嵌在 ChatPanel 底部，用户手动控制显示/隐藏
 */

import { motion, AnimatePresence } from 'framer-motion';
import { getDimensionConfigsByLayer } from '@/config/dimensions';
import type { DimensionProgressItem, DimensionStatus } from '@/types';

interface ProgressPanelProps {
  visible: boolean;
  currentLayer: number | null;
  currentPhase: 'idle' | '现状分析' | '规划思路' | '详细规划' | '修复中';
  dimensionProgress: Map<string, DimensionProgressItem>;
  executingDimensions: Set<string>;
  onClose: () => void;
}

// 阶段标签映射
const PHASE_LABELS: Record<string, string> = {
  idle: '等待开始',
  '现状分析': 'Layer 1: 现状分析',
  '规划思路': 'Layer 2: 规划思路',
  '详细规划': 'Layer 3: 详细规划',
  '修复中': '修复中',
};

// 阶段颜色映射
const PHASE_COLORS: Record<string, string> = {
  idle: 'bg-gray-100 text-gray-600',
  '现状分析': 'bg-blue-100 text-blue-700',
  '规划思路': 'bg-purple-100 text-purple-700',
  '详细规划': 'bg-emerald-100 text-emerald-700',
  '修复中': 'bg-amber-100 text-amber-700',
};

// 状态图标和颜色配置
const STATUS_CONFIG: Record<DimensionStatus, { icon: string; colorClass: string; label: string; animate?: boolean }> = {
  pending: { icon: '⏳', colorClass: 'text-gray-400', label: '等待中' },
  streaming: { icon: '🔄', colorClass: 'text-blue-500', label: '执行中', animate: true },
  completed: { icon: '✅', colorClass: 'text-emerald-500', label: '已完成' },
  failed: { icon: '❌', colorClass: 'text-red-500', label: '失败' },
};

// 格式化字数显示
function formatWordCount(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return count.toString();
}

export default function ProgressPanel({
  visible,
  currentLayer,
  currentPhase,
  dimensionProgress,
  executingDimensions,
  onClose,
}: ProgressPanelProps) {
  // 获取当前层级的所有维度配置
  const allDimensions = currentLayer ? getDimensionConfigsByLayer(currentLayer) : [];

  // 计算完成进度
  const completedCount = allDimensions.filter(dim => {
    const key = `${currentLayer}_${dim.key}`;
    const progress = dimensionProgress.get(key);
    return progress?.status === 'completed';
  }).length;
  const totalCount = allDimensions.length;
  const progressPercent = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;

  // 统计执行中的维度数量
  const executingCount = executingDimensions.size;

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
              <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${PHASE_COLORS[currentPhase]}`}>
                {PHASE_LABELS[currentPhase]}
              </span>
            </div>
            <div className="flex items-center gap-3">
              {executingCount > 0 && (
                <span className="text-xs text-blue-600 flex items-center gap-1">
                  <span className="animate-spin">🔄</span>
                  {executingCount} 个维度执行中
                </span>
              )}
              <span className="text-sm text-slate-500">{completedCount}/{totalCount} 维度</span>
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
                className="h-full bg-gradient-to-r from-emerald-400 to-emerald-500"
                initial={{ width: 0 }}
                animate={{ width: `${progressPercent}%` }}
                transition={{ duration: 0.3, ease: 'easeOut' }}
              />
            </div>
          </div>

          {/* 维度网格 */}
          {allDimensions.length > 0 && (
            <div className="max-h-40 overflow-y-auto px-4 py-2">
              <div className="grid grid-cols-2 gap-1.5">
                {allDimensions.map((dim) => {
                  const key = `${currentLayer}_${dim.key}`;
                  const progress = dimensionProgress.get(key);
                  const status = progress?.status || 'pending';
                  const config = STATUS_CONFIG[status];
                  const isExecuting = executingDimensions.has(key);

                  return (
                    <motion.div
                      key={dim.key}
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className={`flex items-center justify-between px-2 py-1.5 rounded-md text-xs transition-colors ${
                        isExecuting
                          ? 'bg-blue-50 ring-1 ring-blue-300 shadow-sm'
                          : status === 'completed'
                          ? 'bg-emerald-50/50'
                          : status === 'failed'
                          ? 'bg-red-50/50'
                          : 'bg-white/50'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className={`${config.colorClass} ${config.animate ? 'animate-spin' : ''}`}>
                          {config.icon}
                        </span>
                        <span className="truncate text-slate-700 font-medium" title={dim.name}>
                          {dim.name}
                        </span>
                      </div>
                      {/* 字数显示 */}
                      {progress?.wordCount && progress.wordCount > 0 && (
                        <span className={`text-xs ml-1 flex-shrink-0 ${
                          isExecuting ? 'text-blue-600 font-medium' : 'text-slate-400'
                        }`}>
                          {formatWordCount(progress.wordCount)}字
                        </span>
                      )}
                    </motion.div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 空状态 */}
          {allDimensions.length === 0 && (
            <div className="px-4 py-4 text-center text-sm text-slate-400">
              等待规划任务开始...
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
