'use client';

/**
 * GISUploadSidebar - GIS 数据上传侧边栏
 *
 * 用于上传和管理 GIS 数据（GeoJSON, Shapefile, KML 等）
 * 复用 FileViewerSidebar 的动画和 Portal 渲染逻辑
 */

import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faTimes,
  faMap,
  faCheckCircle,
  faExclamationTriangle,
  faTrash,
  faInfoCircle,
} from '@fortawesome/free-solid-svg-icons';
import DataUpload, { type UploadResult } from '@/components/gis/DataUpload';
import { usePlanningStore } from '@/stores';
import type { FeatureCollection, Geometry, GeoJsonProperties } from 'geojson';

// 数据类型标签颜色映射
const DATA_TYPE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  boundary: { bg: 'bg-gray-100', text: 'text-gray-700', border: 'border-gray-300' },
  landuse: { bg: 'bg-orange-100', text: 'text-orange-700', border: 'border-orange-300' },
  protection_zone: { bg: 'bg-red-100', text: 'text-red-700', border: 'border-red-400' },
  geological_hazard: { bg: 'bg-amber-100', text: 'text-amber-700', border: 'border-amber-400' },
  water: { bg: 'bg-blue-100', text: 'text-blue-700', border: 'border-blue-300' },
  road: { bg: 'bg-slate-100', text: 'text-slate-700', border: 'border-slate-300' },
  residential: { bg: 'bg-yellow-100', text: 'text-yellow-700', border: 'border-yellow-300' },
  poi: { bg: 'bg-purple-100', text: 'text-purple-700', border: 'border-purple-300' },
  custom: { bg: 'bg-green-100', text: 'text-green-700', border: 'border-green-300' },
};

// 数据类型名称映射
const DATA_TYPE_NAMES: Record<string, string> = {
  boundary: '行政边界',
  landuse: '土地利用',
  protection_zone: '保护红线',
  geological_hazard: '地质灾害',
  water: '水系',
  road: '道路',
  residential: '居民地',
  poi: '公共设施',
  custom: '自定义数据',
};

// 已上传数据项
interface UploadedDataItem {
  dataType: string;
  fileName: string;
  featureCount: number;
  uploadedAt: number;
  geojson: FeatureCollection<Geometry, GeoJsonProperties>;
}

interface GISUploadSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onDataUploaded?: (result: UploadResult) => void;
}

