'use client';

/**
 * GIS 测试页面 - 开发环境专用
 *
 * 端到端测试 GIS 系统：后端服务 → REST API → 前端渲染
 * 注意：此页面仅在开发环境可用
 */

import { useState, useCallback, useMemo, useEffect } from 'react';
import MapView from '@/features/planning/components/gis/MapView';
import { TracePanel } from '@/features/planning/components/gis/TracePanel';
import { usePlanningStore } from '@/features/planning/store';
import type { GISLayerConfig } from '@/types/message/message-types';
import { JINTIAN_CENTER } from './constants/jintian-planning';
import { useTestLayers } from './hooks/useTestLayers';
import { useGisTestSuite } from './hooks/useGisTestSuite';
import { gisTestApi, type JintianFile } from '@/features/gis-test/api/gis-test-api';
import DebugPanel from './components/DebugPanel';
import MapControls, { type BasemapType } from './components/MapControls';
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
// Main Content Component
// ============================================

function TestGISPageContent() {
  // Static layers from public test data
  const { layers: staticLayers, loading: staticLoading } = useTestLayers();

  // Unified test suite
  const testSuite = useGisTestSuite();
  const { serviceStatus, results, layers: testLayers, runningTests, refreshStatus, clearAll } = testSuite;

  // Pipeline trace from store (populated after spatial-layout test)
  const pipelineTrace = usePlanningStore((s) => s.pipelineTrace);

  // Standard layers from jintian_boundary (loaded via new API)
  const [standardLayers, setStandardLayers] = useState<GISLayerConfig[]>([]);
  const [standardLoading, setStandardLoading] = useState(false);
  const [jintianFiles, setJintianFiles] = useState<JintianFile[]>([]);
  const [visibleFiles, setVisibleFiles] = useState<Record<string, boolean>>({});

  // Map controls
  const [basemap, setBasemap] = useState<BasemapType>('vector');
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);

  // Load service status and jintian files on mount
  useEffect(() => {
    refreshStatus();

    const loadJintianFiles = async () => {
      setStandardLoading(true);
      try {
        const resp = await gisTestApi.listJintianFiles();
        if (resp.success) {
          setJintianFiles(resp.files);
          // Default visibility: only status layers visible
          const defaults: Record<string, boolean> = {};
          resp.files.forEach(f => { defaults[f.filename] = f.group === 'status'; });
          setVisibleFiles(defaults);
        }
      } catch {
        // jintian files not available, that's ok
      } finally {
        setStandardLoading(false);
      }
    };
    loadJintianFiles();
  }, [refreshStatus]);

  // Load visible jintian GeoJSON layers
  useEffect(() => {
    const loadVisible = async () => {
      const layers: GISLayerConfig[] = [];
      // Skip redundant/county-level boundary files
      const SKIP_FILES = new Set([
        'boundary_pingyuan_osm.geojson',  // County-level boundary (Pingyuan County)
        'admin_boundary_line.geojson',    // 561 admin lines (county/town/village, too broad)
        'boundary_current.geojson',       // Duplicate of boundary.geojson (same village boundary)
      ]);
      for (const file of jintianFiles) {
        if (SKIP_FILES.has(file.filename)) continue;
        if (!visibleFiles[file.filename]) continue;
        try {
          const resp = await gisTestApi.getJintianData(file.filename);
          if (resp.success && resp.geojson) {
            layers.push({
              geojson: resp.geojson as GISLayerConfig['geojson'],
              layerType: file.layer_type as GISLayerConfig['layerType'],
              layerName: file.name,
            });
          }
        } catch {
          // skip failed files
        }
      }
      setStandardLayers(layers);
    };
    if (jintianFiles.length > 0) {
      loadVisible();
    }
  }, [jintianFiles, visibleFiles]);

  // Combine all layers
  const allLayers = useMemo(() => {
    return [...standardLayers, ...staticLayers, ...testLayers];
  }, [standardLayers, staticLayers, testLayers]);

  // Service status indicator
  const statusColor = useMemo(() => {
    if (!serviceStatus) return 'gray';
    const s = serviceStatus.services;
    if (s.tianditu_api_key && s.amap_api_key) return 'green';
    if (s.tianditu_api_key || s.amap_api_key) return 'yellow';
    return 'red';
  }, [serviceStatus]);

  // Layer groups for standard layers panel (skip redundant/county-level files)
  const layerGroups = useMemo(() => {
    const groups: Record<string, Array<{
      id: string; name: string; records: number; visible: boolean;
    }>> = { status: [], planned: [], protection: [] };
    // Skip redundant/county-level boundary files
    const SKIP_FILES = new Set([
      'boundary_pingyuan_osm.geojson',  // County-level boundary (Pingyuan County)
      'admin_boundary_line.geojson',    // 561 admin lines (county/town/village, too broad)
      'boundary_current.geojson',       // Duplicate of boundary.geojson (same village boundary)
    ]);

    jintianFiles.forEach(file => {
      if (SKIP_FILES.has(file.filename)) return; // skip redundant/county-level files
      const group = file.group;
      if (groups[group]) {
        groups[group].push({
          id: file.filename,
          name: file.name,
          records: file.records,
          visible: visibleFiles[file.filename] || false,
        });
      }
    });

    return Object.entries(groups).map(([groupKey, items]) => ({
      name: LAYER_GROUP_NAMES[groupKey] || groupKey,
      color: groupKey === 'status' ? '#3B82F6' : groupKey === 'planned' ? '#10B981' : '#EF4444',
      layers: items,
    }));
  }, [jintianFiles, visibleFiles]);

  const toggleFile = useCallback((filename: string) => {
    setVisibleFiles(prev => ({ ...prev, [filename]: !prev[filename] }));
  }, []);

  const loading = staticLoading || standardLoading || runningTests.size > 0;

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow-sm px-6 py-4">
        <div className="max-w-[1800px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`w-3 h-3 rounded-full ${
              statusColor === 'green' ? 'bg-green-500' :
              statusColor === 'yellow' ? 'bg-yellow-500' :
              statusColor === 'red' ? 'bg-red-500' : 'bg-gray-300'
            }`} title={statusColor === 'green' ? '服务正常' : statusColor === 'yellow' ? '部分服务可用' : '服务不可用'} />
            <div>
              <h1 className="text-2xl font-bold text-gray-800">
                GIS 端到端测试 - 金田村
              </h1>
              <p className="text-sm text-gray-500 mt-1">
                图层: {allLayers.length} · 测试结果: {Object.keys(results).length} ·
                标准: {jintianFiles.length} 文件
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={refreshStatus}
              className="px-3 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 text-sm"
            >
              刷新状态
            </button>
            <button
              onClick={clearAll}
              className="px-3 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 text-sm"
            >
              清除所有
            </button>
          </div>
        </div>
      </header>

      {/* Service Status Bar */}
      {serviceStatus && (
        <div className="bg-gray-50 border-b px-6 py-2">
          <div className="max-w-[1800px] mx-auto flex gap-4 text-xs text-gray-600">
            {Object.entries(serviceStatus.services).map(([key, val]) => (
              <span key={key} className="flex items-center gap-1">
                <span className={`w-1.5 h-1.5 rounded-full ${val ? 'bg-green-500' : 'bg-red-400'}`} />
                {key}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-[1800px] mx-auto px-6 py-4">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {/* Left Panel - Standard Layers */}
          <div className="lg:col-span-1 space-y-4">
            <div className="bg-white rounded-lg shadow-sm p-4">
              <h3 className="font-semibold text-gray-800 mb-3">标准图层</h3>
              {layerGroups.map(group => (
                <div key={group.name} className="mb-3">
                  <div className="flex items-center gap-1 mb-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: group.color }} />
                    <span className="text-xs font-medium text-gray-600">{group.name}</span>
                  </div>
                  {group.layers.map(layer => (
                    <label key={layer.id} className="flex items-center gap-2 py-0.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={layer.visible}
                        onChange={() => toggleFile(layer.id)}
                        className="w-3 h-3"
                      />
                      <span className="text-xs text-gray-700">{layer.name}</span>
                      <span className="text-xs text-gray-400">({layer.records})</span>
                    </label>
                  ))}
                </div>
              ))}
              {jintianFiles.length === 0 && loading && (
                <p className="text-xs text-gray-400">加载中...</p>
              )}
            </div>
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
                center={JINTIAN_CENTER}
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

            {/* Test Results Summary */}
            {Object.keys(results).length > 0 && (
              <div className="mt-4 bg-white rounded-lg shadow-sm p-4">
                <h3 className="font-semibold text-gray-800 mb-3">测试结果</h3>
                <div className="space-y-2">
                  {Object.entries(results).map(([id, result]) => (
                    <div key={id} className={`text-sm p-2 rounded ${result.success ? 'bg-green-50' : 'bg-red-50'}`}>
                      <span className={result.success ? 'text-green-700' : 'text-red-700'}>
                        {id}: {result.success ? 'SUCCESS' : 'FAIL'}
                      </span>
                      {result.timing_ms && <span className="text-gray-500 ml-2">({result.timing_ms}ms)</span>}
                      {result.error && <span className="text-red-500 ml-2">- {result.error}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right Panel - Tool Tests */}
          <div className="lg:col-span-1 space-y-4">
            <ToolTestPanel testSuite={testSuite} />
          </div>
        </div>

        {/* Pipeline Trace */}
        {pipelineTrace && (
          <div className="mt-4">
            <TracePanel trace={pipelineTrace} />
          </div>
        )}

        {/* Debug Panel */}
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
            <li><strong>标准图层面板</strong>: 左侧显示金田村标准图层，可切换可见性</li>
            <li><strong>GIS 工具测试</strong>: 右侧面板按分类提供 13 个 GIS 工具测试</li>
            <li><strong>端到端验证</strong>: 每个测试调用后端 REST API，结果渲染到地图</li>
            <li><strong>服务状态</strong>: 顶部指示器显示 API Key 和依赖可用性</li>
          </ul>
          <div className="mt-2 text-xs text-yellow-600">
            后端: /api/dev/gis/* · 数据: docs/gis/jintian_boundary/
          </div>
        </div>
      </main>
    </div>
  );
}

// ============================================
// Export (with production guard)
// ============================================

export default function TestGISPage() {
  if (process.env.NODE_ENV === 'production') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center p-8 bg-white rounded-lg shadow-lg">
          <h1 className="text-2xl font-bold text-gray-800 mb-4">页面不可访问</h1>
          <p className="text-gray-600">此页面仅在开发环境可用</p>
        </div>
      </div>
    );
  }

  return <TestGISPageContent />;
}
