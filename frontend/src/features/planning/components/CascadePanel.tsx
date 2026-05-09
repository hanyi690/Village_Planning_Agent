'use client';

/**
 * CascadePanel - 级联修复可视化组件
 *
 * SVG路径绘制影响链，CSS流动动画，节点入场动画
 * Gemini aesthetic: amber gradient background, rounded corners, smooth transitions
 */

import React, { useMemo } from 'react';
import { motion } from 'framer-motion';

interface CascadePanelProps {
  trigger: string;  // 触发修复的维度key
  impacted: string[];  // 受影响的维度keys
}

// Dimension name mapping (same as DimensionCard)
const DIMENSION_DISPLAY_NAMES: Record<string, string> = {
  resource_endowment: '资源禀赋',
  population_structure: '人口结构',
  spatial_layout: '空间布局',
  infrastructure: '基础设施',
  development_goal: '发展目标',
  landuse_planning: '土地利用',
  spatial_planning: '空间规划',
  detailed_planning: '详细规划',
};

export default function CascadePanel({ trigger, impacted }: CascadePanelProps) {
  // Get display name
  const getDisplayName = (key: string): string => {
    const keyPart = key.split('_').slice(1).join('_');
    return DIMENSION_DISPLAY_NAMES[keyPart] || keyPart;
  };

  // All nodes in chain: trigger + impacted
  const allNodes = useMemo(() => [trigger, ...impacted], [trigger, impacted]);

  // Node positions (horizontal layout)
  const nodePositions = useMemo(() => {
    const width = 100;
    const spacing = width / (allNodes.length + 1);
    return allNodes.map((_, idx) => ({
      x: spacing * (idx + 1),
      y: 50,
    }));
  }, [allNodes]);

  return (
    <div className="w-full px-4 py-4 bg-gradient-to-r from-amber-50 to-orange-50 border-t border-amber-200">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-amber-700 uppercase tracking-wider font-medium">级联修复链</span>
        <span className="text-xs text-slate-500">用户反馈触发</span>
      </div>

      {/* SVG chain visualization */}
      <div className="relative h-[80px]">
        <svg
          viewBox="0 0 100 100"
          className="w-full h-full"
          preserveAspectRatio="xMidYMid meet"
        >
          {/* Connecting lines with flowing animation */}
          {nodePositions.slice(0, -1).map((pos, idx) => {
            const nextPos = nodePositions[idx + 1];
            return (
              <motion.line
                key={`line-${idx}`}
                x1={pos.x}
                y1={pos.y}
                x2={nextPos.x}
                y2={nextPos.y}
                stroke="#F59E0B"
                strokeWidth="2"
                strokeDasharray="4 4"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.5, delay: idx * 0.15 }}
                style={{
                  animation: 'flowDash 1s linear infinite',
                }}
              />
            );
          })}

          {/* Nodes */}
          {allNodes.map((node, idx) => {
            const pos = nodePositions[idx];
            const isTrigger = idx === 0;

            return (
              <motion.g
                key={`node-${idx}`}
                initial={{ scale: 0, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ duration: 0.3, delay: idx * 0.15 }}
              >
                {/* Node circle */}
                <circle
                  cx={pos.x}
                  cy={pos.y}
                  r={8}
                  fill={isTrigger ? '#F59E0B' : '#FBBF24'}
                  stroke={isTrigger ? '#F59E0B' : '#FBBF24'}
                  strokeWidth="2"
                />

                {/* Node label (below) */}
                <text
                  x={pos.x}
                  y={pos.y + 20}
                  textAnchor="middle"
                  fill="#64748B"
                  fontSize="6"
                  fontFamily="system-ui"
                >
                  {getDisplayName(node)}
                </text>

                {/* Trigger arrow indicator */}
                {isTrigger && (
                  <text
                    x={pos.x}
                    y={pos.y - 15}
                    textAnchor="middle"
                    fill="#F59E0B"
                    fontSize="8"
                  >
                    触发
                  </text>
                )}
              </motion.g>
            );
          })}
        </svg>

        {/* Inline style for animation */}
        <style>{`
          @keyframes flowDash {
            to { stroke-dashoffset: -8; }
          }
        `}</style>
      </div>

      {/* Text description */}
      <div className="mt-2 text-xs text-slate-600">
        <span className="text-amber-600 font-medium">{getDisplayName(trigger)}</span>
        <span className="text-slate-500"> 的修改将影响 </span>
        <span className="text-amber-500 font-medium">{impacted.length}</span>
        <span className="text-slate-500"> 个相关维度</span>
      </div>
    </div>
  );
}