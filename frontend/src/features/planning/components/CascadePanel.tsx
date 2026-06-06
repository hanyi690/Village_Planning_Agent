"use client";

import React, { useMemo } from "react";
import { motion } from "framer-motion";
import { getDimensionName, getDimensionLayer } from "../config/dimensions";

interface CascadePanelProps {
  trigger: string;
  impacted: string[];
  revisionCompletedKeys: string[];
}

type LayoutType = "singleRow" | "twoRows" | "grid";

interface LayoutResult {
  type: LayoutType;
  viewBox: string;
  positions: { x: number; y: number }[];
  nodeRadius: number;
  fontSize: number;
  height: string;
}

function computeLayout(totalNodes: number, nodes: string[]): LayoutResult {
  if (totalNodes <= 5) {
    const width = 100;
    const spacing = width / (totalNodes + 1);
    return {
      type: "singleRow",
      viewBox: "0 0 100 70",
      positions: nodes.map((_, idx) => ({ x: spacing * (idx + 1), y: 30 })),
      nodeRadius: 7,
      fontSize: 5,
      height: "70px",
    };
  }
  if (totalNodes <= 10) {
    const firstRowCount = Math.ceil(totalNodes / 2);
    const secondRowCount = totalNodes - firstRowCount;
    const w = 100;
    const s1 = w / (firstRowCount + 1);
    const s2 = w / (secondRowCount + 1);
    return {
      type: "twoRows",
      viewBox: "0 0 100 90",
      positions: [
        ...nodes
          .slice(0, firstRowCount)
          .map((_, i) => ({ x: s1 * (i + 1), y: 28 })),
        ...nodes
          .slice(firstRowCount)
          .map((_, i) => ({ x: s2 * (i + 1), y: 65 })),
      ],
      nodeRadius: 5.5,
      fontSize: 4.5,
      height: "90px",
    };
  }
  // Grid layout for 11+ nodes
  const cols = 6;
  const rows = Math.ceil(totalNodes / cols);
  const cellW = 100 / cols;
  const cellH = 30;
  return {
    type: "grid",
    viewBox: `0 0 100 ${rows * cellH + 15}`,
    positions: nodes.map((_, idx) => ({
      x: cellW * (idx % cols) + cellW / 2,
      y: cellH * Math.floor(idx / cols) + cellH / 2 + 8,
    })),
    nodeRadius: 4.5,
    fontSize: 3.5,
    height: `${rows * 30 + 15}px`,
  };
}

function truncateLabel(name: string, maxLen: number): string {
  if (name.length <= maxLen) return name;
  return name.slice(0, maxLen - 1) + "…";
}

