import { describe, it, expect } from '@jest/globals';
import type { HumanReviewItem, HumanReviewListResponse } from '../../features/planning/api/types';

describe('Human Review SSE Contract', () => {
  it('HumanReviewItem has required fields', () => {
    const item: HumanReviewItem = {
      request_id: 'r1',
      stage: 'execute',
      request_type: 'zone_review',
    };
    expect(item.request_id).toBeDefined();
    expect(item.stage).toBeDefined();
    expect(item.request_type).toBeDefined();
  });

  it('HumanReviewListResponse has required fields', () => {
    const resp: HumanReviewListResponse = {
      session_id: 's1',
      post_l3_status: 'paused',
      pending_items: [],
      count: 0,
    };
    expect(resp.session_id).toBeDefined();
    expect(resp.post_l3_status).toBeDefined();
    expect(resp.pending_items).toBeDefined();
    expect(resp.count).toBeDefined();
  });
});