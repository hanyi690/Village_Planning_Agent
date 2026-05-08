'use client';

/**
 * ReviewPanel - 审查面板
 *
 * 仅提供批准操作，驳回操作通过 ChatPanel 聊天框完成
 */

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck } from '@fortawesome/free-solid-svg-icons';
import { LAYER_VALUE_MAP } from '@/lib/constants';

interface ReviewPanelProps {
  layer: number;
  dimensions?: string[];
  dimensionNames?: Record<string, string>;
  onApprove: () => Promise<void>;
  isSubmitting?: boolean;
}

export default function ReviewPanel({
  layer,
  onApprove,
  isSubmitting = false,
}: ReviewPanelProps) {
  const layerName = LAYER_VALUE_MAP[layer] || `第 ${layer} 层`;

  const handleApproveClick = async () => {
    if (isSubmitting) return;
    await onApprove();
  };

  return (
    <div className="bg-emerald-50/80 border-t border-emerald-200/50">
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2 text-sm">
          <span>⏸️</span>
          <span className="text-emerald-700 font-medium">{layerName} 待审查</span>
        </div>

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

      <p className="text-sm text-gray-500 py-2 text-center">
        如需修改，请在下方聊天框输入意见
      </p>
    </div>
  );
}