export default function CascadePanel({
  trigger,
  impacted,
  revisionCompletedKeys,
}: CascadePanelProps) {
  const { allNodes, pendingNodes, completedNodes, completedCount } =
    useMemo(() => {
      const completedSet = new Set(revisionCompletedKeys);

      const allDims = [trigger, ...impacted];
      const pending = allDims.filter((d) => {
        const layer = getDimensionLayer(d);
        return !completedSet.has(`${layer}_${d}`);
      });
      const completed = impacted.filter((d) => {
        const layer = getDimensionLayer(d);
        return completedSet.has(`${layer}_${d}`);
      });

      return {
        allNodes: allDims,
        pendingNodes: pending,
        completedNodes: completed,
        completedCount: completed.length,
      };
    }, [trigger, impacted, revisionCompletedKeys]);

  const totalNodes = allNodes.length;
  const layout = useMemo(
    () => computeLayout(totalNodes, allNodes),
    [totalNodes, allNodes],
  );

  const maxLabelLen =
    layout.type === "singleRow" ? 6 : layout.type === "twoRows" ? 5 : 4;

  // Build a set of completed dimension keys for quick lookup
  const completedDimSet = useMemo(() => {
    const set = new Set<string>();
    for (const key of revisionCompletedKeys) {
      // key format: "layer_dimKey" -> extract dimKey
      const parts = key.split("_");
      if (parts.length >= 2) {
        set.add(parts.slice(1).join("_"));
      }
    }
    return set;
  }, [revisionCompletedKeys]);

  return (
    <div className="w-full px-4 py-3 bg-gradient-to-r from-amber-50 to-orange-50">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs text-amber-700 uppercase tracking-wider font-medium">
          级联修复链
        </span>
        <span className="text-xs text-slate-500">
          {pendingNodes.length} 个维度待修复
          {completedCount > 0 && (
            <span className="text-emerald-500 ml-1">
              ({completedCount} 个已修复完成)
            </span>
          )}
        </span>
      </div>

      {/* SVG chain visualization */}
      <div className="relative" style={{ height: layout.height }}>
        <svg
          viewBox={layout.viewBox}
          className="w-full"
          style={{ height: layout.height }}
          preserveAspectRatio="xMidYMid meet"
        >
          {/* Connecting lines — only for linear layouts */}
          {layout.type !== "grid" &&
            layout.positions.slice(0, -1).map((pos, idx) => {
              const nextPos = layout.positions[idx + 1];
              if (layout.type === "twoRows") {
                const firstRowCount = Math.ceil(totalNodes / 2);
                if (idx === firstRowCount - 1) return null;
              }
              return (
                <motion.line
                  key={`line-${idx}`}
                  x1={pos.x}
                  y1={pos.y}
                  x2={nextPos.x}
                  y2={nextPos.y}
                  stroke="#F59E0B"
                  strokeWidth="1.5"
                  strokeDasharray="3 3"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 0.4, delay: idx * 0.08 }}
                  style={{ animation: "flowDash 1s linear infinite" }}
                />
              );
            })}

          {/* Nodes */}
          {allNodes.map((node, idx) => {
            const pos = layout.positions[idx];
            const isTrigger = node === trigger;
            const isCompleted = completedDimSet.has(node);
            const label = truncateLabel(getDimensionName(node), maxLabelLen);

            // Color: green for completed revision, amber for trigger, yellow for pending
            const fillColor = isCompleted
              ? "#10B981"
              : isTrigger
                ? "#F59E0B"
                : "#FBBF24";
            const strokeColor = isCompleted
              ? "#059669"
              : isTrigger
                ? "#D97706"
                : "#F59E0B";

            return (
              <motion.g
                key={`node-${idx}`}
                initial={{ scale: 0, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ duration: 0.2, delay: idx * 0.06 }}
              >
                <circle
                  cx={pos.x}
                  cy={pos.y}
                  r={layout.nodeRadius}
                  fill={fillColor}
                  stroke={strokeColor}
                  strokeWidth="1.5"
                />
                <text
                  x={pos.x}
                  y={pos.y + layout.nodeRadius + layout.fontSize + 2}
                  textAnchor="middle"
                  fill={isCompleted ? "#059669" : "#64748B"}
                  fontSize={layout.fontSize}
                  fontFamily="system-ui"
                >
                  {label}
                </text>
                {isTrigger && !isCompleted && (
                  <text
                    x={pos.x}
                    y={pos.y - layout.nodeRadius - 3}
                    textAnchor="middle"
                    fill="#D97706"
                    fontSize={layout.fontSize}
                    fontWeight="bold"
                  >
                    触发
                  </text>
                )}
                {isCompleted && (
                  <text
                    x={pos.x}
                    y={pos.y - layout.nodeRadius - 3}
                    textAnchor="middle"
                    fill="#059669"
                    fontSize={layout.fontSize}
                    fontWeight="bold"
                  >
                    ✓
                  </text>
                )}
              </motion.g>
            );
          })}
        </svg>

        <style>{`
          @keyframes flowDash {
            to { stroke-dashoffset: -6; }
          }
        `}</style>
      </div>

      {/* Text description */}
      <div className="mt-2 text-xs text-slate-600">
        <span className="text-amber-600 font-medium">
          {getDimensionName(trigger)}
        </span>
        <span className="text-slate-500"> 的修改将影响 </span>
        <span className="text-amber-500 font-medium">{impacted.length}</span>
        <span className="text-slate-500"> 个相关维度</span>
        {completedCount > 0 && (
          <span className="text-slate-400 ml-2">
            已修复 {completedCount} 个
          </span>
        )}
      </div>
    </div>
  );
}
