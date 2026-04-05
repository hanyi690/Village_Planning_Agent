'use client';

/**
 * LayerSidebar - Layer 报告侧边栏
 * 复用 HistoryPanel 的动画和 Portal 渲染逻辑
 * 使用 DimensionSection 显示各个维度的独立折叠卡片
 */

import React, { useState, useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faTimes, faLayerGroup } from '@fortawesome/free-solid-svg-icons';
import { usePlanningStore } from '@/stores';
import DimensionSection from '@/components/chat/DimensionSection';
import { getDimensionConfigsByLayer } from '@/config/dimensions';
import { LAYER_VALUE_MAP } from '@/lib/constants';

interface LayerSidebarProps {
  activeLayer: number | null;
  onClose: () => void;
}

export default function LayerSidebar({ activeLayer, onClose }: LayerSidebarProps) {
  const reports = usePlanningStore((state) => state.reports);
  const completedDimensions = usePlanningStore((state) => state.completedDimensions);

  // Derive layerReports and completedLayers from state
  const layerReports = {
    analysis_reports: reports.layer1,
    concept_reports: reports.layer2,
    detail_reports: reports.layer3,
    analysis_report_content: '',
    concept_report_content: '',
    detail_report_content: '',
  };

  const completedLayers = {
    1: completedDimensions.layer1.length > 0,
    2: completedDimensions.layer2.length > 0,
    3: completedDimensions.layer3.length > 0,
  };

  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = 'unset';
    };
  }, []);

  // Get the report content for the active layer
  const layerContent = useMemo(() => {
    if (activeLayer === 1) {
      return {
        reports: layerReports.analysis_reports,
        content: layerReports.analysis_report_content,
      };
    }
    if (activeLayer === 2) {
      return {
        reports: layerReports.concept_reports,
        content: layerReports.concept_report_content,
      };
    }
    if (activeLayer === 3) {
      return {
        reports: layerReports.detail_reports,
        content: layerReports.detail_report_content,
      };
    }
    return { reports: {}, content: '' };
  }, [activeLayer, layerReports]);

  // Animation variants
  const overlayVariants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1 },
    exit: { opacity: 0 },
  };

  const panelVariants = {
    hidden: { x: '100%', opacity: 0 },
    visible: {
      x: 0,
      opacity: 1,
      transition: {
        type: 'spring' as const,
        stiffness: 300,
        damping: 30,
      },
    },
    exit: {
      x: '100%',
      opacity: 0,
      transition: {
        duration: 0.2,
      },
    },
  };

  if (!mounted || !activeLayer) return null;

  const layerName = LAYER_VALUE_MAP[activeLayer] || `Layer ${activeLayer}`;

  return createPortal(
    <>
      {/* Overlay */}
      <motion.div
        variants={overlayVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed inset-0 bg-black/30 backdrop-blur-sm z-[9998]"
        onClick={onClose}
      />

      {/* Panel - Glass morphism style */}
      <motion.div
        variants={panelVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed right-0 top-0 bottom-0 w-[600px] max-w-[90vw] bg-white/95 backdrop-blur-xl shadow-2xl flex flex-col z-[9999] overflow-hidden border-l border-white/20"
      >
        {/* Header - Gradient */}
        <div
          className="px-5 py-4 flex justify-between items-center border-b border-gray-100"
          style={{
            background: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 50%, #14b8a6 100%)',
          }}
        >
          <h2 className="flex items-center gap-2 text-lg font-bold text-white">
            <FontAwesomeIcon icon={faLayerGroup} />
            {layerName}
          </h2>
          <motion.button
            whileHover={{ scale: 1.1, rotate: 90 }}
            whileTap={{ scale: 0.9 }}
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center text-white/80 hover:text-white rounded-full hover:bg-white/10 transition-colors"
          >
            <FontAwesomeIcon icon={faTimes} />
          </motion.button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {layerContent.reports && Object.keys(layerContent.reports).length > 0 ? (
            <div className="space-y-4">
              {getDimensionConfigsByLayer(activeLayer).map(({ key, name, icon }) => {
                const content = layerContent.reports[key] || '';
                if (!content) return null;

                return (
                  <DimensionSection
                    key={key}
                    name={name}
                    content={content}
                    icon={icon}
                    defaultExpanded={false}
                  />
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 text-gray-400">
              <FontAwesomeIcon icon={faLayerGroup} className="text-5xl mb-4" />
              <p className="text-center">
                {completedLayers[activeLayer as 1 | 2 | 3]
                  ? '暂无报告内容'
                  : '该 Layer 尚未完成'}
              </p>
              {!completedLayers[activeLayer as 1 | 2 | 3] && (
                <p className="text-sm mt-2">请先完成此层级的规划</p>
              )}
            </div>
          )}
        </div>
      </motion.div>
    </>,
    document.body
  );
}
