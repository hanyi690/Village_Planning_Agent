'use client';

/**
 * Conversation Context
 * 对话上下文 - 管理对话状态和交互
 */

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { Message, ConversationState, PlanningParams } from '@/types/message';

interface ConversationContextType {
  // Conversation state
  conversationId: string;
  messages: Message[];
  taskId: string | null;
  projectName: string | null;
  status: ConversationState['status'];
  viewerVisible: boolean;
  referencedSection?: string;

  // Actions
  addMessage: (message: Message) => void;
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;
  setTaskId: (taskId: string | null) => void;
  setProjectName: (name: string | null) => void;
  setStatus: (status: ConversationState['status']) => void;

  // Viewer control
  showViewer: () => void;
  hideViewer: () => void;
  toggleViewer: () => void;
  highlightSection: (section: string) => void;
  clearHighlight: () => void;

  // Planning
  startPlanning: (params: PlanningParams) => Promise<void>;

  // Conversation management
  resetConversation: () => void;
}

const ConversationContext = createContext<ConversationContextType | undefined>(undefined);

interface ConversationProviderProps {
  children: ReactNode;
  conversationId: string;
}

export function ConversationProvider({ children, conversationId }: ConversationProviderProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string | null>(null);
  const [status, setStatus] = useState<ConversationState['status']>('idle');
  const [viewerVisible, setViewerVisible] = useState(false);
  const [referencedSection, setReferencedSection] = useState<string | undefined>();

  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const updateLastMessage = useCallback((updates: Partial<Message>) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const lastMessage = prev[prev.length - 1];
      return [
        ...prev.slice(0, -1),
        { ...lastMessage, ...updates },
      ];
    });
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  const showViewer = useCallback(() => {
    setViewerVisible(true);
  }, []);

  const hideViewer = useCallback(() => {
    setViewerVisible(false);
  }, []);

  const toggleViewer = useCallback(() => {
    setViewerVisible((prev) => !prev);
  }, []);

  const highlightSection = useCallback((section: string) => {
    setReferencedSection(section);
    setViewerVisible(true);
  }, []);

  const clearHighlight = useCallback(() => {
    setReferencedSection(undefined);
  }, []);

  const startPlanning = useCallback(async (params: PlanningParams) => {
    // This will be implemented when we connect to the backend API
    setStatus('collecting');
    setProjectName(params.projectName);

    // TODO: Call backend API to start planning
    // For now, just update the status
    setStatus('planning');
  }, []);

  const resetConversation = useCallback(() => {
    setMessages([]);
    setTaskId(null);
    setProjectName(null);
    setStatus('idle');
    setViewerVisible(false);
    setReferencedSection(undefined);
  }, []);

  const value: ConversationContextType = {
    conversationId,
    messages,
    taskId,
    projectName,
    status,
    viewerVisible,
    referencedSection,
    addMessage,
    updateLastMessage,
    clearMessages,
    setTaskId,
    setProjectName,
    setStatus,
    showViewer,
    hideViewer,
    toggleViewer,
    highlightSection,
    clearHighlight,
    startPlanning,
    resetConversation,
  };

  return (
    <ConversationContext.Provider value={value}>
      {children}
    </ConversationContext.Provider>
  );
}

export function useConversationContext(): ConversationContextType {
  const context = useContext(ConversationContext);
  if (!context) {
    throw new Error('useConversationContext must be used within a ConversationProvider');
  }
  return context;
}

/**
 * Hook to use conversation context with optional fallback
 * Returns undefined if context is not available (for components that can work without it)
 */
export function useConversationContextOptional(): ConversationContextType | undefined {
  return useContext(ConversationContext);
}
