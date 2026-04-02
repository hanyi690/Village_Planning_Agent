'use client';

/**
 * PlanningStateContext - 规划状态 Context
 *
 * 管理层级完成状态、当前层级、暂停状态和检查点
 * 核心规划流程状态
 *
 * 注意：当前实现从 UnifiedPlanningContext 读取值
 * 未来可以拆分为完全独立的 Provider
 */

import { createContext, useContext, ReactNode, useMemo } from 'react';
import type { Checkpoint } from '@/types';
import { SessionStatusResponse } from '@/lib/api';
import { useUnifiedPlanningContext } from './UnifiedPlanningContext';

// Re-export ViewMode from constants for consumers
export type { ViewMode } from '@/lib/constants';

// Layer report content type
export interface LayerReportContent {
  analysis_reports: Record<string, string>;
  concept_reports: Record<string, string>;
  detail_reports: Record<string, string>;
  analysis_report_content: string;
  concept_report_content: string;
  detail_report_content: string;
}

// Report sync state type
export interface ReportSyncState {
  lastUpdated: number;
  currentLayer: number | null;
  isStreaming: boolean;
}

// Context type definition
export interface PlanningStateContextType {
  // Layer state
  currentLayer: number | null;
  setCurrentLayer: (layer: number | null) => void;
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };

  // Review state
  isPaused: boolean;
  pendingReviewLayer: number | null;
  setIsPaused: (paused: boolean) => void;
  setPendingReviewLayer: (layer: number | null) => void;

  // Checkpoints
  checkpoints: Checkpoint[];
  setCheckpoints: (checkpoints: Checkpoint[] | ((prev: Checkpoint[]) => Checkpoint[])) => void;
  selectedCheckpoint: string | null;
  setSelectedCheckpoint: (checkpointId: string | null) => void;

  // Content state
  loadingContent: boolean;

  // Layer reports
  layerReports: LayerReportContent;
  setLayerReports: (reports: Partial<LayerReportContent>) => void;
  layerReportVisible: boolean;
  setLayerReportVisible: (visible: boolean) => void;
  activeReportLayer: number;
  setActiveReportLayer: (layer: number) => void;

  // Report sync state
  reportSyncState: ReportSyncState;
  triggerReportUpdate: (layer: number, content: string) => void;

  // Backend sync
  syncBackendState: (backendData: Partial<SessionStatusResponse> & { version?: number }) => void;
  setUILayerCompleted: (layer: number, completed: boolean) => void;

  // Content actions
  loadLayerContent: (layerId: string) => Promise<void>;
  loadCheckpoints: () => Promise<void>;
  rollbackToCheckpoint: (checkpointId: string) => Promise<void>;
}

// Create context for type checking
const PlanningStateContext = createContext<PlanningStateContextType | undefined>(undefined);

/**
 * usePlanningStateContext - 获取规划状态 Context
 *
 * 从 UnifiedPlanningContext 获取规划状态相关的值和方法
 */
export function usePlanningStateContext(): PlanningStateContextType {
  const context = useUnifiedPlanningContext();

  // Return only planning state-related values
  return useMemo(
    () => ({
      currentLayer: context.currentLayer,
      setCurrentLayer: context.setCurrentLayer,
      completedLayers: context.completedLayers,
      isPaused: context.isPaused,
      pendingReviewLayer: context.pendingReviewLayer,
      setIsPaused: context.setIsPaused,
      setPendingReviewLayer: context.setPendingReviewLayer,
      checkpoints: context.checkpoints,
      setCheckpoints: context.setCheckpoints,
      selectedCheckpoint: context.selectedCheckpoint,
      setSelectedCheckpoint: context.setSelectedCheckpoint,
      loadingContent: context.loadingContent,
      layerReports: context.layerReports,
      setLayerReports: context.setLayerReports,
      layerReportVisible: context.layerReportVisible,
      setLayerReportVisible: context.setLayerReportVisible,
      activeReportLayer: context.activeReportLayer,
      setActiveReportLayer: context.setActiveReportLayer,
      reportSyncState: context.reportSyncState,
      triggerReportUpdate: context.triggerReportUpdate,
      syncBackendState: context.syncBackendState,
      setUILayerCompleted: context.setUILayerCompleted,
      loadLayerContent: context.loadLayerContent,
      loadCheckpoints: context.loadCheckpoints,
      rollbackToCheckpoint: context.rollbackToCheckpoint,
    }),
    [
      context.currentLayer,
      context.setCurrentLayer,
      context.completedLayers,
      context.isPaused,
      context.pendingReviewLayer,
      context.setIsPaused,
      context.setPendingReviewLayer,
      context.checkpoints,
      context.setCheckpoints,
      context.selectedCheckpoint,
      context.setSelectedCheckpoint,
      context.loadingContent,
      context.layerReports,
      context.setLayerReports,
      context.layerReportVisible,
      context.setLayerReportVisible,
      context.activeReportLayer,
      context.setActiveReportLayer,
      context.reportSyncState,
      context.triggerReportUpdate,
      context.syncBackendState,
      context.setUILayerCompleted,
      context.loadLayerContent,
      context.loadCheckpoints,
      context.rollbackToCheckpoint,
    ]
  );
}

/**
 * usePlanningStateContextOptional - 可选获取 PlanningState Context
 */
export function usePlanningStateContextOptional(): PlanningStateContextType | undefined {
  return useContext(PlanningStateContext);
}

// Provider placeholder - not used in current architecture
interface PlanningStateProviderProps {
  children: ReactNode;
}

export function PlanningStateProvider({ children }: PlanningStateProviderProps) {
  // In current architecture, PlanningStateProvider is a pass-through
  return children as ReactNode;
}