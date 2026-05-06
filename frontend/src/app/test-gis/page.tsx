'use client';

import { useState, useCallback, useMemo } from 'react';
import MapView from '@/components/gis/MapView';
import type { GISLayerConfig } from '@/types/message/message-types';
import { JINTIAN_CENTER } from './constants/jintian-planning';
import { useTestLayers } from './hooks/useTestLayers';
import { useStandardLayers } from './hooks/useStandardLayers';
import { useReportData } from './hooks/useReportData';
import { useSpatialLayoutTest } from './hooks/useSpatialLayoutTest';
import { useBoundaryFallbackTest } from './hooks/useBoundaryFallbackTest';
import DebugPanel from './components/DebugPanel';
import TestResultPanel from './components/TestResultPanel';
import MapControls, { type BasemapType } from './components/MapControls';
import StandardLayersPanel from './components/StandardLayersPanel';
import ToolTestPanel from './components/ToolTestPanel';

// ============================================
// Constants
// ============================================

const DEFAULT_ZOOM = 12;
const LAYER_GROUP_NAMES: Record<string, string> = {
  status: '现状图层',
  planned: '规划图层',
  protection: '保护红线',
};

// ============================================
// Main Component
// ============================================

export default function TestGISPage() {
  // Static layers from public test data
  const { layers: staticLayers, loading: staticLoading, error: staticError } = useTestLayers();

  // Standard layers from jintian_boundary directory
  const {
    layers: standardLayers,
    layerVisibility,
    toggleLayer,
    setLayerVisibility,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    getVisibleLayers: _getVisibleLayers,
    loading: standardLoading,
    error: standardError,
  } = useStandardLayers();

  // Report data for LLM replacement
  const {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    layer3Report: _layer3Report,
    facilities,
    zones,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    loading: _reportLoading,
  } = useReportData();

  // Spatial layout test
  const {
    layers: layoutLayers,
    loading: layoutLoading,
    error: layoutError,
    statistics,
    center: layoutCenter,
    runTest: runLayoutTest,
    clearTest: clearLayoutTest,
  } = useSpatialLayoutTest();

  // Boundary fallback test
  const {
    loading: boundaryLoading,
    error: boundaryError,
    geojson: boundaryGeojson,
    strategyUsed,
    fallbackHistory,
    warnings,
    stats: boundaryStats,
    runTest: runBoundaryTest,
    clearTest: clearBoundaryTest,
  } = useBoundaryFallbackTest();

  // Test results from tool test panel
  const [toolTestLayers, setToolTestLayers] = useState<GISLayerConfig[]>([]);

  // Map controls state
  const [basemap, setBasemap] = useState<BasemapType>('vector');
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);

  // Create boundary layer from fallback test
  const boundaryLayer: GISLayerConfig[] = boundaryGeojson
    ? [{
        geojson: {
          type: 'FeatureCollection' as const,
          features: [{
            type: 'Feature' as const,
            properties: { name: '代理边界', strategy: strategyUsed },
            geometry: boundaryGeojson as {
              type: 'Polygon';
              coordinates: unknown;
            },
          }],
        },
        layerType: 'boundary',
        layerName: `代理边界 (${strategyUsed || 'unknown'})`,
      }]
    : [];

  // Get visible standard layers
  const visibleStandardLayers = useMemo(() => {
    return standardLayers.filter(layer => {
      const layerId = layer.layerName;
      return layerVisibility[layerId];
    }).map(layer => ({
      geojson: layer.geojson,
      layerType: layer.layerType,
      layerName: layer.layerName,
      color: layer.color,
    }));
  }, [standardLayers, layerVisibility]);

  // Build layer groups for StandardLayersPanel
  const layerGroups = useMemo(() => {
    const groups: Record<string, Array<{
      id: string;
      name: string;
      records: number;
      geometry_type: string;
      visible: boolean;
    }>> = { status: [], planned: [], protection: [] };

    standardLayers.forEach(layer => {
      const group = layer.group;
      const layerId = layer.layerName;
      if (groups[group]) {
        groups[group].push({
          id: layerId,
          name: layer.layerName,
          records: layer.records,
          geometry_type: layer.geometry_type,
          visible: layerVisibility[layerId] || false,
        });
      }
    });

    return Object.entries(groups).map(([groupKey, layers]) => ({
      name: LAYER_GROUP_NAMES[groupKey] || groupKey,
      color: groupKey === 'status' ? '#3B82F6' : groupKey === 'planned' ? '#10B981' : '#EF4444',
      layers,
    }));
  }, [standardLayers, layerVisibility]);

  // Combine all layers for map display
  const allLayers = useMemo(() => {
    return [
      ...visibleStandardLayers,
      ...staticLayers,
      ...layoutLayers,
      ...boundaryLayer,
      ...toolTestLayers,
    ];
  }, [visibleStandardLayers, staticLayers, layoutLayers, boundaryLayer, toolTestLayers]);

  const loading = staticLoading || layoutLoading || boundaryLoading || standardLoading;
  const error = staticError || layoutError || boundaryError || standardError;

  // Use layout center if available, otherwise default
  const mapCenter = layoutCenter ?? JINTIAN_CENTER;

  // Test handlers
  const handleRunLayoutTest = useCallback(async () => {
    await runLayoutTest('金田村委会');
  }, [runLayoutTest]);

  const handleRunBoundaryTest = useCallback(async (forceBbox: boolean = false) => {
    await runBoundaryTest('金田村委会', { skipUserUpload: true, forceBbox });
  }, [runBoundaryTest]);

  const handleClearAll = useCallback(() => {
    clearLayoutTest();
    clearBoundaryTest();
    setToolTestLayers([]);
  }, [clearLayoutTest, clearBoundaryTest]);

  // Handle tool test complete
  const handleToolTestComplete = useCallback((toolId: string, result: any) => {
    if (result.success && result.geojson) {
      const newLayer: GISLayerConfig = {
        geojson: result.geojson,
        layerType: 'function_zone',
        layerName: `${toolId} 测试结果`,
      };
      setToolTestLayers(prev => [...prev.filter(l => !l.layerName.includes(toolId)), newLayer]);
    }
  }, []);

  // Loading state
  if (loading && allLayers.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4" />
          <div className="text-gray-500">
            {boundaryLoading ? '生成代理边界...' :
             layoutLoading ? '生成空间布局...' :
             standardLoading ? '加载标准图层...' : '加载测试数据...'}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow-sm px-6 py-4">
        <div className="max-w-[1800px] mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">
              GIS 测试页面 - 金田村规划验证
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              标准图层: {standardLayers.length} · 可见: {visibleStandardLayers.length} ·
              报告设施: {facilities.length} · 规划分区: {zones.length}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleClearAll}
              className="px-3 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 text-sm"
            >
              清除所有
            </button>
          </div>
        </div>
      </header>

      {/* Main Content - Three Column Layout */}
      <main className="max-w-[1800px] mx-auto px-6 py-4">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {/* Left Panel - Standard Layers */}
          <div className="lg:col-span-1 space-y-4">
            <StandardLayersPanel
              layerGroups={layerGroups}
              onToggleLayer={toggleLayer}
              onSetVisibility={setLayerVisibility}
              loading={standardLoading}
            />
          </div>

          {/* Center Panel - Map */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-lg shadow-sm p-3">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-semibold text-gray-800">地图渲染</h3>
                <div className="text-sm text-gray-600 flex gap-2 flex-wrap">
                  <span>图层: {allLayers.length}</span>
                  {allLayers.slice(0, 3).map((l) => (
                    <span key={l.layerName} className="bg-gray-100 px-1 rounded text-xs">
                      {l.layerName}({l.geojson?.features?.length || 0})
                    </span>
                  ))}
                </div>
              </div>
              <MapView
                layers={allLayers}
                center={mapCenter}
                zoom={zoom}
                height="500px"
                title="金田村空间布局"
                showLegend={true}
              />
              <div className="mt-2">
                <MapControls
                  basemap={basemap}
                  onBasemapChange={setBasemap}
                  zoom={zoom}
                  onZoomChange={setZoom}
                />
              </div>
            </div>

            {/* Test Results */}
            <TestResultPanel
              statistics={statistics}
              strategyUsed={strategyUsed}
              fallbackHistory={fallbackHistory}
              warnings={warnings}
              boundaryStats={boundaryStats}
            />
          </div>

          {/* Right Panel - Tool Tests */}
          <div className="lg:col-span-1 space-y-4">
            <ToolTestPanel onTestComplete={handleToolTestComplete} />

            {/* Quick Tests */}
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <h3 className="font-semibold text-gray-800 mb-3">快捷测试</h3>
              <div className="space-y-2">
                <button
                  onClick={handleRunLayoutTest}
                  disabled={layoutLoading}
                  className="w-full px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {layoutLoading ? '生成中...' : '运行空间布局生成'}
                </button>
                <button
                  onClick={() => handleRunBoundaryTest(false)}
                  disabled={boundaryLoading}
                  className="w-full px-4 py-2 bg-purple-500 text-white rounded hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {boundaryLoading ? '生成中...' : '测试边界兜底机制'}
                </button>
                <button
                  onClick={() => handleRunBoundaryTest(true)}
                  disabled={boundaryLoading}
                  className="w-full px-4 py-2 bg-orange-500 text-white rounded hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  强制 bbox 测试
                </button>
              </div>
            </div>

            {/* Error Display */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                <p className="text-red-700 text-sm">{error}</p>
              </div>
            )}
          </div>
        </div>

        {/* Debug Panel - Collapsible */}
        {allLayers.length > 0 && (
          <div className="mt-4">
            <details className="bg-white rounded-lg shadow-sm">
              <summary className="px-4 py-3 cursor-pointer font-semibold text-gray-700 hover:bg-gray-50">
                图层调试信息
              </summary>
              <div className="px-4 pb-4">
                <DebugPanel layers={allLayers} />
              </div>
            </details>
          </div>
        )}

        {/* Documentation */}
        <div className="mt-4 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <h4 className="font-semibold text-yellow-800 mb-2">使用说明</h4>
          <ul className="text-sm text-yellow-700 list-disc pl-4 space-y-1">
            <li><strong>标准图层面板</strong>: 左侧显示金田村 14 个标准图层，可切换可见性</li>
            <li><strong>GIS 工具测试</strong>: 右侧面板提供 9 个 GIS 工具的独立测试入口</li>
            <li><strong>空间布局生成</strong>: 使用真实金田村边界和道路数据生成布局</li>
            <li><strong>边界兜底测试</strong>: 模拟边界缺失场景，验证代理边界生成策略</li>
            <li><strong>报告数据</strong>: LLM 生成的部分使用 docs 报告替代</li>
          </ul>
          <div className="mt-2 text-xs text-yellow-600">
            数据来源: docs/gis/jintian_boundary (真实 GIS 数据) · docs/layer*_完整报告.md (规划报告)
          </div>
        </div>
      </main>
    </div>
  );
}