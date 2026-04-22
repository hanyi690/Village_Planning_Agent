'use client';

/**
 * DataUpload - GIS 数据上传组件
 *
 * 支持 GeoJSON、Shapefile、KML、GeoTIFF 格式上传。
 * GeoJSON 可在前端直接解析，其他格式发送到后端处理。
 */

import { useState, useCallback, useRef } from 'react';
import type { FeatureCollection, GeoJsonProperties, Geometry } from 'geojson';

// 支持的文件扩展名（用于 input accept 属性）
const ACCEPTED_EXTENSIONS = '.geojson,.json,.shp,.kml,.kmz,.tif,.tiff';

// 不支持的文件扩展名（需要友好提示）
const UNSUPPORTED_EXTENSIONS: Record<string, string> = {
  '.mpk': '不支持 ArcGIS Map Package (.mpk) 格式，请使用 ArcGIS Pro 导出为 Shapefile 或 GeoJSON',
  '.mxd': '不支持 ArcGIS Map Document (.mxd) 格式，请导出为 Shapefile 或 GeoJSON',
  '.aprx': '不支持 ArcGIS Pro Project (.aprx) 格式，请导出为 Shapefile 或 GeoJSON',
};

// 数据类型推断关键词
const DATA_TYPE_KEYWORDS = {
  boundary: ['行政代码', 'boundary_type', '行政级别', '行政区划', '行政边界', '规划范围', '村界'],
  water: ['水系名称', 'water_type', '河流名称', '湖泊名称', '河流', '湖泊', '水库', '水系'],
  road: ['道路名称', 'road_level', '道路等级', '路名', '道路', '公路', '村道', '省道', '国道'],
  residential: ['居民点', 'population', '人口', '户数', '居住区', '村庄', '聚落'],
  poi: ['设施类型', 'facility_type', 'POI类型'],
};

// 上传结果类型
export interface UploadResult {
  geojson: FeatureCollection<Geometry, GeoJsonProperties>;
  dataType: 'boundary' | 'water' | 'road' | 'residential' | 'poi' | 'custom';
  metadata: {
    fileName: string;
    fileSize: number;
    featureCount: number;
    properties: string[];
    crs: string;
  };
}

// 组件属性
export interface DataUploadProps {
  villageName: string;
  onDataUploaded: (result: UploadResult) => void;
  onError?: (error: string) => void;
  className?: string;
  maxSizeMB?: number;
}

// 检测文件类型
function detectFileType(fileName: string): string {
  const ext = fileName.toLowerCase().split('.').pop();
  const extToType: Record<string, string> = {
    'geojson': 'geojson',
    'json': 'geojson',
    'shp': 'shapefile',
    'kml': 'kml',
    'kmz': 'kmz',
    'tif': 'geotiff',
    'tiff': 'geotiff',
  };
  return extToType[ext || ''] || 'unknown';
}

// 检查是否是不支持的格式
function checkUnsupportedFormat(fileName: string): string | null {
  const ext = '.' + fileName.toLowerCase().split('.').pop();
  return UNSUPPORTED_EXTENSIONS[ext] || null;
}

// 推断数据类型
function inferDataType(geojson: FeatureCollection<Geometry, GeoJsonProperties>): string {
  if (!geojson.features || geojson.features.length === 0) {
    return 'custom';
  }

  const firstFeature = geojson.features[0];
  const props = firstFeature.properties || {};
  const propKeys = Object.keys(props);
  const propValues = Object.values(props).filter(v => typeof v === 'string') as string[];

  for (const [dataType, keywords] of Object.entries(DATA_TYPE_KEYWORDS)) {
    // 检查属性键名
    if (keywords.some(kw => propKeys.some(key => key.includes(kw)))) {
      return dataType;
    }
    // 检查属性值
    if (keywords.some(kw => propValues.some(val => val.includes(kw)))) {
      return dataType;
    }
  }

  return 'custom';
}

