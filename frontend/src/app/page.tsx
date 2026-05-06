'use client';

import { useState, useCallback, Suspense } from 'react';
import { PlanningProvider, usePlanningStore, usePlanningActions } from '@/stores';
import { useTaskId } from '@/hooks/planning/usePlanningSelectors';
import UnifiedLayout from '@/components/layout/UnifiedLayout';
import UnifiedContentSwitcher from '@/components/layout/UnifiedContentSwitcher';
import LayerSidebar from '@/components/layer/LayerSidebar';
import FileViewerSidebar from '@/components/chat/FileViewerSidebar';

/**
 * HomePage - Entry Point
 *
 * Simplified architecture:
 * - PlanningProvider: Global state via Zustand + Immer
 * - UnifiedLayout: Header + history panel
 * - UnifiedContentSwitcher: Smart container that renders Form or Chat
 *
 * URL taskId tracking:
 * - If taskId in URL, automatically restore session state
 * - When planning starts, update URL with taskId
 * - Refresh preserves session via URL parameter
 *
 * Review functionality is now embedded in the chat flow via ReviewInteractionMessage,
 * controlled by state (isPaused, pendingReviewLayer).
 */

// Internal component to render FileViewerSidebar with store access
function FileViewerWrapper() {
  const viewingFile = usePlanningStore((state) => state.viewingFile);
  const actions = usePlanningActions();

  return <FileViewerSidebar file={viewingFile} onClose={actions.hideFileViewer} />;
}

// Main content component - uses Suspense for useSearchParams (in PlanningProvider)
function MainContent() {
  // Get taskId from store (useSessionRestore in PlanningProvider handles URL extraction)
  const storeTaskId = useTaskId();
  const taskId = storeTaskId || 'new';

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
    <UnifiedLayout taskId={taskId} onOpenLayerSidebar={handleLayerSidebarOpen}>
      {/* Smart container - automatically shows Form or Chat based on state */}
      <UnifiedContentSwitcher onOpenLayerSidebar={handleLayerSidebarOpen} />
      {/* Layer Sidebar */}
      {layerSidebarOpen && <LayerSidebar activeLayer={activeLayer} onClose={handleLayerSidebarClose} />}
      {/* File Viewer Sidebar */}
      <FileViewerWrapper />
    </UnifiedLayout>
  );
}

export default function HomePage() {
  // Generate conversationId only once per session
  // This is now stable - refresh will use taskId from URL instead
  const conversationId = 'default-session';

  return (
    <PlanningProvider conversationId={conversationId}>
      <Suspense fallback={<div className="flex items-center justify-center h-screen">Loading...</div>}>
        <MainContent />
      </Suspense>
    </PlanningProvider>
  );
}