'use client';

/**
 * UnifiedLayout - 简化布局
 *
 * 所有屏幕尺寸:
 * - 单一主内容区: flex-1
 * - Header (60px)
 * - History panel: 右侧抽屉模态框
 */

import React, { useState, memo, useCallback, ReactElement, Children } from 'react';
import { useRouter } from 'next/navigation';
import Header from './Header';
import HistoryPanel from './HistoryPanel';
import KnowledgePanel from './KnowledgePanel';
import { usePlanningActions } from '@/stores';

interface UnifiedLayoutProps {
  taskId: string;
  children: React.ReactNode;
  onOpenLayerSidebar?: (layer: number) => void;
}

function UnifiedLayoutComponent({ taskId, children, onOpenLayerSidebar }: UnifiedLayoutProps) {
  const router = useRouter();
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [knowledgeModalOpen, setKnowledgeModalOpen] = useState(false);
  const actions = usePlanningActions();

  const handleToggleHistory = useCallback(() => {
    setHistoryModalOpen((prev) => !prev);
  }, []);

  const handleOpenKnowledge = useCallback(() => {
    setKnowledgeModalOpen(true);
  }, []);

  const handleNewTask = useCallback(() => {
    // Clear current session state
    actions.resetConversation();
    // Navigate to root to create new task
    router.push('/');
  }, [actions, router]);

  return (
    <div className="h-screen overflow-hidden bg-[#F9FBF9]">
      {/* Header - fixed at top */}
      <Header
        taskId={taskId}
        onToggleHistory={handleToggleHistory}
        onNewTask={handleNewTask}
        onOpenKnowledge={handleOpenKnowledge}
      />

      {/* Main content - centered with max-width */}
      <main className="mx-auto w-full max-w-[1400px] px-4 pt-14 pb-4 h-full">
        {/* Clone children with onOpenLayerSidebar prop */}
        {Children.map(children, (child) => {
          if (React.isValidElement(child)) {
            // 只在 children 没有 onOpenLayerSidebar 时才注入
            const existingProps = child.props as { onOpenLayerSidebar?: (layer: number) => void };
            if (!existingProps.onOpenLayerSidebar && onOpenLayerSidebar) {
              return React.cloneElement(child as ReactElement<{ onOpenLayerSidebar?: (layer: number) => void }>, {
                onOpenLayerSidebar,
              });
            }
          }
          return child;
        })}
      </main>

      {/* History Panel Modal */}
      {historyModalOpen && <HistoryPanel onClose={() => setHistoryModalOpen(false)} />}

      {/* Knowledge Panel Modal */}
      {knowledgeModalOpen && <KnowledgePanel onClose={() => setKnowledgeModalOpen(false)} />}
    </div>
  );
}

const UnifiedLayout = memo(UnifiedLayoutComponent);

export default UnifiedLayout;