'use client';

/**
 * LayerReportMessage - Specialized message component for layer_completed type
 * 使用 LayerReportCard 组件实现双模显示
 */

import { LayerCompletedMessage } from '@/types';
import { parseLayerReport } from '@/lib/layerReportParser';
import LayerReportCard from './LayerReportCard';
import { useMemo } from 'react';

interface LayerReportMessageProps {
  message: LayerCompletedMessage;
  onOpenInSidebar?: (layer: number) => void;  // NEW: 跳转到侧边栏
  onToggleAll?: (expand: boolean) => void;
  currentLayer?: number;  // NEW: 当前活跃层
  hasStreamingDimensions?: boolean;  // NEW: 是否有流式维度内容
}

// 获取维度友好名称
const getDimensionName = (key: string): string => {
  const nameMap: Record<string, string> = {
    location: '区位分析',
    socio_economic: '社会经济分析',
    villager_wishes: '村民意愿分析',
    superior_planning: '上位规划分析',
    natural_environment: '自然环境分析',
    land_use: '土地利用分析',
    traffic: '道路交通分析',
    public_services: '公共服务设施分析',
    infrastructure: '基础设施分析',
    ecological_green: '生态绿地分析',
    architecture: '建筑分析',
    historical_culture: '历史文化分析',
    resource_endowment: '资源禀赋分析',
    planning_positioning: '规划定位分析',
    development_goals: '发展目标分析',
    planning_strategies: '规划策略分析',
    industry: '产业规划',
    spatial_structure: '空间结构规划',
    land_use_planning: '土地利用规划',
    settlement_planning: '居民点规划',
    public_service: '公共服务规划',
    disaster_prevention: '防灾减灾规划',
    heritage: '遗产保护规划',
    landscape: '景观规划',
    project_bank: '项目库规划',
  };
  return nameMap[key] || key;
};

// 获取维度图标
const getDimensionIcon = (key: string): string => {
  const iconMap: Record<string, string> = {
    location: '📍',
    socio_economic: '👥',
    villager_wishes: '💭',
    superior_planning: '📋',
    natural_environment: '🌿',
    land_use: '🏗️',
    traffic: '🚗',
    public_services: '🏛️',
    infrastructure: '🔧',
    ecological_green: '🌳',
    architecture: '🏠',
    historical_culture: '🏛️',
    resource_endowment: '💎',
    planning_positioning: '🎯',
    development_goals: '🎯',
    planning_strategies: '📊',
    industry: '🏭',
    spatial_structure: '🗺️',
    land_use_planning: '📐',
    settlement_planning: '🏘️',
    public_service: '🏛️',
    disaster_prevention: '🛡️',
    heritage: '🏛️',
    landscape: '🖼️',
    project_bank: '📦',
  };
  return iconMap[key] || '📄';
};

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

