import { useCallback, useState } from 'react';
import { usePlanningStore } from '../store';
import { useSessionId } from './useSelectors';
import { planningApi } from '../api';

/**
 * Shared approve/reject actions with loading state.
 * Replaces duplicated logic in FocusArea and BottomActionBar.
 */
export function useApprovalActions() {
  const sessionId = useSessionId();
  const setPaused = usePlanningStore((state) => state.setPaused);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const approve = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await planningApi.submitFeedback(sessionId, { approve: true });
      setPaused(false);
    } catch (error) {
      console.error('Approve failed:', error);
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, setPaused, isSubmitting]);

  const reject = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await planningApi.submitFeedback(sessionId, { approve: false, feedback: '需要修改' });
      setPaused(false);
    } catch (error) {
      console.error('Reject failed:', error);
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, setPaused, isSubmitting]);

  return { approve, reject, isSubmitting };
}
