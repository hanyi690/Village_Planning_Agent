'use client';

/**
 * ReviewPanel - 审查面板
 *
 * 支持批准和驳回两种操作
 * 驳回时可展开输入框填写修改意见
 * 支持选择特定维度进行定向修订
 */

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faCheck,
  faEdit,
  faTimes,
  faPaperPlane,
  faSpinner,
} from '@fortawesome/free-solid-svg-icons';
import { LAYER_VALUE_MAP } from '@/lib/constants';

interface ReviewPanelProps {
  layer: number;
  dimensions?: string[]; // 可选维度列表
  dimensionNames?: Record<string, string>; // 维度显示名称映射
  onApprove: () => Promise<void>;
  onReject?: (feedback: string, selectedDimensions?: string[]) => Promise<void>;
  isSubmitting?: boolean;
}

export default function ReviewPanel({
  layer,
  dimensions = [],
  dimensionNames = {},
  onApprove,
  onReject,
  isSubmitting = false,
}: ReviewPanelProps) {
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [isRejecting, setIsRejecting] = useState(false);
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);

  const layerName = LAYER_VALUE_MAP[layer] || `第 ${layer} 层`;

  const handleApproveClick = async () => {
    if (isSubmitting) return;
    await onApprove();
  };

  const handleRejectClick = () => {
    setShowRejectInput(true);
  };

  const handleCancelReject = () => {
    setShowRejectInput(false);
    setFeedback('');
    setSelectedDimensions([]);
  };

  const handleDimensionToggle = (dimKey: string) => {
    setSelectedDimensions(prev =>
      prev.includes(dimKey)
        ? prev.filter(d => d !== dimKey)
        : [...prev, dimKey]
    );
  };

  const handleSubmitReject = async () => {
    if (!feedback.trim() || !onReject) return;

    setIsRejecting(true);
    try {
      await onReject(feedback.trim(), selectedDimensions.length > 0 ? selectedDimensions : undefined);
      setShowRejectInput(false);
      setFeedback('');
      setSelectedDimensions([]);
    } catch (error) {
      console.error('[ReviewPanel] Reject failed:', error);
    } finally {
      setIsRejecting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmitReject();
    }
    if (e.key === 'Escape') {
      handleCancelReject();
    }
  };

  return (
    <div className="bg-emerald-50/80 border-t border-emerald-200/50">
      {/* 主操作栏 */}
      <div className="flex items-center justify-between px-4 py-3">
        {/* 左侧：状态信息 */}
        <div className="flex items-center gap-2 text-sm">
          <span>⏸️</span>
          <span className="text-emerald-700 font-medium">{layerName} 待审查</span>
        </div>

        {/* 右侧：操作按钮 */}
        <div className="flex items-center gap-2">
          {/* 驳回按钮 */}
          {onReject && !showRejectInput && (
            <button
              onClick={handleRejectClick}
              disabled={isSubmitting}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed border border-amber-200"
            >
              <FontAwesomeIcon icon={faEdit} className="text-xs" />
              <span>驳回修改</span>
            </button>
          )}

          {/* 批准按钮 */}
          {!showRejectInput && (
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
          )}
        </div>
      </div>

      {/* 驳回输入区 */}
      <AnimatePresence>
        {showRejectInput && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4">
              <div className="bg-white rounded-xl border border-amber-200 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-amber-700">📝 输入修改意见</span>
                  <button
                    onClick={handleCancelReject}
                    className="text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    <FontAwesomeIcon icon={faTimes} className="text-xs" />
                  </button>
                </div>

                {/* 维度选择器 */}
                {dimensions.length > 0 && (
                  <div className="mb-3">
                    <span className="text-xs text-gray-500 mb-1.5 block">
                      🎯 选择需要修订的维度（可选）
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {dimensions.map(dimKey => (
                        <button
                          key={dimKey}
                          onClick={() => handleDimensionToggle(dimKey)}
                          className={`px-2 py-1 text-xs rounded-full transition-all ${
                            selectedDimensions.includes(dimKey)
                              ? 'bg-amber-500 text-white'
                              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                          }`}
                        >
                          {dimensionNames[dimKey] || dimKey}
                        </button>
                      ))}
                    </div>
                    {selectedDimensions.length > 0 && (
                      <p className="text-xs text-amber-600 mt-1.5">
                        已选择 {selectedDimensions.length} 个维度进行定向修订
                      </p>
                    )}
                  </div>
                )}

                <textarea
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="请描述需要修改的内容..."
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-amber-200 focus:border-transparent"
                  rows={3}
                  autoFocus
                />

                <div className="flex items-center justify-between mt-2">
                  <span className="text-xs text-gray-400">或在下方聊天框选择维度后发送</span>
                  <button
                    onClick={handleSubmitReject}
                    disabled={!feedback.trim() || isRejecting}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-amber-500 hover:bg-amber-600 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isRejecting ? (
                      <>
                        <FontAwesomeIcon icon={faSpinner} spin className="text-xs" />
                        <span>提交中...</span>
                      </>
                    ) : (
                      <>
                        <FontAwesomeIcon icon={faPaperPlane} className="text-xs" />
                        <span>提交修改</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
