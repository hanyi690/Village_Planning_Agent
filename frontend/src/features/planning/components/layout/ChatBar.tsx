'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faPaperPlane,
  faCheck,
  faTimes,
  faCommentDots,
  faChevronDown,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../../store';
import { useIsPaused, useCurrentLayer, useApprovalActions, useSessionId } from '../../hooks';
import { planningApi } from '../../api';

export default function ChatBar() {
  const isPaused = useIsPaused();
  const currentLayer = useCurrentLayer();
  const sessionId = useSessionId();
  const chatBarExpanded = usePlanningStore((state) => state.chatBarExpanded);
  const setChatBarExpanded = usePlanningStore((state) => state.setChatBarExpanded);
  const { approve, reject, isSubmitting } = useApprovalActions();

  const [message, setMessage] = useState('');
  const [feedback, setFeedback] = useState('');
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && chatBarExpanded) {
        setChatBarExpanded(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [chatBarExpanded, setChatBarExpanded]);

  useEffect(() => {
    if (chatBarExpanded && !isPaused) {
      inputRef.current?.focus();
    }
  }, [chatBarExpanded, isPaused]);

  const handleSend = useCallback(async () => {
    const trimmed = message.trim();
    if (!trimmed || !sessionId || sending) return;
    setSending(true);
    try {
      await planningApi.sendChatMessage(sessionId, trimmed);
      setMessage('');
    } catch (error) {
      console.error('Send message failed:', error);
    } finally {
      setSending(false);
    }
  }, [message, sessionId, sending]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleRejectWithFeedback = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    try {
      await planningApi.submitFeedback(sessionId, {
        approve: false,
        feedback: feedback.trim() || '需要修改',
      });
      setFeedback('');
    } catch (error) {
      console.error('Reject with feedback failed:', error);
    }
  }, [sessionId, isSubmitting, feedback]);

  return (
    <>
      <AnimatePresence>
        {!chatBarExpanded && (
          <motion.button
            onClick={() => setChatBarExpanded(true)}
            className="fixed bottom-4 right-4 z-50 w-12 h-12 rounded-full bg-emerald-500 text-white shadow-lg hover:bg-emerald-600 transition-colors flex items-center justify-center"
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.95 }}
          >
            <FontAwesomeIcon icon={faCommentDots} style={{ width: 18, height: 18 }} />
          </motion.button>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {chatBarExpanded && (
          <motion.div
            className="fixed bottom-0 left-0 right-0 z-50"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          >
            {isPaused && currentLayer ? (
              <div className="flex items-center gap-3 px-4 lg:px-6 py-3 bg-amber-50/95 backdrop-blur-sm border-t border-amber-200">
                <span className="text-sm text-amber-700 font-medium shrink-0">
                  Layer {currentLayer} 审查
                </span>

                <button
                  onClick={approve}
                  disabled={isSubmitting}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm hover:bg-emerald-600 transition-colors disabled:opacity-50 shrink-0"
                >
                  <FontAwesomeIcon icon={faCheck} style={{ width: 14, height: 14 }} />
                  <span>批准继续</span>
                </button>

                <button
                  onClick={reject}
                  disabled={isSubmitting}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-red-300 bg-white text-red-600 text-sm hover:bg-red-50 transition-colors disabled:opacity-50 shrink-0"
                >
                  <FontAwesomeIcon icon={faTimes} style={{ width: 14, height: 14 }} />
                  <span>需要修订</span>
                </button>

                <div className="flex-1 flex items-center gap-2">
                  <input
                    type="text"
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleRejectWithFeedback();
                      }
                    }}
                    placeholder="输入修订意见..."
                    className="flex-1 px-3 py-2 rounded-lg border border-amber-200 bg-white text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-amber-300"
                  />
                  <button
                    onClick={handleRejectWithFeedback}
                    disabled={isSubmitting || !feedback.trim()}
                    className="px-3 py-2 rounded-lg bg-amber-100 text-amber-700 text-sm hover:bg-amber-200 transition-colors disabled:opacity-50 shrink-0"
                  >
                    提交反馈
                  </button>
                </div>

                <button
                  onClick={() => setChatBarExpanded(false)}
                  className="p-1.5 rounded hover:bg-amber-100 text-amber-500 transition-colors shrink-0"
                >
                  <FontAwesomeIcon icon={faChevronDown} style={{ width: 14, height: 14 }} />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-3 px-4 lg:px-6 py-3 bg-white/95 backdrop-blur-sm border-t border-slate-200 shadow-lg">
                <input
                  ref={inputRef}
                  type="text"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入消息或反馈..."
                  disabled={!sessionId}
                  className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-300 focus:border-emerald-300 disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <button
                  onClick={handleSend}
                  disabled={!message.trim() || sending || !sessionId}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 text-white text-sm font-medium hover:from-emerald-600 hover:to-teal-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
                >
                  <FontAwesomeIcon icon={faPaperPlane} style={{ width: 14, height: 14 }} />
                  <span>发送</span>
                </button>
                <button
                  onClick={() => setChatBarExpanded(false)}
                  className="p-1.5 rounded hover:bg-slate-100 text-slate-400 transition-colors shrink-0"
                >
                  <FontAwesomeIcon icon={faChevronDown} style={{ width: 14, height: 14 }} />
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