export default function GISUploadSidebar({
  isOpen,
  onClose,
  onDataUploaded,
}: GISUploadSidebarProps) {
  const [mounted, setMounted] = useState(false);
  const [uploadedData, setUploadedData] = useState<UploadedDataItem[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [supportedFormats, setSupportedFormats] = useState<string[]>([]);

  // 获取村庄名称
  const villageFormData = usePlanningStore((state) => state.villageFormData);
  const villageName = villageFormData?.projectName || '';

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  // 获取支持的格式列表
  useEffect(() => {
    if (isOpen) {
      fetch('/api/gis/supported-formats')
        .then((res) => res.json())
        .then((data) => {
          const formats = data.supported?.flatMap(
            (f: { ext: string }) => f.ext.split(', ').map((e: string) => e.trim())
          ) || [];
          setSupportedFormats(formats);
        })
        .catch((err) => {
          console.error('[GISUploadSidebar] Failed to fetch supported formats:', err);
        });
    }
  }, [isOpen]);

  // 处理数据上传成功
  const handleDataUploaded = useCallback(
    (result: UploadResult) => {
      setUploadError(null);
      setUploadedData((prev) => {
        // 如果已存在同类型数据，替换它
        const existing = prev.find((item) => item.dataType === result.dataType);
        if (existing) {
          return prev.map((item) =>
            item.dataType === result.dataType
              ? {
                  dataType: result.dataType,
                  fileName: result.metadata.fileName,
                  featureCount: result.metadata.featureCount,
                  uploadedAt: Date.now(),
                  geojson: result.geojson,
                }
              : item
          );
        }
        return [
          ...prev,
          {
            dataType: result.dataType,
            fileName: result.metadata.fileName,
            featureCount: result.metadata.featureCount,
            uploadedAt: Date.now(),
            geojson: result.geojson,
          },
        ];
      });

      // 回调通知父组件
      onDataUploaded?.(result);
    },
    [onDataUploaded]
  );

  // 处理上传错误
  const handleError = useCallback((error: string) => {
    setUploadError(error);
  }, []);

  // 清除已上传数据
  const handleClearData = useCallback(
    async (dataType: string) => {
      if (!villageName) return;

      try {
        await fetch(`/api/gis/clear/${encodeURIComponent(villageName)}/${dataType}`, {
          method: 'DELETE',
        });
        setUploadedData((prev) => prev.filter((item) => item.dataType !== dataType));
      } catch (err) {
        console.error('[GISUploadSidebar] Failed to clear data:', err);
      }
    },
    [villageName]
  );

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

  if (!mounted || !isOpen) return null;

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

      {/* Panel */}
      <motion.div
        variants={panelVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed right-0 top-0 bottom-0 w-[500px] max-w-[90vw] bg-white/95 backdrop-blur-xl shadow-2xl flex flex-col z-[9999] overflow-hidden border-l border-white/20"
      >
        {/* Header */}
        <div
          className="px-5 py-4 flex justify-between items-center border-b border-gray-100"
          style={{
            background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 50%, #1d4ed8 100%)',
          }}
        >
          <div className="flex items-center gap-3">
            <FontAwesomeIcon icon={faMap} className="text-white text-xl" />
            <div>
              <h2 className="text-lg font-bold text-white">GIS 数据上传</h2>
              <p className="text-xs text-white/80">
                {villageName ? `村庄: ${villageName}` : '请先设置村庄名称'}
              </p>
            </div>
          </div>
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
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Upload area */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
              <FontAwesomeIcon icon={faInfoCircle} className="text-blue-500" />
              上传 GIS 数据文件
            </h3>
            <DataUpload
              villageName={villageName}
              onDataUploaded={handleDataUploaded}
              onError={handleError}
              maxSizeMB={50}
              className="w-full"
            />
          </div>

          {/* Error message */}
          {uploadError && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-red-50 border border-red-200 rounded-lg p-3 flex items-start gap-3"
            >
              <FontAwesomeIcon
                icon={faExclamationTriangle}
                className="text-red-500 mt-0.5"
              />
              <div>
                <p className="text-sm font-medium text-red-700">上传失败</p>
                <p className="text-xs text-red-600 mt-1">{uploadError}</p>
              </div>
              <button
                onClick={() => setUploadError(null)}
                className="text-red-400 hover:text-red-600 ml-auto"
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </motion.div>
          )}

          {/* Supported formats */}
          <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
            <h4 className="text-xs font-semibold text-gray-600 mb-2">支持的格式</h4>
            <div className="flex flex-wrap gap-1">
              {supportedFormats.length > 0
                ? supportedFormats.map((fmt) => (
                    <span
                      key={fmt}
                      className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded"
                    >
                      {fmt}
                    </span>
                  ))
                : ['GeoJSON', 'Shapefile (ZIP)', 'KML', 'KMZ', 'GeoTIFF'].map((fmt) => (
                    <span
                      key={fmt}
                      className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded"
                    >
                      {fmt}
                    </span>
                  ))}
            </div>
            <p className="text-xs text-red-500 mt-2 flex items-center gap-1">
              <FontAwesomeIcon icon={faExclamationTriangle} />
              不支持 .mpk (ArcGIS Map Package) 格式
            </p>
          </div>

          {/* Uploaded data list */}
          {uploadedData.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                <FontAwesomeIcon icon={faCheckCircle} className="text-green-500" />
                已上传数据 ({uploadedData.length})
              </h3>
              <div className="space-y-2">
                {uploadedData.map((item) => {
                  const colors = DATA_TYPE_COLORS[item.dataType] || DATA_TYPE_COLORS.custom;
                  const typeName = DATA_TYPE_NAMES[item.dataType] || '自定义数据';
                  return (
                    <motion.div
                      key={item.dataType}
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className={`${colors.bg} ${colors.text} border ${colors.border} rounded-lg p-3 flex items-center justify-between`}
                    >
                      <div>
                        <p className="text-sm font-medium">{typeName}</p>
                        <p className="text-xs opacity-75">
                          {item.fileName} • {item.featureCount} 个特征
                        </p>
                      </div>
                      <motion.button
                        whileHover={{ scale: 1.1 }}
                        whileTap={{ scale: 0.9 }}
                        onClick={() => handleClearData(item.dataType)}
                        className="w-7 h-7 flex items-center justify-center rounded-full hover:bg-black/10 transition-colors"
                        title="删除"
                      >
                        <FontAwesomeIcon icon={faTrash} className="text-sm" />
                      </motion.button>
                    </motion.div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Empty state */}
          {uploadedData.length === 0 && !uploadError && (
            <div className="flex flex-col items-center justify-center py-8 text-gray-400">
              <FontAwesomeIcon icon={faMap} className="text-4xl mb-3" />
              <p className="text-sm">尚未上传 GIS 数据</p>
              <p className="text-xs mt-1">上传的数据将用于规划分析</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-100 bg-gray-50">
          <p className="text-xs text-gray-500">
            提示：上传的数据会优先用于规划分析，覆盖自动获取的数据
          </p>
        </div>
      </motion.div>
    </>,
    document.body
  );
}