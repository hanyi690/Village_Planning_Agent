/**
 * GIS Test API Client - 开发环境专用的 GIS 端到端测试 API
 *
 * 对应后端 backend/app/api/gis_test_routes.py
 * 所有端点前缀: /api/dev/gis
 */

import { apiRequest } from '@/features/planning/api/client';

const BASE = '/api/dev/gis';

// ============================================
// Types
// ============================================

export interface GisServiceStatus {
  status: string;
  services: {
    tianditu_api_key: boolean;
    amap_api_key: boolean;
    osmnx: boolean;
    geopandas: boolean;
    rdflib: boolean;
    jintian_data: boolean;
  };
  jintian_files: number;
}

export interface TestResultBase {
  success: boolean;
  error?: string;
  timing_ms?: number;
}

export interface DataFetchResult extends TestResultBase {
  data?: Record<string, unknown>;
}

export interface CenterResult extends TestResultBase {
  center?: [number, number];
  metadata?: Record<string, unknown>;
}

export interface IsochroneResult extends TestResultBase {
  geojson?: unknown;
  isochrones?: unknown[];
}

export interface AccessibilityResult extends TestResultBase {
  data?: Record<string, unknown>;
}

export interface POISearchResult extends TestResultBase {
  pois?: unknown;
}

export interface CoverageResult extends TestResultBase {
  location?: string;
  coverage_rate?: number;
}

export interface FacilityValidationResult extends TestResultBase {
  overall_score?: number;
  suitability_level?: string;
  checks?: unknown[];
  recommendations?: string[];
}

export interface EcologicalResult extends TestResultBase {
  study_area_km2?: number;
  sensitivity_class?: string;
}

export interface SpatialLayoutResult extends TestResultBase {
  layout_configs?: unknown[];
  conflicts?: { metric_conflicts: number; constraint_violations: number };
}

export interface LanduseChangeResult extends TestResultBase {
  current_parcels?: number;
  planned_parcels?: number;
  geojson?: { current: unknown; planned: unknown };
}

export interface ConstraintValidatorResult extends TestResultBase {
  metric_conflicts?: number;
  constraint_violations?: number;
  is_valid?: boolean;
}

export interface HazardBufferResult extends TestResultBase {
  hazard_count?: number;
  buffer_meters?: number;
  geojson?: unknown;
}

export interface JintianFile {
  filename: string;
  name: string;
  group: string;
  layer_type: string;
  records: number;
}

// ============================================
// API Client
// ============================================

export const gisTestApi = {
  /** GET /api/dev/gis/status */
  async getStatus(): Promise<GisServiceStatus> {
    return apiRequest(`${BASE}/status`);
  },

  /** POST /api/dev/gis/data-fetch */
  async fetchData(params: {
    location?: string;
    buffer_km?: number;
    max_features?: number;
  }): Promise<DataFetchResult> {
    return apiRequest(`${BASE}/data-fetch`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/center */
  async getCenter(params: {
    location?: string;
    buffer_km?: number;
  }): Promise<CenterResult> {
    return apiRequest(`${BASE}/center`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/bbox */
  async getBBox(params: {
    location?: string;
    buffer_km?: number;
  }): Promise<TestResultBase> {
    return apiRequest(`${BASE}/bbox`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/isochrone */
  async generateIsochrones(params: {
    center?: number[];
    time_minutes?: number[];
    travel_mode?: string;
  }): Promise<IsochroneResult> {
    return apiRequest(`${BASE}/isochrone`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/accessibility */
  async analyzeAccessibility(params: {
    analysis_type?: string;
    origin?: number[];
    center?: number[];
  }): Promise<AccessibilityResult> {
    return apiRequest(`${BASE}/accessibility`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/poi-search */
  async searchPOI(params: {
    keyword?: string;
    center?: number[];
    radius?: number;
  }): Promise<POISearchResult> {
    return apiRequest(`${BASE}/poi-search`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/coverage */
  async calculateCoverage(params: {
    location?: string;
    buffer_km?: number;
  }): Promise<CoverageResult> {
    return apiRequest(`${BASE}/coverage`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/facility-validation */
  async validateFacility(params: {
    facility_type?: string;
    location?: number[];
  }): Promise<FacilityValidationResult> {
    return apiRequest(`${BASE}/facility-validation`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/ecological */
  async assessEcological(params: {
    use_jintian_data?: boolean;
  }): Promise<EcologicalResult> {
    return apiRequest(`${BASE}/ecological`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/spatial-layout */
  async generateSpatialLayout(params: {
    village_name?: string;
  }): Promise<SpatialLayoutResult> {
    return apiRequest(`${BASE}/spatial-layout`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/landuse-change */
  async analyzeLanduseChange(params: {
    location?: string;
    buffer_km?: number;
  }): Promise<LanduseChangeResult> {
    return apiRequest(`${BASE}/landuse-change`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/constraint-validator */
  async validateConstraints(params: {
    location?: string;
    strict_mode?: boolean;
  }): Promise<ConstraintValidatorResult> {
    return apiRequest(`${BASE}/constraint-validator`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** POST /api/dev/gis/hazard-buffer */
  async generateHazardBuffer(params: {
    location?: string;
    buffer_meters?: number;
  }): Promise<HazardBufferResult> {
    return apiRequest(`${BASE}/hazard-buffer`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** GET /api/dev/gis/jintian/files */
  async listJintianFiles(): Promise<{ success: boolean; files: JintianFile[] }> {
    return apiRequest(`${BASE}/jintian/files`);
  },

  /** GET /api/dev/gis/jintian/data/{filename} */
  async getJintianData(filename: string): Promise<{ success: boolean; geojson?: unknown }> {
    return apiRequest(`${BASE}/jintian/data/${filename}`);
  },
};
