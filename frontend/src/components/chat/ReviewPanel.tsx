'use client';

/**
 * ReviewPanel - 极简审查面板
 *
 * 基于状态驱动的独立审查组件,不依赖消息流
 * 只根据 isPaused 和 pendingReviewLayer 状态显示
 */

import { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck, faTimes, faEye } from '@fortawesome/free-solid-svg-icons';

interface ReviewPanelProps {
  layer: number;
  onApprove: () => Promise<void>;
  onReject: (feedback: string) => Promise<void>;
  onRollback: (checkpointId: string) => Promise<void>;
  isSubmitting?: boolean;
}

export default function ReviewPanel({
  layer,
  onApprove,
  onReject,
  onRollback,
  isSubmitting = false,
}: ReviewPanelProps) {
  const [showDetails, setShowDetails] = useState(false);
  const [feedback, setFeedback] = useState('');

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

  const handleRejectClick = async () => {
    if (isSubmitting) return;
    if (!feedback.trim()) {
      alert('请提供驳回理由');
      return;
    }
    await onReject(feedback);
    setFeedback('');
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

      {/* 操作按钮 */}
      <div className="flex items-center gap-3">
        {/* 查看详情按钮 */}
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors"
          disabled={isSubmitting}
        >
          <FontAwesomeIcon icon={faEye} />
          <span>{showDetails ? '隐藏详情' : '查看详情'}</span>
        </button>

        {/* 驳回按钮 */}
        <button
          onClick={handleRejectClick}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors"
          disabled={isSubmitting}
        >
          <FontAwesomeIcon icon={faTimes} />
          <span>驳回</span>
        </button>

        {/* 批准继续按钮 - 主操作 */}
        <button
          onClick={handleApproveClick}
          className="flex items-center gap-2 px-6 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors shadow-md hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
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

      {/* 详情区域 */}
      {showDetails && (
        <div className="mt-4 pt-4 border-t border-gray-200">
          <div className="bg-white rounded-lg p-4">
            <h4 className="font-medium text-gray-700 mb-2">驳回反馈</h4>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="请描述需要修改的内容（选填）"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              rows={3}
              disabled={isSubmitting}
            />
            <p className="text-xs text-gray-500 mt-2">
              提供具体的修改建议，帮助系统更好地理解您的需求
            </p>
          </div>
        </div>
      )}
    </div>
  );
}