'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useConversationContext } from '@/contexts/ConversationContext';
import { convertSSEToMessage } from '@/types/message';
import { taskApi } from '@/lib/api';
import ChatInterface from './ChatInterface';
import ViewerSidePanel from './ViewerSidePanel';

interface ConversationManagerProps {
  conversationId: string;
}

// Layer to section mapping for synchronization
const LAYER_SECTIONS: Record<string, string[]> = {
  'layer_1_analysis': ['区位分析', '社会经济', '自然环境', '土地利用', '道路交通', '公共服务', '基础设施', '生态系统', '建筑', '区域文化', '政策法规', '上位规划与策略'],
  'layer_2_concept': ['资源初测', '规划定位', '发展目标', '规划策略'],
  'layer_3_detailed': ['产业规划', '人居环境', '综合交通', '公共服务设施', '基础设施', '生态保护', '文化保护', '实施建议', '项目库'],
};

export default function ConversationManager({ conversationId }: ConversationManagerProps) {
  const {
    taskId,
    status,
    addMessage,
    setTaskId,
    setStatus,
    viewerVisible,
    projectName,
    showViewer,
    toggleViewer,
    referencedSection,
  } = useConversationContext();

  const [activeTab, setActiveTab] = useState<string>('layer_1_analysis');
  const [session, setSession] = useState<string | undefined>();

  // Auto-switch viewer tab based on current layer
  useEffect(() => {
    if (referencedSection) {
      const targetLayer = Object.entries(LAYER_SECTIONS).find(([_, sections]) =>
        sections.some(s => referencedSection.includes(s))
      )?.[0] || 'layer_1_analysis';

      if (targetLayer !== activeTab) {
        setActiveTab(targetLayer);
      }
    }
  }, [referencedSection, activeTab]);

  // SSE event handler
  const handleSSEMessage = useCallback((data: any) => {
    console.log('[ConversationManager] SSE event:', data);

    const message = convertSSEToMessage(data);
    addMessage(message);

    if (data.status) {
      setStatus(data.status as any);
    }

    if (data.result?.session_id) {
      setSession(data.result.session_id);
    }

    // Auto-switch viewer tab based on current layer
    if (data.current_layer) {
      const layerId = data.current_layer.replace('layer_', 'layer_');
      setActiveTab(layerId);
    }

    // Auto-show viewer on pause
    if (data.status === 'paused' || data.event_type === 'pause') {
      showViewer();
    }
  }, [addMessage, setStatus, showViewer]);

  // Listen for task updates via SSE
  useEffect(() => {
    if (!taskId) return;

    console.log('[ConversationManager] Setting up SSE for task:', taskId);

    const es = taskApi.createTaskStream(
      taskId,
      (event) => {
        // New event format: { type, task_id, data: { status, progress, ... } }
        const data = event.data;
        handleSSEMessage(data);
      },
      (error) => {
        console.error('[ConversationManager] SSE error:', error);
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'system',
          type: 'error',
          content: '连接错误: 无法接收任务更新',
          error: error.message,
        });
      }
    );

    return () => {
      console.log('[ConversationManager] Closing SSE connection');
      es.close();
    };
  }, [taskId, handleSSEMessage, addMessage]);

  const handleTabChange = useCallback((tab: string) => {
    setActiveTab(tab);
    console.log('[ConversationManager] Tab changed to:', tab);
  }, []);

  const handleViewerToggle = useCallback(() => {
    toggleViewer();
  }, [toggleViewer]);

  // Memoized header badge
  const statusBadge = useMemo(() => {
    const colorMap = {
      idle: 'secondary',
      planning: 'primary',
      completed: 'success',
    } as const;

    return `bg-${status in colorMap ? colorMap[status as keyof typeof colorMap] : 'warning'}`;
  }, [status]);

  return (
    <div className="conversation-layout" style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Chat Panel */}
      <div
        className="chat-panel"
        style={{
          flex: viewerVisible ? '0 0 60%' : '1',
          display: 'flex',
          flexDirection: 'column',
          minWidth: viewerVisible ? '60%' : '100%',
          transition: 'flex 0.3s ease',
        }}
      >
        {/* Header */}
        <div
          className="chat-header"
          style={{
            padding: '1rem',
            borderBottom: '1px solid #dee2e6',
            backgroundColor: 'white',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <h5 className="mb-0">
              <i className="fas fa-comments me-2" style={{ color: 'var(--primary-green)' }}></i>
              村庄规划助手
            </h5>
            {projectName && (
              <small className="text-muted">项目: {projectName}</small>
            )}
          </div>
          <div>
            {taskId && (
              <span className="badge bg-info me-2">任务: {taskId.slice(0, 8)}...</span>
            )}
            <span className={`badge ${statusBadge}`}>状态: {status}</span>
          </div>
        </div>

        {/* Chat Interface */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <ChatInterface
            conversationId={conversationId}
            onTaskStart={(newTaskId) => setTaskId(newTaskId)}
            onViewerToggle={handleViewerToggle}
          />
        </div>
      </div>

      {/* Viewer Side Panel */}
      {viewerVisible && (
        <div
          className="viewer-side-panel"
          style={{
            flex: '0 0 40%',
            borderLeft: '1px solid #dee2e6',
            backgroundColor: 'white',
            display: 'flex',
            flexDirection: 'column',
            transition: 'flex 0.3s ease',
            animation: 'slideInLeft 0.3s ease',
          }}
        >
          <ViewerSidePanel
            villageName={projectName || ''}
            session={session}
            visible={viewerVisible}
            activeTab={activeTab}
            onTabChange={handleTabChange}
            referencedSection={referencedSection}
            taskId={taskId}
          />
        </div>
      )}

      {/* Floating Toggle Button */}
      {!viewerVisible && projectName && (
        <button
          className="btn btn-primary"
          onClick={showViewer}
          style={{
            position: 'fixed',
            right: '1rem',
            bottom: '1rem',
            borderRadius: '50%',
            width: '3.5rem',
            height: '3.5rem',
            padding: '0',
            zIndex: 1000,
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            transition: 'transform 0.2s ease',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.1)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
          title="显示查看器"
        >
          <i className="fas fa-columns"></i>
        </button>
      )}

      {/* Animation Styles */}
      <style jsx global>{`
        @keyframes slideInLeft {
          from {
            transform: translateX(100%);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }

        .viewer-side-panel {
          animation: slideInLeft 0.3s ease;
        }
      `}</style>
    </div>
  );
}
