'use client';

/**
 * LayerReportMessage - Specialized message component for layer_completed type
 * 使用 LayerReportCard 组件实现双模显示
 */

import { LayerCompletedMessage } from '@/types';
import { parseLayerReport } from '@/lib/layerReportParser';
import LayerReportCard from './LayerReportCard';

interface LayerReportMessageProps {
  message: LayerCompletedMessage;
  onOpenInSidebar?: (layer: number) => void;  // NEW: 跳转到侧边栏
  onToggleAll?: (expand: boolean) => void;
}

export default function LayerReportMessage({
  message,
  onOpenInSidebar,
  onToggleAll,
}: LayerReportMessageProps) {
  // 解析维度
  const dimensions = parseLayerReport(message.fullReportContent || '');

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
        onOpenInSidebar={() => onOpenInSidebar?.(message.layer)}
        onToggleAll={onToggleAll}
      />
    </div>
  );
}

