import { useState } from 'react';
import { usePlanningStore } from '../../store/planningStore';
import type { HumanReviewItem } from '../../api/types';

export function HumanReviewPanel() {
  const isPaused = usePlanningStore((s) => s.isPaused);
  const pausedStage = usePlanningStore((s) => s.pausedStage);
  const items = usePlanningStore((s) => s.humanReviewItems);
  const sessionId = usePlanningStore((s) => s.sessionId);
  const isResolving = usePlanningStore((s) => s.isResolvingReview);
  const error = usePlanningStore((s) => s.humanReviewError);
  const resolveHumanReview = usePlanningStore((s) => s.resolveHumanReview);

  const [decisions, setDecisions] = useState<Record<string, { action: string }>>({});

  if (!isPaused || !pausedStage || items.length === 0) {
    return null;
  }

  const handleDecision = (requestId: string, action: string) => {
    setDecisions((prev) => ({ ...prev, [requestId]: { action } }));
  };

  const handleSubmit = () => {
    if (sessionId && !isResolving) {
      resolveHumanReview(sessionId, decisions);
    }
  };

  return (
    <div className="human-review-panel">
      <h3>Post-L3 Human Review ({pausedStage})</h3>
      <p>{items.length} item(s) pending review</p>
      {error && <div className="review-error">{error}</div>}
      <ul>
        {items.map((item: HumanReviewItem) => (
          <li key={item.request_id}>
            <span>{item.request_type}</span>
            <button
              data-testid={`approve-${item.request_id}`}
              onClick={() => handleDecision(item.request_id, 'approve')}
              disabled={isResolving}
            >Approve</button>
            <button
              data-testid={`reject-${item.request_id}`}
              onClick={() => handleDecision(item.request_id, 'reject')}
              disabled={isResolving}
            >Reject</button>
          </li>
        ))}
      </ul>
      <button
        data-testid="submit-review"
        onClick={handleSubmit}
        disabled={isResolving || Object.keys(decisions).length === 0}
      >
        {isResolving ? 'Resolving...' : 'Submit Review'}
      </button>
    </div>
  );
}