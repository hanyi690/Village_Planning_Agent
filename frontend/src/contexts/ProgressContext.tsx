'use client';

/**
 * ProgressContext - 执行进度 Context
 *
 * 管理维度执行进度、当前阶段和进度面板显示状态
 * SSE 高频更新时减少其他组件重渲染
 *
 * 注意：当前实现从 UnifiedPlanningContext 读取值
 * 未来可以拆分为完全独立的 Provider
 */

import { createContext, useContext, ReactNode, useMemo } from 'react';
import type { DimensionProgressItem } from '@/types';
import { LayerPhase } from '@/lib/constants';
import { useUnifiedPlanningContext } from './UnifiedPlanningContext';

// Progress phase type (extends LayerPhase with '修复中')
export type ProgressPhase = LayerPhase | 'idle' | '修复中';

// Context type definition
export interface ProgressContextType {
  // Progress panel state
  progressPanelVisible: boolean;
  setProgressPanelVisible: (visible: boolean) => void;

  // Dimension progress state
  dimensionProgress: Map<string, DimensionProgressItem>;
  executingDimensions: Set<string>;
  currentPhase: ProgressPhase;

  // Actions
  setCurrentLayerAndPhase: (layer: number) => void;
  updateDimensionProgress: (key: string, updates: Partial<DimensionProgressItem>) => void;
  setDimensionStreaming: (layer: number, dimensionKey: string, dimensionName: string) => void;
  setDimensionCompleted: (layer: number, dimensionKey: string, wordCount: number) => void;
  clearDimensionProgress: () => void;
}

// Create context for type checking
const ProgressContext = createContext<ProgressContextType | undefined>(undefined);

/**
 * useProgressContext - 获取进度 Context
 *
 * 从 UnifiedPlanningContext 获取进度相关的值和方法
 * 使用此 hook 的组件只依赖进度状态变化
 */
export function useProgressContext(): ProgressContextType {
  const context = useUnifiedPlanningContext();

  // Return only progress-related values
  return useMemo(
    () => ({
      progressPanelVisible: context.progressPanelVisible,
      setProgressPanelVisible: context.setProgressPanelVisible,
      dimensionProgress: context.dimensionProgress,
      executingDimensions: context.executingDimensions,
      currentPhase: context.currentPhase,
      setCurrentLayerAndPhase: context.setCurrentLayerAndPhase,
      updateDimensionProgress: context.updateDimensionProgress,
      setDimensionStreaming: context.setDimensionStreaming,
      setDimensionCompleted: context.setDimensionCompleted,
      clearDimensionProgress: context.clearDimensionProgress,
    }),
    [
      context.progressPanelVisible,
      context.setProgressPanelVisible,
      context.dimensionProgress,
      context.executingDimensions,
      context.currentPhase,
      context.setCurrentLayerAndPhase,
      context.updateDimensionProgress,
      context.setDimensionStreaming,
      context.setDimensionCompleted,
      context.clearDimensionProgress,
    ]
  );
}

/**
 * useProgressContextOptional - 可选获取 Progress Context
 */
export function useProgressContextOptional(): ProgressContextType | undefined {
  return useContext(ProgressContext);
}

// Provider placeholder - not used in current architecture
interface ProgressProviderProps {
  children: ReactNode;
}

export function ProgressProvider({ children }: ProgressProviderProps) {
  // In current architecture, ProgressProvider is a pass-through
  return children as ReactNode;
}