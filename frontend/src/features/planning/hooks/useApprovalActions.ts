import { useCallback, useState } from 'react';
import { usePlanningStore } from '../store';
import { useSessionId, useCurrentLayer, useHasGisLayers } from './useSelectors';
import { planningApi } from '../api';

/**
 * Shared approve/reject actions with loading state.
 * Replaces duplicated logic in FocusArea and BottomActionBar.
 */
export function useApprovalActions() {
  const sessionId = useSessionId();
  const currentLayer = useCurrentLayer();
  const hasGisLayers = useHasGisLayers();
  const setPaused = usePlanningStore((state) => state.setPaused);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const approve = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await planningApi.submitFeedback(sessionId, { approve: true });
      setPaused(false);

      // L3 approved → trigger GIS (delay to avoid execution lock race with approve)
      if (currentLayer === 3 && !hasGisLayers) {
        await new Promise(r => setTimeout(r, 500));
        try {
          await planningApi.sendChatMessage(sessionId, '请生成空间布局分析');
        } catch (e) {
          console.error('Failed to trigger GIS analysis:', e);
        }
      }
    } catch (error) {
      console.error('Approve failed:', error);
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, setPaused, currentLayer, hasGisLayers, isSubmitting]);

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
