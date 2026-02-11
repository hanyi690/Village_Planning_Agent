'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { UnifiedPlanningProvider } from '@/contexts/UnifiedPlanningContext';
import UnifiedLayout from '@/components/layout/UnifiedLayout';
import ChatPanel from '@/components/chat/ChatPanel';
import ReviewPanel from '@/components/review/ReviewPanel';
import { planningApi } from '@/lib/api';

/**
 * Unified Planning Page - Single entry point for all planning interactions
 *
 * Route: /village/[taskId]
 * - taskId='new': Create new planning task
 * - taskId=<uuid>: View/manage existing task
 */
export default function VillagePage() {
  const params = useParams();
  const router = useRouter();

  const taskId = params.taskId as string;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showReviewPanel, setShowReviewPanel] = useState(false);

  // Handle 'new' task redirect
  useEffect(() => {
    if (taskId === 'new') {
      // For now, just show the interface with a new conversation ID
      setLoading(false);
      return;
    }

    // Validate task ID and load task data
    loadTaskData();
  }, [taskId]);

  const loadTaskData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Check if task exists
      const taskStatus = await planningApi.getTaskStatus(taskId);

      if (!taskStatus) {
        setError('任务不存在');
        return;
      }

      setLoading(false);
    } catch (err: any) {
      console.error('[VillagePage] Failed to load task:', err);
      setError(err.message || '加载任务失败');
      setLoading(false);
    }
  };

  const handleReviewApprove = async () => {
    try {
      await planningApi.approveReview(taskId);
      setShowReviewPanel(false);
      // SSE will handle the rest
    } catch (err: any) {
      console.error('[VillagePage] Failed to approve:', err);
      alert(`批准失败: ${err.message || '未知错误'}`);
    }
  };

  const handleReviewReject = async (feedback: string, dimensions?: string[]) => {
    try {
      await planningApi.rejectReview(taskId, feedback, dimensions);
      setShowReviewPanel(false);
      // SSE will handle the rest
    } catch (err: any) {
      console.error('[VillagePage] Failed to reject:', err);
      alert(`驳回失败: ${err.message || '未知错误'}`);
    }
  };

  const handleRollback = async (checkpointId: string) => {
    try {
      await planningApi.rollbackCheckpoint(taskId, checkpointId);
      setShowReviewPanel(false);
      // Reload page to refresh state
      window.location.reload();
    } catch (err: any) {
      console.error('[VillagePage] Failed to rollback:', err);
      alert(`回退失败: ${err.message || '未知错误'}`);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-green-600 mb-4" />
          <p className="text-gray-600">加载中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-md">
          <div className="text-6xl mb-4">😕</div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">出错了</h1>
          <p className="text-gray-600 mb-6">{error}</p>
          <div className="flex gap-3 justify-center">
            <button
              onClick={() => router.push('/')}
              className="px-4 py-2 bg-green-600 rounded-lg hover:bg-green-700 transition-colors"
              style={{ color: 'var(--text-cream-primary)' }}
            >
              返回首页
            </button>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  const conversationId = taskId === 'new' ? `conv-${Date.now()}` : taskId;

  return (
    <UnifiedPlanningProvider conversationId={conversationId}>
      <UnifiedLayout taskId={taskId}>
        <ChatPanel />

        {/* Review Panel (overlay) */}
        <ReviewPanel
          isOpen={showReviewPanel}
          onClose={() => setShowReviewPanel(false)}
          onApprove={handleReviewApprove}
          onReject={handleReviewReject}
          onRollback={handleRollback}
        />
      </UnifiedLayout>
    </UnifiedPlanningProvider>
  );
}
