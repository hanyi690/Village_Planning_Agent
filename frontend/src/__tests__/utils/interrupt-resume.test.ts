import { actionForHumanReview } from '@/features/planning/utils/interrupt-resume';

describe('actionForHumanReview', () => {
  it('retries transient provider failures', () => {
    expect(actionForHumanReview({
      pending_items: [{
        request_id: 'l3-provider-failure',
        stage: 'l3',
        request_type: 'transient_llm_failure',
      }],
    })).toBe('retry');
  });

  it('approves ordinary layer gates', () => {
    expect(actionForHumanReview({
      pending_items: [{
        request_id: 'l2-gate-review',
        stage: 'l2',
        request_type: 'gate_review',
      }],
    })).toBe('approve');
  });
});
