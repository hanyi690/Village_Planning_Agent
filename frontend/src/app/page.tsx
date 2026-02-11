'use client';

import { useState, useCallback } from 'react';
import { UnifiedPlanningProvider } from '@/contexts/UnifiedPlanningContext';
import UnifiedLayout from '@/components/layout/UnifiedLayout';
import UnifiedContentSwitcher from '@/components/layout/UnifiedContentSwitcher';
import ReviewPanel from '@/components/review/ReviewPanel';

/**
 * HomePage - Entry Point
 *
 * Simplified architecture:
 * - UnifiedPlanningProvider: Global state and logic
 * - UnifiedLayout: Header + history panel
 * - UnifiedContentSwitcher: Smart container that renders Form or Chat
 * - ReviewPanel: Overlay for review workflow
 */
export default function HomePage() {
  const [showReviewPanel, setShowReviewPanel] = useState(false);
  const conversationId = `conv-${Date.now()}`;

  const handleCloseReviewPanel = useCallback(() => {
    setShowReviewPanel(false);
  }, []);

  const handleReviewApprove = useCallback(async () => {
    setShowReviewPanel(false);
  }, []);

  const handleReviewReject = useCallback(async (_feedback: string, _dimensions?: string[]) => {
    setShowReviewPanel(false);
  }, []);

  const handleRollback = useCallback(async (_checkpointId: string) => {
    setShowReviewPanel(false);
  }, []);

  return (
    <UnifiedPlanningProvider conversationId={conversationId}>
      <UnifiedLayout taskId="new">
        {/* Smart container - automatically shows Form or Chat based on context state */}
        <UnifiedContentSwitcher />

        {/* Review panel overlay - independent of view mode */}
        <ReviewPanel
          isOpen={showReviewPanel}
          onClose={handleCloseReviewPanel}
          onApprove={handleReviewApprove}
          onReject={handleReviewReject}
          onRollback={handleRollback}
        />
      </UnifiedLayout>
    </UnifiedPlanningProvider>
  );
}
