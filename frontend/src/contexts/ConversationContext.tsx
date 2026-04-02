'use client';

/**
 * ConversationContext - 对话状态 Context
 *
 * 管理消息列表、任务 ID、项目名称和对话状态
 * 高频更新的状态，需要独立 Context 减少其他组件重渲染
 *
 * 注意：当前实现从 UnifiedPlanningContext 读取值
 * 未来可以拆分为完全独立的 Provider
 */

import { createContext, useContext, ReactNode, useMemo } from 'react';
import { Message, PlanningParams } from '@/types';
import { VillageInputData } from '@/components/VillageInputForm';
import { PlanningStatus, ViewMode } from '@/lib/constants';
import { useUnifiedPlanningContext } from './UnifiedPlanningContext';

// Re-export types for convenience
export type { ViewMode } from '@/lib/constants';
export type ConversationStatus = PlanningStatus;

// Context type definition
export interface ConversationContextType {
  // Conversation state
  conversationId: string;
  messages: Message[];
  taskId: string | null;
  projectName: string | null;
  status: ConversationStatus;
  viewMode: ViewMode;

  // Form data
  villageFormData: VillageInputData | null;
  setVillageFormData: (data: VillageInputData | null) => void;

  // Actions
  setMessages: (messages: Message[] | ((prev: Message[]) => Message[])) => void;
  addMessage: (message: Message) => void;
  syncMessageToBackend: (message: Message) => void;
  updateLastMessage: (updates: Partial<Message>) => void;
  clearMessages: () => void;
  setTaskId: (taskId: string | null) => void;
  setProjectName: (name: string | null) => void;
  setStatus: (status: ConversationStatus) => void;
  resetConversation: () => void;
  startPlanning: (params: PlanningParams) => Promise<void>;
}

// Create context for type checking
const ConversationContext = createContext<ConversationContextType | undefined>(undefined);

/**
 * useConversationContext - 获取对话 Context
 *
 * 从 UnifiedPlanningContext 获取对话相关的值和方法
 * 使用此 hook 的组件只依赖对话状态变化
 */
export function useConversationContext(): ConversationContextType {
  const context = useUnifiedPlanningContext();

  // Return only conversation-related values
  return useMemo(
    () => ({
      conversationId: context.conversationId,
      messages: context.messages,
      taskId: context.taskId,
      projectName: context.projectName,
      status: context.status,
      viewMode: context.viewMode,
      villageFormData: context.villageFormData,
      setVillageFormData: context.setVillageFormData,
      setMessages: context.setMessages,
      addMessage: context.addMessage,
      syncMessageToBackend: context.syncMessageToBackend,
      updateLastMessage: context.updateLastMessage,
      clearMessages: context.clearMessages,
      setTaskId: context.setTaskId,
      setProjectName: context.setProjectName,
      setStatus: context.setStatus,
      resetConversation: context.resetConversation,
      startPlanning: context.startPlanning,
    }),
    [
      context.conversationId,
      context.messages,
      context.taskId,
      context.projectName,
      context.status,
      context.viewMode,
      context.villageFormData,
      context.setVillageFormData,
      context.setMessages,
      context.addMessage,
      context.syncMessageToBackend,
      context.updateLastMessage,
      context.clearMessages,
      context.setTaskId,
      context.setProjectName,
      context.setStatus,
      context.resetConversation,
      context.startPlanning,
    ]
  );
}

/**
 * useConversationContextOptional - 可选获取 Conversation Context
 */
export function useConversationContextOptional(): ConversationContextType | undefined {
  return useContext(ConversationContext);
}

// Provider placeholder - not used in current architecture
interface ConversationProviderProps {
  children: ReactNode;
  conversationId: string;
}

export function ConversationProvider({ children }: ConversationProviderProps) {
  // In current architecture, ConversationProvider is a pass-through
  return children as ReactNode;
}