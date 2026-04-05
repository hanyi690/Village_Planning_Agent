/**
 * useReviewActions Hook - 审查操作逻辑
 *
 * 提取自 ChatPanel 的审查操作：
 * - approve: 批准当前审查
 * - reject: 拒绝并提供反馈
 * - rollback: 回滚到检查点
 */

import { useCallback, useState } from 'react';
import { usePlanningStore } from '@/stores/planningStore';
import { planningApi } from '@/lib/api';
import { createSystemMessage, createErrorMessage, getErrorMessage } from '@/lib/utils';
import { logger } from '@/lib/logger';

// ============================================
// Types
// ============================================

interface UseReviewActionsOptions {
  onApproveSuccess?: () => void;
  onRejectSuccess?: () => void;
  onRollbackSuccess?: () => void;
}

// ============================================
// Hook Implementation
// ============================================

export function useReviewActions(options: UseReviewActionsOptions = {}) {
  const { onApproveSuccess, onRejectSuccess, onRollbackSuccess } = options;

  // Store access
  const taskId = usePlanningStore((state) => state.taskId);
  const isPaused = usePlanningStore((state) => state.isPaused);
  const pendingReviewLayer = usePlanningStore((state) => state.pendingReviewLayer);
  const checkpoints = usePlanningStore((state) => state.checkpoints);
  const addMessage = usePlanningStore((state) => state.addMessage);
  const setPaused = usePlanningStore((state) => state.setPaused);
  const setPendingReviewLayer = usePlanningStore((state) => state.setPendingReviewLayer);
  const setSelectedCheckpoint = usePlanningStore((state) => state.setSelectedCheckpoint);
  const syncBackendState = usePlanningStore((state) => state.syncBackendState);
  const triggerSseReconnect = usePlanningStore((state) => state.triggerSseReconnect);

  // Local state
  const [isApproving, setIsApproving] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);
  const [isRollingBack, setIsRollingBack] = useState(false);

  // ============================================
  // Approve Action
  // ============================================

  const approve = useCallback(async () => {
    if (!taskId) {
      throw new Error('No task ID available');
    }

    setIsApproving(true);
    try {
      logger.context.info('Approving review', { taskId });

      await planningApi.approveReview(taskId);

      setPaused(false);
      setPendingReviewLayer(null);

      // Trigger SSE reconnect to ensure events are received
      triggerSseReconnect();

      addMessage(createSystemMessage('✅ 已批准规划方案，继续执行...'));

      onApproveSuccess?.();
      logger.context.info('Review approved successfully');
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, 'Unknown error');
      logger.context.error('Failed to approve review', { error: errorMessage });
      addMessage(createErrorMessage(`批准失败: ${errorMessage}`));
      throw error;
    } finally {
      setIsApproving(false);
    }
  }, [taskId, setPaused, setPendingReviewLayer, triggerSseReconnect, addMessage, onApproveSuccess]);

  // ============================================
  // Reject Action
  // ============================================

  const reject = useCallback(async (feedback: string, dimensions?: string[]) => {
    if (!taskId) {
      throw new Error('No task ID available');
    }

    if (!feedback.trim()) {
      throw new Error('Feedback is required');
    }

    setIsRejecting(true);
    try {
      logger.context.info('Rejecting review', { taskId, feedback: feedback.slice(0, 50), dimensions });

      await planningApi.rejectReview(taskId, feedback, dimensions);

      setPaused(false);

      addMessage(createSystemMessage(`🔄 已提交修改意见，正在重新规划...\n\n反馈: ${feedback.slice(0, 200)}${feedback.length > 200 ? '...' : ''}`));

      onRejectSuccess?.();
      logger.context.info('Review rejected successfully');
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, 'Unknown error');
      logger.context.error('Failed to reject review', { error: errorMessage });
      addMessage(createErrorMessage(`提交修改意见失败: ${errorMessage}`));
      throw error;
    } finally {
      setIsRejecting(false);
    }
  }, [taskId, setPaused, addMessage, onRejectSuccess]);

  // ============================================
  // Rollback Action
  // ============================================

  const rollback = useCallback(async (checkpointId: string) => {
    if (!taskId) {
      throw new Error('No task ID available');
    }

    setIsRollingBack(true);
    try {
      logger.context.info('Rolling back to checkpoint', { taskId, checkpointId });

      await planningApi.rollbackCheckpoint(taskId, checkpointId);

      setSelectedCheckpoint(checkpointId);

      // Sync state after rollback
      const statusData = await planningApi.getStatus(taskId);
      syncBackendState(statusData);

      const checkpoint = checkpoints.find((cp) => cp.checkpoint_id === checkpointId);
      const checkpointDesc = checkpoint?.description || checkpointId.slice(0, 8);

      addMessage(createSystemMessage(`⏪ 已回滚到检查点: ${checkpointDesc}`));

      onRollbackSuccess?.();
      logger.context.info('Rollback completed successfully');
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, 'Unknown error');
      logger.context.error('Failed to rollback', { error: errorMessage });
      addMessage(createErrorMessage(`回滚失败: ${errorMessage}`));
      throw error;
    } finally {
      setIsRollingBack(false);
    }
  }, [taskId, checkpoints, setSelectedCheckpoint, syncBackendState, addMessage, onRollbackSuccess]);

  // ============================================
  // Derived State
  // ============================================

  const hasPendingReview = isPaused && pendingReviewLayer !== null;

  return {
    // State
    isPaused,
    pendingReviewLayer,
    hasPendingReview,
    checkpoints,
    isApproving,
    isRejecting,
    isRollingBack,

    // Actions
    approve,
    reject,
    rollback,
  };
}

export default useReviewActions;