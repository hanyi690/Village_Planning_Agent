import { usePlanningStore } from '@/features/planning/store/planningStore';

describe('planning store v1 delivery / resync / human-review events', () => {
  beforeEach(() => {
    usePlanningStore.getState().resetConversation();
    usePlanningStore.getState().clearMessages();
    usePlanningStore.getState().setDelivery(null);
    usePlanningStore.getState().setResyncRequired(false);
    usePlanningStore.getState().setHumanReview(null);
  });

  it('delivery_ready flips status to completed so the UI pulls /delivery + /map-layers', () => {
    usePlanningStore.setState({ status: 'planning' });
    usePlanningStore.getState().handleSSEEvent({
      type: 'delivery_ready',
      data: { seq: 5 },
    });
    expect(usePlanningStore.getState().status).toBe('completed');
  });

  it('resync_required flags a full REST recovery (stale events must not be applied)', () => {
    usePlanningStore.setState({ resyncRequired: false });
    usePlanningStore.getState().handleSSEEvent({
      type: 'resync_required',
      data: { seq: 9 },
    });
    expect(usePlanningStore.getState().resyncRequired).toBe(true);
  });

  it('human_review marks the session paused and sets isPaused', () => {
    usePlanningStore.setState({ status: 'planning', isPaused: false });
    usePlanningStore.getState().handleSSEEvent({
      type: 'human_review_paused',
      data: { seq: 3 },
    });
    expect(usePlanningStore.getState().status).toBe('paused');
    expect(usePlanningStore.getState().isPaused).toBe(true);
  });

  it('does not re-arm the exact human checkpoint while its resume is in flight', () => {
    usePlanningStore.setState({ status: 'paused', isPaused: true });
    usePlanningStore.getState().setHumanReview({
      event_id: 'evt-1',
      paused_stage: 'layer1',
      items: [],
    });
    usePlanningStore.getState().beginHumanReviewResolution('evt-1');

    usePlanningStore.getState().handleSSEEvent({
      type: 'human_review_paused',
      data: {
        seq: 4,
        event_id: 'evt-1',
        paused_stage: 'layer1',
        items: [{ request_id: 'review-1', stage: 'layer1', request_type: 'layer_completion_review', context: {} }],
      },
    });

    expect(usePlanningStore.getState().humanReview).toBeNull();
    expect(usePlanningStore.getState().isPaused).toBe(false);
  });

  it('accepts a new human checkpoint after the previous one resolves', () => {
    usePlanningStore.setState({ status: 'planning', isPaused: false });
    usePlanningStore.getState().beginHumanReviewResolution('evt-1');

    usePlanningStore.getState().handleSSEEvent({
      type: 'human_review_paused',
      data: {
        seq: 5,
        event_id: 'evt-2',
        paused_stage: 'layer2',
        items: [{ request_id: 'review-2', stage: 'layer2', request_type: 'layer_completion_review', context: {} }],
      },
    });

    expect(usePlanningStore.getState().humanReview?.event_id).toBe('evt-2');
    expect(usePlanningStore.getState().pendingReviewLayer).toBe(2);
  });

  it('setDelivery stores the authoritative projection incl. statutory_complete', () => {
    usePlanningStore.getState().setDelivery({
      available: true,
      delivery_status: 'partial',
      statutory_complete: false,
      snapshot_checksum: 'sha256:abc',
      deferral_summary: { count: 3 },
      diagnostic_summary: {},
      deliverables: [],
      downloads: [],
    });
    const delivery = usePlanningStore.getState().delivery;
    expect(delivery).toMatchObject({
      available: true,
      delivery_status: 'partial',
      statutory_complete: false,
      snapshot_checksum: 'sha256:abc',
    });
  });

  it('keeps completed status and diagnostic delivery visible when no execution input exists', () => {
    usePlanningStore.setState({ status: 'planning', delivery: null });

    usePlanningStore.getState().syncBackendState({
      status: 'completed',
      phase: 'post_l3',
      active_stage: 'deliver',
      delivery_status: 'diagnostic_only',
      statutory_complete: false,
      completed_dimensions: { layer1: [], layer2: [], layer3: [] },
    });

    expect(usePlanningStore.getState().status).toBe('completed');
    expect(usePlanningStore.getState().delivery).toMatchObject({
      available: true,
      delivery_status: 'diagnostic_only',
      statutory_complete: false,
    });
  });

  it('deduplicates by seq across new v1 events', () => {
    usePlanningStore.setState({ lastProcessedSeq: 0 });
    usePlanningStore.getState().handleSSEEvent({
      type: 'delivery_ready',
      data: { seq: 5 },
    });
    expect(usePlanningStore.getState().lastProcessedSeq).toBe(5);

    // A stale/older seq must be dropped (not applied), leaving state untouched.
    usePlanningStore.getState().handleSSEEvent({
      type: 'resync_required',
      data: { seq: 4 },
    });
    expect(usePlanningStore.getState().resyncRequired).toBe(false);
    expect(usePlanningStore.getState().lastProcessedSeq).toBe(5);
  });
});
