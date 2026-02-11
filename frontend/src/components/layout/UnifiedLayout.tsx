'use client';

/**
 * UnifiedLayout - 简化布局
 *
 * 所有屏幕尺寸:
 * - 单一主内容区: flex-1
 * - Header (60px)
 * - History panel: 右侧抽屉模态框
 */

import { useState, memo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Header from './Header';
import HistoryPanel from './HistoryPanel';
import { useUnifiedPlanningContext } from '@/contexts/UnifiedPlanningContext';

interface UnifiedLayoutProps {
  taskId: string;
  children: React.ReactNode;
}

function UnifiedLayoutComponent({ taskId, children }: UnifiedLayoutProps) {
  const router = useRouter();
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const { resetConversation } = useUnifiedPlanningContext();

  const handleToggleHistory = useCallback(() => {
    setHistoryModalOpen(prev => !prev);
  }, []);

  const handleNewTask = useCallback(() => {
    // 清除当前会话状态
    resetConversation();
    // 导航到根路由创建新任务
    router.push('/');
  }, [resetConversation, router]);

  return (
    <div className="flex h-screen bg-gray-50">
      <main className="flex-1 overflow-hidden flex flex-col">
        <Header
          taskId={taskId}
          onToggleHistory={handleToggleHistory}
          onNewTask={handleNewTask}
        />
        {children}
      </main>

      {/* History Panel Modal */}
      {historyModalOpen && (
        <HistoryPanel onClose={() => setHistoryModalOpen(false)} />
      )}
    </div>
  );
}

const UnifiedLayout = memo(UnifiedLayoutComponent);

export default UnifiedLayout;
