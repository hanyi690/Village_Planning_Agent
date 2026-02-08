'use client';

import { useState } from 'react';
import { ReviewInteractionMessage as ReviewInteractionMessageType } from '@/types/message';
import DimensionSelector from '../DimensionSelector';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faClipboardCheck, faCheck, faTimes, faUndo,
  faClock, faEdit, faInfoCircle, faFilter,
  faCommentAlt, faLightbulb, faExclamationTriangle, faSpinner,
  faLayerGroup,
} from '@fortawesome/free-solid-svg-icons';

interface ReviewInteractionMessageProps {
  message: ReviewInteractionMessageType;
  onApprove: () => Promise<void>;
  onReject: (feedback: string, dimensions?: string[]) => Promise<void>;
  onRollback: (checkpointId: string) => Promise<void>;
  disabled?: boolean;
}

/**
 * ReviewInteractionMessage - Interactive review UI embedded in chat flow
 *
 * Features:
 * - Dimension selection for targeted feedback
 * - Feedback input with quick options
 * - Approve, reject (with feedback), and rollback actions
 * - Visual state feedback for pending/approved/rejected/rolled_back
 */
export default function ReviewInteractionMessage({
  message,
  onApprove,
  onReject,
  onRollback,
  disabled = false,
}: ReviewInteractionMessageProps) {
  const [feedback, setFeedback] = useState('');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const {
    reviewState,
    layer,
    content,
    availableActions,
    enableDimensionSelection,
    enableRollback,
    checkpoints,
    feedbackPlaceholder,
    quickFeedbackOptions,
    submittedAt,
    submissionType,
    submissionFeedback,
  } = message;

  const isPending = reviewState === 'pending';
  const isApproved = reviewState === 'approved';
  const isRejected = reviewState === 'rejected';
  const isRolledBack = reviewState === 'rolled_back';
  const canReject = availableActions.includes('reject');
  const canRollback = availableActions.includes('rollback');

  const handleApprove = async () => {
    if (isSubmitting || disabled) return;
    setIsSubmitting(true);
    try {
      await onApprove();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (isSubmitting || disabled || !feedback.trim()) return;
    setIsSubmitting(true);
    try {
      await onReject(feedback.trim(), enableDimensionSelection ? selectedDimensions : undefined);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRollback = async () => {
    if (isSubmitting || disabled || !selectedCheckpoint) return;
    if (!confirm('确定要回退吗？之后的内容将被删除。')) return;
    setIsSubmitting(true);
    try {
      await onRollback(selectedCheckpoint);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleQuickFeedback = (option: string) => {
    setFeedback(option);
  };

  // State-specific rendering
  const renderStateBadge = () => {
    if (isApproved) {
      return (
        <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm font-medium">
          <FontAwesomeIcon icon={faCheck} />
          <span>已批准</span>
        </div>
      );
    }
    if (isRejected) {
      return (
        <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-orange-50 border border-orange-200 rounded-lg text-orange-700 text-sm font-medium">
          <FontAwesomeIcon icon={faEdit} />
          <span>已驳回，正在修复...</span>
        </div>
      );
    }
    if (isRolledBack) {
      return (
        <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 border border-blue-200 rounded-lg text-blue-700 text-sm font-medium">
          <FontAwesomeIcon icon={faUndo} />
          <span>已回退</span>
        </div>
      );
    }
    return (
      <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 border border-blue-200 rounded-lg text-blue-700 text-sm font-medium">
        <FontAwesomeIcon icon={faClock} />
        <span>等待审查</span>
      </div>
    );
  };

  const renderSubmissionResult = () => {
    if (!submittedAt) return null;

    const timeStr = new Date(submittedAt).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    });

    return (
      <div className="mt-4 p-4 bg-gray-50 rounded-xl border border-gray-200">
        <div className="flex items-start gap-2 text-sm text-gray-600">
          <FontAwesomeIcon icon={faInfoCircle} className="text-gray-400 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium text-gray-700">
              {submissionType === 'approve' && '您批准了此层内容，规划继续执行'}
              {submissionType === 'reject' && '您驳回了此层内容，AI正在根据反馈修复'}
              {submissionType === 'rollback' && '您回退到了之前的检查点'}
            </p>
            <p className="text-xs text-gray-500 mt-1">提交时间: {timeStr}</p>
            {submissionFeedback && (
              <div className="mt-2 p-2 bg-white rounded border border-gray-200">
                <p className="text-xs text-gray-500 mb-1">您的反馈:</p>
                <p className="text-sm text-gray-700">{submissionFeedback}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="bg-white rounded-xl border-2 border-green-200 shadow-sm overflow-hidden">
      {/* Header with gradient */}
      <div className="bg-gradient-to-r from-green-700 to-green-800 px-5 py-4" style={{ color: 'var(--text-cream-primary)' }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full flex items-center justify-center" style={{ background: 'var(--overlay-cream-light)' }}>
              <FontAwesomeIcon icon={faClipboardCheck} className="text-lg" />
            </div>
            <div>
              <h3 className="font-bold text-lg">人工审查 - Layer {layer}</h3>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-cream-secondary)' }}>{content}</p>
            </div>
          </div>
          {renderStateBadge()}
        </div>
      </div>

      {/* Content */}
      <div className="p-5 space-y-4">
        {/* Instructions */}
        {isPending && (
          <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 rounded-xl p-4">
            <p className="text-sm text-blue-800 leading-relaxed">
              <FontAwesomeIcon icon={faInfoCircle} className="text-blue-500 mr-1.5" />
              请审查当前层级的内容质量。如发现问题，可选择相关维度并提供修改反馈。
            </p>
          </div>
        )}

        {/* Dimension Selector */}
        {isPending && enableDimensionSelection && (
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h4 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <FontAwesomeIcon icon={faFilter} className="text-green-500" />
              选择审查维度（可选）
            </h4>
            <DimensionSelector
              dimensions={[]}
              selectedDimensions={selectedDimensions}
              onChange={setSelectedDimensions}
            />
          </div>
        )}

        {/* Feedback Input - REMOVED: Now using external main chat input */}
        {/* Quick feedback options preserved as reference chips */}
        {isPending && canReject && quickFeedbackOptions && quickFeedbackOptions.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <label className="block text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <FontAwesomeIcon icon={faCommentAlt} className="text-green-500" />
              快速反馈选项（点击后请在下方输入框发送）
            </label>
            <div className="flex flex-wrap gap-2">
              {quickFeedbackOptions.map((option, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => handleQuickFeedback(option)}
                  disabled={disabled}
                  className="px-3 py-1.5 text-xs bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-all duration-200 font-medium shadow-sm hover:shadow disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {option}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-500 mt-2 flex items-center gap-1">
              <FontAwesomeIcon icon={faLightbulb} className="text-yellow-500" />
              点击选项后，请在下方主输入框中按 Enter 发送驳回反馈
            </p>
          </div>
        )}

        {/* Rollback Selector */}
        {isPending && canRollback && checkpoints && checkpoints.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h4 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <FontAwesomeIcon icon={faUndo} className="text-blue-500" />
              回退到检查点（可选）
            </h4>
            <select
              className="w-full px-4 py-2.5 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all duration-200"
              value={selectedCheckpoint}
              onChange={(e) => setSelectedCheckpoint(e.target.value)}
              disabled={disabled}
            >
              <option value="">选择要回退的检查点...</option>
              {checkpoints.map((cp) => (
                <option key={cp.checkpoint_id} value={cp.checkpoint_id}>
                  Layer {cp.layer} - {cp.description} ({new Date(cp.timestamp).toLocaleString('zh-CN')})
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-2">
              <FontAwesomeIcon icon={faExclamationTriangle} className="text-yellow-500 mr-1" />
              回退将删除之后的所有内容，请谨慎操作
            </p>
          </div>
        )}

        {/* Submission Result */}
        {renderSubmissionResult()}

        {/* Action Buttons */}
        {isPending && (
          <div className="flex flex-col sm:flex-row gap-3 pt-2">
            {/* Rollback button */}
            {canRollback && (
              <button
                onClick={handleRollback}
                disabled={!selectedCheckpoint || isSubmitting || disabled}
                className="flex-1 px-4 py-3 border-2 border-blue-500 text-blue-600 rounded-xl hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 font-bold shadow-sm hover:shadow flex items-center justify-center gap-2"
              >
                <FontAwesomeIcon icon={faUndo} />
                <span>回退</span>
              </button>
            )}

            {/* Reject button - NOW DISABLED: Use main input for feedback */}
            {canReject && false && (
              <button
                onClick={handleReject}
                disabled={!feedback.trim() || isSubmitting || disabled}
                className="flex-1 px-4 py-3 border-2 border-orange-500 text-orange-600 rounded-xl hover:bg-orange-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 font-bold shadow-sm hover:shadow flex items-center justify-center gap-2"
              >
                <FontAwesomeIcon icon={faTimes} />
                <span>驳回并修复</span>
              </button>
            )}

            {/* Approve button */}
            <button
              onClick={handleApprove}
              disabled={isSubmitting || disabled}
              className="flex-1 px-4 py-3 bg-gradient-to-r from-green-600 to-green-700 rounded-xl hover:from-green-700 hover:to-green-800 disabled:from-gray-400 disabled:to-gray-500 transition-all duration-200 font-bold shadow-md hover:shadow-lg flex items-center justify-center gap-2 transform hover:-translate-y-0.5 disabled:transform-none"
              style={{ color: 'var(--text-cream-primary)' }}
            >
              {isSubmitting ? (
                <>
                  <FontAwesomeIcon icon={faSpinner} spin />
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
        )}
      </div>
    </div>
  );
}
