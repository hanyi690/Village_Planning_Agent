'use client';

/**
 * LayerReportMessage - Specialized message component for layer_completed type
 * 使用 LayerReportCard 组件实现双模显示
 */

import { LayerCompletedMessage } from '@/types';
import { parseLayerReport, ParsedDimension } from '@/lib/layerReportParser';
import LayerReportCard from './LayerReportCard';
import { useMemo } from 'react';
import { getDimensionName, getDimensionIcon } from '@/config/dimensions';

interface LayerReportMessageProps {
  message: LayerCompletedMessage;
  onOpenInSidebar?: (layer: number) => void;  // NEW: 跳转到侧边栏
  onToggleAllDimensions?: (expand: boolean) => void;
  currentLayer?: number;  // NEW: 当前活跃层
  hasStreamingDimensions?: boolean;  // NEW: 是否有流式维度内容
  dimensionContents?: Map<string, string>;  // NEW: 实时维度内容（解决并行更新竞态）
}

export default function LayerReportMessage({
  message,
  onOpenInSidebar,
  onToggleAllDimensions,
  currentLayer,
  hasStreamingDimensions = false,  // NEW: 是否有流式维度内容
  dimensionContents,  // NEW: 实时维度内容
}: LayerReportMessageProps) {
  // ✅ 使用 dimensionReports 字段，优先使用 dimensionContents（实时流式内容）
  const dimensions = useMemo(() => {
    const dimensionReports = (message as LayerCompletedMessage).dimensionReports || {};

    // ✅ 优先使用 dimensionContents（实时流式内容，解决并行更新竞态问题）
    if (dimensionContents && dimensionContents.size > 0) {
      const result: ParsedDimension[] = [];
      
      // 遍历 dimensionReports 的键（确保维度顺序正确）
      for (const key of Object.keys(dimensionReports)) {
        const contentKey = `${message.layer}_${key}`;
        // 从 dimensionContents 获取实时内容，如果没有则使用 dimensionReports 中的内容
        const content = dimensionContents.get(contentKey) || dimensionReports[key] || '';
        
        result.push({
          name: getDimensionName(key),
          content: content,
          icon: getDimensionIcon(key),
          subsections: [], // Empty subsections array (ParsedSubsection[])
        });
      }
      
      return result;
    }

    // 如果有 dimensionReports，使用它
    if (Object.keys(dimensionReports).length > 0) {
      return Object.entries(dimensionReports).map(([key, content]) => ({
        name: getDimensionName(key),
        content: content,
        icon: getDimensionIcon(key),
        subsections: [], // Empty subsections array (ParsedSubsection[])
      }));
    }

    // 回退到解析 fullReportContent
    return parseLayerReport(message.fullReportContent || '');
  }, [message.dimensionReports, message.fullReportContent, message.layer, dimensionContents]);

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
        onToggleAll={onToggleAllDimensions}
      />
    </div>
  );
}

