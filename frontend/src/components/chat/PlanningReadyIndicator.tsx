'use client';

// ============================================
// PlanningReadyIndicator - 规划就绪指示器组件
// ============================================

import { motion } from 'framer-motion';

interface PlanningReadyIndicatorProps {
  projectName: string;
  isPlanning: boolean;
  onStartPlanning: () => void;
}

/**
 * PlanningReadyIndicator - 规划就绪指示器
 * 当规划任务已准备时显示开始规划按钮
 */
export default function PlanningReadyIndicator({
  projectName,
  isPlanning,
  onStartPlanning,
}: PlanningReadyIndicatorProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-3 px-4 py-3 bg-emerald-50 border border-emerald-200 rounded-2xl flex items-center justify-between"
    >
      <div className="flex items-center gap-3">
        <span className="text-2xl">📋</span>
        <div>
          <div className="font-semibold text-emerald-800">规划任务已准备</div>
          <div className="text-sm text-emerald-700">
            村庄：{projectName}
          </div>
        </div>
      </div>
      <motion.button
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        className="px-5 py-2 font-medium text-white rounded-full"
        style={{
          background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
          boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)',
        }}
        onClick={onStartPlanning}
        disabled={isPlanning}
      >
        {isPlanning ? (
          <span className="flex items-center gap-2">
            <i className="fas fa-spinner fa-spin text-sm" />
            启动中...
          </span>
        ) : (
          <span className="flex items-center gap-2">
            <span>🚀</span>
            开始规划
          </span>
        )}
      </motion.button>
    </motion.div>
  );
}