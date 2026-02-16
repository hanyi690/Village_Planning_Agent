'use client';

import { UnifiedPlanningProvider } from '@/contexts/UnifiedPlanningContext';
import UnifiedLayout from '@/components/layout/UnifiedLayout';
import UnifiedContentSwitcher from '@/components/layout/UnifiedContentSwitcher';

/**
 * HomePage - Entry Point
 *
 * Simplified architecture:
 * - UnifiedPlanningProvider: Global state and logic
 * - UnifiedLayout: Header + history panel
 * - UnifiedContentSwitcher: Smart container that renders Form or Chat
 *
 * Review functionality is now embedded in the chat flow via ReviewInteractionMessage,
 * controlled by Context state (isPaused, pendingReviewLayer).
 */
export default function HomePage() {
  const conversationId = `conv-${Date.now()}`;

  return (
    <UnifiedPlanningProvider conversationId={conversationId}>
      <UnifiedLayout taskId="new">
        {/* Smart container - automatically shows Form or Chat based on context state */}
        <UnifiedContentSwitcher />
      </UnifiedLayout>
    </UnifiedPlanningProvider>
  );
}
