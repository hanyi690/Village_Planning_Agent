import { describe, it, expect } from 'vitest';
import { usePlanningStore } from '../../features/planning/store/planningStore';

describe('PlanningStore HITL state fields', () => {
  it('initializes human review fields as empty/null', () => {
    const state = usePlanningStore.getState();
    expect(state.humanReviewEventId).toBeNull();
    expect(state.pausedStage).toBeNull();
    expect(state.humanReviewItems).toEqual([]);
    expect(state.humanReviewError).toBeNull();
    expect(state.isResolvingReview).toBe(false);
  });
});

describe('human_review_paused event handling', () => {
  it('sets status to paused and stores review metadata', () => {
    usePlanningStore.setState({ status: 'planning', humanReviewEventId: null, pausedStage: null });
    usePlanningStore.getState().handleSSEEvent({
      type: 'human_review_paused',
      data: { event_id: 'evt-001', paused_stage: 'execute', reason: 'post_l3_human_review', item_count: 2 },
    });
    const state = usePlanningStore.getState();
    expect(state.status).toBe('paused');
    expect(state.isPaused).toBe(true);
    expect(state.humanReviewEventId).toBe('evt-001');
    expect(state.pausedStage).toBe('execute');
  });

  it('does not override existing paused state from duplicate event', () => {
    usePlanningStore.setState({ status: 'paused', humanReviewEventId: 'evt-001', pausedStage: 'execute' });
    usePlanningStore.getState().handleSSEEvent({
      type: 'human_review_paused',
      data: { event_id: 'evt-002', paused_stage: 'execute', item_count: 1 },
    });
    // Idempotent: keep the first event_id, don't override
    expect(usePlanningStore.getState().humanReviewEventId).toBe('evt-001');
  });
});