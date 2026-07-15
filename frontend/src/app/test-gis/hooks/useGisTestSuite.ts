'use client';

import { useState, useCallback, useRef } from 'react';
import { gisTestApi, type GisServiceStatus } from '@/features/gis-test/api/gis-test-api';
import { useGisLayers } from '@/features/planning/hooks';
import { usePlanningStore } from '@/features/planning/store';
import type { GISLayerConfig } from '@/types/message/message-types';

// ============================================
// Types
// ============================================

export interface TestResult {
  success: boolean;
  data?: Record<string, unknown>;
  error?: string;
  timing_ms?: number;
}

export interface GisTestSuiteState {
  serviceStatus: GisServiceStatus | null;
  results: Record<string, TestResult>;
  layers: GISLayerConfig[];
  runningTests: Set<string>;
  runTest: (testId: string, params?: Record<string, unknown>) => Promise<void>;
  clearTest: (testId: string) => void;
  clearAll: () => void;
  refreshStatus: () => Promise<void>;
}

// ============================================
// Test ID -> API method mapping
// ============================================

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TestRunner = (params: Record<string, unknown>) => Promise<any>;

const TEST_RUNNERS: Record<string, TestRunner> = {
  'data-fetch': (p) => gisTestApi.fetchData(p),
  'center': (p) => gisTestApi.fetchData({ ...p, include: ['center'] }),
  'bbox': (p) => gisTestApi.fetchData({ ...p, include: ['bbox'] }),
  'isochrone': (p) => gisTestApi.analyze({ ...p, analysis_type: 'isochrone' }),
  'accessibility': (p) => gisTestApi.analyze({ ...p, analysis_type: 'accessibility' }),
  'poi-search': (p) => gisTestApi.analyze({ ...p, analysis_type: 'poi' }),
  'coverage': (p) => gisTestApi.fetchData({ ...p, include: ['coverage'] }),
  'facility-validation': (p) => gisTestApi.validate({ ...p, validation_type: 'facility' }),
  'ecological': (p) => gisTestApi.validate({ ...p, validation_type: 'ecological' }),
  'spatial-layout': (p) => gisTestApi.generateLayout(p),
  'landuse-change': (p) => gisTestApi.generateLayout({ ...p, include_landuse_change: true }),
  'constraint-validator': (p) => gisTestApi.validate({ ...p, validation_type: 'constraint' }),
  'hazard-buffer': (p) => gisTestApi.validate({ ...p, validation_type: 'hazard' }),
  'layout-validate': (p) => gisTestApi.validate({ ...p, validation_type: 'layout' }),
};

// Map test IDs to layer types for MapView rendering
const TEST_LAYER_TYPE_MAP: Record<string, GISLayerConfig['layerType']> = {
  'data-fetch': 'infrastructure',
  'isochrone': 'isochrone',
  'accessibility': 'infrastructure',
  'poi-search': 'facility_point',
  'coverage': 'function_zone',
  'facility-validation': 'facility_point',
  'ecological': 'sensitivity_zone',
  'spatial-layout': 'planning_zone',
  'landuse-change': 'function_zone',
  'constraint-validator': 'sensitivity_zone',
  'hazard-buffer': 'sensitivity_zone',
  'layout-validate': 'planning_zone',
};

// ============================================
// Store helpers — write test layers via setState for proper Immer integration
// ============================================

function setTestLayers(key: string, layerConfigs: GISLayerConfig[]) {
  usePlanningStore.setState((state) => {
    state.gisLayers[`test_${key}`] = layerConfigs;
  });
}

function removeTestLayers(key: string) {
  usePlanningStore.setState((state) => {
    delete state.gisLayers[`test_${key}`];
  });
}

function clearAllTestLayers() {
  usePlanningStore.setState((state) => {
    for (const k of Object.keys(state.gisLayers)) {
      if (k.startsWith('test_')) delete state.gisLayers[k];
    }
  });
}

// ============================================
// Hook
// ============================================

