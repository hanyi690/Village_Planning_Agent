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
  'center': (p) => gisTestApi.getCenter(p),
  'bbox': (p) => gisTestApi.getBBox(p),
  'isochrone': (p) => gisTestApi.generateIsochrones(p),
  'accessibility': (p) => gisTestApi.analyzeAccessibility(p),
  'poi-search': (p) => gisTestApi.searchPOI(p),
  'coverage': (p) => gisTestApi.calculateCoverage(p),
  'facility-validation': (p) => gisTestApi.validateFacility(p),
  'ecological': (p) => gisTestApi.assessEcological(p),
  'spatial-layout': (p) => gisTestApi.generateSpatialLayout(p),
  'landuse-change': (p) => gisTestApi.analyzeLanduseChange(p),
  'constraint-validator': (p) => gisTestApi.validateConstraints(p),
  'hazard-buffer': (p) => gisTestApi.generateHazardBuffer(p),
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
};

// ============================================
// Store helper — write test layers into gisLayers
// ============================================

function setTestLayers(key: string, layerConfigs: GISLayerConfig[]) {
  const store = usePlanningStore.getState();
  store.gisLayers[`test_${key}`] = layerConfigs;
}

function removeTestLayers(key: string) {
  const store = usePlanningStore.getState();
  delete store.gisLayers[`test_${key}`];
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
    // Remove all test_ keys from store
    const store = usePlanningStore.getState();
    for (const key of Object.keys(store.gisLayers)) {
      if (key.startsWith('test_')) {
        delete store.gisLayers[key];
      }
    }
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
