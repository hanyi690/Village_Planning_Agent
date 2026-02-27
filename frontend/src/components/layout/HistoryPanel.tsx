'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useRouter } from 'next/navigation';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faTimes, faHistory, faSearch, faSpinner, faInbox, faChevronRight, faClock } from '@fortawesome/free-solid-svg-icons';
import { useUnifiedPlanningContext } from '@/contexts/UnifiedPlanningContext';

export default function HistoryPanel({ onClose }: { onClose: () => void }) {
  const {
    villages,
    historyLoading,
    loadVillagesHistory,
    loadHistoricalSession,
    taskId
  } = useUnifiedPlanningContext();

  const [mounted, setMounted] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    setMounted(true);
    document.body.style.overflow = 'hidden';
    
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      loadVillagesHistory();
    }

    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [loadVillagesHistory]);

  const filteredVillages = useMemo(() => {
    console.log('[HistoryPanel] villages:', villages);
    console.log('[HistoryPanel] searchTerm:', searchTerm);
    const result = villages.filter(v => 
      v.display_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      v.name.toLowerCase().includes(searchTerm.toLowerCase())
    );
    console.log('[HistoryPanel] filteredVillages count:', result.length);
    return result;
  }, [villages, searchTerm]);

  // 详细渲染日志
  console.log('[HistoryPanel] RENDER - mounted:', mounted);
  console.log('[HistoryPanel] RENDER - historyLoading:', historyLoading);
  console.log('[HistoryPanel] RENDER - villages.length:', villages.length);
  console.log('[HistoryPanel] RENDER - filteredVillages.length:', filteredVillages.length);
  console.log('[HistoryPanel] RENDER - Condition 1 (loading):', historyLoading && villages.length === 0);
  console.log('[HistoryPanel] RENDER - Condition 2 (hasData):', filteredVillages.length > 0);
  console.log('[HistoryPanel] RENDER - document.body exists:', !!document.body);

  if (!mounted) {
    console.log('[HistoryPanel] NOT MOUNTED, returning null');
    return null;
  }

  console.log('[HistoryPanel] CALLING createPortal');
  return createPortal(
    <>
      {/* Overlay */}
      <div
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          backdropFilter: 'blur(4px)',
          zIndex: 9998,
          visibility: 'visible',
          opacity: 1
        }}
        onClick={onClose}
      />

      {/* Panel - 使用纯内联样式 */}
      <div style={{
        position: 'fixed',
        right: 0,
        top: 0,
        bottom: 0,
        width: '400px',
        maxWidth: '400px',
        backgroundColor: 'white',
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 9999,
        visibility: 'visible',
        opacity: 1,
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{ padding: '1rem', backgroundColor: '#16a34a', color: 'var(--text-cream-primary)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 'bold' }}>
            <FontAwesomeIcon icon={faHistory} style={{ marginRight: '8px' }} /> 历史记录
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-cream-primary)', cursor: 'pointer', fontSize: '1.2rem' }}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        {/* Search */}
        <div style={{ padding: '1rem', borderBottom: '1px solid #eee' }}>
          <input 
            type="text"
            placeholder="搜索村庄..."
            style={{ width: '100%', padding: '8px 12px', borderRadius: '6px', border: '1px solid #ddd', outline: 'none' }}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}>
          {(() => {
            console.log('[HistoryPanel] LIST RENDER - historyLoading:', historyLoading, 'villages.length:', villages.length);
            console.log('[HistoryPanel] LIST RENDER - filteredVillages.length:', filteredVillages.length);
            if (historyLoading && villages.length === 0) {
              console.log('[HistoryPanel] LIST RENDER - Showing LOADING');
              return (
                <div style={{ textAlign: 'center', marginTop: '40px', color: '#666' }}>
                  <FontAwesomeIcon icon={faSpinner} spin size="2x" style={{ color: '#16a34a', marginBottom: '10px' }} />
                  <p>加载中...</p>
                </div>
              );
            } else if (filteredVillages.length > 0) {
              console.log('[HistoryPanel] LIST RENDER - Showing VILLAGES LIST');
              return filteredVillages.map(village => {
                console.log('[HistoryPanel] LIST RENDER - Village:', village.display_name, 'sessions:', village.sessions?.length);
                return (
                  <div key={village.name} style={{ marginBottom: '15px', border: '2px solid #16a34a', borderRadius: '8px', overflow: 'hidden' }}>
                    <div style={{ padding: '10px', backgroundColor: '#fafafa', fontWeight: 'bold', borderBottom: '1px solid #f0f0f0', color: '#111827' }}>
                      {village.display_name} ({village.sessions?.length || 0} 条记录)
                    </div>
                    <div style={{ padding: '5px' }}>
                      {village.sessions && village.sessions.length > 0 ? village.sessions.map(session => (
                        <div 
                          key={session.session_id}
                          onClick={() => {
                            loadHistoricalSession(village.name, session.session_id);
                            onClose();
                          }}
                          style={{ 
                            padding: '8px 10px', cursor: 'pointer', borderRadius: '4px', fontSize: '0.9rem',
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            backgroundColor: '#fff', color: '#374151'
                          }}
                          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f0fdf4'}
                          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#fff'}
                        >
                          <span><FontAwesomeIcon icon={faClock} style={{ marginRight: '8px', color: '#999' }} /> {new Date(session.timestamp).toLocaleString('zh-CN')}</span>
                          <FontAwesomeIcon icon={faChevronRight} size="xs" style={{ color: '#ccc' }} />
                        </div>
                      )) : (
                        <div style={{ padding: '10px', color: '#999', textAlign: 'center' }}>无会话记录</div>
                      )}
                    </div>
                  </div>
                );
              });
            } else {
              console.log('[HistoryPanel] LIST RENDER - Showing EMPTY STATE');
              return (
                <div style={{ textAlign: 'center', marginTop: '100px', color: '#ccc' }}>
                  <FontAwesomeIcon icon={faInbox} size="3x" style={{ marginBottom: '10px' }} />
                  <p>暂无数据</p>
                </div>
              );
            }
          })()}
        </div>
      </div>
    </>,
    document.body
  );
}