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