import { useCallback, useState } from 'react';
import { usePlanningStore } from '../store';
import { useSessionId, useCurrentLayer, useHasGisLayers } from './useSelectors';
import { planningApi } from '../api';
import { createErrorMessage } from '../utils/message-helpers';

/**
 * Shared approve/reject actions with loading state.
 * Replaces duplicated logic in FocusArea and BottomActionBar.
 */
export function useApprovalActions() {
  const sessionId = useSessionId();
  const currentLayer = useCurrentLayer();
  const hasGisLayers = useHasGisLayers();
  const setPaused = usePlanningStore((state) => state.setPaused);
  const setPendingReviewLayer = usePlanningStore((state) => state.setPendingReviewLayer);
  const triggerSseReconnect = usePlanningStore((state) => state.triggerSseReconnect);
  const addMessage = usePlanningStore((state) => state.addMessage);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const approve = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    setIsSubmitting(true);
    try {
      const result = await planningApi.submitFeedback(sessionId, { approve: true });
      // Read current_layer from backend response for immediate UI sync
      if (result?.current_layer) {
        usePlanningStore.setState({ lastPauseLayer: result.current_layer });
      }
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
  }, [sessionId, setPaused, setPendingReviewLayer, triggerSseReconnect, addMessage, isSubmitting]);

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
  }, [sessionId, setPaused, setPendingReviewLayer, triggerSseReconnect, addMessage, isSubmitting]);

  return { approve, reject, isSubmitting };
}
