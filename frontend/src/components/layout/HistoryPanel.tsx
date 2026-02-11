'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
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
    return villages.filter(v => 
      v.display_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      v.name.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [villages, searchTerm]);

  if (!mounted) return null;

  return createPortal(
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, display: 'flex', justifyContent: 'flex-end' }}>
      {/* 遮罩 */}
      <div 
        style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)' }}
        onClick={onClose}
      />
      
      {/* 面板 */}
      <div style={{ 
        position: 'relative', width: '100%', maxWidth: '400px', backgroundColor: 'white', 
        height: '100%', display: 'flex', flexDirection: 'column', boxShadow: '-4px 0 15px rgba(0,0,0,0.1)' 
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
          {historyLoading && villages.length === 0 ? (
            <div style={{ textAlign: 'center', marginTop: '40px', color: '#666' }}>
              <FontAwesomeIcon icon={faSpinner} spin size="2x" style={{ color: '#16a34a', marginBottom: '10px' }} />
              <p>加载中...</p>
            </div>
          ) : filteredVillages.length > 0 ? (
            filteredVillages.map(village => (
              <div key={village.name} style={{ marginBottom: '15px', border: '1px solid #f0f0f0', borderRadius: '8px', overflow: 'hidden' }}>
                <div style={{ padding: '10px', backgroundColor: '#fafafa', fontWeight: 'bold', borderBottom: '1px solid #f0f0f0' }}>
                  {village.display_name}
                </div>
                <div style={{ padding: '5px' }}>
                  {village.sessions.map(session => (
                    <div 
                      key={session.session_id}
                      onClick={() => {
                        loadHistoricalSession(village.name, session.session_id); // 修复点：直接使用 village.name
                        onClose();
                      }}
                      style={{ 
                        padding: '8px 10px', cursor: 'pointer', borderRadius: '4px', fontSize: '0.9rem',
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between'
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f0fdf4'}
                      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                    >
                      <span><FontAwesomeIcon icon={faClock} style={{ marginRight: '8px', color: '#999' }} /> {session.timestamp}</span>
                      <FontAwesomeIcon icon={faChevronRight} size="xs" style={{ color: '#ccc' }} />
                    </div>
                  ))}
                </div>
              </div>
            ))
          ) : (
            <div style={{ textAlign: 'center', marginTop: '100px', color: '#ccc' }}>
              <FontAwesomeIcon icon={faInbox} size="3x" style={{ marginBottom: '10px' }} />
              <p>暂无数据</p>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}