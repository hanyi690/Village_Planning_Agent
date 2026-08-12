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