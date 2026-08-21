import { planningApi } from '../api';
import type { HumanReviewListResponse } from '../api/types';

export type InterruptDecisionOptions = {
  feedback?: string;
  dimensions?: string[];
};

function isCheckpointConflict(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const status = (error as Error & { status?: number }).status;
  if (status === 409) return true;
  const message = error.message.toLowerCase();
  return (
    message.includes('event_id does not match')
    || message.includes('checkpoint was already resumed')
    || message.includes('no active human checkpoint')
  );
}

export async function fetchActiveHumanReview(
  sessionId: string,
): Promise<HumanReviewListResponse> {
  return planningApi.getHumanReview(sessionId);
}

/**
 * Load the authoritative interrupt from the backend and sync it into the store.
 */
export async function loadActiveHumanReview(
  sessionId: string,
): Promise<HumanReviewListResponse> {
  const { usePlanningStore } = await import('../store/planningStore');
  await usePlanningStore.getState().refreshHumanReview(sessionId);
  // Read from the API after refreshing the store. The store can still contain
  // an SSE-era checkpoint while the backend has already moved to a new event.
  return fetchActiveHumanReview(sessionId);
}

/**
 * Submit a decision against the active HUMAN checkpoint.
 * Uses the canonical v1 transport: POST /api/v1/sessions/{id}/human-review
 */
export async function submitInterruptDecision(
  sessionId: string,
  review: HumanReviewListResponse,
  action: 'approve' | 'retry' | 'reject',
  options: InterruptDecisionOptions = {},
): Promise<void> {
  const eventId = review.event_id;
  if (!eventId) {
    throw new Error('没有待审核的中断检查点（缺少 event_id）');
  }

  const decisions: Record<string, unknown> = { action };
  if (options.feedback) {
    decisions.feedback = options.feedback;
  }
  if (options.dimensions?.length) {
    decisions.dimensions = options.dimensions;
  }

  await planningApi.resolveHumanReview(sessionId, eventId, {
    action,
    feedback: options.feedback,
    decisions,
  });
}

/**
 * Fetch the current checkpoint, submit the decision, and retry once on 409 conflicts.
 */
export async function resolveActiveInterrupt(
  sessionId: string,
  action: 'approve' | 'retry' | 'reject',
  options: InterruptDecisionOptions = {},
): Promise<void> {
  const { usePlanningStore } = await import('../store/planningStore');

  let review = await loadActiveHumanReview(sessionId);
  try {
    try {
      await submitInterruptDecision(sessionId, review, action, options);
    } catch (retryError) {
      if (isCheckpointConflict(retryError)) {
        throw new Error('审核检查点已更新，请刷新审核状态后重试');
      }
      throw retryError;
    }
  } catch (error) {
    if (!isCheckpointConflict(error)) {
      throw error;
    }
    review = await loadActiveHumanReview(sessionId);
    if (!review.event_id) {
      throw new Error('审核检查点已失效，请刷新页面后重试');
    }
    await submitInterruptDecision(sessionId, review, action, options);
  }

  usePlanningStore.getState().clearHumanReview();
}
