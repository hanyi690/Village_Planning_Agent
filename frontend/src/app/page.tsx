'use client';

import { useState, useCallback, Suspense } from 'react';
import {
  PlanningProvider,
  usePlanningStore,
  usePlanningActions,
  useTaskId,
} from '@/features/planning';
import Dashboard from '@/features/planning/components/Dashboard';
import FileViewerSidebar from '@/features/planning/components/chat/FileViewerSidebar';
import LayerSidebar from '@/components/layer/LayerSidebar';

/**
 * HomePage - Entry Point
 *
 * Simplified architecture:
 * - PlanningProvider: Global state via Zustand + Immer
 * - Dashboard: New Demo System layout (Brutalist/Raw style)
 *
 * URL taskId tracking:
 * - If taskId in URL, automatically restore session state
 * - When planning starts, update URL with taskId
 * - Refresh preserves session via URL parameter
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
    <>
      {/* New layout - Dashboard */}
      <Dashboard onOpenLayerSidebar={handleLayerSidebarOpen} />

      {/* Layer Sidebar */}
      {layerSidebarOpen && <LayerSidebar activeLayer={activeLayer} onClose={handleLayerSidebarClose} />}

      {/* File Viewer Sidebar */}
      <FileViewerWrapper />
    </>
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