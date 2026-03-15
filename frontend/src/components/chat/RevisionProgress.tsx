'use client';

/**
 * RevisionProgress - 修复进度显示组件
 *
 * 显示修复任务的进度，区分目标维度（用户修改）和级联维度（自动更新）
 * 参考 GitHub PR review UI 设计
 */

import { motion, AnimatePresence } from 'framer-motion';
import { RevisionItem } from '@/types';

interface RevisionProgressProps {
  revisions: RevisionItem[];
  currentWave: number;
  maxWave: number;
  targetDimensions: string[]; // 用户选择的目标维度
}

export default function RevisionProgress({
  revisions,
  currentWave,
  maxWave,
  targetDimensions: _targetDimensions,
}: RevisionProgressProps) {
  // 按维度类型分组
  const targetRevisions = revisions.filter((r) => r.isTarget);
  const cascadeRevisions = revisions.filter((r) => !r.isTarget);

  // 计算进度
  const completedCount = revisions.filter((r) => r.status === 'completed').length;
  const totalCount = revisions.length;
  const progress = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;

  return (
    <div className="bg-gradient-to-r from-slate-50 to-gray-50 rounded-xl border border-slate-200 p-4 mb-4">
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">🔄</span>
          <span className="font-medium text-slate-700">修复进度</span>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <span>
            Wave {currentWave}/{maxWave}
          </span>
          <span className="text-slate-300">|</span>
          <span>
            {completedCount}/{totalCount} 完成
          </span>
        </div>
      </div>

      {/* 进度条 */}
      <div className="h-2 bg-slate-200 rounded-full overflow-hidden mb-4">
        <motion.div
          className="h-full bg-gradient-to-r from-emerald-400 to-emerald-500"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
      </div>

      {/* 目标维度列表 */}
      {targetRevisions.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 rounded-full">
              🎯 目标维度
            </span>
            <span className="text-xs text-slate-400">用户选择的修改维度</span>
          </div>
          <div className="space-y-1.5">
            <AnimatePresence>
              {targetRevisions.map((revision, index) => (
                <RevisionItemRow key={revision.dimension} revision={revision} index={index} />
              ))}
            </AnimatePresence>
          </div>
        </div>
      )}

      {/* 级联维度列表 */}
      {cascadeRevisions.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded-full">
              🔗 级联更新
            </span>
            <span className="text-xs text-slate-400">依赖维度的自动调整</span>
          </div>
          <div className="space-y-1.5">
            <AnimatePresence>
              {cascadeRevisions.map((revision, index) => (
                <RevisionItemRow key={revision.dimension} revision={revision} index={index} />
              ))}
            </AnimatePresence>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 单个修复项行
 */
function RevisionItemRow({ revision, index }: { revision: RevisionItem; index: number }) {
  const statusIcons: Record<string, { icon: string; color: string }> = {
    pending: { icon: '⏳', color: 'text-slate-400' },
    processing: { icon: '🔄', color: 'text-blue-500 animate-spin' },
    completed: { icon: '✅', color: 'text-emerald-500' },
    failed: { icon: '❌', color: 'text-red-500' },
  };

  const status = statusIcons[revision.status] || statusIcons.pending;

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.05 }}
      className={`flex items-center justify-between p-2 rounded-lg ${
        revision.isTarget
          ? 'bg-amber-50/50 border border-amber-100'
          : 'bg-blue-50/50 border border-blue-100'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={status.icon}>{status.icon}</span>
        <span className="text-sm font-medium text-slate-700">
          {revision.dimensionName || revision.dimension}
        </span>
        {revision.status === 'completed' && !revision.isTarget && (
          <span className="text-xs text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">
            【级联更新】
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span>Layer {revision.layer}</span>
      </div>
    </motion.div>
  );
}
