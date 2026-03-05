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
    return villages.filter(v => 
      v.display_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      v.name.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [villages, searchTerm]);

  if (!mounted) return null;

  return createPortal(
    <>
      {/* Overlay - Gemini style */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[9998] animate-fade-in"
        onClick={onClose}
      />

      {/* Panel - Gemini dark style */}
      <div className="fixed right-0 top-0 bottom-0 w-[400px] max-w-[400px] bg-[#1a1a1a] border-l border-[#2d2d2d] flex flex-col z-[9999] animate-slide-in-right">
        
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#2d2d2d]">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-green-500/20 to-green-600/10 border border-green-500/30">
              <FontAwesomeIcon icon={faHistory} className="text-green-400" style={{ width: '14px', height: '14px' }} />
            </div>
            <h2 className="text-lg font-semibold text-white">历史记录</h2>
          </div>
          <button 
            onClick={onClose} 
            className="p-2 rounded-lg text-zinc-400 hover:text-white hover:bg-[#2d2d2d] transition-colors"
          >
            <FontAwesomeIcon icon={faTimes} style={{ width: '16px', height: '16px' }} />
          </button>
        </div>

        {/* Search */}
        <div className="px-4 py-3 border-b border-[#2d2d2d]">
          <div className="relative">
            <FontAwesomeIcon 
              icon={faSearch} 
              className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
              style={{ width: '14px', height: '14px' }}
            />
            <input 
              type="text"
              placeholder="搜索村庄..."
              className="w-full bg-[#242424] border border-[#3f3f46] rounded-xl py-2.5 pl-10 pr-4 text-white placeholder-zinc-500 focus:outline-none focus:border-green-500/50 focus:ring-1 focus:ring-green-500/20 transition-all"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-4">
          {historyLoading && villages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-zinc-400">
              <div className="w-10 h-10 border-2 border-green-500/30 border-t-green-500 rounded-full animate-spin mb-4" />
              <p className="text-sm">加载中...</p>
            </div>
          ) : filteredVillages.length > 0 ? (
            <div className="space-y-3">
              {filteredVillages.map(village => (
                <div 
                  key={village.name} 
                  className="bg-[#1e1e1e] border border-[#2d2d2d] rounded-xl overflow-hidden hover:border-green-500/30 transition-colors"
                >
                  {/* Village header */}
                  <div className="px-4 py-3 bg-[#242424] border-b border-[#2d2d2d] flex items-center justify-between">
                    <span className="font-medium text-white">{village.display_name}</span>
                    <span className="text-xs text-zinc-500 bg-[#1a1a1a] px-2 py-1 rounded-full">
                      {village.sessions?.length || 0} 条记录
                    </span>
                  </div>
                  
                  {/* Sessions list */}
                  <div className="p-2">
                    {village.sessions && village.sessions.length > 0 ? (
                      village.sessions.map(session => (
                        <button
                          key={session.session_id}
                          onClick={() => {
                            loadHistoricalSession(village.name, session.session_id);
                            onClose();
                          }}
                          className="w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-left text-zinc-300 hover:bg-[#2d2d2d] hover:text-white transition-colors group"
                        >
                          <div className="flex items-center gap-2">
                            <FontAwesomeIcon 
                              icon={faClock} 
                              className="text-zinc-500 group-hover:text-green-400 transition-colors"
                              style={{ width: '12px', height: '12px' }}
                            />
                            <span className="text-sm">
                              {new Date(session.timestamp).toLocaleString('zh-CN')}
                            </span>
                          </div>
                          <FontAwesomeIcon 
                            icon={faChevronRight} 
                            className="text-zinc-600 group-hover:text-green-400 transition-colors"
                            style={{ width: '10px', height: '10px' }}
                          />
                        </button>
                      ))
                    ) : (
                      <div className="py-4 text-center text-zinc-500 text-sm">
                        无会话记录
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
              <FontAwesomeIcon icon={faInbox} className="text-4xl mb-4" />
              <p>暂无数据</p>
            </div>
          )}
        </div>
      </div>
    </>,
    document.body
  );
}
