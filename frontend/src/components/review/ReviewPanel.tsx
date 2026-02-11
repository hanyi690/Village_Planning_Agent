'use client';

import { useState } from 'react';
import { useUnifiedPlanningContext } from '@/contexts/UnifiedPlanningContext';
import DimensionSelector from '../DimensionSelector';

interface ReviewPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onApprove: () => void;
  onReject: (feedback: string, dimensions?: string[]) => void;
  onRollback: (checkpointId: string) => void;
}

/**
 * ReviewPanel - Simplified review interface for human-in-the-loop planning
 *
 * @deprecated This component is being replaced by ReviewInteractionMessage
 * which embeds review functionality directly in the chat flow.
 * This component is kept for backward compatibility with existing pages.
 *
 * Desktop: Right-side drawer (600px width)
 * Mobile: Bottom sheet (90vh height)
 *
 * Features:
 * - Content review with dimension selection
 * - Feedback submission
 */
export default function ReviewPanel({
  isOpen,
  onClose,
  onApprove,
  onReject,
  onRollback
}: ReviewPanelProps) {
  const { currentLayer } = useUnifiedPlanningContext();

  const [feedback, setFeedback] = useState('');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);

  const handleReject = () => {
    if (!feedback.trim()) {
      alert('请提供修改反馈');
      return;
    }
    onReject(feedback, selectedDimensions);
    setFeedback('');
    setSelectedDimensions([]);
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Overlay with backdrop blur */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 animate-[fadeIn_0.2s_ease-in-out]"
        onClick={onClose}
      />

      {/* Panel with modern styling */}
      <div
        className="
          fixed right-0 top-0 bottom-0 w-[600px] bg-white shadow-2xl z-50 flex flex-col
          border-l-4 border-green-500 transition-transform duration-300
        "
      >
        {/* Header - Gradient background */}
        <div className="flex-shrink-0 bg-gradient-to-r from-green-700 to-green-800 p-5 flex items-center justify-between shadow-md" style={{ color: 'var(--text-cream-primary)' }}>
          <div>
            <h2 className="text-lg font-bold flex items-center gap-2">
              <span className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: 'var(--overlay-cream-light)' }}>
                <i className="fas fa-clipboard-check text-sm"></i>
              </span>
              人工审查 - Layer {currentLayer}
            </h2>
            <p className="text-xs mt-1 ml-10" style={{ color: 'var(--text-cream-secondary)' }}>
              审查并决定是否继续执行
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/10 rounded-lg transition-all duration-200 backdrop-blur-sm"
            aria-label="Close"
          >
            <i className="fas fa-times icon-sm" style={{ color: 'var(--text-cream-primary)' }} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 bg-gradient-to-br from-gray-50 to-white">
          <div className="space-y-5 animate-[fadeIn_0.3s_ease-in-out]">
            {/* Instructions - Enhanced card */}
            <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 rounded-xl p-5 shadow-sm">
              <h3 className="text-sm font-bold text-blue-900 mb-2 flex items-center gap-2">
                <span className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center" style={{ color: 'var(--text-cream-primary)' }}>
                  <i className="fas fa-info text-xs"></i>
                </span>
                审查说明
              </h3>
              <p className="text-sm text-blue-800 leading-relaxed">
                请审查当前层级的内容质量。如发现问题，可选择相关维度并提供修改反馈。
              </p>
            </div>

            {/* Dimension Selector */}
            <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-200">
              <h3 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                <i className="fas fa-filter text-green-500"></i>
                选择审查维度
              </h3>
              <DimensionSelector
                dimensions={[]}
                selectedDimensions={selectedDimensions}
                onChange={setSelectedDimensions}
              />
            </div>

            {/* Feedback Form */}
            <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-200">
              <label htmlFor="feedback" className="block text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                <i className="fas fa-comment-alt text-green-500"></i>
                修改反馈
              </label>
              <textarea
                id="feedback"
                className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-green-500/20 focus:border-green-500 transition-all duration-200 shadow-sm resize-none"
                rows={6}
                placeholder="请描述需要修改的内容..."
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
              />
              <p className="text-xs text-gray-500 mt-2 flex items-center gap-1">
                <i className="fas fa-lightbulb text-yellow-500"></i>
                提供具体的修改建议，帮助AI更好地理解您的需求
              </p>
            </div>

            {/* Quick actions - Enhanced buttons */}
            <div className="flex gap-2">
              <button
                onClick={() => setFeedback('内容结构需要优化，请重新组织')}
                className="px-4 py-2 text-xs bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-all duration-200 font-medium shadow-sm hover:shadow"
              >
                <i className="fas fa-sitemap mr-1.5"></i>
                结构优化
              </button>
              <button
                onClick={() => setFeedback('部分内容不够详细，需要补充')}
                className="px-4 py-2 text-xs bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-all duration-200 font-medium shadow-sm hover:shadow"
              >
                <i className="fas fa-plus-circle mr-1.5"></i>
                内容补充
              </button>
              <button
                onClick={() => setFeedback('存在错误或不准确的信息')}
                className="px-4 py-2 text-xs bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-all duration-200 font-medium shadow-sm hover:shadow"
              >
                <i className="fas fa-exclamation-triangle mr-1.5"></i>
                错误修正
              </button>
            </div>
          </div>
        </div>

        {/* Footer - Gradient approve button, outlined reject button */}
        <div className="flex-shrink-0 border-t border-gray-200 p-5 bg-white shadow-[0_-4px_12px_rgba(0,0,0,0.05)] flex gap-3">
          <button
            onClick={handleReject}
            disabled={!feedback.trim()}
            className="flex-1 px-4 py-3 border-2 border-red-500 text-red-600 rounded-xl hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 font-bold shadow-sm hover:shadow flex items-center justify-center gap-2"
          >
            <i className="fas fa-times"></i>
            驳回并修复
          </button>
          <button
            onClick={onApprove}
            className="flex-1 px-4 py-3 bg-gradient-to-r from-green-600 to-green-700 rounded-xl hover:from-green-700 hover:to-green-800 transition-all duration-200 font-bold shadow-md hover:shadow-lg flex items-center justify-center gap-2 transform hover:-translate-y-0.5"
            style={{ color: 'var(--text-cream-primary)' }}
          >
            <i className="fas fa-check"></i>
            批准继续
          </button>
        </div>
      </div>
    </>
  );
}
