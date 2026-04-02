'use client';

/**
 * ViewerContext - 查看器状态 Context
 *
 * 管理文件查看器和文档查看器的显示状态
 * 独立于对话状态，减少其他组件重渲染
 *
 * 注意：当前实现从 UnifiedPlanningContext 读取值
 * 未来可以拆分为完全独立的 Provider
 */

import { createContext, useContext, ReactNode, useMemo } from 'react';
import type { FileMessage } from '@/types';
import { useUnifiedPlanningContext } from './UnifiedPlanningContext';

// Context type definition
export interface ViewerContextType {
  // Viewer state
  viewerVisible: boolean;
  referencedSection?: string;
  viewingFile: FileMessage | null;

  // Actions
  showViewer: () => void;
  hideViewer: () => void;
  toggleViewer: () => void;
  highlightSection: (section: string) => void;
  clearHighlight: () => void;
  showFileViewer: (file: FileMessage) => void;
  hideFileViewer: () => void;
}

// Create context for type checking
const ViewerContext = createContext<ViewerContextType | undefined>(undefined);

/**
 * useViewerContext - 获取查看器 Context
 *
 * 从 UnifiedPlanningContext 获取查看器相关的值和方法
 * 使用此 hook 的组件只依赖查看器状态变化
 */
export function useViewerContext(): ViewerContextType {
  const context = useUnifiedPlanningContext();

  // Return only viewer-related values
  return useMemo(
    () => ({
      viewerVisible: context.viewerVisible,
      referencedSection: context.referencedSection,
      viewingFile: context.viewingFile,
      showViewer: context.showViewer,
      hideViewer: context.hideViewer,
      toggleViewer: context.toggleViewer,
      highlightSection: context.highlightSection,
      clearHighlight: context.clearHighlight,
      showFileViewer: context.showFileViewer,
      hideFileViewer: context.hideFileViewer,
    }),
    [
      context.viewerVisible,
      context.referencedSection,
      context.viewingFile,
      context.showViewer,
      context.hideViewer,
      context.toggleViewer,
      context.highlightSection,
      context.clearHighlight,
      context.showFileViewer,
      context.hideFileViewer,
    ]
  );
}

/**
 * useViewerContextOptional - 可选获取 Viewer Context
 */
export function useViewerContextOptional(): ViewerContextType | undefined {
  return useContext(ViewerContext);
}

// Provider placeholder - not used in current architecture
interface ViewerProviderProps {
  children: ReactNode;
}

export function ViewerProvider({ children }: ViewerProviderProps) {
  // In current architecture, ViewerProvider is a pass-through
  return children as ReactNode;
}