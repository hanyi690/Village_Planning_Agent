"use client";

import React, { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";

import { useCascadeChain, useStatus } from "../hooks";
import { usePlanningStore } from "../store";
import CascadePanel from "./CascadePanel";

export default function CascadeNotificationBanner() {
  const cascadeChain = useCascadeChain();
  const status = useStatus();
  const completedDimensions = usePlanningStore((s) => s.completedDimensions);
  const clearCascadeChain = usePlanningStore((s) => s.clearCascadeChain);

  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  // Count pending dimensions (excluding completed)
  const pendingCount = useMemo(() => {
    if (!cascadeChain) return 0;
    const allCompleted = new Set([
      ...completedDimensions.layer1,
      ...completedDimensions.layer2,
      ...completedDimensions.layer3,
    ]);
    const triggerPending = allCompleted.has(cascadeChain.trigger) ? 0 : 1;
    const impactedPending = cascadeChain.impacted.filter(
      (d) => !allCompleted.has(d),
    ).length;
    return triggerPending + impactedPending;
  }, [cascadeChain, completedDimensions]);

  const visible = cascadeChain && status !== "idle" && !dismissed;

  if (!visible) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ y: 100, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 100, opacity: 0 }}
        transition={{ type: "spring", damping: 25, stiffness: 300 }}
        className="fixed bottom-0 left-0 right-0 z-50"
      >
        <div className="bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-lg">
          {/* Compact banner */}
          <div className="flex items-center justify-between px-4 py-2">
            <div className="flex items-center gap-2">
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                className="text-amber-100"
              >
                <path
                  d="M6.5 1.5L1 13h14L9 4l-2.5 3"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="text-sm font-medium">
                级联修复进行中：{pendingCount} 个维度待更新
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setExpanded(!expanded)}
                className="p-1.5 rounded hover:bg-white/20 transition-colors"
                title={expanded ? "收起详情" : "展开详情"}
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="currentColor"
                  style={{
                    transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
                    transition: "transform 0.2s",
                  }}
                >
                  <path d="M7 10L2 5h10L7 10z" />
                </svg>
              </button>
              <button
                onClick={() => {
                  setDismissed(true);
                  clearCascadeChain();
                }}
                className="p-1.5 rounded hover:bg-white/20 transition-colors"
                title="关闭"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="currentColor"
                >
                  <path
                    d="M3.5 2.5l8 8M11.5 2.5l-8 8"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    fill="none"
                  />
                </svg>
              </button>
            </div>
          </div>

          {/* Expandable detail panel */}
          <AnimatePresence>
            {expanded && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="bg-white text-slate-700 border-t border-amber-400">
                  <CascadePanel
                    trigger={cascadeChain!.trigger}
                    impacted={cascadeChain!.impacted}
                    completedDimensions={completedDimensions}
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
