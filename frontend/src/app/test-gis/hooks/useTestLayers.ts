'use client';

import { useState, useEffect } from 'react';
import type { GISLayerConfig, GeoJsonFeatureCollection } from '@/types/message/message-types';

interface TestLayerState {
  layers: GISLayerConfig[];
  loading: boolean;
  error: string | null;
}

// Enhance road data with infrastructure_type
function enhanceRoadData(geojson: GeoJsonFeatureCollection): GeoJsonFeatureCollection {
  return {
    type: 'FeatureCollection',
    features: geojson.features.map(f => {
      const rn = f.properties?.RN as string | undefined;
      const infraType = rn?.startsWith('Y') ? '乡道' : (rn?.startsWith('X') ? '县道' : '道路');
      return {
        ...f,
        properties: {
          ...f.properties,
          infrastructure_type: infraType,
        },
      };
    }),
  };
}

// Enhance water data with infrastructure_type
function enhanceWaterData(geojson: GeoJsonFeatureCollection): GeoJsonFeatureCollection {
  return {
    type: 'FeatureCollection',
    features: geojson.features.map(f => ({
      ...f,
      properties: {
        ...f.properties,
        infrastructure_type: '河流',
      },
    })),
  };
}

// Infer facility type from POI category
function inferFacilityType(category: string | undefined): string {
  if (!category) return '公共服务设施';
  if (category.includes('学校') || category.includes('教育')) return '教育设施';
  if (category.includes('医院') || category.includes('诊所') || category.includes('卫生')) return '医疗设施';
  if (category.includes('商店') || category.includes('超市') || category.includes('市场')) return '商业设施';
  if (category.includes('餐饮') || category.includes('饭店')) return '餐饮设施';
  return '公共服务设施';
}

// Enhance POI data with status and facility_type
function enhancePOIData(geojson: GeoJsonFeatureCollection): GeoJsonFeatureCollection {
  return {
    type: 'FeatureCollection',
    features: geojson.features.map(f => ({
      ...f,
      properties: {
        ...f.properties,
        status: '现状保留',
        facility_type: inferFacilityType(f.properties?.category as string),
      },
    })),
  };
}

// Load GeoJSON from public directory
async function loadGeoJSON(filename: string): Promise<GeoJsonFeatureCollection> {
  const response = await fetch(`/test-data/${filename}`);
  if (!response.ok) {
    throw new Error(`Failed to load ${filename}: ${response.status}`);
  }
  return response.json();
}

export function useTestLayers(): TestLayerState {
  const [state, setState] = useState<TestLayerState>({
    layers: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
    async function loadAllData() {
      try {
        // Load all GeoJSON files (no default boundary - user generates via fallback test)
        const roadData = await loadGeoJSON('wfs_lrdl.geojson');
        const waterData = await loadGeoJSON('wfs_hydl.geojson');
        const poiData = await loadGeoJSON('amap_pois_all.geojson');

        // Build GISLayerConfig array (only infrastructure and facility layers)
        const layers: GISLayerConfig[] = [
          {
            geojson: enhanceRoadData(roadData),
            layerType: 'infrastructure',
            layerName: '道路网络',
          },
          {
            geojson: enhanceWaterData(waterData),
            layerType: 'infrastructure',
            layerName: '水系网络',
          },
          {
            geojson: enhancePOIData(poiData),
            layerType: 'facility_point',
            layerName: '现状设施',
          },
        ];

        setState({ layers, loading: false, error: null });
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        setState({ layers: [], loading: false, error: errorMessage });
      }
    }

    loadAllData();
  }, []);

  return state;
}