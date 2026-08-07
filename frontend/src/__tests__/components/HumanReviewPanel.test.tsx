import { describe, it, expect } from '@jest/globals';
import { render, screen } from '@testing-library/react';
import { HumanReviewPanel } from '../../features/planning/components/review/HumanReviewPanel';
import { usePlanningStore } from '../../features/planning/store/planningStore';

describe('HumanReviewPanel', () => {
  it('renders nothing when not paused for human review', () => {
    usePlanningStore.setState({ isPaused: false, humanReviewItems: [], pausedStage: null });
    const { container } = render(<HumanReviewPanel />);
    expect(container.firstChild).toBeNull();
  });

  it('renders items with approve/reject buttons', () => {
    usePlanningStore.setState({
      isPaused: true, pausedStage: 'execute', humanReviewItems: [
        { request_id: 'req-1', stage: 'execute', request_type: 'zone_review' },
      ], sessionId: 'sess-1', isResolvingReview: false, humanReviewError: null,
    });
    render(<HumanReviewPanel />);
    expect(screen.getByText(/zone_review/)).toBeDefined();
    expect(screen.getByTestId('approve-req-1')).toBeDefined();
    expect(screen.getByTestId('reject-req-1')).toBeDefined();
  });

  it('disables submit while resolving', () => {
    usePlanningStore.setState({
      isPaused: true, pausedStage: 'execute', isResolvingReview: true,
      humanReviewItems: [{ request_id: 'r1', stage: 'execute', request_type: 'zone_review' }],
      sessionId: 'sess-1', humanReviewError: null,
    });
    render(<HumanReviewPanel />);
    expect((screen.getByTestId('submit-review') as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows error message on resolve failure', () => {
    usePlanningStore.setState({
      isPaused: true, pausedStage: 'execute', isResolvingReview: false,
      humanReviewError: 'Failed to resolve review',
      humanReviewItems: [{ request_id: 'r1', stage: 'execute', request_type: 'zone_review' }],
      sessionId: 'sess-1',
    });
    render(<HumanReviewPanel />);
    expect(screen.getByText(/Failed to resolve review/)).toBeDefined();
  });
});