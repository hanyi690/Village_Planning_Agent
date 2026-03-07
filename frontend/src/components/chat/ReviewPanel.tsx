'use client';

/**
 * ReviewPanel - 审查面板
 *
 * 支持批准和驳回两种操作
 * 驳回时可展开输入框填写修改意见
 */

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck, faEdit, faTimes, faPaperPlane, faSpinner } from '@fortawesome/free-solid-svg-icons';

interface ReviewPanelProps {
  layer: number;
  onApprove: () => Promise<void>;
  onReject?: (feedback: string) => Promise<void>;
  isSubmitting?: boolean;
}

export default function ReviewPanel({
  layer,
  onApprove,
  onReject,
  isSubmitting = false,
}: ReviewPanelProps) {
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [isRejecting, setIsRejecting] = useState(false);

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

  const handleRejectClick = () => {
    setShowRejectInput(true);
  };

  const handleCancelReject = () => {
    setShowRejectInput(false);
    setFeedback('');
  };

  const handleSubmitReject = async () => {
    if (!feedback.trim() || !onReject) return;
    
    setIsRejecting(true);
    try {
      await onReject(feedback.trim());
      setShowRejectInput(false);
      setFeedback('');
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
                  <span className="text-xs font-medium text-amber-700">
                    📝 输入修改意见
                  </span>
                  <button
                    onClick={handleCancelReject}
                    className="text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    <FontAwesomeIcon icon={faTimes} className="text-xs" />
                  </button>
                </div>
                
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
                  <span className="text-xs text-gray-400">
                    或在下方聊天框选择维度后发送
                  </span>
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
