'use client';

/**
 * DimensionSection - Gemini Style
 * Single collapsible dimension card component
 * 使用 Tailwind CSS + Framer Motion
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ParsedSubsection } from '@/lib/layerReportParser';
import MarkdownRenderer from '../MarkdownRenderer';

interface DimensionSectionProps {
  name: string;
  content: string;
  icon: string;
  subsections?: ParsedSubsection[];
  defaultExpanded?: boolean;
  expanded?: boolean;
  onCopy?: () => void;
  onExport?: () => void;
  onToggle?: (expanded: boolean) => void;
}

function DimensionSection({
  name,
  content,
  icon,
  subsections = [],
  defaultExpanded = false,
  expanded: controlledExpanded,
  onCopy,
  onExport,
  onToggle,
}: DimensionSectionProps) {
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  const isExpanded = controlledExpanded !== undefined ? controlledExpanded : internalExpanded;

  // Animation variants
  const contentVariants = {
    collapsed: {
      height: 0,
      opacity: 0,
      transition: {
        height: { duration: 0.3, ease: 'easeInOut' as const },
        opacity: { duration: 0.2 },
      },
    },
    expanded: {
      height: 'auto',
      opacity: 1,
      transition: {
        height: { duration: 0.3, ease: 'easeInOut' as const },
        opacity: { duration: 0.3, delay: 0.1 },
      },
    },
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-xl border border-emerald-100 overflow-hidden shadow-sm hover:shadow-lg hover:shadow-emerald-100/50 hover:border-emerald-200 transition-all duration-300"
    >
      {/* Header */}
      <motion.div
        layout
        onClick={() => {
          if (controlledExpanded === undefined) {
            setInternalExpanded(!internalExpanded);
          }
          onToggle?.(!isExpanded);
        }}
        className="group flex justify-between items-center px-4 py-3 bg-gradient-to-r from-emerald-50 to-transparent cursor-pointer hover:from-emerald-100 transition-colors"
      >
        <h4 className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
          <i className={`fas ${icon} text-emerald-500`} />
          {name}
        </h4>

        <div className="flex items-center gap-2">
          {/* Action buttons - 始终可见 */}
          <div className="flex gap-1">
            {onCopy && (
              <motion.button
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                onClick={(e) => {
                  e.stopPropagation();
                  onCopy();
                }}
                className="w-7 h-7 flex items-center justify-center text-gray-500 hover:text-emerald-600 hover:bg-emerald-50 rounded-lg transition-colors"
                title="复制内容"
              >
                <i className="fas fa-copy text-xs" />
              </motion.button>
            )}
            {onExport && (
              <motion.button
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                onClick={(e) => {
                  e.stopPropagation();
                  onExport();
                }}
                className="w-7 h-7 flex items-center justify-center text-gray-500 hover:text-emerald-600 hover:bg-emerald-50 rounded-lg transition-colors"
                title="导出"
              >
                <i className="fas fa-download text-xs" />
              </motion.button>
            )}
          </div>

          {/* Chevron icon */}
          <motion.div animate={{ rotate: isExpanded ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <i className="fas fa-chevron-down text-gray-400 text-xs" />
          </motion.div>
        </div>
      </motion.div>

      {/* Content */}
      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            key="content"
            variants={contentVariants}
            initial="collapsed"
            animate="expanded"
            exit="collapsed"
            className="overflow-hidden"
          >
            <div className="px-4 py-4 border-t border-emerald-50">
              {subsections.length > 0 ? (
                <div className="space-y-4">
                  {subsections.map((subsection, index) => (
                    <div key={index} className="pl-4 border-l-2 border-emerald-200">
                      <div className="flex items-center gap-2 text-sm font-medium text-emerald-700 mb-2">
                        <i className="fas fa-caret-right text-xs text-emerald-400" />
                        {subsection.title}
                      </div>
                      <div className="text-sm text-gray-600 leading-relaxed">
                        <MarkdownRenderer content={subsection.content} />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-gray-600 leading-relaxed">
                  <MarkdownRenderer content={content} />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// React.memo 优化：避免父组件更新导致的不必要重渲染
const MemoizedDimensionSection = React.memo(DimensionSection);

export default MemoizedDimensionSection;