// 构建 GeoJSON FeatureCollection
function buildFeatureCollection(data: unknown): FeatureCollection<Geometry, GeoJsonProperties> {
  if (!data || typeof data !== 'object') {
    throw new Error('Invalid GeoJSON data');
  }

  const geojson = data as Record<string, unknown>;

  // 已经是 FeatureCollection
  if (geojson.type === 'FeatureCollection' && Array.isArray(geojson.features)) {
    return data as unknown as FeatureCollection<Geometry, GeoJsonProperties>;
  }

  // 单个 Feature
  if (geojson.type === 'Feature') {
    return {
      type: 'FeatureCollection' as const,
      features: [data as unknown as FeatureCollection<Geometry, GeoJsonProperties>['features'][0]],
    };
  }

  // 纯几何对象
  if (geojson.type && 'coordinates' in geojson) {
    return {
      type: 'FeatureCollection' as const,
      features: [{
        type: 'Feature' as const,
        geometry: data as unknown as Geometry,
        properties: {},
      }],
    };
  }

  throw new Error('Unsupported GeoJSON format');
}

export default function DataUpload({
  villageName,
  onDataUploaded,
  onError,
  className = '',
  maxSizeMB = 50,
}: DataUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 最大文件大小（字节）
  const maxFileSize = maxSizeMB * 1024 * 1024;

  // 处理文件上传
  const handleFile = useCallback(async (file: File) => {
    setUploading(true);
    setSelectedFile(file);

    try {
      // 检查文件大小
      if (file.size > maxFileSize) {
        throw new Error(`文件大小超过限制 (${maxSizeMB}MB)`);
      }

      // 检查是否是不支持的格式（如 MPK）
      const unsupportedError = checkUnsupportedFormat(file.name);
      if (unsupportedError) {
        throw new Error(unsupportedError);
      }

      const fileType = detectFileType(file.name);

      // GeoJSON - 前端直接解析
      if (fileType === 'geojson') {
        const text = await file.text();
        const rawData = JSON.parse(text);
        const geojson = buildFeatureCollection(rawData);

        // 推断数据类型
        const dataType = inferDataType(geojson) as UploadResult['dataType'];

        // 提取属性字段
        const properties = new Set<string>();
        geojson.features.forEach(f => {
          if (f.properties) {
            Object.keys(f.properties).forEach(k => properties.add(k));
          }
        });

        const result: UploadResult = {
          geojson,
          dataType,
          metadata: {
            fileName: file.name,
            fileSize: file.size,
            featureCount: geojson.features.length,
            properties: Array.from(properties),
            crs: 'EPSG:4326',
          },
        };

        onDataUploaded(result);
        return;
      }

      // 其他格式 - 发送到后端解析
      if (['shapefile', 'kml', 'kmz', 'geotiff'].includes(fileType)) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('village_name', villageName);

        const response = await fetch('/api/gis/upload', {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `上传失败: ${response.status}`);
        }

        const data = await response.json();
        onDataUploaded(data);
        return;
      }

      throw new Error(`不支持的文件格式: ${file.name}`);

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '上传失败';
      onError?.(errorMessage);
      console.error('[DataUpload] Error:', error);
    } finally {
      setUploading(false);
      setSelectedFile(null);
    }
  }, [maxFileSize, maxSizeMB, villageName, onDataUploaded, onError]);

  // 文件选择处理
  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFile(file);
    }
    // 重置 input 以允许重复选择同一文件
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, [handleFile]);

  // 拖放处理
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);

    const file = e.dataTransfer.files[0];
    if (file) {
      handleFile(file);
    }
  }, [handleFile]);

  // 点击触发文件选择
  const handleClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  return (
    <div className={`relative ${className}`}>
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_EXTENSIONS}
        onChange={handleFileSelect}
        className="hidden"
      />

      <div
        onClick={handleClick}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`
          border-2 border-dashed rounded-lg p-6 text-center cursor-pointer
          transition-colors duration-200
          ${dragOver
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
          }
          ${uploading ? 'opacity-50 pointer-events-none' : ''}
        `}
      >
        {uploading ? (
          <div className="flex flex-col items-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mb-2" />
            <span className="text-gray-600">
              {selectedFile ? `解析 ${selectedFile.name}...` : '处理中...'}
            </span>
          </div>
        ) : (
          <div className="flex flex-col items-center">
            <svg
              className="w-10 h-10 text-gray-400 mb-2"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
              />
            </svg>
            <span className="text-gray-600 font-medium">拖拽或点击上传 GIS 数据</span>
            <span className="text-gray-400 text-sm mt-1">
              支持 GeoJSON, Shapefile, KML, GeoTIFF
            </span>
            <span className="text-gray-400 text-xs mt-1">
              最大 {maxSizeMB}MB
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// 导出便捷函数
export { detectFileType, inferDataType, buildFeatureCollection, checkUnsupportedFormat };