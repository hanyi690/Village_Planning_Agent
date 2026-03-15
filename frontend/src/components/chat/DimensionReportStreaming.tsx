'use client';

/**
 * DimensionReportStreaming - Streaming dimension report component
 * 流式维度报告组件，实时显示维度内容
 */

import { useState, useEffect } from 'react';
import MarkdownRenderer from '../MarkdownRenderer';

interface DimensionReportStreamingProps {
  layer: number;
  dimensionKey: string;
  dimensionName: string;
  content: string;
  streamingState: 'streaming' | 'completed' | 'error';
  wordCount: number;
}

export default function DimensionReportStreaming({
  layer: _layer,
  dimensionKey,
  dimensionName,
  content,
  streamingState,
  wordCount,
}: DimensionReportStreamingProps) {
  const [expanded, setExpanded] = useState(true);
  const [displayContent, setDisplayContent] = useState('');

  // 实时更新内容
  useEffect(() => {
    setDisplayContent(content);
  }, [content]);

  // 添加脉冲动画（仅在客户端）
  useEffect(() => {
    if (typeof document === 'undefined') return;

    const style = document.createElement('style');
    style.textContent = `
      @keyframes pulse {
        0% {
          opacity: 1;
          transform: scale(1);
        }
        50% {
          opacity: 0.5;
          transform: scale(1.2);
        }
        100% {
          opacity: 1;
          transform: scale(1);
        }
      }
    `;
    document.head.appendChild(style);

    return () => {
      document.head.removeChild(style);
    };
  }, []);

  // 获取维度图标
  const getDimensionIcon = (key: string): string => {
    const iconMap: Record<string, string> = {
      location: 'fa-map-marker-alt',
      socio_economic: 'fa-chart-line',
      villager_wishes: 'fa-users',
      superior_planning: 'fa-file-alt',
      natural_environment: 'fa-leaf',
      land_use: 'fa-th',
      traffic: 'fa-road',
      public_services: 'fa-hospital',
      infrastructure: 'fa-cogs',
      ecological_green: 'fa-tree',
      architecture: 'fa-building',
      historical_culture: 'fa-landmark',
      resource_endowment: 'fa-gem',
      planning_positioning: 'fa-crosshairs',
      development_goals: 'fa-bullseye',
      planning_strategies: 'fa-chess',
      industry: 'fa-industry',
      spatial_structure: 'fa-project-diagram',
      land_use_planning: 'fa-draw-polygon',
      settlement_planning: 'fa-home',
      public_service: 'fa-graduation-cap',
      disaster_prevention: 'fa-shield-alt',
      heritage: 'fa-monument',
      landscape: 'fa-mountain',
      project_bank: 'fa-list-check',
    };
    return iconMap[key] || 'fa-file';
  };

  // 获取状态颜色
  const getStateColor = (state: string): string => {
    switch (state) {
      case 'streaming':
        return '#1976d2'; // 蓝色
      case 'completed':
        return '#388e3c'; // 绿色
      case 'error':
        return '#d32f2f'; // 红色
      default:
        return '#757575';
    }
  };

  const stateColor = getStateColor(streamingState);

  return (
    <div
      className={`dimension-streaming-card ${expanded ? 'expanded' : ''}`}
      style={{
        border: `1px solid ${streamingState === 'streaming' ? '#64b5f6' : '#c8e6c9'}`,
        background: 'white',
        marginBottom: '12px',
        borderRadius: '8px',
        transition: 'all 0.3s ease',
        overflow: 'hidden',
        boxShadow:
          streamingState === 'streaming'
            ? '0 2px 8px rgba(25, 118, 210, 0.15)'
            : '0 2px 6px rgba(0,0,0,0.03)',
      }}
    >
      {/* Header */}
      <div
        className="dimension-header"
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '10px 16px',
          cursor: 'pointer',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background:
            streamingState === 'streaming' ? 'linear-gradient(90deg, #e3f2fd, #bbdefb)' : '#e8f5e9',
          transition: 'background 0.3s ease',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
          <i
            className={`fas ${getDimensionIcon(dimensionKey)}`}
            style={{
              color: stateColor,
              fontSize: '14px',
              width: '20px',
              textAlign: 'center',
            }}
          />
          <span
            style={{
              fontWeight: 500,
              color: '#333',
              fontSize: '14px',
              flex: 1,
            }}
          >
            {dimensionName}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* 状态指示器 */}
          {streamingState === 'streaming' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: stateColor,
                  animation: 'pulse 1.5s infinite',
                }}
              />
              <span style={{ fontSize: '12px', color: '#666' }}>生成中...</span>
            </div>
          )}

          {/* 字数统计 */}
          <span style={{ fontSize: '12px', color: '#666', minWidth: '60px', textAlign: 'right' }}>
            {wordCount} 字
          </span>

          {/* 展开/折叠图标 */}
          <i
            className={`fas ${expanded ? 'fa-chevron-up' : 'fa-chevron-down'}`}
            style={{ color: '#666', fontSize: '12px' }}
          />
        </div>
      </div>

      {/* Content */}
      {expanded && (
        <div
          className="dimension-content"
          style={{
            padding: '16px',
            background: '#fafafa',
            borderTop: streamingState === 'streaming' ? '1px solid #64b5f6' : '1px solid #c8e6c9',
          }}
        >
          {displayContent ? (
            <MarkdownRenderer
              content={displayContent}
              className="text-sm leading-relaxed text-gray-700"
            />
          ) : (
            <div style={{ color: '#999', fontSize: '13px' }}>
              {streamingState === 'streaming' ? '等待生成...' : '暂无内容'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
