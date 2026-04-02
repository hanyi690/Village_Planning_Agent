'use client';

/**
 * HistoryContext - 历史记录 Context
 *
 * 管理村庄列表、会话历史和历史加载状态
 * 独立于对话状态，减少其他组件重渲染
 *
 * 注意：当前实现从 UnifiedPlanningContext 读取值
 * 未来可以拆分为完全独立的 Provider
 */

import { createContext, useContext, ReactNode, useMemo } from 'react';
import { VillageInfo, VillageSession } from '@/lib/api';
import { useUnifiedPlanningContext } from './UnifiedPlanningContext';

// Context type definition
export interface HistoryContextType {
  // History state
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;
  historyLoading: boolean;
  historyError: string | null;
  deletingSessionId: string | null;

  // Task ID for current session comparison
  taskId: string | null;

  // Actions
  loadVillagesHistory: () => Promise<void>;
  selectVillage: (village: VillageInfo) => void;
  selectSession: (session: VillageSession) => void;
  deleteSession: (sessionId: string, villageName: string) => Promise<boolean>;
  loadHistoricalSession: (villageName: string, sessionId: string) => Promise<void>;
}

// Create context for type checking
const HistoryContext = createContext<HistoryContextType | undefined>(undefined);

/**
 * useHistoryContext - 获取历史记录 Context
 *
 * 从 UnifiedPlanningContext 获取历史相关的值和方法
 * 使用此 hook 的组件只依赖历史状态变化
 */
export function useHistoryContext(): HistoryContextType {
  const context = useUnifiedPlanningContext();

  // Return only history-related values
  return useMemo(
    () => ({
      villages: context.villages,
      selectedVillage: context.selectedVillage,
      selectedSession: context.selectedSession,
      historyLoading: context.historyLoading,
      historyError: context.historyError,
      deletingSessionId: context.deletingSessionId,
      taskId: context.taskId,
      loadVillagesHistory: context.loadVillagesHistory,
      selectVillage: context.selectVillage,
      selectSession: context.selectSession,
      deleteSession: context.deleteSession,
      loadHistoricalSession: context.loadHistoricalSession,
    }),
    [
      context.villages,
      context.selectedVillage,
      context.selectedSession,
      context.historyLoading,
      context.historyError,
      context.deletingSessionId,
      context.taskId,
      context.loadVillagesHistory,
      context.selectVillage,
      context.selectSession,
      context.deleteSession,
      context.loadHistoricalSession,
    ]
  );
}

/**
 * useHistoryContextOptional - 可选获取 History Context
 */
export function useHistoryContextOptional(): HistoryContextType | undefined {
  return useContext(HistoryContext);
}

// Provider placeholder - not used in current architecture
interface HistoryProviderProps {
  children: ReactNode;
}

export function HistoryProvider({ children }: HistoryProviderProps) {
  // In current architecture, HistoryProvider is a pass-through
  return children as ReactNode;
}