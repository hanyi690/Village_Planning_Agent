'use client';

import { useState, useEffect, useCallback } from 'react';
import type { GISLayerConfig, GeoJsonFeatureCollection } from '@/types/message/message-types';

interface JintianFile {
  filename: string;
  source_gdb: string;
  source_layer: string;
  records: number;
  geometry_type: string;
}

interface StandardLayerConfig extends GISLayerConfig {
  source: string;
  records: number;
  geometry_type: string;
  group: 'status' | 'planned' | 'protection';
}

interface StandardLayersState {
  layers: StandardLayerConfig[];
  layerVisibility: Record<string, boolean>;
  loading: boolean;
  error: string | null;
}

const JINTIAN_API_BASE = '/api/jintian';

const LAYER_GROUP_MAP: Record<string, 'status' | 'planned' | 'protection'> = {
  'boundary_current.geojson': 'status',
  'road_current.geojson': 'status',
  'landuse_current.geojson': 'status',
  'admin_boundary_line.geojson': 'status',
  'annotation_current.geojson': 'status',
  'boundary.geojson': 'planned',
  'road_planned.geojson': 'planned',
  'landuse_planned.geojson': 'planned',
  'geological_hazard_points.geojson': 'planned',
  'construction_zone.geojson': 'planned',
  'annotation_planned.geojson': 'planned',
  'farmland_protection.geojson': 'protection',
  'ecological_protection.geojson': 'protection',
  'historical_protection.geojson': 'protection',
};

const LAYER_TYPE_MAP: Record<string, string> = {
  'boundary': 'boundary',
  'boundary_current': 'boundary',
  'road_current': 'infrastructure',
  'road_planned': 'development_axis',
  'landuse_current': 'function_zone',
  'landuse_planned': 'function_zone',
  'geological_hazard_points': 'sensitivity_zone',
  'farmland_protection': 'sensitivity_zone',
  'ecological_protection': 'sensitivity_zone',
  'historical_protection': 'sensitivity_zone',
  'construction_zone': 'function_zone',
  'annotation_current': 'facility_point',
  'annotation_planned': 'facility_point',
  'admin_boundary_line': 'boundary',
};

const LAYER_NAME_MAP: Record<string, string> = {
  'boundary_current.geojson': '现状边界',
  'road_current.geojson': '现状道路',
  'landuse_current.geojson': '现状用地',
  'admin_boundary_line.geojson': '行政区划界线',
  'annotation_current.geojson': '现状注记',
  'boundary.geojson': '规划边界',
  'road_planned.geojson': '规划道路',
  'landuse_planned.geojson': '规划用地',
  'geological_hazard_points.geojson': '地质灾害点',
  'construction_zone.geojson': '建设用地',
  'annotation_planned.geojson': '规划注记',
  'farmland_protection.geojson': '农田保护红线',
  'ecological_protection.geojson': '生态保护红线',
  'historical_protection.geojson': '历史保护红线',
};

const LAYER_COLOR_MAP: Record<string, string> = {
  'status': '#3B82F6',
  'planned': '#10B981',
  'protection': '#EF4444',
};

export function useStandardLayers(): StandardLayersState & {
  toggleLayer: (layerId: string) => void;
  setLayerVisibility: (layerId: string, visible: boolean) => void;
  getVisibleLayers: () => StandardLayerConfig[];
  refreshLayers: () => Promise<void>;
} {
  const [state, setState] = useState<StandardLayersState>({
    layers: [],
    layerVisibility: {},
    loading: true,
    error: null,
  });

  const loadLayerData = useCallback(async (filename: string): Promise<GeoJsonFeatureCollection | null> => {
    try {
      const response = await fetch(`${JINTIAN_API_BASE}/data/${filename}`);
      if (!response.ok) {
        console.warn(`[useStandardLayers] Failed to load ${filename}: ${response.status}`);
        return null;
      }
      const data = await response.json();
      return data.geojson as GeoJsonFeatureCollection;
    } catch (err) {
      console.warn(`[useStandardLayers] Error loading ${filename}:`, err);
      return null;
    }
  }, []);

  const refreshLayers = useCallback(async () => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const filesResponse = await fetch(`${JINTIAN_API_BASE}/files`);
      if (!filesResponse.ok) {
        throw new Error(`Failed to get files list: ${filesResponse.status}`);
      }
      const filesData = await filesResponse.json();
      const files: JintianFile[] = filesData.files || [];

      const layers: StandardLayerConfig[] = [];
      const visibility: Record<string, boolean> = {};

      for (const file of files) {
        const geojson = await loadLayerData(file.filename);
        if (geojson && geojson.features?.length > 0) {
          const group = LAYER_GROUP_MAP[file.filename] || 'status';
          const layerId = file.filename.replace('.geojson', '');
          const layerType = LAYER_TYPE_MAP[layerId] || 'function_zone';
          const layerName = LAYER_NAME_MAP[file.filename] || file.filename;

          layers.push({
            geojson,
            layerType: layerType as GISLayerConfig['layerType'],
            layerName: layerName,
            color: LAYER_COLOR_MAP[group],
            source: file.source_gdb,
            records: file.records,
            geometry_type: file.geometry_type,
            group,
          });

          visibility[layerId] = false;
        }
      }

      setState({
        layers,
        layerVisibility: visibility,
        loading: false,
        error: null,
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setState(prev => ({
        ...prev,
        loading: false,
        error: errorMessage,
      }));
    }
  }, [loadLayerData]);

  useEffect(() => {
    refreshLayers();
  }, [refreshLayers]);

  const toggleLayer = useCallback((layerId: string) => {
    setState(prev => ({
      ...prev,
      layerVisibility: {
        ...prev.layerVisibility,
        [layerId]: !prev.layerVisibility[layerId],
      },
    }));
  }, []);

  const setLayerVisibility = useCallback((layerId: string, visible: boolean) => {
    setState(prev => ({
      ...prev,
      layerVisibility: {
        ...prev.layerVisibility,
        [layerId]: visible,
      },
    }));
  }, []);

  const getVisibleLayers = useCallback(() => {
    return state.layers.filter(layer => {
      const layerId = layer.layerName;
      return state.layerVisibility[layerId];
    });
  }, [state.layers, state.layerVisibility]);

  return {
    ...state,
    toggleLayer,
    setLayerVisibility,
    getVisibleLayers,
    refreshLayers,
  };
}