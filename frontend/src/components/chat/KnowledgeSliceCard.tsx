'use client';

/**
 * KnowledgeSliceCard - Knowledge Source Display Card
 * 知识库切片显示卡片
 *
 * Features:
 * - 默认折叠状态
 * - 浅灰色背景
 * - 显示切片数量、来源、页码、内容预览
 * - 紧凑布局，与 GIS 数据卡片风格协调
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { KnowledgeSource } from '@/types';
import MarkdownRenderer from '@/components/MarkdownRenderer';

interface KnowledgeSliceCardProps {
  sources: KnowledgeSource[];
  className?: string;
}

export default function KnowledgeSliceCard({ sources, className = '' }: KnowledgeSliceCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedSliceIndex, setExpandedSliceIndex] = useState<number | null>(null);

  if (!sources || sources.length === 0) {
    return null;
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      className={`bg-gray-50 border border-gray-200 rounded-lg mt-4 mb-2 ${className}`}
    >
      {/* Header - Clickable */}
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-100 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <i className="fas fa-book text-gray-500 text-sm" />
          <span className="text-sm font-medium text-gray-700">知识参考</span>
          <span className="text-xs text-gray-500 bg-gray-200 px-1.5 py-0.5 rounded">
            {sources.length} 条
          </span>
        </div>
        <motion.i
          animate={{ rotate: isExpanded ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="fas fa-chevron-down text-gray-400 text-xs"
        />
      </div>

      {/* Content - Collapsible */}
      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 py-2 border-t border-gray-100 space-y-2">
              {sources.map((source, idx) => (
                <div key={idx} className="text-sm bg-white p-2 rounded border border-gray-100">
                  {/* Source header - Clickable */}
                  <div
                    className="flex items-center gap-2 mb-1 cursor-pointer hover:bg-gray-50 transition-colors rounded px-1 py-0.5 -mx-1 -my-0.5"
                    onClick={() => setExpandedSliceIndex(expandedSliceIndex === idx ? null : idx)}
                  >
                    <span className="text-gray-500 font-medium text-xs">#{idx + 1}</span>
                    <span className="font-medium text-gray-900 text-xs truncate max-w-[200px]">
                      {source.source}
                    </span>
                    {source.doc_type && (
                      <span className="text-xs text-gray-400">[{source.doc_type}]</span>
                    )}
                    <motion.i
                      animate={{ rotate: expandedSliceIndex === idx ? 180 : 0 }}
                      transition={{ duration: 0.15 }}
                      className="fas fa-chevron-down text-gray-400 text-xs ml-auto"
                    />
                  </div>

                  {/* Page info */}
                  {source.page > 0 && (
                    <div className="text-xs text-gray-500 mb-1">第 {source.page} 页</div>
                  )}

                  {/* Content preview (collapsed) */}
                  {source.content && expandedSliceIndex !== idx && (
                    <div className="text-xs text-gray-600 bg-gray-50 p-1.5 rounded italic line-clamp-2">
                      &quot;{source.content.substring(0, 150)}
                      {source.content.length > 150 ? '...' : ''}&quot;
                    </div>
                  )}

                  {/* Full content with Markdown (expanded) */}
                  <AnimatePresence initial={false}>
                    {expandedSliceIndex === idx && source.content && (
                      <motion.div
                        key="detail"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden mt-2"
                      >
                        <div className="bg-gray-50 p-2 rounded border border-gray-200 text-xs text-gray-700 prose prose-sm max-w-none">
                          <MarkdownRenderer content={source.content} />
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
