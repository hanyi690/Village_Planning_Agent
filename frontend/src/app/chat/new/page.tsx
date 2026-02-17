'use client';

/**
 * New Chat Page
 * 新建对话页面 - 自动创建对话并重定向
 */

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { sessionApi } from '@/lib/api';

export default function NewChatPage() {
  const router = useRouter();

  useEffect(() => {
    // Create a new session and redirect
    const createNewSession = async () => {
      try {
        const response = await sessionApi.createSession('conversation');
        if (response.session_id) {
          router.replace(`/chat/${response.session_id}`);
        }
      } catch (error) {
        console.error('Failed to create session:', error);
        // Fallback: redirect to a random ID
        const randomId = Math.random().toString(36).substring(2, 15);
        router.replace(`/chat/${randomId}`);
      }
    };

    createNewSession();
  }, [router]);

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        flexDirection: 'column',
        gap: '1rem',
      }}
    >
      <div className="spinner-border" role="status">
        <span className="visually-hidden">Loading...</span>
      </div>
      <p className="text-muted">正在创建新对话...</p>
    </div>
  );
}
