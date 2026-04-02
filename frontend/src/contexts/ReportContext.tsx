'use client';

/**
 * ReportContext - 报告状态 Context
 *
 * 管理层级报告内容和报告显示状态
 * 与 PlanningStateContext 分离，减少高频更新影响
 *
 * 注意：当前实现从 UnifiedPlanningContext 读取值
 * 未来可以拆分为完全独立的 Provider
 */

import { createContext, useContext, ReactNode, useMemo } from 'react';
import { useUnifiedPlanningContext } from './UnifiedPlanningContext';
import type { LayerReportContent } from './PlanningStateContext';

// Re-export LayerReportContent
export type { LayerReportContent } from './PlanningStateContext';

// Context type definition
export interface ReportContextType {
  // Layer reports
  layerReports: LayerReportContent;
  setLayerReports: (reports: Partial<LayerReportContent>) => void;

  // Report display state
  layerReportVisible: boolean;
  setLayerReportVisible: (visible: boolean) => void;
  activeReportLayer: number;
  setActiveReportLayer: (layer: number) => void;
}

// Create context for type checking
const ReportContext = createContext<ReportContextType | undefined>(undefined);

/**
 * useReportContext - 获取报告 Context
 *
 * 从 UnifiedPlanningContext 获取报告相关的值和方法
 * 使用此 hook 的组件只依赖报告状态变化
 */
export function useReportContext(): ReportContextType {
  const context = useUnifiedPlanningContext();

  // Return only report-related values
  return useMemo(
    () => ({
      layerReports: context.layerReports,
      setLayerReports: context.setLayerReports,
      layerReportVisible: context.layerReportVisible,
      setLayerReportVisible: context.setLayerReportVisible,
      activeReportLayer: context.activeReportLayer,
      setActiveReportLayer: context.setActiveReportLayer,
    }),
    [
      context.layerReports,
      context.setLayerReports,
      context.layerReportVisible,
      context.setLayerReportVisible,
      context.activeReportLayer,
      context.setActiveReportLayer,
    ]
  );
}

/**
 * useReportContextOptional - 可选获取 Report Context
 */
export function useReportContextOptional(): ReportContextType | undefined {
  return useContext(ReportContext);
}

// Provider placeholder - not used in current architecture
interface ReportProviderProps {
  children: ReactNode;
}

export function ReportProvider({ children }: ReportProviderProps) {
  // In current architecture, ReportProvider is a pass-through
  return children as ReactNode;
}