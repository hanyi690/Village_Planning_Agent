'use client';

/**
 * LayerReportMessage - Specialized message component for layer_completed type
 * 使用 LayerReportCard 组件实现双模显示
 */

import { LayerCompletedMessage } from '@/types';
import { parseLayerReport } from '@/lib/layerReportParser';
import LayerReportCard from './LayerReportCard';
import { useMemo } from 'react';
import { getDimensionName, getDimensionIcon } from '@/config/dimensions';

interface LayerReportMessageProps {
  message: LayerCompletedMessage;
  onOpenInSidebar?: (layer: number) => void;  // NEW: 跳转到侧边栏
  onToggleAll?: (expand: boolean) => void;
  currentLayer?: number;  // NEW: 当前活跃层
  hasStreamingDimensions?: boolean;  // NEW: 是否有流式维度内容
}

export default function LayerReportMessage({
  message,
  onOpenInSidebar,
  onToggleAll,
  currentLayer,
  hasStreamingDimensions = false,  // NEW: 是否有流式维度内容
}: LayerReportMessageProps) {
  // ✅ 使用 dimensionReports 字段，而不是解析 fullReportContent
  const dimensions = useMemo(() => {
    const dimensionReports = (message as LayerCompletedMessage).dimensionReports || {};

    // ✅ 添加 Layer 2 专用调试日志
    if (message.layer === 2) {
      console.log('[LayerReportMessage] === Layer 2 ===');
      console.log('[LayerReportMessage] message:', message);
      console.log('[LayerReportMessage] message.dimensionReports:', message.dimensionReports);
      console.log('[LayerReportMessage] message.dimensionReports keys:', Object.keys(message.dimensionReports || {}));
      console.log('[LayerReportMessage] dimensionReports:', dimensionReports);
      console.log('[LayerReportMessage] dimensionReports keys:', Object.keys(dimensionReports));
      console.log('[LayerReportMessage] dimensionReports length:', Object.keys(dimensionReports).length);
      if (dimensionReports) {
        for (const [key, value] of Object.entries(dimensionReports)) {
          console.log(`[LayerReportMessage]   - ${key}: ${value.length} chars`);
        }
      }
    }

    // 如果有 dimensionReports，使用它
    if (Object.keys(dimensionReports).length > 0) {
      return Object.entries(dimensionReports).map(([key, content]) => ({
        name: getDimensionName(key),
        content: content,
        icon: getDimensionIcon(key),
        subsections: [],
      }));
    }

    // 回退到解析 fullReportContent
    return parseLayerReport(message.fullReportContent || '');
  }, [message.dimensionReports, message.fullReportContent]);

  // ✅ 判断是否为当前活跃层
  const isActive = message.layer === currentLayer;

  return (
    <div className="w-full mb-4">
      {/* 使用 mode='chat' 的 LayerReportCard */}
      <LayerReportCard
        layerNumber={message.layer}
        content={message.fullReportContent || ''}
        dimensions={dimensions}
        mode="chat"
        defaultExpanded={false}
        maxHeight="500px"
        showExpandAll={false}
        isActive={isActive}  // ✅ 传递活跃状态
        hasStreamingDimensions={hasStreamingDimensions}  // ✅ 传递流式维度状态
        onOpenInSidebar={() => onOpenInSidebar?.(message.layer)}
        onToggleAll={onToggleAll}
      />
    </div>
  );
}

