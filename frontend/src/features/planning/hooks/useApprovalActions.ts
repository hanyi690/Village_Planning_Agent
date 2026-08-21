import { useCallback, useState } from 'react';
import { usePlanningStore } from '../store';
import { useSessionId } from './useSelectors';
import { createErrorMessage } from '../utils/message-helpers';
import { resolveActiveInterrupt, type InterruptDecisionOptions } from '../utils/interrupt-resume';

/**
 * Shared approve/reject actions with loading state.
 * Always loads the current backend checkpoint before submitting.
 */
export function useApprovalActions() {
  const sessionId = useSessionId();
  const setPaused = usePlanningStore((state) => state.setPaused);
  const setPendingReviewLayer = usePlanningStore((state) => state.setPendingReviewLayer);
  const triggerSseReconnect = usePlanningStore((state) => state.triggerSseReconnect);
  const addMessage = usePlanningStore((state) => state.addMessage);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const resolveWithDecision = useCallback(
    async (
      action: 'approve' | 'retry' | 'reject',
      options: InterruptDecisionOptions = {},
    ) => {
      if (!sessionId) throw new Error('No session ID');
      await resolveActiveInterrupt(sessionId, action, options);
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
      usePlanningStore.getState().setStatus('planning');
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
      await resolveWithDecision('reject', { feedback: '需要修改' });
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
