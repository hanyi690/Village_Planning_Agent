'use client';

/**
 * ReviewPanel - 极简审查面板
 *
 * 单行简洁设计：图标 + 状态 + 批准按钮
 */

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck } from '@fortawesome/free-solid-svg-icons';

interface ReviewPanelProps {
  layer: number;
  onApprove: () => Promise<void>;
  isSubmitting?: boolean;
}

export default function ReviewPanel({
  layer,
  onApprove,
  isSubmitting = false,
}: ReviewPanelProps) {
  const layerNames: Record<number, string> = {
    1: '现状分析',
    2: '规划思路',
    3: '详细规划',
  };

  const layerName = layerNames[layer] || `第 ${layer} 层`;

  const handleApproveClick = async () => {
    if (isSubmitting) return;
    await onApprove();
  };

  return (
    <div className="flex items-center justify-between px-4 py-3 bg-emerald-50/80 border-t border-emerald-200/50">
      {/* 左侧：状态信息 */}
      <div className="flex items-center gap-2 text-sm">
        <span>⏸️</span>
        <span className="text-emerald-700 font-medium">{layerName} 待审查</span>
      </div>

      {/* 右侧：批准按钮 */}
      <button
        onClick={handleApproveClick}
        disabled={isSubmitting}
        className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        style={{
          background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
          boxShadow: '0 2px 8px rgba(16, 185, 129, 0.3)',
        }}
      >
        {isSubmitting ? (
          <>
            <span className="animate-spin">⏳</span>
            <span>处理中...</span>
          </>
        ) : (
          <>
            <FontAwesomeIcon icon={faCheck} className="text-xs" />
            <span>批准继续</span>
          </>
        )}
      </button>
    </div>
  );
}