export function useGisTestSuite(): GisTestSuiteState {
  const [serviceStatus, setServiceStatus] = useState<GisServiceStatus | null>(null);
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const [runningTests, setRunningTests] = useState<Set<string>>(new Set());
  const abortRef = useRef<Record<string, AbortController>>({});

  // Read layers from store (includes SSE + test layers)
  const layers = useGisLayers();

  const refreshStatus = useCallback(async () => {
    try {
      const status = await gisTestApi.getStatus();
      setServiceStatus(status);
    } catch {
      setServiceStatus(null);
    }
  }, []);

  const runTest = useCallback(async (testId: string, params: Record<string, unknown> = {}) => {
    const runner = TEST_RUNNERS[testId];
    if (!runner) {
      setResults(prev => ({ ...prev, [testId]: { success: false, error: `Unknown test: ${testId}` } }));
      return;
    }

    // Cancel previous run if any
    abortRef.current[testId]?.abort();
    const controller = new AbortController();
    abortRef.current[testId] = controller;

    setRunningTests(prev => new Set(prev).add(testId));
    const t0 = Date.now();

    try {
      const result = await runner(params);
      const timing_ms = Date.now() - t0;

      const testResult: TestResult = {
        success: Boolean(result.success),
        data: result,
        error: result.error as string | undefined,
        timing_ms,
      };
      setResults(prev => ({ ...prev, [testId]: testResult }));

      // Auto-add GeoJSON layers to store
      const geojson = result.geojson;
      if (geojson && testResult.success) {
        const layerType = TEST_LAYER_TYPE_MAP[testId] || 'function_zone';
        const newLayer: GISLayerConfig = {
          geojson: geojson as GISLayerConfig['geojson'],
          layerType,
          layerName: `${testId} (${timing_ms}ms)`,
        };
        setTestLayers(testId, [newLayer]);
      }

      // Special handling for spatial-layout: layout_configs contain multiple layers
      if (testId === 'spatial-layout' && result.layout_configs) {
        const configs = result.layout_configs as GISLayerConfig[];
        const layoutLayers = configs.map(cfg => ({
          geojson: cfg.geojson,
          layerType: cfg.layerType || 'function_zone',
          layerName: cfg.layerName || `layout-${cfg.layerType}`,
          color: cfg.color,
        })).filter(l => l.geojson);
        setTestLayers('layout', layoutLayers);

        // Store pipeline_trace in planning store
        if (result.pipeline_trace) {
          usePlanningStore.setState({ pipelineTrace: result.pipeline_trace as any });
        }
      }

      // Special handling for landuse-change: two geojsons
      if (testId === 'landuse-change' && result.geojson) {
        const gj = result.geojson as { current: unknown; planned: unknown };
        const newLayers: GISLayerConfig[] = [];
        if (gj.current) {
          newLayers.push({ geojson: gj.current as GISLayerConfig['geojson'], layerType: 'function_zone', layerName: 'landuse-change-current' });
        }
        if (gj.planned) {
          newLayers.push({ geojson: gj.planned as GISLayerConfig['geojson'], layerType: 'planning_zone', layerName: 'landuse-change-planned' });
        }
        setTestLayers('landuse-change', newLayers);
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setResults(prev => ({ ...prev, [testId]: { success: false, error: errorMsg, timing_ms: Date.now() - t0 } }));
    } finally {
      setRunningTests(prev => {
        const next = new Set(prev);
        next.delete(testId);
        return next;
      });
    }
  }, []);

  const clearTest = useCallback((testId: string) => {
    setResults(prev => {
      const next = { ...prev };
      delete next[testId];
      return next;
    });
    removeTestLayers(testId);
    removeTestLayers('layout');
    removeTestLayers('landuse-change');
  }, []);

  const clearAll = useCallback(() => {
    setResults({});
    clearAllTestLayers();
    Object.values(abortRef.current).forEach(c => c.abort());
    abortRef.current = {};
  }, []);

  return {
    serviceStatus,
    results,
    layers,
    runningTests,
    runTest,
    clearTest,
    clearAll,
    refreshStatus,
  };
}
