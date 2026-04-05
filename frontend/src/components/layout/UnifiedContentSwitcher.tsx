'use client';

import { useCallback, useMemo } from 'react';
import { usePlanningStore } from '@/stores';
import { VillageInputData } from '@/components/VillageInputForm';
import { createSystemMessage } from '@/lib/utils';
import ChatPanel from '@/components/chat/ChatPanel';
import VillageInputForm from '@/components/VillageInputForm';

/**
 * UnifiedContentSwitcher - Smart Container for View State
 *
 * This component:
 * 1. Consumes Zustand store
 * 2. Determines current view mode from state
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
  const taskId = usePlanningStore((state) => state.taskId);
  const status = usePlanningStore((state) => state.status);
  const setVillageFormData = usePlanningStore((state) => state.setVillageFormData);
  const setProjectName = usePlanningStore((state) => state.setProjectName);
  const addMessage = usePlanningStore((state) => state.addMessage);
  const setStatus = usePlanningStore((state) => state.setStatus);

  // Derive viewMode from state
  const viewMode = useMemo(() => {
    if (taskId && taskId !== 'new') return 'SESSION_ACTIVE';
    if (status !== 'idle') return 'SESSION_ACTIVE';
    return 'WELCOME_FORM';
  }, [taskId, status]);

  const handleFormSubmit = useCallback(
    async (data: VillageInputData) => {
      console.log('[UnifiedContentSwitcher] Form submitted:', data);

      // Save form data to state
      setVillageFormData(data);
      setProjectName(data.projectName);

      // Add confirmation message
      addMessage(
        createSystemMessage(
          `✅ Planning task set\n\nVillage: ${data.projectName}\nRequirement: ${data.taskDescription}`
        )
      );

      // Set status to 'collecting' to trigger view mode change
      // This will switch to chat view WITHOUT starting planning
      setStatus('collecting');

      // ❌ Remove: await startPlanning(...)
      // ✅ Let user click "开始规划" button in chat interface instead
    },
    [setVillageFormData, setProjectName, addMessage, setStatus]
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