'use client';

/**
 * Chat Route Page
 * 对话路由页面
 */

import React from 'react';
import { ConversationProvider } from '@/contexts/ConversationContext';
import ConversationManager from '@/components/ConversationManager';
import Link from 'next/link';

interface ChatPageProps {
  params: {
    conversationId: string;
  };
}

export default function ChatPage({ params }: ChatPageProps) {
  const conversationId = params.conversationId;

  return (
    <ConversationProvider conversationId={conversationId}>
      <div className="chat-page" style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
        {/* Top Navigation Bar */}
        <nav
          className="navbar navbar-light bg-white border-bottom"
          style={{ padding: '0.5rem 1rem' }}
        >
          <div className="container-fluid">
            <Link
              href="/"
              className="navbar-brand d-flex align-items-center"
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              <i
                className="fas fa-leaf me-2"
                style={{ color: 'var(--primary-green)', fontSize: '1.5rem' }}
              ></i>
              <span style={{ fontSize: '1.25rem', fontWeight: 'bold' }}>
                Village Planning Agent
              </span>
            </Link>

            <div className="d-flex align-items-center">
              <span className="text-muted me-3" style={{ fontSize: '0.875rem' }}>
                对话ID: {conversationId.slice(0, 8)}...
              </span>
              <Link href="/" className="btn btn-outline-secondary btn-sm">
                <i className="fas fa-home me-2"></i>
                返回首页
              </Link>
            </div>
          </div>
        </nav>

        {/* Conversation Manager */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <ConversationManager conversationId={conversationId} />
        </div>
      </div>
    </ConversationProvider>
  );
}
