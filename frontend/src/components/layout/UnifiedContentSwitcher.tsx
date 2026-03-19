'use client';

import { useCallback } from 'react';
import { useUnifiedPlanningContext } from '@/contexts/UnifiedPlanningContext';
import { VillageInputData } from '@/components/VillageInputForm';
import { createSystemMessage } from '@/lib/utils';
import ChatPanel from '@/components/chat/ChatPanel';
import VillageInputForm from '@/components/VillageInputForm';

/**
 * UnifiedContentSwitcher - Smart Container for View State
 *
 * This component:
 * 1. Consumes UnifiedPlanningContext
 * 2. Determines current view mode from context state
 * 3. Renders the appropriate component
 * 4. Eliminates need for local view state management
 *
 * Benefits:
 * - Single source of truth for view state
 * - No manual useEffect sync needed
 * - Easy to add new views
 * - Consistent view transitions
 */
interface UnifiedContentSwitcherProps {
  onOpenLayerSidebar?: (layer: number) => void;
}

export default function UnifiedContentSwitcher({ onOpenLayerSidebar }: UnifiedContentSwitcherProps) {
  const { viewMode, setVillageFormData, setStatus, setProjectName, addMessage } =
    useUnifiedPlanningContext();

  const handleFormSubmit = useCallback(
    async (data: VillageInputData) => {
      console.log('[UnifiedContentSwitcher] Form submitted:', data);

      // Save form data to context
      setVillageFormData(data);
      setProjectName(data.projectName);

      // Add confirmation message
      addMessage(
        createSystemMessage(
          `✅ 已设置规划任务\n\n村庄：${data.projectName}\n需求：${data.taskDescription}`
        )
      );

      // Set status to 'collecting' to trigger view mode change
      // This will switch to chat view WITHOUT starting planning
      setStatus('collecting');

      // ❌ Remove: await startPlanning(...)
      // ✅ Let user click "开始规划" button in chat interface instead
    },
    [setVillageFormData, setStatus, setProjectName, addMessage]
  );

  return (
    <div className="w-full">
      {viewMode === 'SESSION_ACTIVE' ? (
        <div className="w-full h-[calc(100vh-80px)] overflow-hidden">
          <ChatPanel onOpenLayerSidebar={onOpenLayerSidebar} />
          {/* Viewer sidebar will be rendered by ChatPanel when needed */}
        </div>
      ) : (
        <div className="container mx-auto max-w-4xl py-10">
          <VillageInputForm onSubmit={handleFormSubmit} />
        </div>
      )}
    </div>
  );
}
