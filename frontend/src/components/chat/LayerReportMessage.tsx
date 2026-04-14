'use client';

/**
 * LayerReportMessage - Specialized message component for layer_completed type
 * 使用 LayerReportCard 组件实现双模显示
 */

import { LayerCompletedMessage } from '@/types';
import { parseLayerReport, ParsedDimension } from '@/lib/layerReportParser';
import LayerReportCard from './LayerReportCard';
import React, { useMemo } from 'react';
import { getDimensionName, getDimensionIcon } from '@/config/dimensions';

interface LayerReportMessageProps {
  message: LayerCompletedMessage;
  onOpenInSidebar?: (layer: number) => void; // NEW: 跳转到侧边栏
  onToggleAllDimensions?: (expand: boolean) => void;
  currentLayer?: number; // NEW: 当前活跃层
  hasStreamingDimensions?: boolean; // NEW: 是否有流式维度内容
  dimensionContents?: Record<string, string>; // NEW: 实时维度内容（解决并行更新竞态）
}

function LayerReportMessage({
  message,
  onOpenInSidebar,
  onToggleAllDimensions,
  currentLayer,
  hasStreamingDimensions = false,
  dimensionContents,
}: LayerReportMessageProps) {
  // ✅ 修复：调整渲染优先级，确保层级完成时使用 REST API 完整数据
  // 策略：
  // 1. 如果 dimensionReports 有完整数据（来自 REST API），优先使用它
  // 2. 否则使用 dimensionContents 作为流式显示
  // 3. 最后回退到解析 fullReportContent
  const dimensions = useMemo(() => {
    const dimensionReports = (message as LayerCompletedMessage).dimensionReports || {};
    const dimensionReportKeys = Object.keys(dimensionReports);
    const hasDimensionReports = dimensionReportKeys.length > 0;

    // 检查 dimensionReports 内容是否完整（非空字符串）
    const hasCompleteDimensionReports =
      hasDimensionReports &&
      dimensionReportKeys.some((key) => {
        const content = dimensionReports[key];
        return content && content.length > 0;
      });

    const hasDimensionContents = dimensionContents && Object.keys(dimensionContents).length > 0;

    // 1. ✅ 优先使用 dimensionReports（REST API 完整数据）
    // 当 dimensionReports 有完整内容时，说明层级已完成，REST API 返回了完整数据
    if (hasCompleteDimensionReports) {
      return Object.entries(dimensionReports).map(([key, content]) => ({
        name: getDimensionName(key),
        content: content,
        icon: getDimensionIcon(key),
        subsections: [],
      }));
    }

    // 2. 使用 dimensionContents（流式累积内容）
    if (hasDimensionContents) {
      const result: ParsedDimension[] = [];

      // 如果有 dimensionReports 键但内容为空，使用键顺序
      if (hasDimensionReports) {
        for (const key of dimensionReportKeys) {
          const contentKey = `${message.layer}_${key}`;
          const content = dimensionContents[contentKey] || '';
          if (content) {
            result.push({
              name: getDimensionName(key),
              content: content,
              icon: getDimensionIcon(key),
              subsections: [],
            });
          }
        }
      } else {
        // 没有 dimensionReports，直接遍历 dimensionContents
        Object.entries(dimensionContents).forEach(([key, content]) => {
          const parts = key.split('_');
          if (parts.length >= 2) {
            const keyLayer = parseInt(parts[0], 10);
            if (keyLayer === message.layer && content) {
              const dimKey = parts.slice(1).join('_');
              result.push({
                name: getDimensionName(dimKey),
                content: content,
                icon: getDimensionIcon(dimKey),
                subsections: [],
              });
            }
          }
        });
      }

      if (result.length > 0) return result;
    }

    // 3. 回退到解析 fullReportContent
    if (message.fullReportContent) {
      return parseLayerReport(message.fullReportContent);
    }

    console.warn(`[LayerReportMessage] Layer ${message.layer} 无可用数据源！`);
    return [];
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        dimensionGisData={message.dimensionGisData}
        dimensionKnowledgeSources={message.dimensionKnowledgeSources}
        mode="chat"
        defaultExpanded={true}
        maxHeight="none"
        showExpandAll={false}
        isActive={isActive} // ✅ 传递活跃状态
        hasStreamingDimensions={hasStreamingDimensions} // ✅ 传递流式维度状态
        onOpenInSidebar={() => onOpenInSidebar?.(message.layer)}
        onToggleAll={onToggleAllDimensions}
      />
    </div>
  );
}

// React.memo 优化：减少层级报告组件的不必要重渲染
const MemoizedLayerReportMessage = React.memo(LayerReportMessage);

export default MemoizedLayerReportMessage;
