'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import type { GISLayerConfig, GeoJsonFeatureCollection } from '@/types/message/message-types';
import type { VillagePlanningScheme } from '../types/planning';
import { dataApi } from '@/lib/api/data-api';

// ============================================
// Constants
// ============================================

const DEFAULT_TEST_CENTER: [number, number] = [116.044146, 24.818629];

// ============================================
// Types
// ============================================

interface SpatialLayoutStatistics {
  zone_count: number;
  facility_count: number;
  axis_count: number;
  total_area_km2: number;
}

interface SpatialLayoutState {
  loading: boolean;
  error: string | null;
  layers: GISLayerConfig[];
  statistics: SpatialLayoutStatistics | null;
  center: [number, number] | null;
}

interface SpatialLayoutResult {
  success: boolean;
  geojson?: GeoJsonFeatureCollection;
  zones_geojson?: GeoJsonFeatureCollection;
  facilities_geojson?: GeoJsonFeatureCollection;
  axes_geojson?: GeoJsonFeatureCollection;
  statistics?: SpatialLayoutStatistics;
  center?: [number, number];
  error?: string;
}

export function useSpatialLayoutTest() {
  const [state, setState] = useState<SpatialLayoutState>({
    loading: false,
    error: null,
    layers: [],
    statistics: null,
    center: null,
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const runTest = useCallback(async (
    villageName?: string,
    customScheme?: VillagePlanningScheme
  ) => {
    // Cancel previous request if still pending
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Prevent duplicate requests while loading
    if (state.loading) return;

    // Create new AbortController for this request
    abortControllerRef.current = new AbortController();

    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const result: SpatialLayoutResult = await dataApi.testSpatialLayout(
        villageName,
        customScheme ? (customScheme as unknown as Record<string, unknown>) : undefined
      );

      // Check if request was aborted
      if (abortControllerRef.current?.signal.aborted) return;

      if (result.success && result.geojson) {
        const layers: GISLayerConfig[] = [];

        if (result.zones_geojson?.features?.length) {
          layers.push({
            geojson: result.zones_geojson,
            layerType: 'function_zone',
            layerName: '规划用地',
          });
        }

        if (result.facilities_geojson?.features?.length) {
          layers.push({
            geojson: result.facilities_geojson,
            layerType: 'facility_point',
            layerName: '公共设施',
          });
        }

        if (result.axes_geojson?.features?.length) {
          layers.push({
            geojson: result.axes_geojson,
            layerType: 'development_axis',
            layerName: '发展轴线',
          });
        }

        setState({
          loading: false,
          error: null,
          layers,
          statistics: result.statistics ?? null,
          center: result.center ?? DEFAULT_TEST_CENTER,
        });
      } else {
        setState(prev => ({
          ...prev,
          loading: false,
          error: result.error ?? '生成失败',
          layers: [],
          statistics: null,
          center: null,
        }));
      }
    } catch (err) {
      // Ignore abort errors
      if (err instanceof Error && err.name === 'AbortError') return;

      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setState(prev => ({
        ...prev,
        loading: false,
        error: errorMessage,
      }));
    }
  }, [state.loading]);

  const clearTest = useCallback(() => {
    setState({
      loading: false,
      error: null,
      layers: [],
      statistics: null,
      center: null,
    });
  }, []);

  return { ...state, runTest, clearTest };
}