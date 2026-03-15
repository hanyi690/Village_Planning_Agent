'use client';

// ============================================
// RateLimitWarning - 限流警告组件
// ============================================

import { motion } from 'framer-motion';

interface RateLimitWarningProps {
  projectName: string;
  onReset: () => void;
}

/**
 * RateLimitWarning - 限流警告组件
 * 当项目触发速率限制时显示警告和重置按钮
 */
export default function RateLimitWarning({ projectName, onReset }: RateLimitWarningProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-3 px-4 py-3 bg-amber-50 border border-amber-200 rounded-2xl flex items-center justify-between"
    >
      <div className="flex items-center gap-3">
        <span className="text-2xl">⚠️</span>
        <div>
          <div className="font-semibold text-amber-800">请求过于频繁</div>
          <div className="text-sm text-amber-700">
            项目 &quot;{projectName}&quot; 触发了速率限制
          </div>
        </div>
      </div>
      <button
        className="px-4 py-2 text-sm font-medium text-amber-700 bg-white border border-amber-300 rounded-full hover:bg-amber-100 transition-colors"
        onClick={onReset}
      >
        🔄 重置限制
      </button>
    </motion.div>
  );
}
