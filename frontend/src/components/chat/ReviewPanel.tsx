'use client';

/**
 * ReviewPanel - 极简审查面板
 *
 * 基于状态驱动的独立审查组件，不依赖消息流
 * 只根据 isPaused 和 pendingReviewLayer 状态显示
 * 
 * 简化版：只保留批准按钮，反馈通过聊天框输入
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
    <div className="border-t border-gray-200 bg-yellow-50 p-4 shadow-lg animate-slide-up">
      {/* 标题行 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-2xl">📋</span>
          <div>
            <h3 className="font-semibold text-gray-800">
              {layerName} 已完成
            </h3>
            <p className="text-sm text-gray-600">
              请审查后决定下一步操作
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
            等待审查
          </span>
        </div>
      </div>

      {/* 操作按钮 - 只保留批准 */}
      <div className="flex items-center justify-center">
        <button
          onClick={handleApproveClick}
          className="flex items-center gap-2 px-8 py-3 bg-green-100 hover:bg-green-200 text-gray-900 border border-green-300 rounded-lg transition-colors shadow-md hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed text-lg"
          disabled={isSubmitting}
        >
          {isSubmitting ? (
            <>
              <span className="animate-spin">⏳</span>
              <span>处理中...</span>
            </>
          ) : (
            <>
              <FontAwesomeIcon icon={faCheck} />
              <span>批准继续</span>
            </>
          )}
        </button>
      </div>

      {/* 提示信息 */}
      <p className="text-center text-sm text-gray-600 mt-3">
        💡 如需修改，请在下方输入框输入反馈意见后发送
      </p>
    </div>
  );
}
