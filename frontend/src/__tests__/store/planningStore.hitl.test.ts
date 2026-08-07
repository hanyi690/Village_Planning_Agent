import { describe, it, expect, jest } from '@jest/globals';
import { usePlanningStore } from '../../features/planning/store/planningStore';
import * as planningApi from '../../features/planning/api/planning-api';

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

describe('fetchHumanReviewItems action', () => {
  it('fetches items and stores them', async () => {
    const items = [{ request_id: 'req-1', stage: 'execute', request_type: 'zone_review' }];
    jest.spyOn(planningApi.planningApi, 'getHumanReview').mockResolvedValue({
      session_id: 'sess-1', post_l3_status: 'paused', pending_items: items, count: 1,
    });
    await usePlanningStore.getState().fetchHumanReviewItems('sess-1');
    expect(usePlanningStore.getState().humanReviewItems).toEqual(items);
    jest.restoreAllMocks();
  });

  it('sets error on fetch failure', async () => {
    jest.spyOn(planningApi.planningApi, 'getHumanReview').mockRejectedValue(new Error('network'));
    await usePlanningStore.getState().fetchHumanReviewItems('sess-1');
    expect(usePlanningStore.getState().humanReviewError).toBeTruthy();
    jest.restoreAllMocks();
  });
});

describe('resolveHumanReview action', () => {
  it('sets isResolvingReview on success but does NOT set status=planning', async () => {
    usePlanningStore.setState({ status: 'paused', humanReviewEventId: 'evt-1', pausedStage: 'execute' });
    jest.spyOn(planningApi.planningApi, 'resolveHumanReview').mockResolvedValue({
      session_id: 'sess-1', resolved: true, result: {},
    });
    await usePlanningStore.getState().resolveHumanReview('sess-1', { r1: { action: 'approve' } });
    const state = usePlanningStore.getState();
    expect(state.isResolvingReview).toBe(true);
    expect(state.status).toBe('paused');
    jest.restoreAllMocks();
  });

  it('does NOT clear paused state on resolve failure', async () => {
    usePlanningStore.setState({ status: 'paused', humanReviewEventId: 'evt-1', pausedStage: 'execute' });
    jest.spyOn(planningApi.planningApi, 'resolveHumanReview').mockRejectedValue(new Error('server'));
    await usePlanningStore.getState().resolveHumanReview('sess-1', { r1: { action: 'approve' } });
    const state = usePlanningStore.getState();
    expect(state.status).toBe('paused');
    expect(state.humanReviewEventId).toBe('evt-1');
    expect(state.humanReviewError).toBeTruthy();
    expect(state.isResolvingReview).toBe(false);
    jest.restoreAllMocks();
  });
});

describe('execution_resumed clears HITL state', () => {
  it('clears all HITL fields when execution resumes', () => {
    usePlanningStore.setState({
      status: 'paused', humanReviewEventId: 'evt-1', pausedStage: 'execute',
      humanReviewItems: [{ request_id: 'r1', stage: 'execute', request_type: 'zone_review' }],
      isResolvingReview: true, humanReviewError: null,
    });
    usePlanningStore.getState().handleSSEEvent({ type: 'execution_resumed', data: {} });
    const state = usePlanningStore.getState();
    expect(state.status).toBe('planning');
    expect(state.humanReviewEventId).toBeNull();
    expect(state.pausedStage).toBeNull();
    expect(state.humanReviewItems).toEqual([]);
    expect(state.isResolvingReview).toBe(false);
    expect(state.humanReviewError).toBeNull();
  });
});