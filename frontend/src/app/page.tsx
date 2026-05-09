'use client';

import { Suspense } from 'react';
import {
  PlanningProvider,
  usePlanningStore,
  usePlanningActions,
} from '@/features/planning';
import Dashboard from '@/features/planning/components/Dashboard';
import FileViewerSidebar from '@/features/planning/components/chat/FileViewerSidebar';

/**
 * HomePage - Entry Point
 *
 * Three-panel workbench layout:
 * AppHeader + LayerNav + FocusArea + ContextPanel + BottomActionBar
 *
 * URL sessionId tracking: restored via useSessionRestore in PlanningProvider.
 */

function FileViewerWrapper() {
  const viewingFile = usePlanningStore((state) => state.viewingFile);
  const actions = usePlanningActions();

  return <FileViewerSidebar file={viewingFile} onClose={actions.hideFileViewer} />;
}

function MainContent() {
  return (
    <>
      <Dashboard />
      <FileViewerWrapper />
    </>
  );
}

export default function HomePage() {
  const conversationId = 'default-session';

  return (
    <PlanningProvider conversationId={conversationId}>
      <Suspense fallback={<div className="flex items-center justify-center h-screen">Loading...</div>}>
        <MainContent />
      </Suspense>
    </PlanningProvider>
  );
}
