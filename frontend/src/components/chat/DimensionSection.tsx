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
import MapView from '@/components/gis/MapView';
import type { GISData, GISAnalysisData } from '@/types/message/message-types';

// Metric card configuration for data-driven rendering
const METRIC_CONFIG: Array<{
  key: keyof Pick<GISAnalysisData, 'overallScore' | 'suitabilityLevel' | 'sensitivityClass'>;
  label: string;
  bgClass: string;
  textClass: string;
  format?: (value: unknown) => string;
}> = [
  {
    key: 'overallScore',
    label: '综合评分',
    bgClass: 'bg-emerald-50',
    textClass: 'text-emerald-700',
    format: (v) => `${v}/100`,
  },
  {
    key: 'suitabilityLevel',
    label: '适宜性等级',
    bgClass: 'bg-blue-50',
    textClass: 'text-blue-700',
  },
  {
    key: 'sensitivityClass',
    label: '敏感性等级',
    bgClass: 'bg-amber-50',
    textClass: 'text-amber-700',
  },
];

interface DimensionSectionProps {
  name: string;
  content: string;
  icon: string;
  subsections?: ParsedSubsection[];
  gisData?: GISData;
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
  gisData,
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
          {gisData?.layers && gisData.layers.length > 0 && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 text-xs font-normal">
              <i className="fas fa-map-marker-alt mr-1" />
              空间分析
            </span>
          )}
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
              {/* GIS 分析数据 */}
              {gisData && (
                <div className="mb-4 pb-4 border-b border-emerald-100">
                  {/* 分析指标 - data-driven rendering */}
                  {gisData.analysisData && (
                    <div className="grid grid-cols-2 gap-2 text-sm mb-3">
                      {METRIC_CONFIG.map(({ key, label, bgClass, textClass, format }) => {
                        const value = gisData.analysisData?.[key];
                        if (value === undefined || value === null) return null;
                        return (
                          <div key={key} className={`${bgClass} rounded-lg px-3 py-2`}>
                            <span className="text-gray-500 text-xs">{label}</span>
                            <div className={`font-semibold ${textClass}`}>
                              {format ? format(value) : String(value)}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* 建议 */}
                  {gisData.analysisData?.recommendations && gisData.analysisData.recommendations.length > 0 && (
                    <div className="text-sm text-gray-600">
                      <div className="font-medium mb-2 text-emerald-700">建议</div>
                      <ul className="list-disc list-inside space-y-1">
                        {gisData.analysisData.recommendations.slice(0, 3).map((rec, i) => (
                          <li key={i} className="text-gray-600">
                            {rec}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* GIS 地图 */}
                  {gisData.layers && gisData.layers.length > 0 && (
                    <div className="mt-3">
                      {/* Analysis summary */}
                      <div className="mb-2 p-2 bg-blue-50 rounded-lg flex items-center gap-2">
                        <i className="fas fa-layer-group text-blue-500" />
                        <span className="text-sm text-gray-700">
                          分析图层：{gisData.layers.map(l => l.layerName).join('、')}
                        </span>
                      </div>
                      <MapView
                        layers={gisData.layers}
                        center={gisData.mapOptions?.center}
                        zoom={gisData.mapOptions?.zoom}
                        height="300px"
                        title="空间分析结果"
                      />
                    </div>
                  )}
                </div>
              )}

              {/* 维度内容 */}
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
