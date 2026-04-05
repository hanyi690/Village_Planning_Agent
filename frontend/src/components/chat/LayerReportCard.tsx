'use client';

/**
 * LayerReportCard - Gemini Style
 * Complete layer report card with collapsible dimensions
 * 使用 Tailwind CSS + Framer Motion
 */

import { useState, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ParsedDimension, parseLayerReport } from '@/lib/layerReportParser';
import DimensionSection from './DimensionSection';

interface LayerReportCardProps {
  layerNumber: number;
  content: string;
  dimensions?: ParsedDimension[];
  mode?: 'chat' | 'sidebar';
  defaultExpanded?: boolean;
  maxHeight?: string;
  showExpandAll?: boolean;
  onOpenInSidebar?: () => void;
  onToggleAll?: (expand: boolean) => void;
  isActive?: boolean;
  hasStreamingDimensions?: boolean;
  simplified?: boolean;
}

export default function LayerReportCard({
  layerNumber,
  content,
  dimensions: propDimensions,
  mode = 'sidebar',
  defaultExpanded,
  maxHeight,
  showExpandAll,
  onOpenInSidebar,
  onToggleAll,
  isActive = false,
  hasStreamingDimensions = false,
  simplified = false,
}: LayerReportCardProps) {
  const actualDefaultExpanded =
    defaultExpanded ?? (simplified ? false : (mode === 'sidebar' || isActive || hasStreamingDimensions));
  const actualMaxHeight = maxHeight ?? (mode === 'chat' ? '800px' : 'none');
  const actualShowExpandAll = showExpandAll ?? (mode === 'sidebar' && !simplified);

  const [allExpanded, setAllExpanded] = useState(false);
  const [localExpanded, setLocalExpanded] = useState(actualDefaultExpanded);
  const [expandedMap, setExpandedMap] = useState<Record<string, boolean>>({});

  const dimensions = useMemo(() => {
    if (propDimensions && propDimensions.length > 0) {
      return propDimensions;
    }
    return parseLayerReport(content);
  }, [content, propDimensions]);

  // 🔧 计算实际字符数（从 dimensions 内容计算，而非使用 content.length）
  const actualCharCount = useMemo(() => {
    return dimensions.reduce((sum, dim) => sum + (dim.content?.length || 0), 0);
  }, [dimensions]);

  // Initialize expandedMap when dimensions change
  useEffect(() => {
    if (dimensions.length > 0) {
      setExpandedMap((prev) => {
        // Only initialize if empty or new dimensions added
        if (Object.keys(prev).length === 0) {
          const initial: Record<string, boolean> = {};
          dimensions.forEach((dim) => {
            initial[dim.name] = actualDefaultExpanded;
          });
          return initial;
        }
        // Add new dimensions with default value
        const updated = { ...prev };
        dimensions.forEach((dim) => {
          if (!(dim.name in updated)) {
            updated[dim.name] = actualDefaultExpanded;
          }
        });
        return updated;
      });
    }
  }, [dimensions, actualDefaultExpanded]);

  // Handle toggle all dimensions
  const handleToggleAll = (expand: boolean) => {
    const newMap: Record<string, boolean> = {};
    dimensions.forEach((dim) => {
      newMap[dim.name] = expand;
    });
    setExpandedMap(newMap);
    setAllExpanded(expand);
    onToggleAll?.(expand);
  };

  // Handle single dimension toggle
  const handleDimensionToggle = (dimensionName: string, expanded: boolean) => {
    setExpandedMap((prev) => {
      const newMap = {
        ...prev,
        [dimensionName]: expanded,
      };
      // Update allExpanded state based on new state
      const allDimsExpanded = dimensions.every(
        (dim) => newMap[dim.name] ?? actualDefaultExpanded
      );
      setAllExpanded(allDimsExpanded);
      return newMap;
    });
  };

  const handleCopyDimension = (dimensionName: string, dimensionContent: string) => {
    const textToCopy = `## ${dimensionName}\n\n${dimensionContent}`;
    navigator.clipboard.writeText(textToCopy);
  };

  const handleExportDimension = (dimensionName: string, dimensionContent: string) => {
    const blob = new Blob([`## ${dimensionName}\n\n${dimensionContent}`], {
      type: 'text/markdown',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `layer${layerNumber}_${dimensionName}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleToggleExpanded = () => {
    setLocalExpanded((prev) => !prev);
  };

  // Animation variants
  const containerVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.3,
        staggerChildren: 0.05,
      },
    },
  };

  if (dimensions.length === 0) {
    return (
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="bg-gradient-to-br from-emerald-50 to-green-50 rounded-2xl p-6 text-center text-gray-500 my-6"
      >
        <i className="fas fa-file-alt text-3xl mb-3 text-emerald-300" />
        <p>暂无维度数据</p>
      </motion.div>
    );
  }

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      layout
      className={`relative bg-gradient-to-br from-cyan-50/80 to-teal-50/80 rounded-xl p-5 my-6 backdrop-blur-sm ${
        !isActive ? 'opacity-70' : ''
      }`}
      style={{
        maxHeight: localExpanded ? 'none' : actualMaxHeight,
        overflow: 'hidden',
      }}
    >
      {/* 非活跃层标识 */}
      <AnimatePresence>
        {!isActive && mode === 'chat' && (
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
            className="absolute top-3 right-3 bg-gray-100/80 px-2 py-1 rounded-lg text-xs text-gray-600 z-10"
          >
            已完成
          </motion.div>
        )}
      </AnimatePresence>

      {/* Header - Sidebar simplified mode skips header */}
      {!simplified && (
        <>
          {mode === 'chat' ? (
            <div className="mb-4 pb-3 border-b border-cyan-200/50">
              <h3 className="flex items-center gap-2 text-base font-semibold text-cyan-800">
                <i className="fas fa-layer-group text-cyan-500" />
                Layer {layerNumber} 报告
              </h3>
              <p className="text-sm text-gray-500 mt-1">
                {dimensions.length} 个维度 · {actualCharCount} 字
              </p>
              {/* Chat mode expand/collapse toggle button */}
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => handleToggleAll(!allExpanded)}
                className={allExpanded
                  ? "flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-cyan-600 bg-white border border-cyan-200 rounded-lg"
                  : "flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-white rounded-lg shadow-sm"
                }
                style={!allExpanded ? {
                  background: 'linear-gradient(135deg, #0891B2 0%, #06B6D4 100%)',
                } : undefined}
              >
                <i className={`fas ${allExpanded ? 'fa-compress-alt' : 'fa-expand-alt'}`} />
                {allExpanded ? '折叠全部' : '展开全部'}
              </motion.button>
            </div>
          ) : (
            <div className="flex justify-between items-center mb-5 pb-4 border-b border-cyan-200/50">
              <div>
                <h3 className="flex items-center gap-2 text-lg font-semibold text-cyan-800">
                  <i className="fas fa-layer-group text-cyan-500" />
                  Layer {layerNumber} 完整报告
                </h3>
                <p className="text-sm text-gray-500 mt-1">
                  共 {dimensions.length} 个维度 · {actualCharCount} 字
                </p>
              </div>

              {/* Action buttons - Sidebar only */}
              {actualShowExpandAll && (
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => handleToggleAll(!allExpanded)}
                  className={allExpanded
                    ? "flex items-center gap-2 px-4 py-2 text-sm font-medium text-cyan-600 bg-white border border-cyan-200 rounded-lg hover:bg-cyan-50 transition-colors"
                    : "flex items-center gap-2 px-4 py-2 text-sm font-medium text-white rounded-lg shadow-md"
                  }
                  style={!allExpanded ? {
                    background: 'linear-gradient(135deg, #0891B2 0%, #06B6D4 100%)',
                    boxShadow: '0 4px 12px rgba(8, 145, 178, 0.3)',
                  } : undefined}
                >
                  <i className={`fas ${allExpanded ? 'fa-compress-alt' : 'fa-expand-alt'}`} />
                  {allExpanded ? '折叠全部' : '展开全部'}
                </motion.button>
              )}
            </div>
          )}
        </>
      )}

      {/* Dimension sections */}
      <div className="space-y-3">
        {dimensions.map((dimension, index) => (
          <DimensionSection
            key={index}
            name={dimension.name}
            content={dimension.content}
            icon={dimension.icon}
            subsections={dimension.subsections}
            expanded={expandedMap[dimension.name] ?? actualDefaultExpanded}
            onToggle={(expanded) => handleDimensionToggle(dimension.name, expanded)}
            onCopy={() => handleCopyDimension(dimension.name, dimension.content)}
            onExport={() => handleExportDimension(dimension.name, dimension.content)}
          />
        ))}
      </div>

      {/* Chat mode: Expand button */}
      <AnimatePresence>
        {mode === 'chat' && !localExpanded && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute bottom-0 left-0 right-0 p-5 bg-gradient-to-t from-cyan-50 via-cyan-50/95 to-transparent flex flex-col items-center gap-3"
          >
            <motion.button
              whileHover={{ scale: 1.02, y: -2 }}
              whileTap={{ scale: 0.98 }}
              onClick={handleToggleExpanded}
              className="flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-cyan-600 bg-white border border-cyan-200 rounded-xl shadow-md hover:bg-cyan-50 transition-colors"
            >
              <i className="fas fa-chevron-down" />
              展开全文
            </motion.button>

            {onOpenInSidebar && (
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={onOpenInSidebar}
                className="flex items-center gap-2 px-4 py-2 text-sm text-cyan-600 hover:text-cyan-700 transition-colors"
              >
                <i className="fas fa-external-link-alt" />
                在侧边栏查看
              </motion.button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
