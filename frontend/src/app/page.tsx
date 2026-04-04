'use client';

import { useState, useCallback } from 'react';
import { PlanningProvider, usePlanningContext } from '@/providers/PlanningProvider';
import UnifiedLayout from '@/components/layout/UnifiedLayout';
import UnifiedContentSwitcher from '@/components/layout/UnifiedContentSwitcher';
import LayerSidebar from '@/components/layer/LayerSidebar';
import FileViewerSidebar from '@/components/chat/FileViewerSidebar';

/**
 * HomePage - Entry Point
 *
 * Simplified architecture:
 * - PlanningProvider: Global state and logic (replaces 7 Context files)
 * - UnifiedLayout: Header + history panel
 * - UnifiedContentSwitcher: Smart container that renders Form or Chat
 *
 * Review functionality is now embedded in the chat flow via ReviewInteractionMessage,
 * controlled by Context state (isPaused, pendingReviewLayer).
 */

// Internal component to render FileViewerSidebar with Context access
function FileViewerWrapper() {
  const { state, actions } = usePlanningContext();

  return <FileViewerSidebar file={state.viewingFile} onClose={actions.hideFileViewer} />;
}

export default function HomePage() {
  const conversationId = `conv-${Date.now()}`;

  // Layer sidebar state
  const [layerSidebarOpen, setLayerSidebarOpen] = useState(false);
  const [activeLayer, setActiveLayer] = useState<number | null>(null);

  const handleLayerSidebarOpen = useCallback((layer: number) => {
    setActiveLayer(layer);
    setLayerSidebarOpen(true);
  }, []);

  const handleLayerSidebarClose = useCallback(() => {
    setLayerSidebarOpen(false);
    setActiveLayer(null);
  }, []);

  return (
    <PlanningProvider conversationId={conversationId}>
      <UnifiedLayout taskId="new" onOpenLayerSidebar={handleLayerSidebarOpen}>
        {/* Smart container - automatically shows Form or Chat based on context state */}
        <UnifiedContentSwitcher onOpenLayerSidebar={handleLayerSidebarOpen} />
      </UnifiedLayout>
      {/* Layer Sidebar */}
      {layerSidebarOpen && <LayerSidebar activeLayer={activeLayer} onClose={handleLayerSidebarClose} />}
      {/* File Viewer Sidebar */}
      <FileViewerWrapper />
    </PlanningProvider>
  );
}
