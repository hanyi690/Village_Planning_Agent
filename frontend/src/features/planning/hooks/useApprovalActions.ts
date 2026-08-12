import { useCallback, useState } from 'react';
import { usePlanningStore } from '../store';
import { useSessionId } from './useSelectors';
import { planningApi } from '../api';
import { createErrorMessage } from '../utils/message-helpers';

/**
 * Shared approve/reject actions with loading state.
 * Replaces duplicated logic in FocusArea and BottomActionBar.
 *
 * Uses the v1 /human-review endpoint with the current event_id as an
 * optimistic lock. A stale/conflicting event_id returns 409 and the caller
 * should refresh /state + /human-review rather than auto-retry.
 */
export function useApprovalActions() {
  const sessionId = useSessionId();
  const setPaused = usePlanningStore((state) => state.setPaused);
  const setPendingReviewLayer = usePlanningStore((state) => state.setPendingReviewLayer);
  const triggerSseReconnect = usePlanningStore((state) => state.triggerSseReconnect);
  const addMessage = usePlanningStore((state) => state.addMessage);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch the current HUMAN event_id (optimistic lock) before submitting.
  const resolveWithDecision = useCallback(
    async (action: 'approve' | 'retry' | 'reject', feedback?: string) => {
      if (!sessionId) throw new Error('No session ID');
      const review = usePlanningStore.getState().humanReview;
      const eventId =
        review?.event_id ??
        (await planningApi.getHumanReview(sessionId)).event_id ??
        null;
      if (!eventId) {
        throw new Error('没有待审核的人工审核项（缺少 event_id）');
      }
      await planningApi.resolveHumanReview(sessionId, eventId, {
        action,
        ...(feedback ? { feedback } : {}),
      });
      usePlanningStore.getState().clearHumanReview();
    },
    [sessionId],
  );

  const approve = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await resolveWithDecision('approve');
      setPaused(false);
      setPendingReviewLayer(null);
      // Reconnect/sync SSE so layer_start and subsequent dimension events are not missed.
      triggerSseReconnect();
    } catch (error) {
      console.error('Approve failed:', error);
      const message = error instanceof Error ? error.message : String(error);
      addMessage(createErrorMessage(`批准失败：${message}`));
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, setPaused, setPendingReviewLayer, triggerSseReconnect, addMessage, resolveWithDecision, isSubmitting]);

  const reject = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await resolveWithDecision('reject', '需要修改');
      setPaused(false);
      triggerSseReconnect();
    } catch (error) {
      console.error('Reject failed:', error);
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, setPaused, triggerSseReconnect, resolveWithDecision, isSubmitting]);

  return { approve, reject, isSubmitting, resolveWithDecision };
}