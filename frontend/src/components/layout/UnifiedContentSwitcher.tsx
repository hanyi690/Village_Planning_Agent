'use client';

import { useCallback, useMemo } from 'react';
import { usePlanningContext } from '@/providers/PlanningProvider';
import { VillageInputData } from '@/components/VillageInputForm';
import { createSystemMessage } from '@/lib/utils';
import ChatPanel from '@/components/chat/ChatPanel';
import VillageInputForm from '@/components/VillageInputForm';

/**
 * UnifiedContentSwitcher - Smart Container for View State
 *
 * This component:
 * 1. Consumes PlanningContext
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
  const { state, dispatch } = usePlanningContext();

  // Derive viewMode from state
  const viewMode = useMemo(() => {
    if (state.taskId && state.taskId !== 'new') return 'SESSION_ACTIVE';
    if (state.status !== 'idle') return 'SESSION_ACTIVE';
    return 'WELCOME_FORM';
  }, [state.taskId, state.status]);

  const handleFormSubmit = useCallback(
    async (data: VillageInputData) => {
      console.log('[UnifiedContentSwitcher] Form submitted:', data);

      // Save form data to state
      dispatch({ type: 'SET_VILLAGE_FORM_DATA', data });
      dispatch({ type: 'SET_PROJECT_NAME', projectName: data.projectName });

      // Add confirmation message
      dispatch({
        type: 'ADD_MESSAGE',
        message: createSystemMessage(
          `✅ Planning task set\n\nVillage: ${data.projectName}\nRequirement: ${data.taskDescription}`
        ),
      });

      // Set status to 'collecting' to trigger view mode change
      // This will switch to chat view WITHOUT starting planning
      dispatch({ type: 'SET_STATUS', status: 'collecting' });

      // ❌ Remove: await startPlanning(...)
      // ✅ Let user click "开始规划" button in chat interface instead
    },
    [dispatch]
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
