'use client';

/**
 * HistoryPanel - Gemini Style
 * 历史记录面板 - 玻璃态效果 + Framer Motion 动画
 */

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
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

  // Animation variants
  const overlayVariants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1 },
    exit: { opacity: 0 },
  };

  const panelVariants = {
    hidden: { x: '100%', opacity: 0 },
    visible: {
      x: 0,
      opacity: 1,
      transition: {
        type: 'spring' as const,
        stiffness: 300,
        damping: 30,
      },
    },
    exit: {
      x: '100%',
      opacity: 0,
      transition: {
        duration: 0.2,
      },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, x: 20 },
    visible: { opacity: 1, x: 0 },
  };

  if (!mounted) return null;

  return createPortal(
    <>
      {/* Overlay */}
      <motion.div
        variants={overlayVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed inset-0 bg-black/30 backdrop-blur-sm z-[9998]"
        onClick={onClose}
      />

      {/* Panel - Glass morphism style */}
      <motion.div
        variants={panelVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed right-0 top-0 bottom-0 w-[400px] max-w-[400px] bg-white/95 backdrop-blur-xl shadow-2xl flex flex-col z-[9999] overflow-hidden border-l border-white/20"
      >
        {/* Header - Gradient */}
        <div
          className="px-5 py-4 flex justify-between items-center"
          style={{
            background: 'linear-gradient(135deg, #8b5cf6 0%, #3b82f6 50%, #ec4899 100%)',
          }}
        >
          <h2 className="flex items-center gap-2 text-lg font-bold text-white">
            <FontAwesomeIcon icon={faHistory} />
            历史记录
          </h2>
          <motion.button
            whileHover={{ scale: 1.1, rotate: 90 }}
            whileTap={{ scale: 0.9 }}
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center text-white/80 hover:text-white rounded-full hover:bg-white/10 transition-colors"
          >
            <FontAwesomeIcon icon={faTimes} />
          </motion.button>
        </div>

        {/* Search */}
        <div className="p-4 border-b border-gray-100">
          <div className="relative">
            <FontAwesomeIcon
              icon={faSearch}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
            />
            <input
              type="text"
              placeholder="搜索村庄..."
              className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border-0 rounded-xl text-gray-900 placeholder-gray-400 focus:bg-white focus:ring-2 focus:ring-violet-200 transition-all"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-4">
          <AnimatePresence mode="wait">
            {historyLoading && villages.length === 0 ? (
              <motion.div
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-center py-10"
              >
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                >
                  <FontAwesomeIcon
                    icon={faSpinner}
                    className="text-3xl"
                    style={{ color: 'linear-gradient(135deg, #8b5cf6, #3b82f6)' }}
                  />
                </motion.div>
                <p className="mt-3 text-gray-500">加载中...</p>
              </motion.div>
            ) : filteredVillages.length > 0 ? (
              <motion.div
                key="list"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="space-y-3"
              >
                {filteredVillages.map((village, index) => (
                  <motion.div
                    key={village.name}
                    variants={itemVariants}
                    initial="hidden"
                    animate="visible"
                    transition={{ delay: index * 0.05 }}
                    className="bg-gray-50 rounded-xl border border-gray-100 overflow-hidden hover:border-violet-200 hover:shadow-md transition-all"
                  >
                    {/* Village Header */}
                    <div className="px-4 py-3 font-semibold text-gray-800 bg-gradient-to-r from-gray-50 to-white border-b border-gray-100">
                      {village.display_name}
                      <span className="ml-2 text-xs font-normal text-gray-400">
                        {village.sessions?.length || 0} 条记录
                      </span>
                    </div>

                    {/* Sessions */}
                    <div className="p-2 space-y-1">
                      {village.sessions && village.sessions.length > 0 ? (
                        village.sessions.map((session) => (
                          <motion.button
                            key={session.session_id}
                            whileHover={{ x: 4, backgroundColor: '#f0fdf4' }}
                            whileTap={{ scale: 0.98 }}
                            onClick={() => {
                              loadHistoricalSession(village.name, session.session_id);
                              onClose();
                            }}
                            className="w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-left bg-white hover:bg-emerald-50 transition-colors group"
                          >
                            <span className="flex items-center gap-2 text-sm text-gray-600">
                              <FontAwesomeIcon
                                icon={faClock}
                                className="text-gray-300 group-hover:text-emerald-400 transition-colors"
                              />
                              {new Date(session.timestamp).toLocaleString('zh-CN')}
                            </span>
                            <FontAwesomeIcon
                              icon={faChevronRight}
                              className="text-gray-200 group-hover:text-emerald-400 transition-colors"
                            />
                          </motion.button>
                        ))
                      ) : (
                        <div className="text-center text-gray-400 text-sm py-3">
                          无会话记录
                        </div>
                      )}
                    </div>
                  </motion.div>
                ))}
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="text-center py-16"
              >
                <FontAwesomeIcon
                  icon={faInbox}
                  className="text-5xl text-gray-200 mb-4"
                />
                <p className="text-gray-400">暂无历史记录</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.div>
    </>,
    document.body
  );
}
